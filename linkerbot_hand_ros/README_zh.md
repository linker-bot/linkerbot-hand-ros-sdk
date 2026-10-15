# Linkerbot Hand ROS 2 使用手册

[English](README.md) | 简体中文

通过 ROS 2 Topic 和 Service 控制 L6、O6、L20Lite、L20、O20、L30、O30。
驱动持有一个 `HandDevice`，连接、查询和命令调度由最新 Hand Python `main` 负责；
业务节点通过 ROS 接口使用设备，无需另外打开 CAN。

## 快速开始

[网站使用手册总览](docs/zh/getting_started.md)

[安装与首组角度](docs/zh/quick_start.md)：选择 Humble 或 Jazzy 环境、安装源码、构建并读取设备状态。

## 连接设备

- [准备通信接口](docs/zh/connection.md)，再[手动连接](docs/zh/manual_connection.md)：SocketCAN、MiniCANFD、型号和左右手。
- [自动发现与多手部署](docs/zh/discovery.md)：连接单手、多手及保存现场配置。
- [适配器配置示例](docs/zh/discovery_examples.md)：PCAN、SLCAN、MiniCANFD 及固定部署模板。

## 设备功能

- [七种型号的 ROS 用法](docs/zh/models.md)：关节数、速度/加速度、电流/转矩、特殊操作。
- [命令与 Python 示例](docs/zh/examples.md)：发送目标、读取配置、接入常驻客户端。
- [触觉字段](docs/zh/force.md)：点阵、法向/切向字段、接近数据及轮询。
- [O6 图形界面](docs/zh/gui.md)：URDF 预览和显式启用的实机控制。

## ROS 参考与集成

- [ROS API](docs/zh/ros_api.md)：Topic、Service、消息语义、QoS。
- [Lifecycle 与参数](docs/zh/configuration.md)：默认值、在线调频、超时和恢复。
- [业务集成](docs/zh/business_integration.md)：就绪、反馈、到位判断和资源释放。
- [客户端等待](docs/zh/client_waits.md)：同步/异步等待和 executor 要求。
- [频率测试](docs/zh/frequency_benchmark.md)：区分命令发送、设备采样和 ROS 发布频率。

## 维护

- [故障排查](docs/zh/troubleshooting.md)
- [更新 SDK 与 ROS](docs/zh/update.md)
- [本地开发检查](../DEVELOPMENT.md)
- [Hand Python 使用手册](https://github.com/linker-bot/linkerbot-hand-python-sdk/blob/main/docs/zh/src/reference/README.md)

关节顺序、范围和接口支持性以已连接设备的 `capabilities` 为准。
命令被接受、已发送、协议确认与机械到位是不同阶段；到位需检查当前连接代次的有效反馈。
