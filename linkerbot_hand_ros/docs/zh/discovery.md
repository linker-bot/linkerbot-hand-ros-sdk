# 自动发现并复用启动配置

启动支持手工 launch、ROS 参数 YAML 和自动发现。发现模式通过 Hand SDK 读取身份、关闭探测
连接，再用候选工厂构造节点。它不修改宿主 CAN 设置，不额外发送运动、使能、清错或
标定命令。当前维护范围仍是一条物理 CAN/CAN FD 通道一只手。

## 三种启动方式

```bash
# 手工启动（已有）
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l6 side:=left \
  transport_json:='{"backend":"socketcan","channel":"can0"}'

# 唯一已验证单手，保持 /linkerbot_hand
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true

# 范围内全部已验证设备，保存 ./hands.yaml 后组激活
ros2 launch linkerbot_hand_ros multi_hand.launch.py discover:=true
```

单手未发现、身份不完整或发现多只时打印摘要并退出；多只时给出可复制的限定命令：

```bash
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true channels:=can0
```

`channels` 用逗号分隔 SDK 报告接口名称，例如 `can0`、`pcan:PCAN_USBBUS1`、
`slcan:COM5`、`minicanfd:0:0`。指定接口缺失不会回退到其他接口。
自动模式不能同时指定手工 `model`、`side`、`transport_json`；
单手原有运行参数（如 `angles_hz:=50`）和 `namespace` 仍可使用。
单手遵循 ROS namespace 规则：相对路径接在外层 `PushROSNamespace` 下，绝对路径保持固定。

多手至少需要一只已验证设备。摘要显示接口、型号、物理侧别、后端，再给出 namespace。
以下仅为格式示例：

```text
can0: L6, left, socketcan [verified]
can1: O6, right, socketcan [verified]
binding namespace=/l6l -> can0 (L6)
binding namespace=/o6r -> can1 (O6)
configuration saved: /实际执行目录/hands.yaml
```

PARTIAL 和后端失败单独显示。所选通道有多个响应端点、绑定重复或探测资源清理
未完成时拒绝启动；任一所选节点激活失败，现有容器对整组回滚。
发现模式启动失败时，launch 返回非零退出码，便于脚本识别。

## 保存后直接复用

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py \
  discover:=true channels:=can0,can1 output:=./hands-lab.yaml

ros2 launch linkerbot_hand_ros multi_hand.launch.py config:=./hands-lab.yaml
```

默认输出是执行 launch 时工作目录的 `hands.yaml`，打印绝对路径。
已有文件在扫描前拒绝；文件原子写出，即使扫描期间别的进程先创建同名文件也不覆盖。
必需写出失败时不激活。保存与激活分别报告：保存后激活仍可能失败，文件会保留。

`config` 同时识别 ROS 参数 YAML 和发现部署 YAML。发现部署文件包含
`schema: linkerbot_hand_ros.discovery`、`version: 1`、`autostart`、`discovery`，以及
`hands` 列表内的 `namespace`、`match`、`parameters`。
未知版本/字段、重复键、namespace 或通道均拒绝。此文件须通过 launch 加载，不能
直接作为 ROS `--params-file`。

SDK 别名用于初始 namespace（如 `/l6l`），可在保存文件中编辑为业务角色。
多手发现将别名放到容器的 namespace 下：外层 `PushROSNamespace("/robot")`
对应 `/robot/l6l`、`/robot/o6r`，完整绝对路径只保存一次。
已有文件在另一个父级 namespace 下加载时仍保持保存路径；迁移角色需编辑或重新生成。
内部手节点防止容器进程的 `__node`/`__ns` 覆盖身份，同时保留全局参数
（包括 `use_sim_time`）与主题 remap。ROS 参数文件先执行 launch substitution
再由 ROS 校验参数；发现部署使用静态 schema。

文件启动重新扫描保存的资源，唯一匹配保存的集合；新接入设备不自动加入，
扫描别名编号变化不重排角色，缺失或身份不符不换手兜底。
可取得的序列号/产品身份结合接口、协议和端点使用；缺少或重复身份时，不能保证
永久、全球唯一的物理设备识别。

文件保存已校验输入，不序列化工厂、cleanup 回调或旧指纹。新扫描的候选工厂保留
FD 配方、O30 非默认地址、L30 Node ID 和本次指纹，首次打开、重试、恢复继续校验。
L30 显示物理侧别，但构造侧别仍为 NOT_APPLICABLE。
生成的选择条件不锁固件版本；升级前先停止并 cleanup，退出旧会话后重新发现。

新发现默认 `autostart=true`；文件启动保留保存值，可显式覆盖。
`autostart:=false` 仍扫描、保存并保留未配置的 Lifecycle 节点，等待外部管理，
不打开运行期 Hand，也不会扫描后退出。发现或保存成功不代表就绪；仍检查 active、
运行时 verified capability 和当前状态。多手路径带保存的 namespace，
例如 `/l6l/linkerbot_hand/state/angles`。

## 高级发现设置

两个发现入口均支持 `discovery_config:=/路径/settings.yaml`，直接表达 SDK
`DiscoveryConfig` 字段，不带部署 schema：

```yaml
backends: [socketcan]
channels: [can0, can1]
total_timeout_s: 30.0
l30_node_ids: [13]
o30_request_ids: [23]
```

本项目的 SLCAN 模板用于 Windows CAN FD（`probe_protocols: [can_fd]`）；PCAN 模板按适配器能力选择经典 CAN 或 FD。

PCAN/SLCAN 支持原生 `channels`、`bitrate`、`data_bitrate`、
`probe_protocols: [can, can_fd]`、标量 `bus_options` 及 `fd_timing` 内的
`can.BitTimingFd` 字段。SLCAN 的 `bus_options.tty_baudrate` 是串口速率，
与 CAN 速率分开。MiniCANFD 支持 `library_path`、设备索引到通道列表的
`linux_channels` 和 `config` 中的 SDK `CANFDConfigOptions`。
相对库路径以设置/部署文件目录为基准。逐手 `parameters` 使用已有运行参数名，
不能夹带手工产品或 transport 字段。launch 与文件范围矛盾时拒绝，不扩大范围。

后端省略时沿用 SDK 平台默认：Linux 为 SocketCAN（经典 CAN/CAN FD）与 MiniCANFD；Windows 为
PCAN（经典 CAN/CAN FD）、MiniCANFD、SLCAN（CAN FD）。库、权限、已配置接口和适配器固件必须可用。
扫描预算不是硬截止，厂商调用和必要清理可能更久；一期不提供运行中重扫、
热插拔替换或交互输入。软件测试使用源码 SDK/内存协议替身，Windows、适配器及
各型号实机仍需独立验收。

可复制的适配器设置和单手/双手部署见[配置示例](discovery_examples.md)；按后端、接口、端点和角色定位失败见[故障排查](troubleshooting.md#自动发现与部署加载故障)。
