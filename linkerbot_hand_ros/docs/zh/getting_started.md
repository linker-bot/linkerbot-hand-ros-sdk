# 灵巧手 ROS 2 使用手册

`linkerbot_hand_ros` 将 LinkerHand 灵巧手接入 ROS 2，提供设备发现、角度控制、状态与触觉读取，以及管理服务。支持 L6、O6、L20Lite、L20、O20、L30 和 O30。

> [!TIP]
> 首次使用时，请从快速开始完成安装与状态读取，再查看对应型号的功能。

## 快速开始

[快速开始](quick_start.md)：安装 Python 依赖与 ROS 包，连接一只手并读取首组角度。

- Ubuntu 22.04 / Python 3.10：使用 [Humble](quick_start.md#ubuntu-2204humble)。
- Ubuntu 24.04 / Python 3.12：使用 [Jazzy](quick_start.md#ubuntu-2404jazzy)。

两者使用同一份 `main` 源码和 ROS 接口；分别安装、构建后，按[对应发行版加载环境](quick_start.md#4-每个终端加载环境)，再使用下方连接与功能文档。

## 连接设备

先[准备通信接口](connection.md)，再选择连接方式：

- [手动连接](manual_connection.md)：明确型号、侧别和适配器参数。
- [自动连接](discovery.md)：自动识别单手、多手，并保存可复用的部署配置。

## 设备功能

各型号均提供身份与能力信息、角度、速度设置、电流与温度等状态；实际端点以当前设备的 `capabilities` 为准。

| 型号 | 功能 |
| --- | --- |
| [L6](l6.md) | 角度、速度、力矩模式、控制增益、限位补偿、触觉 |
| [O6](o6.md) | 角度、速度、加速度、触觉、O6 图形界面 |
| [L20Lite](l20lite.md) | 角度、速度、加速度、触觉点阵及合力/方向/接近值 |
| [L20](l20.md) | 角度、速度、触觉、故障清除 |
| [O20](o20.md) | 角度、速度、配置回读、触觉、故障清除 |
| [L30](l30.md) | 角度、速度、触觉、使能/失能、标定 |
| [O30](o30.md) | 角度、速度、加速度、力矩限幅、运动时间、descriptor 触觉 |

[型号差异](models.md)说明配置回读、单位和传感器差异。

## 开发集成

- [控制与 Python 示例](examples.md)：读状态、发目标、复用 `HandCommandClient`。
- [业务节点集成](business_integration.md)：就绪判断、命令状态、到位判定和恢复。
- [ROS 2 API](ros_api.md)：话题、服务、QoS 和错误语义。
- [消息字段](messages.md)、[触觉数据](force.md)、[生命周期与参数](configuration.md)：按需查阅。

## 补充说明

- [故障排查](troubleshooting.md)：定位安装、连接、状态和控制问题。
- [更新 SDK 与 ROS](update.md)：更新源码、重建消息和驱动。
- [频率测试](frequency_benchmark.md)：区分命令发送、设备采样和 ROS 接收频率。

[English](../getting_started.md)
