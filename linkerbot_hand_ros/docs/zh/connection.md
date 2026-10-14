# 准备通信接口

先完成[安装](quick_start.md)。一条物理 CAN/CAN FD 通道连接一只手，多手分别使用独立通道。
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

## 厂商适配器

MiniCANFD 需安装厂商驱动及 `libcanbus.so`（Linux）或 `HCanbus.dll`（Windows）。PCAN 需安装 PCANBasic 和驱动；SLCAN FD 需确认 CANable 2.0 FD 固件。动态库位数须与 Python 进程一致。

Linux 通过 `can0` 等接口使用的适配器走 SocketCAN；Windows 的 SDK 适配器支持不代表 ROS Windows 部署已经验证。

## 选择连接方式

- [手动连接](manual_connection.md)：填写已知型号和接口。
- [自动连接](discovery.md)：识别一只手，或发现多只手并生成部署文件。

再次扫描或用 SDK 脚本访问同一设备前，先停止旧驱动并执行 deactivate、cleanup。

[返回总览](getting_started.md) · [English](../connection.md)
