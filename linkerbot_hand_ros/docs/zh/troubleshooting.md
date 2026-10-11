# 故障排查

## 自动发现与部署加载故障

先确认平台：Linux 为 SocketCAN（经典 CAN/CAN FD）、MiniCANFD；Windows 为 PCAN（经典 CAN/CAN FD）、MiniCANFD、SLCAN（CAN FD）。`backends` 不会启用其他平台的来源。出现 `backend ... is unavailable on this platform` 时先选择本平台模板；Linux 下若适配器已经暴露为 SocketCAN 网络接口，应使用 SocketCAN，串口 SLCAN 模式不属于此入口范围。

先保留同一次启动的扫描摘要、失败行及最后的生命周期错误。关注 `operation`（SDK 操作）、`backend`、`channel`/`native_channel`、`protocol`、角色 namespace 和配置路径；`stage` 是容器阶段，`cause` 是原始异常。SDK 不提供的字段不会推测，`backend=selection` 表示接口筛选阶段，不是物理适配器。配置模板见[配置示例](discovery_examples.md)。

以下是日志格式示例，不代表现场扫描结果：

```text
discovery unavailable: requested discovery channel was not enumerated (operation=enumerate_selection_unavailable error_type=DiscoveryError backend=selection native_channel='can0')
activate failed: [identity_mismatch] ... (node=/left_hand/linkerbot_hand backend=socketcan channel='can0' protocol=can scheme=classic_can_id request_id=0x28 response_id=0x28 extended_id=False)
```

### 配置或文件错误

- `discovery_config=...` 指向高级扫描设置；`deployment_config=...` 指向可复用部署。`hands[0]` 为从 0 开始的列表位置，后面的 namespace 定位角色。检查未知/重复字段、参数类型、namespace 和接口冲突。
- 高级设置须用 `discovery_config`，schema/version 1 的部署须用 `config`，不能作为 ROS `--params-file`。保留旧 ROS 参数文件和 launch substitution 的原用法。
- `output already exists` 在扫描前拒绝；复用文件使用 `config:=...`，重新发现使用新的 output 路径。写失败时检查父目录存在及写权限，不删除原文件来绕过保护。

### `unavailable`：指定接口没有枚举到

先按失败行定位接口。Linux SocketCAN 用以下只读检查确认名称、UP、CAN/FD 和速率：

```bash
ip -details link show can0
```

PCAN 高级配置中的原生名称是 `PCAN_USBBUS1`，全局筛选名是 `pcan:PCAN_USBBUS1`。SLCAN 对应串口路径或 COM 端口；MiniCANFD 使用枚举索引。核对连接和配置后再启动；指定接口缺失不会自动改扫别的接口。接口设置由宿主环境负责。

### 没有候选、候选不唯一或 `partial`

若同时存在后端失败，先处理后端失败，不能将其解释为“设备不存在”。接口已可用时，检查手的供电、接线、终端、协议和速率。单手多候选用正确的 `channels` 限定，或改用多手入口；PARTIAL 的 `problem code: message` 表示身份缺失，不会自动补侧别或激活。L30 Node ID、O30 非默认请求 ID 须在已知范围内配置，不猜测身份。

### 厂商库加载、驱动或权限失败

SDK 错误码可能按枚举阶段命名，具体原因见 `error_type`、message 和 cause。检查实际库路径、进程/库位数以及依赖；Linux MiniCANFD 需要真实 `libcanbus.so` 和 USB 访问权限，Windows 需要正确 `HCanbus.dll`、厂商 USB 驱动与其运行库。Windows PCAN 需要对应 PCANBasic/驱动，SLCAN 需确认实际 COM 端口和占用状态；可在设备管理器核对。Linux MiniCANFD 的 USB 权限可只读检查：

```bash
id
lsusb
ls -l /dev/bus/usb
```

按系统的设备权限管理方式解决访问问题；不要用全局放开设备权限或强制管理员运行代替原因定位。相对库路径以设置/部署文件目录为基准，库不随 ROS/SDK 分发。

### `busy`：资源仍被占用

`deactivate` 只停止命令和轮询，连接租约到 `cleanup` 才释放。对自己管理的旧节点有序失活、cleanup 并退出后再扫描；MiniCANFD 枚举还要求本进程关闭同一厂商库的连接。不要强制终止他人的进程；系统或其他应用占用需由其所有者释放。一期没有运行中重扫入口。

### `layout`：MiniCANFD Linux 布局未确认

