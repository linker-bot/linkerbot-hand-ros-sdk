# ROS 2 API Reference

默认节点名为 `/linkerbot_hand`。所有向量顺序、范围、单位说明和支持性均读取
`/linkerbot_hand/capabilities`，ROS 不维护第二份型号表。

多设备入口会在同一进程中创建多个 `/namespace/linkerbot_hand`，每个节点的 Topic、Service
和 Lifecycle 名称都位于自己的 namespace。相同物理 transport key 只在这个进程内共享
runtime 和总线仲裁；独立进程不共享。

## 元数据

读取 `~/capabilities.commands` 中 `semantic="angles"` 的
`returns_current_state`，可判断角度写命令回包是否包含可用作反馈的当前状态。
该标记与 `ack_support` 独立，不表示目标回显、协议 ACK 或机械到位。
`angles_hz>0` 时，SDK 会拒绝在此标记为 false 的设备上启用
`command_feedback_only`。程序应读取所连接 SDK 的能力字段，不硬编码型号表；
Hand #148 的 O30 角度反馈修复也会更新该值。

能力 schema `1.5` 包含此字段、`force_fields`、`payload_projection` 和扩展身份信息，改变相关
ROSIDL 类型。需同时重建消息包、驱动、GUI 和所有外部能力消息
消费者；新旧构建不能混用，revision 字符串不能解决底层类型不兼容。

| Topic | 类型 | QoS | 内容 |
| --- | --- | --- | --- |
| `~/capabilities` | `linkerbot_hand_msgs/msg/HandCapabilities` | reliable + transient local | configure 发布 declared capability，activate 后发布 verified capability |
| `~/device_info` | `linkerbot_hand_msgs/msg/HandDeviceInfo` | reliable + transient local | 型号、side、序列号、PCB/固件/机械版本、传感器变体和原始身份 |

`HandCapabilities` 包含：

- `identity`：型号、side、固件、硬件、机械和传感器变体及 verified 状态。
- `joints`：关节名称、顺序、运动类型、协议 raw 范围、percent 方向和可选物理角度映射。
- `commands`：命令语义、通道、raw 范围/编码/单位说明、percent 映射和 ACK 能力。
- `telemetry`：读取模式、shape、推荐/实测频率、过期时间、事务成本和是否设备实测。
- `firmware_unsupported_telemetry`：当前连接代已探测为固件不支持的查询语义；协议 metadata
  仍保留在 `telemetry` 中，但驱动不会再收到该通道的新样本。
- `stall_protection`、`transport` 和 `operations`。

`identity` 和 `HandDeviceInfo` 同步包含转接板、控制板、bootloader 版本，协议名称/版本、
供电范围、MCU UID、编译时间、接口列表和 `reported_side`。缺失项使用 `has_*` 或
`VersionField.available` 标记；`reported_side` 表示设备身份提供的侧别证据，区别于配置/解析后的 `side`。

SDK 在运行时完成旧固件单功能降级后，驱动会重新发布 transient-local capability。业务节点
应把新消息视为当前连接代的有效能力，不要只缓存 configure 阶段的 declared capability。

## 角度命令

Topic：`~/command/angles`

类型：`linkerbot_hand_msgs/msg/HandJointCommand`

```text
uint64 client_id
uint64 user_sequence
builtin_interfaces/Time publisher_stamp
uint8 representation
float64[] values
```

- `client_id`：发布者实例的非零关联标识，与 `user_sequence` 共同构成命令键。
- `publisher_stamp`：发布者 ROS 时钟下的发送时刻；`HandCommandClient` 自动填写。
- `REPRESENTATION_PERCENT=1`：严格 `0..100`。屈伸轴为 0 弯曲、100 伸直；方向轴按
  capability endpoint label 解释。
- `REPRESENTATION_RAW=2`：设备协议原值，不做 percent、方向、LUT 或物理单位转换。
- 长度必须等于 capability 关节数量，整数 raw 通过 ROS float64 传输时必须是整数形式。

