# 准备通信接口与手工连接

[English](../connection.md) · [使用手册](../../README_zh.md)

先完成[安装](getting_started.md)。一条物理 CAN/CAN FD 通道连接一只手，多手分别使用独立通道。
本仓库安装流程面向 Ubuntu 22.04/Humble 或 Ubuntu 24.04/Jazzy；Windows 适配器配置沿用 SDK 能力，Windows ROS 与硬件运行需单独验证。

## Linux SocketCAN

安装适配器驱动或固件，确认系统提供 `can0` 等网络接口。仅出现串口名不代表具备 SocketCAN FD。
启动驱动前配置接口；自动发现不会修改接口状态或速率。

L6、O6、L20Lite、L20 使用经典 CAN，速率为 1 Mbit/s：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
```

O20、L30、O30 使用 CAN FD。SDK 标准配置为仲裁 1 Mbit/s、数据 5 Mbit/s：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000 dbitrate 5000000 fd on
sudo ip link set can0 up
ip -details -statistics link show can0
```

O20/L30 要求 capability 声明的数据速率。O30 使用 BRS off；capability 未约束数据段速率且
JSON 未指定时，ROS 采用当前链路值，读取不到时回落到 5 Mbit/s。接口仍须启用 FD 并使用正确仲裁速率。

## 手工启动单手

填写实际型号、左右手和接口：

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=o6 side:=right \
  transport_json:='{"backend":"socketcan","channel":"can0"}'
```

`socketcan` 根据型号能力选择经典 CAN 或 FD。
`model` 不区分大小写：`l6`、`o6`、`l20lite`（也接受 `l20-lite`）、`l20`、`o20`、`l30`、`o30`。
`side` 使用 `left/right`；L30 的配置侧别必须为空：

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l30 side:='' \
  transport_json:='{"backend":"socketcan","channel":"can0"}'
```

## MiniCANFD

安装厂商驱动及与进程位数匹配的动态库：Linux 为 `libcanbus.so`，Windows 为 `HCanbus.dll`。
ROS 和 SDK 不分发厂商库。O20、L30、O30 可使用手工 `vendor_canfd` 后端：

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=o30 side:=right \
  transport_json:='{"backend":"vendor_canfd","device_index":0,"channel_index":0,"library_path":"/opt/minicanfd/libcanbus.so"}'
```

Linux 的两个编号分别是设备和通道；Windows 的 `device_index` 是 DLL 的 `devNum`，
`channel_index` 固定为 0。手工连接只使用指定编号，可选 JSON 字段见[参数配置](configuration.md#transport-json)。

自动枚举时，将以下内容保存为设置文件，并在 `discover:=true` 后传入
`discovery_config:=/绝对路径/settings.yaml`：

```yaml
backends: [minicanfd]
minicanfd:
  library_path: /opt/minicanfd/libcanbus.so
```

未指定通道时，Linux 对每个适配器先检查通道 0；没有身份候选且已成功清理连接时再检查 1。
通道 0 不是 FD 时直接检查 1；在 0 找到候选后不再回退。
显式全局 `channels` 或 `minicanfd.linux_channels` 会关闭自动回退。Windows 枚举可用 FD 通道。
随包模板是固定通道示例；需要自动枚举时省略模板中的通道筛选。

## PCAN 与 SLCAN

Linux 下驱动提供 `can0` 后使用 SocketCAN。
Windows 经典 PCAN 可通过手工 `python_can` JSON 指定
`interface_name="PCAN_USBBUS1"`、`interface_type="pcan"`。
PCAN FD 和 SLCAN FD 使用[发现设置](discovery_examples.md)，手工 `python_can` 仅支持经典 CAN。

PCAN 需要 PCANBasic 和厂商驱动。SLCAN FD 需要 CANable 2.0 FD 固件；默认枚举 USB
`16D0:117E`，串口速率 115200。其他设备显式填写通道。`tty_baudrate` 是串口速率，与 CAN 速率分开设置。

## 下一步

[读取首组角度](getting_started.md#5-连接一只手)、[自动发现与多手部署](discovery.md)，
或使用[手工多手参数文件](configuration.md#多设备)。
另一个 ROS 进程或 SDK 脚本连接同一设备前，先停止并 cleanup 当前驱动。
