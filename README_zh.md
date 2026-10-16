# Linkerbot Hand ROS 2

[English](README.md) | 简体中文

本仓库包含三个可由 ROS 2 独立发现的 package：

- [`linkerbot_hand_msgs`](./linkerbot_hand_msgs)：类型化消息和服务。
- [`linkerbot_hand_ros`](./linkerbot_hand_ros)：Lifecycle 驱动和配套工具。
- [`linkerbot_hand_gui`](./linkerbot_hand_gui)：O6 URDF 关节滑块预览和安全控制桥。

## 快速启动

Ubuntu 22.04 使用 ROS 2 Humble，Ubuntu 24.04 使用 Jazzy；依赖和本仓库使用最新
`main`。使用对应的系统 Python，各 ROS 发行版使用独立工作空间。

1. 按[快速入门](linkerbot_hand_ros/docs/zh/quick_start.md)安装并构建。
2. [准备通信接口](linkerbot_hand_ros/docs/zh/connection.md)，启动唯一一只手：

   ```bash
   ros2 launch linkerbot_hand_ros hand.launch.py discover:=true
   ```

3. 在另一个已加载环境的终端读取首组角度：

   ```bash
   ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/angles
   ```

[完整使用手册](linkerbot_hand_ros/README_zh.md) ·
[型号功能](linkerbot_hand_ros/docs/zh/models.md) ·
[ROS API](linkerbot_hand_ros/docs/zh/ros_api.md) ·
[更新源码](linkerbot_hand_ros/docs/zh/update.md)

O6 的 URDF 关节滑块 GUI 见[`linkerbot_hand_gui/README.md`](./linkerbot_hand_gui/README.md)。
它使用 `linker-sim-assets` 中的 URDF 和 mesh，启动前请安装 Git LFS 并设置
`LINKERBOT_HAND_ASSETS_ROOT`。

项目专属的验证命令见[开发检查](DEVELOPMENT.md)。

## 贡献与许可证

欢迎用中文或英文参与贡献，请遵循[Linkerbot 贡献指南](https://github.com/linker-bot/.github/blob/main/CONTRIBUTING.md)。
安全问题请按[组织安全策略](https://github.com/linker-bot/.github/blob/main/SECURITY.md)私下报告。

本项目采用 [MIT 许可证](LICENSE)。