```bash
ros2 topic pub --once /linkerbot_hand/command/angles \
  linkerbot_hand_msgs/msg/HandJointCommand \
  '{client_id: 1, user_sequence: 101, representation: 1, values: [50, 50, 50, 50, 50, 50]}'
```

命令行未填写 `publisher_stamp` 时该字段为零，因此不能计算发布到驱动接收延迟；正式控制与
性能测试应使用 `HandCommandClient`。并行发布者必须使用不同的非零 `client_id`。

## 其他命令

以下 Topic 使用 `linkerbot_hand_msgs/msg/HandRawCommand`，同样包含 `client_id`、
`user_sequence`、`publisher_stamp` 和 `raw[]`：

| Topic | SDK 语义 |
| --- | --- |
| `~/command/speeds` | configured speed，不等于实测速度 |
| `~/command/accelerations` | configured acceleration |
| `~/command/current_limits` | 电流上限，不等于真实扭矩 |
| `~/command/torques_limits` | O30 `0x06` 转矩限制原值，与 `0x04` 电流限制分开 |
| `~/command/torques` | 只有 capability 确认为真实扭矩时存在 |
| `~/command/motion_times` | 协议 motion-time 配置 |
| `~/command/limit_compensations` | 逐关节限位补偿原值，当前仅 L6 声明 |
| `~/command/position_kp`、`~/command/position_kd`、`~/command/torque_kd` | L6 逐关节控制增益原值 |

驱动 active 后只创建 capability 支持的订阅。命令 Topic 使用
best-effort + keep-last(1)，不保证每条发布都进入 SDK。SDK 中角度、速度、电流上限、
转矩上限和扭矩使用独立 latest slot；加速度、运动时间、限位补偿和控制增益属于有界 FIFO 配置。
需要明确接纳结果的低频限位补偿或控制增益配置优先使用下方可靠服务。

## 命令阶段

Topic：`~/command/status`

类型：`linkerbot_hand_msgs/msg/HandCommandStatusBatch`，reliable QoS。每次消息的
`statuses[]` 最多包含 512 条发生变化的 `HandCommandStatus`，调用方必须逐条遍历。

| stage | 精确定义 |
| --- | --- |
| `ACCEPTED=1` | 参数、能力和生命周期校验通过，进入 SDK 有界调度器 |
| `DISPATCHED=2` | transport 对该命令全部请求帧实际 send 成功 |
| `ACKNOWLEDGED=3` | 设备协议返回可关联的明确正向 ACK |
| `FAILED=4` | 编码、发送、超时、协议拒绝、断线或通信失败 |
| `SUPERSEDED=5` | transport claim 前被同类新目标覆盖，确认未发送 |

不支持设备 ACK 的型号 `ack_support=ACK_UNSUPPORTED`，成功终态为 `DISPATCHED`。
任何 stage 都不表示机械到位。用 `(client_id, user_sequence)` 将业务目标与 status 对应；
`command_id` 是 SDK 内部命令标识。`publisher_stamp` 原样回传发布时刻，
`driver_received_stamp` 是驱动 callback 入口时刻，`transitions[]` 保留 SDK 每个阶段的时刻；
统计 DISPATCHED 必须检查完整历史，不能用最终 ACKNOWLEDGED 代替。

## 角度状态

Topic：`~/state/angles`

类型：`linkerbot_hand_msgs/msg/HandJointState`

- `joint_names[]`：本消息的关节顺序。
- `raw[]`：设备协议真实回复，永不因 percent 映射未知而丢失。
- `percent[] + percent_valid[]`：capability 可转换轴的 percent。
- `physical_rad[] + physical_rad_valid[]`：仅经可信物理标定的轴有效。
- `meta`：采集时间、sequence、age、valid、stale、连接代次、来源和范围状态。

