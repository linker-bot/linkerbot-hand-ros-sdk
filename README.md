# Linkerbot Hand ROS 2

This repository contains three independently discoverable ROS 2 packages:

- [`linkerbot_hand_msgs`](./linkerbot_hand_msgs): typed messages and services.
- [`linkerbot_hand_ros`](./linkerbot_hand_ros): the Lifecycle driver and tools.
- [`linkerbot_hand_gui`](./linkerbot_hand_gui): O6 URDF slider preview and safe
  ROS 2 control bridge.

## Quick Start

[简体中文](README_zh.md)

Use ROS 2 Humble on Ubuntu 22.04 or Jazzy on Ubuntu 24.04, with the latest `main`
of Transport, Hand Python and this repository. Use the matching system Python
and a separate workspace for each ROS distribution.

1. [Install and build](linkerbot_hand_ros/docs/quick_start.md).
2. [Prepare the adapter](linkerbot_hand_ros/docs/connection.md), then launch one hand:

   ```bash
   ros2 launch linkerbot_hand_ros hand.launch.py discover:=true
   ```

3. In another configured terminal, read the first angle sample:

   ```bash
   ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/angles
   ```

[User manual](linkerbot_hand_ros/README.md) ·
[Model guide](linkerbot_hand_ros/docs/models.md) ·
[ROS API](linkerbot_hand_ros/docs/ros_api.md) ·
[Update sources](linkerbot_hand_ros/docs/update.md)

The O6 URDF slider GUI is documented in
[`linkerbot_hand_gui/README.md`](./linkerbot_hand_gui/README.md). It uses the
URDF and meshes from `linker-sim-assets`; install Git LFS and set
`LINKERBOT_HAND_ASSETS_ROOT` before launching it.
