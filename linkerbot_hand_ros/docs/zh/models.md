# 型号功能与 ROS 用法

[English](../models.md) · [使用手册](../../README_zh.md)

先完成[连接](connection.md)，再按型号选择功能。所有型号均支持身份、能力、角度、速度设置、
电流上限、实时电流、温度、故障和触觉；具体可用性取决于已连接设备的 capability 和传感器。

| 型号 | 关节数 | 总线 | SDK 功能与关节顺序 |
| --- | ---: | --- | --- |
| [L6](#l6) | 6 | CAN | [L6 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/zh/src/reference/tutorials/l6.md) |
| [O6](#o6) | 6 | CAN | [O6 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/zh/src/reference/tutorials/o6.md) |
| [L20Lite](#l20lite) | 10 | CAN | [L20Lite SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/zh/src/reference/tutorials/l20lite.md) |
| [L20](#l20) | 16 | CAN | [L20 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/zh/src/reference/tutorials/l20.md) |
| [O20](#o20) | 16 | CAN FD | [O20 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/zh/src/reference/tutorials/o20.md) |
| [L30](#l30) | 17 | CAN FD | [L30 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/zh/src/reference/tutorials/l30.md) |
| [O30](#o30) | 20 | CAN FD | [O30 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/zh/src/reference/tutorials/o30.md) |

## 通用用法

- `~/capabilities`：读取 `joints` 的顺序、数量、raw 范围、percent 方向，以及支持的命令和读取模式。
- `~/state/angles`：订阅角度；`~/command/angles` 或 `HandCommandClient` 发送 raw/percent 目标。
- `~/command/speeds`：速度设置；`~/state/measured_speeds` 是实际速度，`configured_speeds` 是配置。
- `current_hz`、`temperature_hz`、`faults_hz`：按需启用实时状态轮询；触觉见[字段指南](force.md)。

raw 是协议原值。屈伸轴 percent 为 0=弯曲、100=伸直，方向轴读取 `percent_mapping`。
ROS 不提供 SDK 的所有同名 getter；实时数据通过轮询与 Topic 获取，按需配置读取通过服务。
代码及命令格式见[示例](examples.md)，完整入口见 [ROS API](ros_api.md)。

## L6

六关节角度及速度控制。`get_configured_speeds` 返回设备速度写回包，须先有有效写入。
`torques` 是原始输出/模式值：0 为位置模式，1..255 为力矩模式输出等级，并非实测 N·m。
切回位置模式不会自动设置角度；再次发角度前确认模式状态。`torques_hz` 控制模式回读轮询。

另外支持电流限制查询、堵转设置与查询、清错、`save_parameters`，以及控制增益和限位补偿：

| 名称 | 原值范围 | 含义 |
| --- | --- | --- |
| `position_kp` | 0..200 | Kp = raw × 10；默认 50 |
| `position_kd` | 0..255 | 默认 21；建议 ≤40 |
| `torque_kd` | 0..255 | 默认 1；物理比例未知 |
| `limit_compensations` | 0..255 | 协议计数；物理比例/方向未知 |

四项均有 `command/<name>`、`set_<name>`、`get_<name>` 和 `state/<name>`。
配置写入共用有界 FIFO，不自动换模式或掉电保存。限位补偿需六字节精确回显才确认成功。
范围及冲突说明以 capability 为准；推荐值不是安全认证或强制上限。没有增益/补偿轮询参数。

## O6

六关节角度、速度和加速度设置。速度配置可主动查询；加速度范围 0..254，0 是设备定义的最大加速度。
电流上限读取返回完整设备写回包缓存，实时电流独立查询。恢复后需新的有效写回包才能读取限制。
支持堵转读取/设置和 `save_parameters`，不提供清错。fn 为五指 10×4 触觉点阵。

## L20Lite

十关节角度、速度、加速度和电流限制设置。速度/加速度/电流限制读取使用设备写回包缓存；
实时速度与电流独立查询。堵转配置只提供写入和已确认写回包状态，没有 `get_stall_protection`。
不提供清错或掉电保存。

fn 为五指 12×6 点阵；fns、fts、fds、px 为独立查询的五指标量。
fns 由设备提供，不由点阵求和；fds 保留方向编码和有效性，不换算角度。

## L20

十六关节角度、速度和电流限制设置，可读取实时速度、电流、温度、故障与 fn 点阵，并支持清错。
没有配置速度或电流限制的回读服务；实时电流不能当作限制回读。

## O20

十六关节 CAN FD 设备，支持角度、速度、电流限制、实时速度/电流、温度、故障、fn 点阵和清错。
配置速度与电流限制可以主动查询。不提供加速度设置。

## L30

十七关节 CAN FD 设备，配置 `side` 为空。支持角度、速度、电流限制和实时速度/电流等状态。
配置速度及电流限制 getter 读取本地已发送命令缓存；它不证明设备确认，恢复后缓存失效。

`enable`、`disable`、`calibrate` 使用 `SubmitCommand` 服务，按 command status 观察协议结果。
标定是显式操作，不会在启动或恢复时自动执行。

## O30

二十关节 CAN FD 设备。支持角度、速度、加速度、电流限制、转矩限制和运动时间设置；
对应配置可主动查询，还可轮询实测电流、实测转矩和电压。支持堵转读取/设置。

`current_limits` 与 `torques_limits` 是不同配置对象；`torques_hz` 读取实测转矩，
并不使 `command/torques` 可用。角度命令回包是否提供反馈，读取 `returns_current_state`。

触觉由实际 descriptor 决定。先检查 `force_fields.support_known/supported`，再选择 fn/fns/ft/fts/fd/fds/px。
TASHAN_GATHER 的 fn/ft/fd/px 为每指单值；没有 FnS 时不发布五指法向合力。详见[触觉指南](force.md)。

## 配置读取的三种结果

`read_mode=query` 为主动查询，`command_response` 为设备写回包缓存，`command_cache` 为本地已发送命令缓存。
缓存读取不刷新 sequence 或采集时间；成功响应仍可能 stale。任何模式都应检查 `state.meta`。
完整电流/转矩接口对应关系见 [ROS API](ros_api.md#按需读取配置与限制状态)。
