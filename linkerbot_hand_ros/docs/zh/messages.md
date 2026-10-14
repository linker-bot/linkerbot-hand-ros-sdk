# 消息字段

`linkerbot_hand_msgs` 定义 ROS 消息与服务，不依赖具体手型号。消息包、驱动、GUI 和业务节点须使用相同接口版本构建。

## 查询完整定义

```bash
ros2 interface show linkerbot_hand_msgs/msg/HandCapabilities
ros2 interface show linkerbot_hand_msgs/msg/HandJointState
ros2 interface show linkerbot_hand_msgs/msg/HandCommandStatusBatch
ros2 interface show linkerbot_hand_msgs/srv/GetRawValues
```

端点和 QoS 见 [ROS 2 API](ros_api.md)。

## 能力与身份

`HandCapabilities` 的 `identity` 表示型号、侧别和身份验证；`joints` 给出数组顺序、raw 范围与 percent 映射。`commands`、`telemetry`、`operations` 决定可用接口，`force_fields` 决定当前触觉字段。

configure 阶段的能力是声明值，activate 后须等待 `identity.verified=true`。固件可选查询降级会重新发布能力；不要一直使用最早收到的副本。身份中的可选字段通过 `has_*` 或 `VersionField.available` 判断，`reported_side` 是设备报告的侧别。

## 状态元数据

角度、telemetry 和触觉均携带 `SampleMetadata`：

| 字段 | 含义 |
| --- | --- |
| `collected_at` | 采集时刻投影到 ROS 时钟 |
| `sequence` | SDK 样本序号；相同序号的发布可能只是有效性变化 |
| `age_s`、`stale` | 样本年龄与过期状态 |
| `valid`、`within_declared_range` | 样本有效与是否在声明范围内 |
| `connection_generation` | 连接代次；恢复后重新建立基线 |
| `origin` | 设备查询、主动上报、配置回复、命令反馈或本地命令缓存 |

缓存读取保留原采集时间与序号，不能仅用服务成功或消息接收时间判断新鲜度。

## 角度与 telemetry

`HandJointState` 的 `joint_names`、`raw`、`percent`、`physical_rad` 对齐；分别检查 `percent_valid` 和 `physical_rad_valid`。占位零不代表有效角度。

`HandTelemetry` 保留 `semantic`、`channel_names`、`raw`、`raw_unit`、`raw_scale_note`、`unit_confidence`、`device_measured` 和 `device_queried`。`device_queried` 描述通道能力，具体样本来源由 `meta.origin` 判断；配置值不等于实测值。

## 命令与状态

`HandJointCommand` 使用 `representation=1`（percent）或 `2`（raw）；其他逐轴命令使用 `HandRawCommand.raw`。所有话题命令用非零 `client_id` 与 `user_sequence` 关联。

`HandCommandStatusBatch.statuses[]` 中每项保留命令键、驱动接收时刻和 `transitions[]` 完整历史。遍历整个 batch，按两个 ID 匹配；`ACKNOWLEDGED` 不代表机械到位。服务写入按返回的 `command_id` 关联，见[业务节点集成](business_integration.md)。

## 故障与触觉

`HandJointFaultStatus` 保留 raw 字节、`supported_flags`、保留位和解释。仅支持的标记有定义；不支持的标记为 false 不能证明设备正常。L6 的 MCU/电机温度、过载和相电流标记独立，L20 的通信、自检、软锁、堵转和转子锁独立。

触觉使用 `HandTactileState`（点阵）、`HandTactileSensorState`（descriptor）和 `HandForceField`（具名字段）。缺失传感器保留身份与空数组；不要补零或自行求和生成 FnS。完整布局见[触觉数据](force.md)。

[返回总览](getting_started.md) · [English](../messages.md)
