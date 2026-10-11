# 自动发现配置示例

以下文件随驱动安装到 `share/linkerbot_hand_ros/config`，源码位于本包 `config`。它们是可校验的模板；接口、时序、固件和厂商库必须按现场填写，软件加载通过不代表适配器实机验收通过。

## 平台范围

沿用 SDK 的真实平台来源：Linux 支持 SocketCAN（经典 CAN/CAN FD）和 MiniCANFD；Windows 支持 PCAN（经典 CAN/CAN FD）、MiniCANFD 和 SLCAN（CAN FD）。显式 `backends` 只筛选本平台来源，不启用其他平台后端；这里没有 Linux SLCAN/PCAN 的发现模板。Windows 配置的软件路由验证不等于 Windows ROS 或适配器实机验收。

## 快速启动与模板使用

单手不需要配置文件，先限定实际接口：

```bash
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true channels:=can0
```

Linux 上复制 SocketCAN 模板到可写目录，再按实际接口编辑；相对厂商库路径以复制后的 YAML 所在目录为基准：

```bash
hand_share="$(ros2 pkg prefix linkerbot_hand_ros)/share/linkerbot_hand_ros"
mkdir -p ~/hand-config
cp "$hand_share/config/discovery-socketcan.yaml" ~/hand-config/
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true \
  discovery_config:="$HOME/hand-config/discovery-socketcan.yaml"
```

高级扫描设置使用 `discovery_config`；部署文件使用 `config`。两种文件不能混用。文件已经限定 channels 时，额外的 `channels` 必须与文件完全一致；想缩小范围时编辑文件。

Windows 使用对应 PCAN、MiniCANFD 或 SLCAN 模板；例如在已配置 ROS 的 PowerShell 中复制 SLCAN FD 设置，编辑真实 COM 端口后启动：

```powershell
$handShare = Join-Path (ros2 pkg prefix linkerbot_hand_ros) "share\linkerbot_hand_ros"
$handConfig = Join-Path $HOME "hand-config"
New-Item -ItemType Directory -Force $handConfig | Out-Null
Copy-Item (Join-Path $handShare "config\discovery-slcan-windows.yaml") $handConfig
$handSettings = Join-Path $handConfig "discovery-slcan-windows.yaml"
# 编辑 COM5 并确认 CANable 2.0 FD 固件、CAN/数据速率。
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true "discovery_config:=$handSettings"
```

## 四类适配器

- [discovery-socketcan.yaml](../../config/discovery-socketcan.yaml)：显式 `can0`；系统接口须已配置。`ip -details link show can0` 可只读检查 UP、CAN/CAN FD 和速率，扫描不会配置接口。
- [discovery-pcan-classic.yaml](../../config/discovery-pcan-classic.yaml)：Windows 经典 CAN，原生通道 `PCAN_USBBUS1`；修改为实际 PCAN 通道并匹配设备速率。
- [discovery-pcan-fd.yaml](../../config/discovery-pcan-fd.yaml)：Windows FD 模式与完整 `BitTimingFd` 配方，示例为 80 MHz 时钟、1 Mbit/s 仲裁、5 Mbit/s 数据；仅用于已确认 FD 能力的适配器，按硬件时钟和总线时序修改。
- [discovery-slcan-windows.yaml](../../config/discovery-slcan-windows.yaml)：Windows 显式 `COM5`，针对已确认的 CANable 2.0 FD 固件。`tty_baudrate` 是串口速率，不是 CAN 速率；任意串口设备或其他固件不能据此宣称支持 FD。
- [discovery-minicanfd-linux.yaml](../../config/discovery-minicanfd-linux.yaml)：填写真实 `libcanbus.so` 路径及已确认的设备/通道布局；`{0: [0]}` 只是模板，不能由设备数量猜通道。
- [discovery-minicanfd-windows.yaml](../../config/discovery-minicanfd-windows.yaml)：填写 `HCanbus.dll` 路径，省略 Linux 布局；`minicanfd:0:0` 的第一项为 DLL 的 `devNum`，后一项固定为 0。

MiniCANFD 两份模板显式使用 `config: 6`（0x06，不启用内置终端电阻），其余配置保留 SDK 默认；按实际接线确认外置/内置终端方案后编辑，扫描不会替用户选择。厂商库不随 ROS 或 SDK 分发。

## 一手、双手的固定部署

[deployment-single.yaml](../../config/deployment-single.yaml) 为 L6 左手/can0、角色 `/left_hand`；[deployment-dual.yaml](../../config/deployment-dual.yaml) 再加入 O6 右手/can1、角色 `/right_hand`。它们使用实际经典 CAN 左/右地址，但不是现场扫描记录，未填写序列号；不能保证同型号同侧设备更换后仍识别为原来那只手。生产部署优先生成现场文件。

模板设为 `autostart: false`，加载后仍扫描并创建未配置节点，等待生命周期管理，并非无设备 I/O 的文件检查。核对接线与绑定后才运行：

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py config:=/实际路径/deployment-dual.yaml
```

生成现场绑定的推荐流程：

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py discover:=true \
  channels:=can0,can1 output:=./hands-lab.yaml
# 结束前有序失活、cleanup 并退出；下一进程复用该文件。
ros2 launch linkerbot_hand_ros multi_hand.launch.py config:=./hands-lab.yaml
```

生成文件保留可取得的身份条件、实际端点、namespace 和逐手参数；新设备不自动加入，已有输出不覆盖。跨后端使用对应高级模板生成，例：`discover:=true discovery_config:=/实际路径/discovery-pcan-fd.yaml output:=./hands-pcan.yaml`。

## 软件验证边界

八份模板均经当前 SDK 配置/schema 校验；每份部署或由高级模板生成的部署都在新进程加载、重新匹配内存候选并 configure，未打开厂商库或向硬件发送帧。实际接口名称、库位数、驱动、固件、CAN 时序和 Windows ROS 支持仍需实机验收。常见失败见[故障排查](troubleshooting.md#自动发现与部署加载故障)。
