# 更新 SDK 与 ROS

更新前停止业务目标，deactivate/cleanup 驱动并退出进程。
保留本地修改；切换分支或快进失败时先处理分支状态，不用重置工作区绕过错误。

先按[安装指南](quick_start.md#1-选择-ros-发行版并准备环境)选择与系统匹配的 ROS 发行版。
下面按发行版区分 venv 和工作空间；已有同发行版安装使用其他路径时，替换为实际路径。
跨发行版安装使用独立工作空间，不能复用另一发行版的 build/install 产物。

在新终端加载构建环境：
先设置 `export LINKERBOT_ROS_DISTRO=humble` 或 `export LINKERBOT_ROS_DISTRO=jazzy`。

```bash
source "/opt/ros/${LINKERBOT_ROS_DISTRO}/setup.bash"
source "$HOME/venvs/linkerbot-hand-${ROS_DISTRO}/bin/activate"
```

将 Transport、Hand 和 ROS 的 `origin` 设为当前仓库地址，更新三个仓库的 `main`，重新安装源码依赖：

```bash
git -C ~/linkerbot_deps/linkerbot-transport remote set-url origin \
  https://github.com/linker-bot/linkerbot-transport.git
git -C ~/linkerbot_deps/linkerbot-transport switch main
git -C ~/linkerbot_deps/linkerbot-transport pull --ff-only origin main
git -C ~/linkerbot_deps/linkerbot-hand remote set-url origin \
  https://github.com/linker-bot/linkerbot-hand-python-sdk.git
git -C ~/linkerbot_deps/linkerbot-hand switch main
git -C ~/linkerbot_deps/linkerbot-hand pull --ff-only origin main
git -C "$HOME/linkerbot_${ROS_DISTRO}_ws/src/linkerbot-hand-ros" remote set-url origin \
  https://github.com/linker-bot/linkerbot-hand-ros-sdk.git
git -C "$HOME/linkerbot_${ROS_DISTRO}_ws/src/linkerbot-hand-ros" switch main
git -C "$HOME/linkerbot_${ROS_DISTRO}_ws/src/linkerbot-hand-ros" pull --ff-only origin main
python -m pip install -e "$HOME/linkerbot_deps/linkerbot-transport[all]" \
  -e "$HOME/linkerbot_deps/linkerbot-hand"
```

重建工作空间及依赖消息定义的下游包：

```bash
cd "$HOME/linkerbot_${ROS_DISTRO}_ws"
rosdep install --from-paths src --ignore-src -y --rosdistro "${ROS_DISTRO}"
rosdep check --from-paths src --ignore-src --rosdistro "${ROS_DISTRO}"
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source "$HOME/linkerbot_${ROS_DISTRO}_ws/install/setup.bash"
python -c 'import linkerbot_transport, linkerbot_hand; print("Python dependencies: OK")'
ros2 pkg prefix linkerbot_hand_msgs
ros2 pkg prefix linkerbot_hand_ros
ros2 pkg prefix linkerbot_hand_gui
ros2 pkg executables linkerbot_hand_gui
ros2 interface show linkerbot_hand_msgs/msg/HandJointCommand
```

确认依赖检查成功，三个包均来自当前工作空间，GUI 可执行文件列表包含 `o6_gui_bridge`。
GUI 用户还需确认外部 `linker-sim-assets` 资源完整；缺失或下载不完整时按
[资源准备](gui.md)补齐 Git LFS 文件。
ROS 重建不会下载或更新该资源仓库。

在新终端[重新加载环境](quick_start.md#4-每个终端加载环境)，再次发现设备，确认能力及当前反馈后再发目标。
若生成的 ROS 接口不一致，只清理受影响的 build/install 产物，并一起重建消息包与消费者。

记录实际使用的源码提交，便于复现：

```bash
git -C ~/linkerbot_deps/linkerbot-transport rev-parse HEAD
git -C ~/linkerbot_deps/linkerbot-hand rev-parse HEAD
git -C "$HOME/linkerbot_${ROS_DISTRO}_ws/src/linkerbot-hand-ros" rev-parse HEAD
```

[返回总览](getting_started.md) · [English](../update.md)
