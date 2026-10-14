# 频率测试

`frequency_benchmark` 对比“连续角度命令 + 角度反馈”和“连续角度命令 + 角度反馈 + 完整触觉”两种负载。默认保持首次有效 percent 姿态，但仍持续发送实机命令，不能视作只读测试。

## 测试前提

- 按[快速开始](quick_start.md)或[更新指南](update.md)准备依赖，确认驱动 active、身份已验证、当前代次角度有效。
- 关闭其他目标发布者和主动查询程序，每只手使用独立通道。
- 预先验证总线、终端电阻、设备 ID、急停和机械空间。
- 启动时设置足够的 `command_rate_hz`，该静态参数不会由测试工具自动修改。

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l6 side:=left command_rate_hz:=250 \
  transport_json:='{"backend":"socketcan","channel":"can1"}'
```

## 角度收发

每个候选点运行 180 秒，重复 3 次：

```bash
ros2 run linkerbot_hand_ros frequency_benchmark \
  --angle-feedback query_only \
  --angle-rates 50 100 150 200 \
  --duration 180 --repetitions 3
```

工具原子设置 `angles_hz`、`angle_feedback`、`publish_rate_hz`、`diagnostic_rate_hz`，清零所有触觉字段频率，再设置 `force_hz`。默认 diagnostics 为 1 Hz；提高 `--diagnostic-hz` 会增加观测成本，比较结果时须记录。

不提供 `--angle-values` 时，工具先用 `query_only + 100 Hz` 获取基准姿态，再切换候选配置；预读不计入计时窗口。显式目标或 `--no-configure-driver` 不执行此预读。

| 策略 | 负载与指标 |
| --- | --- |
| `query_only` | 主动查询，适合与相同“设置+查询”负载比较 |
| `command_feedback_only` | 使用设备命令反馈，须支持 `returns_current_state` |
| `adaptive` | 优先反馈，在反馈不足时补查询 |

三种策略的总线工作量不同，分别测试，不把结果混为同一上限。

## 角度与完整触觉

```bash
ros2 run linkerbot_hand_ros frequency_benchmark \
  --angle-rates 20 50 100 150 200 \
  --tactile-hz 30 \
  --duration 180 --repetitions 3
```

30 Hz 指每秒 30 个完整多指样本，不是手指、字段或 CAN 分片数。工具按 `payload_projection` 选择矩阵或 descriptor；缺少身份、字段不全的样本不算有效完整采样。明确缺失的传感器允许保留身份与空数据。

L20Lite 的 `force_hz` 同时请求 fn 与 fns 两个独立事务，但触觉通过率统计点阵。仅测试点阵时，手动配置 `force_fn_hz` 并使用 `--no-configure-driver`。O30 的 FnS 合力另计为 `resultant_cache/resultant_ros`；没有 FnS 的 descriptor 仍可测试触觉频率，不会生成合力样本。

预热应覆盖首次完整触觉读取；能力查询与缓存后的采集成本不同。单位、真实受压响应和机械到位不由频率工具证明。事务成本超出设备或总线能力时，参数校验可能拒绝，运行时也可能超时；提高 ROS 发布频率不能弥补。

## 可选目标与扰动

确认方向、速度、限制和空间后才启用扰动；下例对索引 2 施加 3 个 percent 点幅度：

```bash
ros2 run linkerbot_hand_ros frequency_benchmark \
  --angle-rates 50 100 --angle-amplitude 3 --joint-index 2 --angle-period 2 \
  --duration 180 --repetitions 3
```

可用 `--angle-values 50 50 50 50 50 50` 指定六关节基准目标；数量须匹配设备。固定外部参数时使用 `--no-configure-driver --angle-rates 100`，调用方负责设置足够的轮询、发布和诊断频率。

## 指标与通过标准

`ros2 topic hz` 只观察 ROS 接收，不能替代设备采样与命令下发计数。工具分别记录：

- 本地发布、驱动接收、SDK `ACCEPTED`、实际 `DISPATCHED` 和协议终态频率。
- 发布→接收、接收→接受、接受→下发、发布→下发的 P50/P95/P99 延迟；发布间隔 P95。
- 完整查询 `completed_reads`、命令反馈、策略有效反馈、SDK 缓存序号更新及有效 ROS 接收频率。
- FAILED、SUPERSEDED、连接代次、pending、timeout、drop、route miss 和 bus error 增量。

命令按 `(client_id, user_sequence, stage)` 去重；即使最终状态是 ACK，也从 `transitions[]` 确认实际 DISPATCHED。状态按 generation 与 sequence 区分新样本，查询、反馈和上报不能互相替代；`origin` 表明当前来源。

默认 `minimum_ratio=0.9`。每轮要求各命令阶段及角度有效反馈/缓存/ROS 频率达到目标的 90%；query_only 还须查询完成率达标，command_feedback_only 还须命令反馈率达标，adaptive 可组合两者。触觉的完整读取/缓存/ROS 频率也须分别达标。

同时要求无 FAILED、无缺失或倒序延迟时间戳、连接代次不变、drain 后 `pending_commands=0`，且连续错误、角度/触觉 timeout、transport drop/route miss/bus error 不增加。SUPERSEDED 单独记录，并受实际下发频率门槛约束。

候选点连续三轮全通过才算稳定。默认首个失败后停止；`--continue-after-failure` 可继续测试更高点。连接断开或代次变化会中止，重新建立基线后再测试。

## 退出码与记录

| 退出码 | 含义 |
| --- | --- |
| `0` | 全部候选点和轮次通过 |
| `2` | 正常完成但存在失败点 |
| `1` | 启动、参数、状态或能力不满足 |
| `130` | 用户中断 |

记录驱动日志、`/diagnostics`、CPU/RSS、线程/FD 和 `ip -details -statistics link show canX`。与 raw SocketCAN 或 Python SDK 比较时，使用相同请求、回复校验、目标更新与时长。

[返回总览](getting_started.md) · [English](../frequency_benchmark.md)