角度命令返回的当前设备状态使用 `ORIGIN_DEVICE_COMMAND_FEEDBACK`；它是反馈样本来源，
不表示目标原样回显，也不表示协议 `ACKNOWLEDGED`。

三套数值来自同一次 SDK 样本，不应为另一种表示再次查询设备。不要把 percent 或 raw 填入
标准 `sensor_msgs/JointState.position`；该字段要求弧度。

## Telemetry 与触觉

通用协议 raw 状态使用 `linkerbot_hand_msgs/msg/HandTelemetry`：

```text
semantic, channel_names[], raw[]
raw_unit, raw_scale_note, unit_confidence
device_measured, device_queried, meta
```

可能出现的状态 Topic：

- `~/state/measured_speeds`
- `~/state/configured_speeds`
- `~/state/configured_accelerations`
- `~/state/currents`
- `~/state/current_limits`
- `~/state/torques_limits`
- `~/state/torques`
- `~/state/temperatures`
- `~/state/faults`
- `~/state/voltages`
- `~/state/motion_times`
- `~/state/limit_compensations`
- `~/state/position_kp`、`~/state/position_kd`、`~/state/torque_kd`（当前仅 L6）
- `~/state/force`（标量 force profile）

`raw_unit/raw_scale_note` 只是 capability 说明。ROS 不将 count 自动换算为 RPM、mA、N.m；
协议字段本身以 mA 表示时 raw 数字才直接是 mA。

矩阵触觉发布到 `~/state/tactile`，类型 `HandTactileState`。每个 `TactileMatrix` 包含
finger name、rows、columns 和 row-major raw；一个消息代表一次完整多指事务，不按关节或
单指计算频率。

force capability 的 `payload_projection` 决定公共发布契约：

| 投影 | 话题 | 数据 |
| --- | --- | --- |
| `tactile_matrix` | `~/state/tactile` | 矩阵触觉，当前六个非 O30 型号 |
| `tactile_descriptor` | `~/state/tactile_sensors` | O30 五指身份、metadata、fields 和 raw_bytes |
| `tactile_descriptor` 且五指都有标量 FnS | `~/state/normal_force_resultant` | 从同一 force 样本提取的五指合力，无额外设备查询 |
| `raw_vector` | `~/state/force` | 标量 force；当前没有型号声明 |

`HandCommandClient.telemetry_capability("force")` 返回能力副本；未收到能力、未声明或固件禁用时
返回 None，不产生设备 I/O，也不代表驱动已 active。外部节点可直接读取能力消息中的同名字段。

`HandTactileSensor.maximum_rows/maximum_columns` 替代旧 `rows/columns`，同时保留
`requested_rows/requested_columns`、`selected_sensor`、`available`、
`valid_data_position_mode`、`rectangle_fill`。最大尺寸和请求尺寸都不能用来强行 reshape
返回数据，实际字段数量和字节偏移以 descriptor 为准。明确缺失的手指保留身份与空字段/字节，
不表示零力；缺少任一手指 FnS 时不发布五指合力。合力为设备 FnS 原值，不由矩阵求和或换算成 N。

统一触觉使用 `~/state/force_fn`、`force_fns`、`force_ft`、`force_fts`、
`force_fd`、`force_fds`、`force_px`，类型为 `HandForceField`。
支持表、单位、缺失值、共享查询和频率参数见[统一触觉字段](force.md)。

故障解释中的 `supported_flags` 列出当前协议有定义的标志；其他 false 字段不代表
设备确认正常。L20Lite 保留原字节、未知位以及负载过载、过流、过热、磁编码异常、
过压/欠压解释，不支持清错。堵转维持输出统一使用 `hold_current` 和
`has_hold_current`，包括 L20Lite C7；旧 `hold_torque/has_hold_torque` 已删除。
schema 1.5 需要一起重建消息包、驱动、GUI 和外部消费者。

`~/state/fault_statuses` 的 L6/L20 具名字段与 SDK 一致：

