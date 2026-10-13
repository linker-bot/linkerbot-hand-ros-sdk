# ROS 2 API 参考

[English](../ros_api.md) · [使用手册](../../README_zh.md)

默认节点名为 `/linkerbot_hand`。所有向量顺序、范围、单位说明和支持性均读取
`/linkerbot_hand/capabilities`，ROS 不维护第二份型号表。

多设备入口会在同一进程中创建多个 `/namespace/linkerbot_hand`，每个节点的 Topic、Service
和 Lifecycle 名称都位于自己的 namespace。相同物理 transport key 只在这个进程内共享
runtime 和总线仲裁；独立进程不共享。
当前维护范围为一条物理 CAN/CAN FD 通道一只手，随包示例中 L6 左手使用 `can0`、
O6 右手使用 `can1`。共享 runtime 是资源机制，不代表支持同通道多手；namespace
只区分 ROS 实体，不隔离设备报文。

## 元数据

读取 `~/capabilities.commands` 中 `semantic="angles"` 的
`returns_current_state`，可判断角度写命令回包是否包含可用作反馈的当前状态。
该标记与 `ack_support` 独立，不表示目标回显、协议 ACK 或机械到位。
`angles_hz>0` 时，SDK 会拒绝在此标记为 false 的设备上启用
`command_feedback_only`。程序应读取所连接 SDK 的能力字段，不硬编码型号表。

能力 schema `1.5` 包含此字段、`force_fields`、`payload_projection` 和扩展身份信息。
消息包、驱动、GUI 和外部消费者应使用最新 `main` 中一致的 ROSIDL 定义构建。

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

SDK 在运行时完成固件不支持的可选查询降级后，驱动会重新发布 transient-local capability。业务节点
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

