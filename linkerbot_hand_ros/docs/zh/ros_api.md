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
`command_feedback_only`。当前 L6/O6/L20Lite/L20 为 true，L30/O20/O30 为 false；
程序应读取字段，不硬编码型号表。

能力 schema `1.2` 增加此字段，改变 `CommandCapability` 及包含它的
`HandCapabilities` 的 ROSIDL 类型。需同时重建消息包、驱动、GUI 和所有外部能力消息
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
| `~/command/effort_limits` | 未确认物理单位的 effort 上限 |
| `~/command/torques` | 只有 capability 确认为真实扭矩时存在 |
| `~/command/motion_times` | 协议 motion-time 配置 |
| `~/command/limit_compensations` | 逐关节限位补偿原值，当前仅 L6 声明 |

驱动 active 后只创建 capability 支持的订阅。命令 Topic 使用
best-effort + keep-last(1)，不保证每条发布都进入 SDK。SDK 中角度、速度、电流上限、
effort 上限和扭矩使用独立 latest slot；加速度、运动时间、限位补偿属于有界 FIFO 配置。
需要明确接纳结果的低频限位补偿配置优先使用下方可靠服务。

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
- `~/state/effort_limits`
- `~/state/torques`
- `~/state/temperatures`
- `~/state/faults`
- `~/state/voltages`
- `~/state/motion_times`
- `~/state/limit_compensations`
- `~/state/force`（标量 force profile）

`raw_unit/raw_scale_note` 只是 capability 说明。ROS 不将 count 自动换算为 RPM、mA、N.m；
协议字段本身以 mA 表示时 raw 数字才直接是 mA。

完整触觉发布到 `~/state/tactile`，类型 `HandTactileState`。每个 `TactileMatrix` 包含
finger name、rows、columns 和 row-major raw；一个消息代表一次完整多指事务，不按关节或
单指计算频率。

## 堵转状态

`~/state/stall_protection` 使用 `HandStallProtectionState`，分别保存 detection times、
thresholds 和 hold currents 三个 raw 样本及独立元数据。协议范围不等于已验证安全范围；
`safety_range_verified=false` 时不要做极限写入。

## 管理服务

| Service | 类型 | 说明 |
| --- | --- | --- |
| `~/get_device_info` | `GetDeviceInfo` | 主动刷新身份和全部支持版本字段 |
| `~/get_stall_protection` | `GetStallProtection` | 在一个总 timeout 内读取三项堵转配置 |
| `~/get_configured_speeds` | `GetRawValues` | 配置速度；按能力查询设备或读取写入回包/本地命令缓存 |
| `~/get_configured_accelerations` | `GetRawValues` | 配置加速度 |
| `~/get_current_limits` | `GetRawValues` | 电流上限；按能力查询设备或读取本地命令缓存 |
| `~/get_effort_limits` | `GetRawValues` | effort 通道；L20/L20Lite 返回当前实测负载 |
| `~/get_motion_times` | `GetRawValues` | 运动时间配置 |
| `~/set_stall_detection_times` | `SetRawValues` | 非阻塞提交 raw 配置 |
| `~/set_stall_thresholds` | `SetRawValues` | 非阻塞提交 raw 配置 |
| `~/set_stall_hold_currents` | `SetRawValues` | 非阻塞提交 raw 配置 |
| `~/get_limit_compensations` | `GetRawValues` | 主动查询限位补偿原值、单位说明及采集元数据 |
| `~/set_limit_compensations` | `SetRawValues` | 非阻塞提交 FIFO 配置，明确返回接纳或队列满 |
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
`10 ms/count`，以及名称为堵转扭矩但公式单位为 mA 的冲突项。写入成功后如需掉电保留，先等
对应 command status 到达 `ACKNOWLEDGED`，再调用 `save_parameters` 并等待它的 ACK；该操作
不会自动重启设备。

主动读取在独立、有界 admin worker 中执行，不阻塞控制 callback。setter/离散服务的
`accepted=true` 仅表示进入 SDK，后续阶段看 `/command/status`。服务错误通过稳定
`error_code` 返回，调用方不能解析 message 文本分类。

## 按需读取配置与限制状态

上述六个 `GetRawValues` 入口在 configure 时按 telemetry capability 创建，在 active
状态下调用，直接复用 SDK getter。只有写命令能力不代表存在可读通道。订阅
`~/state/<semantic>` 只是观察缓存，不会触发设备查询；主动查询成功后更新 SDK 缓存，
启用状态发布时会发布变化后的样本。调用这些服务不增加轮询通道，也不发送配置写命令。

读取 `~/capabilities.telemetry` 中的 `read_mode`，区分以下行为：

| `read_mode` | 调用行为 | 当前示例 |
| --- | --- | --- |
| `query` | 请求调用之后的新设备样本 | O6 配置速度/加速度/电流上限；O30 运动时间 |
| `command_response` | 返回最近一次有效的设备写入回包，不发新查询 | L6 配置速度 |
| `command_cache` | 返回最近一次有效的本地已发送命令缓存，不表示设备已确认，不发新查询 | L30 配置速度/电流上限 |

L20/L20Lite 的 `get_effort_limits` 查询的是**当前实测负载**，不是读取保存的限制配置；
保留 `device_measured=true` 和 SDK 给出的原始单位、比例说明。所有型号均透传 SDK
元数据，不根据方法名推断为真实扭矩。

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