| 型号 | 字段与含义 |
| --- | --- |
| L6 | `mcu_over_temperature` MCU 过温；`motor_over_temperature` 电机过温；`overload_2`、`overload_1` 两种过载标志；`phase_a_over_current`、`phase_c_over_current`、`phase_b_over_current` 分别为 A/C/B 相过流 |
| L20 | `motor_communication_abnormal` 电机通信异常；`soft_rotor_lock` 软堵转；`motor_self_test_abnormal` 电机自检异常；`motor_stall` 失速；`motor_rotor_lock` 堵转；以及 `over_temperature`、`over_current`、`voltage_abnormal` |

L6 不把 MCU 与电机过温合并为通用过温，也不合并各相过流。L20 软堵转与失速、堵转
分别保留；软堵转可能在抓握时出现、释放后自动解除，不表示清错命令。`raw`、保留位和
文字解释仍原样提供。新增字段改变了嵌套的 ROS 故障消息类型，发布方与所有订阅方必须
一起重建消息包和依赖包；不能混用旧版故障消息。

## 堵转状态

`~/state/stall_protection` 使用 `HandStallProtectionState`，分别保存 detection times、
thresholds 和 hold currents 三个 raw 样本及独立元数据。协议范围不等于已验证安全范围；
`safety_range_verified=false` 时不要做极限写入。

L20Lite C5/C6/C7 分别对应阈值、判定时间和维持电流：三个 setter 服务均可用，
使用同一 FIFO 配置队列。每项只有两组写回显都通过校验才成为有效状态；
该型号没有主动读取配置的协议契约，不创建 `~/get_stall_protection` 服务。
`~/state/stall_protection` 保留各字段的有效性和原始回显时间，不发送补充查询。

## 管理服务

| Service | 类型 | 说明 |
| --- | --- | --- |
| `~/get_device_info` | `GetDeviceInfo` | 主动刷新身份和全部支持版本字段 |
| `~/get_stall_protection` | `GetStallProtection` | 在一个总 timeout 内读取三项堵转配置 |
| `~/get_configured_speeds` | `GetRawValues` | 配置速度；按能力查询设备或读取写入回包/本地命令缓存 |
| `~/get_configured_accelerations` | `GetRawValues` | 配置加速度 |
| `~/get_current_limits` | `GetRawValues` | 电流上限；按能力查询设备或读取写回包/本地命令缓存，L20 不提供 |
| `~/get_torques_limits` | `GetRawValues` | O30 `0x06` 转矩限制配置，不是实时转矩 |
| `~/get_motion_times` | `GetRawValues` | 运动时间配置 |
| `~/set_stall_detection_times` | `SetRawValues` | 非阻塞提交 raw 配置 |
| `~/set_stall_thresholds` | `SetRawValues` | 非阻塞提交 raw 配置 |
| `~/set_stall_hold_currents` | `SetRawValues` | 非阻塞提交 raw 配置 |
| `~/get_limit_compensations` | `GetRawValues` | 主动查询限位补偿原值、单位说明及采集元数据 |
| `~/set_limit_compensations` | `SetRawValues` | 非阻塞提交 FIFO 配置，明确返回接纳或队列满 |
| `~/get_position_kp`、`~/get_position_kd`、`~/get_torque_kd` | `GetRawValues` | L6 按需查询增益原值和元数据 |
| `~/set_position_kp`、`~/set_position_kd`、`~/set_torque_kd` | `SetRawValues` | L6 增益有界 FIFO 接纳，异步等待协议确认 |
| `~/save_parameters` | `SubmitCommand` | capability 支持时持久化配置；有协议 ACK 的设备等待明确确认 |
| `~/clear_faults` | `SubmitCommand` | 独立有界 FIFO 的清错命令 |
| `~/enable` / `~/disable` / `~/calibrate` | `SubmitCommand` | capability 支持时提交 |
| `~/recover` | `Recover` | 重新验证身份、清旧目标并读取 baseline 的安全恢复 |