发送目标见[O6 命令示例](examples.md#发送一个-o6-角度目标)。

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
| `~/command/torques` | capability 声明的力矩输出/模式原值，当前为 L6，不是已校准 N·m |
| `~/command/motion_times` | 协议 motion-time 配置 |
| `~/command/limit_compensations` | 逐关节限位补偿原值，当前仅 L6 声明 |
| `~/command/position_kp`、`~/command/position_kd`、`~/command/torque_kd` | L6 逐关节控制增益原值 |

驱动 active 后只创建 capability 支持的订阅。命令 Topic 使用
best-effort + keep-last(1)，不保证每条发布都进入 SDK。SDK 中角度、速度、电流上限、
转矩上限使用独立 latest slot；L6 力矩输出/模式、加速度、运动时间、限位补偿和控制增益使用有界 FIFO。
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

### L6 力矩输出/模式

`HandCommandClient.set_torques(values)` 向 `~/command/torques` 发布六个整数原值，
顺序取 capability。L6 `0x03` 接受 `0..255`：逐关节的 0 选择位置模式，`1..255`
选择力矩模式及输出。这些是协议 count，不是已校准 N·m，也不是电流上限。

进入 SDK 后使用共享的有界配置/操作 FIFO，返回位置模式的 0 不能被后续力矩目标覆盖。
ROS Topic 仍为 best-effort、depth 1，因此 FIFO 不保证每条 DDS 发布都被接纳；已接纳
命令通过 command status 关联。SDK 在发送前等待 20 ms，发送后任一轴为 0 时等待
150 ms，否则等待 20 ms，负责模式切换间隔；ROS 不新增另一套定时控制。

合法写回包可能包含之前的输出/模式值，ACK 只确认交换成功，不证明回包等于目标。
`~/state/torques` 保留真实回包；`torques_hz` 控制 SDK 新鲜回读，也可在 SDK 使用
`get_torques()` 主动查询，当前没有 ROS `~/get_torques` 服务。L6 状态保留
`raw_unit="count"`、`device_measured=false`、`device_queried=true` 和
`ORIGIN_DEVICE_CONFIG_RESPONSE`；`device_queried` 表示通道可查询，单次样本来源看
`meta.origin`。回读反映输出/模式原值，不能称为实测物理力矩。电流上限 `0x02` 与
实时电流 `0x36` 继续使用各自独立通道。

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

触觉字段通过 `HandForceField` 发布；点阵、descriptor、FnS、字段有效性及共享查询见
[触觉指南](force.md)。消息结构见[消息包说明](../../../linkerbot_hand_msgs/README.md)。

<a id="o30-tashan_gather-单值字段"></a>
O30 TASHAN_GATHER 提供 fn/ft/fd/px 单值，按实际 descriptor 和 `valid_values` 使用，
不由 ROS 推断物理单位或生成 FnS。

故障解释见 `state/fault_statuses` 的 `supported_flags`、`raw`、`reserved_bits` 和
`descriptions`；未声明字段为 false 不代表设备正常。L6 MCU/电机温度及各相过流、L20
软堵转/失速/堵转等分别保留其 SDK 语义。

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
`10 ms/count`，以及比例未经验证的维持电流。
写入成功后如需掉电保留，先等
对应 command status 到达 `ACKNOWLEDGED`，再调用 `save_parameters` 并等待它的 ACK；该操作
不会自动重启设备。

主动读取在独立、有界 admin worker 中执行，不阻塞控制 callback。setter/离散服务的
`accepted=true` 仅表示进入 SDK，后续阶段看 `/command/status`。服务错误通过稳定
`error_code` 返回，调用方不能解析 message 文本分类。

在 SDK 接纳前被拒绝的 Topic 命令可能只记入 diagnostics，没有 command handle 或状态消息。
需要逐次确认接纳时使用可靠 setter 服务；服务命令 `client_id=0`，按响应的 `command_id`
关联状态。Topic 命令按 `(client_id, user_sequence)` 关联。inactive 返回 `device_not_ready`。

## 按需读取配置与限制状态

`GetRawValues` 入口在 configure 时按 telemetry capability 创建，在 active 时调用。
有写命令不代表有可读通道。主动查询更新 SDK 缓存并经正常状态流程发布；
订阅 Topic 不查询设备，服务读取也不会启用轮询或发送配置写命令。

| `read_mode` | 行为 | 示例 |
| --- | --- | --- |
| `query` | 请求调用之后的新设备样本 | O6 配置速度/加速度、O30 运动时间 |
| `command_response` | 返回有效设备写回包，不产生 I/O | L6 配置速度、O6 电流限制、L20Lite 配置 |
| `command_cache` | 返回本地已发送命令缓存，不证明设备确认 | L30 配置速度/电流限制 |

先检查 `success`，再检查 `state.meta`、原始单位、比例说明和可信度。
缓存保留原采集时刻及 sequence，成功响应仍可能 stale。`device_queried` 是通道能力，
单个样本来源看 `meta.origin`；ROS 不做物理单位换算，程序不应解析响应 message。

电流与转矩接口保持独立：

- 实时电流用 `current_hz` 与 `state/currents`，不会填充或替换电流限制缓存。
- O6 `get_current_limits` 保留完整写回包，回值允许不同于目标。其来源为
  `ORIGIN_DEVICE_CONFIG_RESPONSE`，`device_measured=false`、`device_queried=false`。
  同代次内后续写入失败时，已有有效回包仍可读取，但不证明失败目标生效；恢复后须有新完整回包。
- L20 没有限制回读。L20Lite 速度/电流限制命令收齐两组有效回复才 ACK，
  配置缓存与实时速度/电流独立。
- O30 `0x04` 电流限制和 `0x06` 转矩限制分别有命令、getter 和状态；
  `torques_hz` 读取实测转矩，不代表支持 `command/torques`。
- L6 `command/torques` 是上文定义的输出/模式命令。

各型号设置与操作见[型号指南](models.md)。L20Lite 堵转有三项 setter 和已确认回包状态，
没有 `get_stall_protection`；`hold_current` 为通用的堵转后保持电流字段。

| 失败条件 | 结果 |
| --- | --- |
| 缓存尚无有效样本 | `unsupported_operation` 与无效状态，不代发写命令制造样本 |
| 可选查询已被当前固件能力降级 | `unsupported_firmware`，端点保留 |
| inactive 或关闭中 | `device_not_ready` |
| timeout 非法 | `validation` |
| SDK 超时/协议错误 | 保留稳定 SDK 错误码 |

`timeout_s` 须有限且为正，并为 `shutdown_timeout_s` 留出 worker 结束余量。
查询与命令共用设备/总线调度，应在总线预算内按需调用。

## L6 控制增益

`position_kp`、`position_kd`、`torque_kd` 均提供命令 Topic、可靠 setter 服务、主动 getter
和缓存状态。范围与原值解释见[型号功能](models.md#l6)。写入共用有界 FIFO，
`accepted` 表示接纳；后续协议结果看 command status，不隐式换模式或保存，无增益轮询参数。

## L6 限位补偿

`limit_compensations` 使用六个 0..255 原值，物理比例和方向未知。
Topic/client setter 或 `set_limit_compensations` 提交配置，`get_limit_compensations` 主动查询，
`state/limit_compensations` 发布配置缓存。六字节精确回显才确认 ACK，不自动保存。

## Diagnostics

`/diagnostics` 只映射 `get_health()` 缓存，至少包含：连接状态、连接代次、identity verified、
最后成功收发/事务时间、连续错误、最近错误码、重连次数、命令 pending/覆盖计数、各状态
requested/achieved Hz、`completed_reads`、角度命令反馈数、有效反馈数、反馈策略、
deadline/timeout/age，以及 transport 帧、字节、route miss 和总线错误。

读取 diagnostics 不产生 CAN 查询。需要新 fault 样本时设置 `faults_hz`；
ROS 不把 health timer 变成故障轮询器。

## 发布规则和 QoS

| 接口 | Reliability | Durability | Depth |
| --- | --- | --- | --- |
| 命令、状态与触觉 | best effort | volatile | 1 |
| command status | reliable | volatile | 32 |
| capabilities/device info | reliable | transient local | 1 |

`~/` 相对驱动节点展开，默认 `/linkerbot_hand`；状态订阅须兼容 best-effort。
SDK 缓存变化唤醒独立发布线程，sequence 或有效性变化时发布。
相同序号的 stale/valid 变化不是新设备采样。`publish_rate_hz` 正值用于空闲有效性复查，
0 暂停 ROS 状态发布；polling=0 不清除缓存，也不阻止写回包更新。
生产 ROS 入口使用多线程 executor；等待规则见[客户端等待](client_waits.md)。
