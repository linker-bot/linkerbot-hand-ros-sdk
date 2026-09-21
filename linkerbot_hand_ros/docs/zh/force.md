# 统一触觉字段

本接口需要包含统一触觉功能的 Hand SDK 源码版本。正式包发布前，请从最新 Hand
源码安装；旧的 2.0.0 发布包不包含这些字段。消息 schema 为 1.5，消息包、ROS
驱动和订阅方需要一起重新构建。

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
可以不同，不能当作同一时刻的数据。O30 fn/fns 共享一次原生读取，元数据相同。
矩阵行列及 descriptor 详细布局仍分别从 `state/tactile`、
`state/tactile_sensors` 取得，不能只凭数组长度猜测二维形状。

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

O30 的 `force_fn_hz=20, force_fns_hz=10` 只产生最高 20 Hz 的同一查询，两字段都会
随之更新；不会产生 30 Hz 查询。其他独立物理查询各自调度。
频率是请求目标，仍受 CAN 带宽及事务耗时限制。

`publish_rate_hz` 限制 ROS 缓存发布，采集时应至少达到所需最高字段频率，或设为 0
启用缓存变化驱动。diagnostics 的 `force_<字段>_requested_hz/query_hz/achieved_hz`
分别记录字段请求、物理查询目标和实际样本频率，`query_channel` 标明共享关系。
不要把共享字段的频率或样本数相加估算总线负载；物理计数仍在 `channel_*` 中。

旧 `state/tactile`、`state/tactile_sensors` 和 O30
`state/normal_force_resultant` 继续提供原有视图。独立标量更新不会重发旧点阵或修改
旧点阵采集时间；有效性/过期状态变化可能发布同一序号，统计采样率需按 generation
和 sequence 去重。`state/force` 仍是原有 raw_vector 投影，不是上述字段的聚合话题。
