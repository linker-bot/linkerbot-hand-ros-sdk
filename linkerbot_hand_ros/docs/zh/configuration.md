# Lifecycle 与参数配置

启动可选择手工参数、单手 `discover:=true`、多手发现及生成文件复用。
扫描发生在启动准备阶段，configure 仍保持零设备 I/O；详见
[自动发现指南](discovery.md)。发现部署 YAML 与下面的 ROS 参数 YAML 均受支持。

## Lifecycle 行为

| 状态转换 | 行为 |
| --- | --- |
| configure | 解析参数，构造 transport 描述、唯一 `HandDevice` 和 ROS 实体；零连接、零设备 I/O |
| activate | `open()`，验证型号/固件/传感器变体，安装 polling plan，启用命令和状态发布 |
| deactivate | 先撤销命令入口，再停止 SDK polling；不自动运动、不关闭连接 |
| cleanup | 有界停止 admin worker、polling 和设备 runtime，销毁 ROS 实体 |
| shutdown/error | 无论来自哪个状态都尝试有界 stop/close，不依赖析构函数 |

launch 默认 `autostart:=true`。外部 lifecycle manager 接管时：

```bash
ros2 launch linkerbot_hand_ros hand.launch.py autostart:=false
ros2 lifecycle set /linkerbot_hand configure
ros2 lifecycle set /linkerbot_hand activate
```

## 静态参数

静态参数在 configure 后拒绝修改，需先 `deactivate -> cleanup`：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `model` | `l6` | `l6/o6/l20lite/l20/o20/l30/o30`，不区分大小写；也接受 `l20-lite` 作为 `L20Lite` 的拼写别名 |
| `side` | `left` | `left/right`；L30 必须为空字符串 |
| `transport_json` | SocketCAN `can0` | 严格 JSON transport 配置 |
| `command_rate_hz` | `250` | SDK 连续命令调度上限 |
| `discrete_queue_capacity` | `16` | 离散和安全配置命令的有界 FIFO 容量 |
| `mailbox_capacity` | `256` | 设备 runtime mailbox 容量 |
| `route_queue_capacity` | `256` | transport 路由队列容量 |
| `identity_timeout_s` | `0.2` | 每个身份响应阶段的等待秒数，包含 L30/O30 后续阶段 |
| `transaction_timeout_s` | `0.0` | `0.0` 沿用各协议默认响应窗口；正数覆盖每个普通响应阶段的等待秒数 |
| `shutdown_timeout_s` | `2.0` | worker 和连接关闭总边界 |
| `auto_reconnect` | `false` | SDK 自动安全恢复 |
| `reconnect_initial_delay_s` | `0.1` | 首次重连退避 |
| `reconnect_max_delay_s` | `2.0` | 最大重连退避 |
| `recovery_max_attempts` | `3` | 每轮恢复最多进行的身份与 baseline 初始化尝试次数，包含首次；正整数 |
| `recovery_timeout_s` | `5.0` | 每轮恢复执行总预算，包含准备、读取与重试等待；正数 |
| `recovery_retry_delay_s` | `0.2` | 响应超时后重试前的最小接收静默间隔；正数 |

响应超时从该阶段整批请求发送完成开始计时，完整回复提前到达即结束等待。
`transaction_timeout_s=0.0` 在 ROS 适配层转换为 SDK 的 `None`；
直接调用 SDK 时应使用 `None`，不接受 `0`。该参数覆盖 baseline、
主动查询、轮询和需要回复的命令，保留协议发送间隔及无需回复命令的行为，不增加重试。
身份阶段使用独立的 `identity_timeout_s`。管理服务的 `timeout_s` 仍是调用者等待预算，
不代表单阶段响应时间，也不因为等待超时而取消 SDK 后台恢复。

恢复策略参数只能在未配置状态下修改。仅身份和 baseline
的响应超时允许重试；身份不匹配、协议错误和写入不重试。实际静默窗口取配置、失败阶段
响应窗口和协议隔离窗口的最大值，收到本设备的帧会重新计时，整轮仍受总预算限制。
无请求序号协议无法识别超出静默窗口的任意迟到旧帧，可按现场最大延迟增大间隔。
服务等待超时不取消共享恢复；达到恢复执行截止后不提交成功。底层阻塞 I/O 不能强制
抢占，SDK 在返回后复核截止。开启自动重连时，失败后仍可按退避策略另起有界的一轮。