填写已经确认的 `linux_channels`（设备索引 → 通道索引列表），不要从设备数量推测通道。Windows 不填写 Linux 布局，DLL 的 devNum 直接作为 device_index，channel_index 固定为 0。检查复制的模板是否适合目标平台。

### `unsupported_protocol` 或 FD 配方错误

核对适配器是否实际支持 FD、设备需要经典 CAN 还是 FD，以及时钟/位时序/数据速率是否匹配。PCAN classic 模板不能替代 FD 模板；SLCAN USB 识别不证明固件支持 FD，需已确认的 CANable 2.0 FD 固件。不要通过强行添加 `can_fd` 绕过 SDK 能力拒绝。

### `scan_timeout`：扫描预算耗尽

检查前面的后端失败及配置范围；有已知接口/Node ID/请求 ID 时限定正确范围，需要时调整 `total_timeout_s`。它是协作式预算，厂商阻塞调用及清理可能延长总耗时，不能把超过预算直接解释成死锁，也不要遗弃仍执行的后台任务。发送/响应预算与运行期事务预算分开。

### 探测关闭或运行期 cleanup 失败

日志给出原失败的接口/协议和每次清理原因。探测资源未释放会阻止保存/启动；运行期 close 失败仍需确认连接状态。处理库、占用或设备错误后按 SDK/适配器要求释放资源，再启动新会话。不能因报错后进程退出就声称厂商资源已释放。

### `identity_mismatch` 或保存角色匹配失败

激活/恢复的身份不符会拒绝控制。检查 node/namespace、接口、request/response ID、L30 Node ID 和原始 cause；文件匹配失败还显示保存的 `match` 条件。核对是否换手、换线、升级固件或编辑了选择条件，有序 cleanup 后重新发现并确认角色；不要删除身份条件来让错误设备通过。新生成文件使用新路径，保留原配置供核对。

模板中没有序列号的绑定只能提供型号/侧别/接口/端点约束，不能保证永久物理身份；生产部署优先生成现场文件。实机仍需独立验收。


## 找不到 ROS package

```text
Package 'linkerbot_hand_ros' not found
```

```bash
cd ~/linkerbot_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source ~/linkerbot_ws/install/setup.bash
ros2 pkg executables linkerbot_hand_ros
```

不要混用 Humble 和 Jazzy setup。

## 找不到或加载了错误的 Hand SDK

```bash
python3 -c 'import sys, linkerbot_hand; print(sys.executable); print(linkerbot_hand.__file__)'
```

安装 1.x：

```bash
python3 -m pip install \
  --index-url https://gitea.linkerhub.work/api/packages/zhuzhixiang/pypi/simple \
  --extra-index-url https://pypi.org/simple \
  'linkerbot-hand==2.0.0'
```

开发源码：

```bash
python3 -m pip install -e /path/to/linkerbot-transport -e /path/to/linkerbot-hand
```

旧 0.x 包不提供本驱动需要的 `HandDevice` 1.x 类型契约。

## configure 失败

configure 不连接设备，失败通常是纯配置问题：

- `model` 或 `side` 无效；L30 的 side 必须是空字符串。
- `transport_json` 不是 JSON object、缺 `backend`、缺必填键或含未知键。
- 配置 bitrate 与 capability 冲突。
- queue capacity、timeout、rate 或 reconnect 参数类型/范围错误。
- 请求了 capability 不支持的非零 polling 通道。

```bash
ros2 param dump /linkerbot_hand
```

## activate 失败

activate 才产生 transport open、身份读取和 baseline 事务：

```bash
ip -details -statistics link show can0
ros2 topic echo --once /diagnostics
```

依次检查接口 up 状态、classic CAN/CAN FD 模式、nominal/data bitrate、终端电阻、设备供电、
型号、side、设备地址和 firmware。`unsupported_firmware` 表示设备回复存在，但没有安全匹配的
protocol profile；不能提高 timeout 后继续猜测运行。

activate 失败会停止 polling 并关闭候选连接，可在修复硬件/参数后再次 activate。

## active 但没有命令或状态

```bash
ros2 lifecycle get /linkerbot_hand
ros2 topic list | rg linkerbot_hand
ros2 topic echo --once /linkerbot_hand/capabilities
```

inactive 会撤销命令订阅并停止 polling。状态 Topic 只有 SDK 新 sequence 或有效性变化时才
发布；对应 polling rate 为 0 时不产生消息。

## 状态频率低或过期

```bash
ros2 param get /linkerbot_hand angles_hz
ros2 param get /linkerbot_hand angle_feedback
ros2 param get /linkerbot_hand force_hz
ros2 param get /linkerbot_hand publish_rate_hz
ros2 topic echo --once /diagnostics
```

