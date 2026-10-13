# 业务节点集成

[English](../business_integration.md) | [使用手册](../../README_zh.md)

业务节点通过 `HandCommandClient` 与 `linkerbot_hand_msgs` 接入驱动；驱动的 `HandDevice`
负责设备 I/O。业务无需打开 CAN、导入 SDK 型号类或维护另一份型号范围表。

## 就绪与启动

1. configure 驱动，读取 declared capability。
2. activate，等待 `identity.verified=true`、设备信息及 operational diagnostics。
3. 等待当前 `connection_generation` 的有效角度 baseline，确认 fault 与业务安全条件。
4. 启用命令产生逻辑。

按 capability 获取关节名称/顺序、percent 端点、raw 范围、命令和 telemetry 支持性。
客户端 `is_ready("angles")` 还核对指定驱动的 active 状态及命令订阅归属；
它不能替代设备健康和机械安全检查。就绪有效期与 executor 约定见[客户端等待](client_waits.md)。

## 控制循环

```text
发布目标 → 异步观察 SDK 接受/发送/协议确认 → 检查新鲜角度 → 误差与稳定时间满足 → 到位
```

连续命令使用 best-effort、depth 1 和 latest-wins；业务按最新目标设计，不能假设历史
setpoint 全部下发。`SUPERSEDED` 表示目标在 transport claim 前确认未发送。
高频控制用非阻塞状态机；低频异步调用见[示例](examples.md#常驻-python-客户端)。

| 阶段 | 能证明什么 |
| --- | --- |
| `CommandPublication` | 消息已交给本地 DDS publisher |
| `driver_received_stamp` | 驱动 callback 已收到消息 |
| `ACCEPTED` | SDK 校验通过并接受调度 |
| `DISPATCHED` | 全部请求帧 send 成功 |
| `ACKNOWLEDGED` | 支持 ACK 的协议明确确认 |
| 到位 | 当前连接代次的新鲜反馈满足业务判据 |

Topic 状态用 `(client_id, user_sequence)` 关联，服务写命令用返回的 `command_id`。
直接订阅 `HandCommandStatusBatch` 时遍历 `statuses[]`；客户端已展开批消息并过滤自己的 `client_id`。
状态 `transitions[]` 保存阶段历史，可结合 publisher/driver 时间戳分析延迟。

## 反馈与到位

收到 `HandJointState` 后检查：

- `meta.valid=true`、`meta.stale=false`，代次与当前连接一致。
- `joint_names` 与 verified capability 完全一致。
- 使用 percent/弧度的轴分别具有 `percent_valid`/`physical_rad_valid`。
- 以 `meta.sequence` 判断新设备样本；仅有效性变化也可能发布相同 sequence。

只对新鲜有效样本计算误差和稳定时间；丢样、过期、断连或换代次时重置到位窗口。
raw、percent、物理弧度是独立表示，不能互相冒充；配置速度、限制值和实时测量的区别见[型号指南](models.md)。

## 错误与恢复

按稳定 `error_code` 分支，不解析中英文 message。`validation` 修正输入，
`unsupported_operation` 按能力禁用功能，`queue_full` 降低提交频率，
`identity_mismatch`、反复 transport 错误和设备 fault 应停止业务控制并诊断。
Topic 在 SDK 接受前的拒绝可能只出现在 diagnostics，不能只等待 status。

断线、恢复或代次改变时停止目标，清空 pending 和到位窗口；不要排队等待补发。
恢复重新校验身份和 baseline 后，再确认 fault 与安全条件并显式产生新目标。
恢复不重放目标，也不自动清 fault、enable 或 calibrate。

## 停止与多设备

先停止业务目标，再 deactivate 驱动，最后 cleanup/shutdown 释放连接。
驱动失活不会隐式执行保持、全开或握拳；业务需要的停止动作应有明确目标、反馈与超时。
关闭失败需处理并确认资源释放，不能立即在同接口启动另一驱动。

每只手使用独立物理通道、namespace、客户端及反馈状态机。
`multi_hand.launch.py` 提供组启动与失败回滚，参数见[多设备配置](configuration.md#多设备)。
namespace 不能隔离同一总线上的设备报文，也不能保证不同型号有相同关节数或能力。