```bash
ros2 service call /linkerbot_hand/get_device_info \
  linkerbot_hand_msgs/srv/GetDeviceInfo '{timeout_s: 0.2}'
ros2 service call /linkerbot_hand/clear_faults \
  linkerbot_hand_msgs/srv/SubmitCommand '{}'
```

O6 的三项堵转配置顺序由 SDK capability 决定：threshold=`C5`、detection time=`C6`、hold
current=`C7`。ROS 只收发 raw；当前资料给出的解释分别为 `1000/255 mA/count`、
`10 ms/count`，以及统一为维持电流、但旧资料称堵转扭矩且比例未经验证的项目。
写入成功后如需掉电保留，先等
对应 command status 到达 `ACKNOWLEDGED`，再调用 `save_parameters` 并等待它的 ACK；该操作
不会自动重启设备。

主动读取在独立、有界 admin worker 中执行，不阻塞控制 callback。setter/离散服务的
`accepted=true` 仅表示进入 SDK，后续阶段看 `/command/status`。服务错误通过稳定
`error_code` 返回，调用方不能解析 message 文本分类。

## 按需读取配置与限制状态

上述 `GetRawValues` 入口在 configure 时按 telemetry capability 创建，在 active
状态下调用，直接复用 SDK getter。只有写命令能力不代表存在可读通道。订阅
`~/state/<semantic>` 只是观察缓存，不会触发设备查询；主动查询成功后更新 SDK 缓存，
启用状态发布时会发布变化后的样本。调用这些服务不增加轮询通道，也不发送配置写命令。

读取 `~/capabilities.telemetry` 中的 `read_mode`，区分以下行为：

| `read_mode` | 调用行为 | 当前示例 |
| --- | --- | --- |
| `query` | 请求调用之后的新设备样本 | O6 配置速度/加速度/电流上限；O30 运动时间 |
| `command_response` | 返回最近一次有效的设备写入回包，不发新查询 | L6 配置速度；L20Lite 配置速度/电流上限 |
| `command_cache` | 返回最近一次有效的本地已发送命令缓存，不表示设备已确认，不发新查询 | L30 配置速度/电流上限 |

L20/L20Lite 的实时电流由 `current_hz` 轮询并发布到 `~/state/currents`，
保留 `device_measured=true`；L20 仍没有电流限制回读服务。
使用已隔离 L20Lite 设置回显的 Hand SDK 源码时，L20Lite 的
`~/get_configured_speeds`、`~/get_current_limits` 按 `command_response` 读取缓存。
`~/command/speeds`、`~/command/current_limits` 收齐两组有效写回包后才进入
`ACKNOWLEDGED`；设备实际回值发布到 `~/state/configured_speeds`、`~/state/current_limits`，
来源为 `ORIGIN_DEVICE_CONFIG_RESPONSE`，`device_measured=false`、`device_queried=false`。
读取服务不发设备请求，不刷新样本 sequence 或采集时刻；尚无完整回显时返回
`unsupported_operation` 和无效状态。实时速度、电流的查询与轮询仍与写回显分开。
此行为需要包含 L20Lite 设置回显缓存支持的 Hand SDK，无需修改 ROS 消息。
O30 的实时电流与转矩分别使用
`current_hz` / `torques_hz`，发布到 `~/state/currents` / `~/state/torques`；限制值分别使用
`~/get_current_limits` / `~/get_torques_limits` 服务，发布到对应限制状态话题。
所有型号均透传 SDK 的原始单位、比例说明，不增加物理换算。

原 `effort_limits` 名称已删除，迁移如下：

