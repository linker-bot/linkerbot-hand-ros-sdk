# 更新 SDK 与 ROS

[English](../update.md) · [使用手册](../../README_zh.md)

更新前停止业务目标，deactivate/cleanup 驱动并退出进程。
保留本地修改；切换分支或快进失败时先处理分支状态，不用重置工作区绕过错误。

在新终端加载构建环境：

```bash
source /opt/ros/jazzy/setup.bash
source ~/venvs/linkerbot-hand-ros/bin/activate
```

更新三个仓库的 `main`，重新安装源码依赖：

```bash
git -C ~/linkerbot_deps/linkerbot-transport switch main
git -C ~/linkerbot_deps/linkerbot-transport pull --ff-only origin main
git -C ~/linkerbot_deps/linkerbot-hand switch main
git -C ~/linkerbot_deps/linkerbot-hand pull --ff-only origin main
git -C ~/linkerbot_ws/src/linkerbot-hand-ros switch main
git -C ~/linkerbot_ws/src/linkerbot-hand-ros pull --ff-only origin main
python -m pip install -e "$HOME/linkerbot_deps/linkerbot-transport[all]" \
  -e "$HOME/linkerbot_deps/linkerbot-hand"
```

重建工作空间及依赖消息定义的下游包：

```bash
cd ~/linkerbot_ws
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source ~/linkerbot_ws/install/setup.bash
python -c 'import linkerbot_transport, linkerbot_hand; print("Python dependencies: OK")'
ros2 pkg prefix linkerbot_hand_msgs
ros2 pkg prefix linkerbot_hand_ros
ros2 interface show linkerbot_hand_msgs/msg/HandJointCommand
```

在新终端[重新加载环境](getting_started.md#4-每个终端加载环境)，再次发现设备，确认能力及当前反馈后再发目标。
若生成的 ROS 接口不一致，只清理受影响的 build/install 产物，并一起重建消息包与消费者。

记录实际使用的源码提交，便于复现：

```bash
git -C ~/linkerbot_deps/linkerbot-transport rev-parse HEAD
git -C ~/linkerbot_deps/linkerbot-hand rev-parse HEAD
git -C ~/linkerbot_ws/src/linkerbot-hand-ros rev-parse HEAD
```