重点检查 `channel_<name>_requested_hz/achieved_hz/completed_reads/feedback_samples/`
`command_feedback_samples/feedback_policy/missed_deadlines/timeouts/age_s` 以及 transport
frame、route miss 和 bus error。`publish_rate_hz` 只影响无新 revision 时的 age/stale 复查，
不会提高或降低 SDK 查询；新缓存 revision 会立即唤醒发布线程。触觉是完整多帧事务，
角度+触觉上限需用 benchmark 实测。

## 旧固件缺少个别查询

订阅最新 transient-local capability，检查 `firmware_unsupported_telemetry`。SDK 对标为可选
的查询连续 3 次超时或结构不符后，只禁用该语义并保持连接；中间任一次成功会清零失败计数。
ROS 会重新发布 capability，且不再
发布该通道的新样本。重新连接后 SDK 会重新探测。若所有 opcode 都无响应、SocketCAN 只有
TX 没有 RX，应先检查供电、线序、终端和 bitrate，不能误判成某一个协议不支持。

## 百分比或物理角度无效

`HandJointState.raw` 始终保留设备回复。某轴 `percent_valid=false` 表示 capability 没有可信
percent endpoint；`physical_rad_valid=false` 表示没有可信物理标定。不能把占位 0 当成实际
值，也不能把 raw/percent 伪装成弧度。

检查：

```bash
ros2 topic echo --once /linkerbot_hand/capabilities
ros2 topic echo --once /linkerbot_hand/state/angles
```

## 静态参数被拒绝

configured/inactive/active 状态不能修改 model、side、transport、DeviceConfig 或 reconnect：

```bash
ros2 lifecycle set /linkerbot_hand deactivate
ros2 lifecycle set /linkerbot_hand cleanup
ros2 param set /linkerbot_hand model o6
ros2 param set /linkerbot_hand side right
ros2 lifecycle set /linkerbot_hand configure
ros2 lifecycle set /linkerbot_hand activate
```

## 命令被拒绝

常见原因：

- node 非 active 或 SDK 正在恢复。
- `client_id`/`user_sequence`/representation 无效。
- 数组长度不等于 capability channel count。
- NaN、Inf、percent 越界或整数协议值带小数。
- command semantic 不受当前 verified capability 支持。
- 离散 FIFO 已满。

订阅：

```bash
ros2 topic echo /linkerbot_hand/command/status
```

Topic 返回 `HandCommandStatusBatch`；逐条检查 `statuses[]`，按每条状态的 `error_code` 分类，
不解析 `error_message`。

## 已 ACCEPTED 但设备未动

`ACCEPTED` 只表示进入 SDK。检查是否到达 `DISPATCHED`，有 ACK 的型号是否到达
`ACKNOWLEDGED`，以及是否 FAILED/SUPERSEDED。SocketCAN send 成功也不代表设备已机械到位；
到位必须读取当前 generation 的有效、未过期角度。

## 高频命令被大量 SUPERSEDED

连续目标是 latest-wins，这是有意行为。若目标提交高于 SDK/transport 实际发送能力，旧目标
会在发送前被覆盖。检查 `command_rate_hz`、transport pending、CPU/executor backlog 和总线
事务成本。不能通过增大历史 FIFO 保存连续轨迹；轨迹采样应由上层按可实现频率生成。

## 管理服务 timeout

设备信息、堵转读取和 recover 在独立 admin worker 中执行，`timeout_s` 必须为正且小于
`shutdown_timeout_s` 留出的边界。worker FIFO 满返回 `queue_full`；不要用多个客户端并发刷
低频管理事务。

## 断线恢复后旧目标没有执行

这是安全契约。恢复会清除断线前和断线期间目标、重新验证身份并读取 baseline，不会自动
重放。等待新 generation 的有效角度和 fault 后，由业务显式提交新目标。

若返回 `identity_mismatch`，说明重连后的设备指纹不同，必须人工确认，不能继续控制。

## Lifecycle 关闭超时或线程泄漏

检查 `shutdown_timeout_s`、admin service 是否仍被调用、transport backend 是否能有界退出。
不要依赖 Python 析构释放设备，也不要在同一物理接口启动第二个驱动进程。复现时记录：

```bash
ps -L -p <PID>
ls /proc/<PID>/fd | wc -l
ros2 lifecycle get /linkerbot_hand
```

100 次 configure/activate/deactivate/cleanup 后线程、FD 和连接数应回到基线。