| 型号 | 原命令 `effort_limits` / 客户端 `set_effort_limits()` | 原状态 / 读取服务 |
| --- | --- | --- |
| L20 | `current_limits` / `set_current_limits()` | 状态改为 `currents`；使用 `current_hz`，无限制回读 |
| L20Lite | `current_limits` / `set_current_limits()` | 实时 `currents` 使用 `current_hz`；独立的 `current_limits` 状态/服务保留完整写回显，不发查询 |
| O20 | `current_limits` / `set_current_limits()` | `current_limits` / `get_current_limits` |
| O30 | `torques_limits` / `set_torques_limits()` | `torques_limits` / `get_torques_limits` |

O30 `0x04` 现有电流接口保留，与 `0x06` 转矩对象独立；当前各型号均未声明
`set_torques()` 命令，转矩限制设置不代表开放实时转矩目标控制。

成功响应的 `state` 保留 raw、通道名称、单位、比例说明、可信度及 `meta`。读取回包或
缓存不会刷新原采集时刻和 sequence；age/stale 按读取时刻计算，因此 `success=true`
的缓存仍可能 `meta.stale=true`。`device_queried` 表示通道能力，不代表每条已发布样本
都来自查询；某条样本的来源看 `meta.origin`。回包/缓存模式的 message 会说明未执行设备
查询，程序判断应使用结构化元数据。

先检查 `success` 再使用 `state`。回包/缓存尚无有效样本时返回 `unsupported_operation`，
不会为了取得数据而代发写命令。当前固件不支持某可选查询时，入口保留，SDK 完成降级后
返回 `unsupported_firmware`。inactive 或正在关闭时返回 `device_not_ready`；timeout
参数非法返回 `validation`；SDK 超时、协议等错误保留原有稳定错误码。`timeout_s` 必须
有限且大于零，并为 `shutdown_timeout_s` 留出管理 worker 的结束余量。服务不增加固件
版本门槛；查询仍与命令共享 SDK 设备/总线调度，应在总线预算内按需调用。

## L6 控制增益

三个增益使用 SDK 同名接口，只在当前型号声明对应能力时开放；当前为 L6。每次提交
六关节原值，顺序见 `~/capabilities`，不会自动转换物理值、切换控制模式或保存到非易失存储。

| 名称 | 协议码 | 原始范围与解释 | ROS 客户端 setter |
| --- | --- | --- | --- |
| `position_kp` | `0x06` | `0..200` 整数；位置模式；协议 Kp = raw × 10，默认 raw 50；通用字节范围与 Kp 上限有冲突，按 SDK 能力取值 | `set_position_kp(values)` |
| `position_kd` | `0x07` | `0..255` 整数；位置模式；默认 21，建议不大于 40，建议值不是强制上限 | `set_position_kd(values)` |
| `torque_kd` | `0x08` | `0..255` 整数；力矩模式；默认 1，没有明确物理单位或比例 | `set_torque_kd(values)` |

Kd 原表概述 `0..255` 与逐字节说明 `1..255` 有冲突，ROS 沿用 SDK 能力，不另加范围。
各通道的 `raw_unit`、`raw_scale_note`、`unit_confidence` 保留 SDK 描述；ROS 收发仍为原值。

每个名称都对应以下通路，例如 `position_kp`：

- `~/command/position_kp`：`HandRawCommand`，与 `HandCommandClient.set_position_kp()` 对应。
- `~/set_position_kp`：`SetRawValues`，可靠服务提交，`accepted` 只代表有界 FIFO 接纳；
  队列满返回 `queue_full`，后续通过命令状态观察 `ACKNOWLEDGED` 或失败。
- `~/get_position_kp`：`GetRawValues`，在 active 状态按需查询设备。
- `~/state/position_kp`：`HandTelemetry`，只发布 SDK 缓存变化；订阅不会发 CAN 请求。

`position_kd`、`torque_kd` 使用同样命名。写回包与配置查询保留 SDK 样本来源，均不是
关节运动实测量。没有新增增益轮询参数，不应把这些配置加入默认高频采集。

```bash
ros2 service call /linkerbot_hand/get_position_kp \
  linkerbot_hand_msgs/srv/GetRawValues '{timeout_s: 0.2}'
```

