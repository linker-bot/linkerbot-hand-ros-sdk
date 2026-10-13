# 统一触觉字段

[English](../force.md) · [使用手册](../../README_zh.md)

本指南描述最新 Hand SDK 和 ROS `main` 的统一触觉接口。能力消息 schema 为 `1.5`；
消息包、ROS 驱动和订阅方使用一致的接口定义构建。

每个字段发布到 `~/state/force_<字段>`，类型为 `HandForceField`。
例如 `/linkerbot_hand/state/force_fn` 和 `/linkerbot_hand/state/force_fns`。
ROS 只投影 SDK 缓存，不增加 CAN 查询。

| 字段 | 含义 | L6 / O6 / L20 / L30 / O20 | L20Lite | O30 |
| --- | --- | --- | --- | --- |
| fn | 测点法向力 / 点阵原值 | 支持 | B1–B5 点阵 | 依实际 descriptor |
| fns | 法向汇总原值 | 不支持 | 0x20 五指标量 | 依实际 descriptor |
| ft | 测点切向力 | 不支持 | 不支持 | 依实际 descriptor |
| fts | 切向汇总原值 | 不支持 | 0x21 五指标量 | 依实际 descriptor |
| fd | 测点切向方向 | 不支持 | 不支持 | 依实际 descriptor |
| fds | 切向汇总方向 | 不支持 | 0x22 五指标量 | 依实际 descriptor |
| px | 接近感应 | 不支持 | 0x23 五指标量 | 依实际 descriptor |

表格描述 SDK 声明；当前固件是否回答由运行时能力决定，不按固件版本阻止使用。
O30 不会仅凭协议名称声明所有字段已安装。查询 descriptor 前
`support_known=false`；查询后 `supported` 反映实际传感器。
订阅 `~/capabilities.force_fields`，或使用
`HandCommandClient.force_field_capability("fn")` 获取缓存能力副本。
其中 `firmware_unsupported` 表示本次连接检测到该查询不支持；重新连接会重新探测。

`HandForceField.sensors` 保留手指顺序，每个元素包含：

- `sensor_name`、`present`：身份及此手指是否提供该字段。缺失时 raw 为空，不补零。
- `raw`：原始数值数组；标量也为长度 1。不会对点阵求和生成合力，不做单位换算。
- `valid_values`：逐值有效性。L20Lite fds 的 255 和保留编码原样保存，但标为无效。
- `unit`、`encoding`：原始单位及编码，空字符串为未知；`scale_note` 说明比例和争议。

每个字段有独立 `meta` 和 `query_channel`。L20Lite fn 和 fns 来自不同查询，时间戳
可以不同，不能当作同一时刻的数据。O30 同一次原生读取中实际存在的字段共享元数据；
带 FnS 的布局可同时取得 fn/fns，TASHAN_GATHER 则返回 fn/ft/fd/px。
矩阵行列及 descriptor 详细布局仍分别从 `state/tactile`、
`state/tactile_sensors` 取得，不能只凭数组长度猜测二维形状。

`HandTactileSensor` 保留最大行列、请求行列、`selected_sensor`、`available`、位置模式和矩形填充信息。
这些尺寸不决定 descriptor 数组的形状或顺序；使用 `descriptor`、`fields` 和 `raw_bytes` 解读。
缺失传感器保留身份及空字段，不能当作零力测量。六种非 O30 型号采用 `tactile_matrix`，
O30 采用 `tactile_descriptor`，以 force telemetry 的 `payload_projection` 为准。

## O30 TASHAN_GATHER

已观察到的 descriptor 为 `Fn_F32_1;Ft_F32_1;Fd_U16_1;Px_U32_1`，每指 14 字节
小端数据，四个字段各为单值。通过 `state/force_fn`、`force_ft`、`force_fd`、
`force_px` 读取，每个 present 传感器的 `raw` 长度为 1。单位与编码来自实际样本：
Fn/Ft 保留设备上报的力单位，Fd/Px 单位未确认时为空，不根据力单位推断。

零 Fn/Ft/Px 保留为存在的采样值；缺失手指才使用 `present=false` 和空数组。
原生 descriptor 及字节流仍可在 `state/tactile_sensors` 中查看，最大或请求行列为 0
不表示缺少传感器，是否安装以实际 metadata 为准。Fd `65535` 原值保留，既不换算
角度，也不由 ROS 解释成无效码；其特殊含义未确认，值的有效性只透传 SDK 的判定。

此布局没有 FnS，不发布新的 `force_fns` 和 `normal_force_resultant`；不能把 Fn
求和、改名或套用其他布局的点阵结果生成合力。各字段共享同次采样的 sequence、采集时间和
连接代次。传感器布局切换后按更新的 capability 判断支持字段，不沿用旧布局的数据。
话题仍存在不表示字段受支持，应同时检查 `support_known/supported` 和实际样本。

## 轮询频率

参数名称与 SDK PollingPlan 一致，默认均为 0：

```yaml
force_hz: 0.0
force_fn_hz: 20.0
force_fns_hz: 10.0
force_px_hz: 5.0
```

上例适用于 L20Lite，分别查询点阵、法向汇总和接近值。
`force_ft_hz/force_fts_hz/force_fd_hz/force_fds_hz` 同理；型号不支持的显式正频率
会被拒绝。字段为 0 仅表示不主动请求该字段，共享查询仍可能带回它。

`force_hz` 是可用 fn + fns 的频率简写。例如 `force_hz=20`：
L6 查询 fn，L20Lite 独立查询 fn 和 fns，O30 一次完整原生查询返回实际 descriptor
中的字段。不能同时设置正的 `force_hz` 与正的 `force_fn_hz/force_fns_hz`；
切换方式时用原子参数更新同时清零旧值。

具有 FnS 的 O30 布局中，`force_fn_hz=20, force_fns_hz=10` 只产生最高 20 Hz 的同一
查询。TASHAN_GATHER 使用 `force_fn_hz=10, force_ft_hz=20, force_fd_hz=15,
force_px_hz=5` 时也只产生最高 20 Hz 的同一查询，而非 50 Hz；返回实际 descriptor
中存在的字段，显式设置不支持字段的正频率会被拒绝。其他独立物理查询各自调度。
频率是请求目标，仍受 CAN 带宽及事务耗时限制。

`publish_rate_hz` 控制无新数据时 age/stale 的缓存复查频率；设为 0 会停止 ROS 状态
发布。启用发布时，SDK 缓存变化立即唤醒状态发布线程。diagnostics 的
`force_<字段>_requested_hz/query_hz/achieved_hz`
分别记录字段请求、物理查询目标和实际样本频率，`query_channel` 标明共享关系。
不要把共享字段的频率或样本数相加估算总线负载；物理计数仍在 `channel_*` 中。

`state/tactile` 提供矩阵视图，`state/tactile_sensors` 提供 descriptor 视图；O30 的
`state/normal_force_resultant` 提供同次查询中五指都有的标量 FnS。独立标量更新不会重发
点阵缓存或修改其采集时间；有效性/过期状态变化可能发布同一序号，统计采样率需按 generation
和 sequence 去重。`state/force` 对应 `raw_vector` 投影，当前没有型号声明该投影；
它不是具名字段的聚合话题。