型号解析使用 Hand SDK 的统一规则：`model` 填写 `o6`、`l6`、`l20lite`、`l20`、
`o20`、`o30` 或 `l30`，大小写不敏感，L20Lite 也接受 `l20-lite`。不能用完整产品编号
替代型号。SDK 在 configure 阶段校验配置；
消息中的 `model` 使用规范型号，`product_code` 原样保留设备上报的编号。

## 动态轮询与发布

| 参数 | 默认值 | 查询/发布对象 |
| --- | --- | --- |
| `angles_hz` | `100` | SDK 角度查询 |
| `angle_feedback` | `adaptive` | 角度查询与设备命令回显的组合策略 |
| `speeds_hz` | `0` | SDK 实测速度查询 |
| `force_hz` | `0` | SDK force 或完整触觉事务 |
| `temperature_hz` | `0` | SDK 温度查询 |
| `current_hz` | `0` | SDK 实测电流查询 |
| `faults_hz` | `0` | SDK 故障查询 |
| `torques_hz` | `0` | SDK 力矩通道查询，仅 capability 支持时；L6 为输出/模式原值，物理测量语义以 capability 为准 |
| `voltage_hz` | `0` | SDK 电压查询 |
| `publish_rate_hz` | `100` | 无新 revision 时的缓存 age/stale 复查频率 |
| `diagnostic_rate_hz` | `1` | `/diagnostics` 发布频率 |

非零 polling 只允许 capability 声明 `device_queried=true` 的通道。请求不支持通道时参数
事务失败，不会静默忽略。频率设为 0 后 SDK 不再生成该通道的查询；
`publish_rate_hz=0` 只暂停 ROS 状态发布，并不停止设备 polling。

`angle_feedback` 的三个取值分别为：

- `query_only`：只由主动角度查询满足 `angles_hz`，命令回显仍更新 SDK 缓存和指标，但不发布到
  ROS `~/state/angles`、也不唤醒状态发布线程，避免同一目标周期产生两条角度消息；
- `command_feedback_only`：只用已验证的设置回显满足反馈，不主动补充角度查询；
- `adaptive`：优先使用设置回显，目标周期内没有回显时主动查询补足，默认使用该策略。

生产入口使用 `MultiThreadedExecutor`，Lifecycle 与参数服务仍共享默认互斥回调组。
SDK 缓存 revision 变化会立即唤醒独立状态发布线程，避免固定 timer
与反馈同频时发生采样混叠；`publish_rate_hz` 只控制无新 revision 时 age/stale 的复查频率。
sequence 未变化时不会重复发布旧样本。

```bash
ros2 param set /linkerbot_hand angles_hz 100.0
ros2 param set /linkerbot_hand angle_feedback query_only
ros2 param set /linkerbot_hand force_hz 30.0
ros2 param set /linkerbot_hand publish_rate_hz 100.0
ros2 param set /linkerbot_hand diagnostic_rate_hz 10.0
```

运行中多个 rate 参数作为一次原子事务修改：

```bash
ros2 param set --help
```

需要严格原子更新时应通过 `rcl_interfaces/srv/SetParametersAtomically` 或代码中的
`AsyncParameterClient.set_parameters_atomically()`，频率 benchmark 已按此方式实现。

动态更新先经过所有 ROS 校验回调，只有参数提交成功后才应用 SDK polling 和 ROS 发布频率。
后续校验拒绝时不会改变运行配置。应用失败会尝试恢复整批参数和运行配置，返回
`successful=false` 与失败原因；逐个参数 API 保留前面已成功的更新。

ROS 参数事件可能先发布新值、再发布恢复的旧值，post-set 回调也在 SDK 应用之前运行。
因此参数事件不能作为设备已采用新频率的确认，应检查参数服务的最终响应。请勿在参数回调
内部再次设置参数，嵌套更新会明确拒绝；自定义校验、pre-set/post-set 回调同样参与恢复，
SDK 不会绕过它们强改 ROS 内部参数字典。