## L6 限位补偿

入口按 command/telemetry capability 创建，当前只有 L6 声明。协议 `0x38` 携带六个
`0..255` 整数，顺序为 `thumb_flex`、`thumb_abd`、`index`、`middle`、`ring`、`pinky`。
单位为原始 `count`，物理比例和正负方向未知；ROS 不换算成角度或百分比。

`HandCommandClient.set_limit_compensations(values)` 会校验已确认身份的 capability、
驱动 active、长度、整数与范围，再发布到 `~/command/limit_compensations`。
返回 `CommandPublication` 只说明消息已发布。Topic 沿用 best-effort、keep-last(1)；
在 SDK 接纳前发生的拒绝记入 diagnostics，此时没有 command handle，也不会产生该命令
的状态。需要逐次确认接纳时，使用可靠的 `~/set_limit_compensations` 服务。

SDK 接纳后，`CommandFamily.LIMIT_COMPENSATION` 与其他 FIFO 配置、离散操作共用
`discrete_queue_capacity` 限定的有界队列，保持顺序，不使用新值覆盖待执行旧值。
队列满时 setter 服务返回 `accepted=false`、`error_code=queue_full`；
`accepted=true` 只表示已入队，需继续观察 `~/command/status` 的 `ACKNOWLEDGED` 或
`FAILED`。L6 要求六字节精确回显才确认成功；不会隐式调用 `save_parameters()`。
服务命令的 `client_id=0`，按响应中的 `command_id` 关联状态；客户端 Topic 命令仍按
`(client_id, user_sequence)` 关联。

```bash
ros2 service call /linkerbot_hand/get_limit_compensations \
  linkerbot_hand_msgs/srv/GetRawValues '{timeout_s: 0.5}'
```

查询在有界 admin worker 执行。成功响应的 `state` 是 `HandTelemetry`，保留 raw、关节
名称、`raw_unit`、`raw_scale_note`、`unit_confidence` 和 `meta`。失败返回 SDK 稳定
错误码；旧固件连续失败达到可选查询降级条件后返回 `unsupported_firmware`，不按固件
版本限制连接。inactive 时服务返回 `device_not_ready`。

`~/state/limit_compensations` 发布变化后的配置缓存及有效性，包括成功查询和经验证的
写响应。订阅该 Topic 不触发设备 I/O，也不增加轮询频率参数；使用者须检查 `meta.valid`、
`meta.stale`、来源及连接代次。这是配置数据，`device_measured=false`。

使用 `GetRawValues` 服务需重新构建 `linkerbot_hand_msgs` 及依赖它的驱动。新增服务入口
本身不改变服务字段；本次另有上文所述 command capability 消息类型变更，能力消息的所有
消费者也必须一起重建。

## Diagnostics

`/diagnostics` 只映射 `get_health()` 缓存，至少包含：连接状态、连接代次、identity verified、
最后成功收发/事务时间、连续错误、最近错误码、重连次数、命令 pending/覆盖计数、各状态
requested/achieved Hz、`completed_reads`、角度命令反馈数、有效反馈数、反馈策略、
deadline/timeout/age，以及 transport 帧、字节、route miss 和总线错误。

读取 diagnostics 不产生 CAN 查询。需要新 fault 样本时设置 `faults_hz` 或使用 SDK 主动读取；
ROS 不把 health timer 变成故障轮询器。

## 发布规则和 QoS

- 高频命令：best-effort、depth 1、volatile。
- 状态和触觉：sensor-data 风格 best-effort、小深度。
- command status 和 service：reliable、有界。
- capabilities/device info：reliable、transient local。
- SDK 缓存 revision 变化会立即唤醒独立状态发布线程；`publish_rate_hz` 只控制无新数据时
  age/stale 的缓存复查频率，sequence 未变化时不会重复发布旧样本伪装新数据。
