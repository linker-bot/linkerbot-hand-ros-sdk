# 故障排查

## 自动发现与部署加载故障

扫描无设备、多候选、库/权限、通道选择、配置文件和身份匹配错误见[发现与部署排障](discovery_troubleshooting.md)。
保留同一次尝试的扫描摘要、原始 cause、配置路径和 Lifecycle 错误，避免只截取最后一行。

## 环境或包找不到

每个终端按顺序加载 ROS、venv、workspace：

先设置 `export LINKERBOT_ROS_DISTRO=humble` 或 `export LINKERBOT_ROS_DISTRO=jazzy`。

```bash
source "/opt/ros/${LINKERBOT_ROS_DISTRO}/setup.bash"
source "$HOME/venvs/linkerbot-hand-${ROS_DISTRO}/bin/activate"
source "$HOME/linkerbot_${ROS_DISTRO}_ws/install/setup.bash"
ros2 pkg executables linkerbot_hand_ros
python -c 'import sys, linkerbot_hand; print(sys.executable); print(linkerbot_hand.__file__)'
```

不要混用 ROS 发行版或其他 Python 环境。包缺失按[安装](getting_started.md)构建；
SDK 路径错误或更新后 ROSIDL 类型不一致，按[更新](update.md)重装源码并一起重建消费者。

## DDS 崩溃或离线测试间歇超时

在独立终端和空闲发现域运行离线测试，见[本地检查](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-ros2/src/branch/main/scripts/README.md)。
驱动 pytest 默认设置 `ROS_DOMAIN_ID=87`、`ROS_LOCALHOST_ONLY=1`，保留显式设置，
测试前检查域内是否已有其他 ROS 节点。并行 worker 使用不同域号。
这是测试发现域隔离措施，不能据此确定原生 DDS 崩溃的根因。

出现 `sequence size exceeds remaining buffer`、非预期 graph 节点或原生崩溃时，
保留 ROS/RMW/Fast DDS 版本、域号、graph 和原生线程栈；Python 栈不能单独确定
故障 DDS 线程。生产系统中需要通信的节点必须使用约定的同一域，变更时需同步
所有通信方。隔离域的 fake 设备测试通过，不代表生产组网和实机行为已验证。

## configure 或 activate 失败

configure 检查静态参数：型号/side、JSON 字段、速率/队列/超时范围及 polling 能力。
L30 的 side 为空。activate 才打开连接、验证身份并读取 baseline。

```bash
ros2 param dump /linkerbot_hand
ip -details -statistics link show can0
ros2 topic echo --once /diagnostics
```

激活失败先检查供电、接线、终端电阻、接口 UP、CAN/FD 模式、速率及设备地址。
`identity_mismatch` 按实际连接身份排查；`unsupported_firmware` 按错误正文定位不支持的操作，
不能仅凭错误码推断整台设备无可用 profile。关闭失败需先处理资源释放，再重试。
静态参数需 deactivate、cleanup 后修改；流程见[配置](configuration.md)。

如果清理报告 worker 或回调未退出，驱动会保留其 ROS 实体和 SDK 所有者。
处理日志中的超时后重试 cleanup 或节点销毁；再次 configure 必须先成功释放上次配置，
才会创建替代对象。清理未完成时会拒绝激活和参数修改。进程退出时先等待已提交的回调
结束，再销毁实体；等待超时会报告清理未完成，不会强制释放仍被使用的资源。

## active 但没有状态，或状态频率低

```bash
ros2 lifecycle get /linkerbot_hand
ros2 topic echo --once /linkerbot_hand/capabilities
ros2 param get /linkerbot_hand angles_hz
ros2 param get /linkerbot_hand angle_feedback
ros2 param get /linkerbot_hand force_hz
ros2 param get /linkerbot_hand publish_rate_hz
```

使用与驱动兼容的 best-effort 状态订阅。除角度外，多数通道默认不轮询；但写命令回包也能更新缓存，
因此 polling=0 不等于绝无状态。`publish_rate_hz=0` 暂停状态发布；正值控制空闲时的有效性复查，
新缓存立即唤醒发布。相同 sequence 的有效性变化不是新设备样本。

看 diagnostics 的 requested/achieved Hz、completed reads、feedback samples、timeouts、age、
route miss 和 bus error，区分总线、设备与 ROS 接收问题。频率评估见[测试工具](frequency_benchmark.md)。

## 个别查询、服务或角度表示不可用

以最新 capability 为准，检查 `firmware_unsupported_telemetry`；可选查询连续失败可能被 SDK
停用，而连接继续工作。恢复连接后重新探测。全部请求无响应时先查总线和供电。
服务不存在时先确认型号能力；配置回读服务成功后仍需检查来源、有效性和采样时间。

`percent_valid=false` 或 `physical_rad_valid=false` 表示该表示没有可信映射，
占位 0 不能当作实测角度。原始回复保留在 raw 中。

## 命令被拒绝、被覆盖或未运动

核对 active、设备是否恢复中、命令能力、非零 `client_id`、序号、数组长度、有限数值和 raw 整数范围。
按 `command/status` 的 `statuses[].error_code` 处理；SDK 接受前的拒绝可能只在 diagnostics 中。

`ACCEPTED` 只代表 SDK 接受。继续观察 DISPATCHED、ACKNOWLEDGED、FAILED、SUPERSEDED；
机械到位需当前代次的新鲜角度。L6 要核对位置/力矩模式。
连续目标 latest-wins，大量 SUPERSEDED 时检查提交速率与实际发送能力，不能靠增大 FIFO 保留轨迹。
详见[业务集成](business_integration.md)。

## 服务超时、恢复与关闭失败

查询和 recover 经有界 admin worker 执行，超时必须满足[配置约束](configuration.md)。
`queue_full` 时减少并发管理请求；不要在单线程 executor 回调里同步等待服务或命令状态。

恢复不重放目标，成功后等新代次有效反馈并显式提交新目标。
关闭前停止业务和服务请求，再 deactivate、cleanup。若 close 超时或线程未退出，
记录原始 cause、backend、线程/FD 状态并确认资源释放，避免同一接口重复打开。

[返回总览](getting_started.md) · [English](../troubleshooting.md)