如果运行时恢复失败，或其他回调拒绝/改写了参数恢复，驱动停止接收命令、停止 polling 并
关闭连接，报告 `cleanup required`。在成功 cleanup 后重新 configure/activate；若已通过
ROS error transition 完整释放运行时，直接重新 configure/activate 即可。驱动保留的参数
表示下次配置的目标值，不能将此故障状态解释为设备仍按该频率运行。

参数服务与 Lifecycle 服务使用同一互斥回调组。应用内直接调用参数或 Lifecycle 方法时，
也应在该组中调度或由调用方串行化，避免绕过 ROS 服务调度并发改变生命周期。

## Transport JSON

Linux SocketCAN，classic CAN 和 CAN FD 均由 capability 决定：

```json
{"backend":"socketcan","channel":"can0"}
```

可选字段：`nominal_bitrate`、`data_bitrate`、`auto_reconfigure`、
`receive_own_messages`。

`nominal_bitrate` 必须与型号 capability 一致，冲突时 configure 失败。

`data_bitrate` 分两种情况。声明了数据段速率的型号（O20、L30 为 5 Mbit/s）同样严格校验，冲突即失败。而 O30 使用 BRS off，数据段恒等于标称速率、接口 dbitrate 不影响通信，其 capability 不声明数据段速率 —— 这类型号**推荐 5 Mbit/s，但任意波特率都可用**：不填 `data_bitrate` 时驱动采用该 SocketCAN 链路当前实际运行的数据段速率，只有在链路读不到时（未配置、未 UP）才回落到推荐的 5 Mbit/s。显式填写时以填写值为准，此时不读链路。

因此在 1M、2M、7M 等任意数据段速率的总线上都无需为 O30 额外配置 `data_bitrate`。

其他 python-can classic backend：

```json
{"backend":"python_can","interface_name":"PCAN_USBBUS1","interface_type":"pcan"}
```

厂商 CAN FD：

```json
{"backend":"vendor_canfd","device_index":0,"channel_index":0,"library_path":"/path/to/lib.so"}
```

`transport_json` 按 backend 提供连接配置；未知 backend、缺失必填键或多余键均为配置错误。

## 多设备

当前维护范围为一条物理 CAN/CAN FD 通道一只手，多只手使用不同接口。
`multi_hand.launch.py` 在一个 Python 进程中统一管理多个 Lifecycle 节点及失败回滚；
同进程管理不意味着多个设备共用同一通道。示例接线为 L6 左手接 `can0`、O6 右手接
`can1`，启动前分别配置两个接口。参数文件结构如下：

```yaml
/linkerbot_hand_container:
  ros__parameters:
    device_namespaces: [l6_left, o6_right]
    autostart: true

/l6_left/linkerbot_hand:
  ros__parameters:
    model: l6
    side: left
    transport_json: '{"backend":"socketcan","channel":"can0"}'
    angles_hz: 100.0

/o6_right/linkerbot_hand:
  ros__parameters:
    model: o6
    side: right
    transport_json: '{"backend":"socketcan","channel":"can1"}'
    angles_hz: 100.0
```

启动：

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py \
  config:=/absolute/path/to/hands.yaml
```

容器参数：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `device_namespaces` | 空 | 非空且不重复的设备 namespace 列表 |
| `autostart` | `true` | 先 configure 全部设备，再 activate 全部设备 |

`autostart=true` 时，任一节点 configure 或 activate 失败都会按逆序 deactivate/cleanup
已经启动的节点，进程不会保留部分激活状态。`autostart=false` 时可逐个控制：

```bash
ros2 lifecycle set /l6_left/linkerbot_hand configure
ros2 lifecycle set /l6_left/linkerbot_hand activate
```

两只手的 `transport_json` 物理 key 相同时，`linkerbot-transport` 才共享一个 runtime、RX
reactor 和 TX arbiter。不同 channel 仍位于同一 ROS 进程，但各自拥有独立 transport
runtime；共享机制不能作为同通道多手的支持承诺，namespace 也不能隔离总线报文。
独立 `hand.launch.py` 进程没有容器的组启动/回滚，也不能共享进程内仲裁器。

## 恢复

自动或显式恢复会重新验证身份和固件、清除旧命令并读取 baseline 状态。不会重放断线前或
断线期间目标，不会自动张开、握拳、清错、enable 或 calibrate。业务层看到
`connection_generation` 增加后必须清空旧到位判断，并显式提交新目标。
