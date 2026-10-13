# Update SDK and ROS

[简体中文](zh/update.md) · [Manual](../README.md)

Stop target publishers, deactivate/cleanup drivers and exit their processes before updating.
Keep local changes; if switching or fast-forwarding fails, resolve the branch state before continuing.
Do not reset a working tree to bypass the error.

Open a fresh terminal and load the build environment:

```bash
source /opt/ros/jazzy/setup.bash
source ~/venvs/linkerbot-hand-ros/bin/activate
```

Set Transport, Hand and ROS origins to their current repository URLs, update all three
`main` branches and reinstall the editable dependencies:

```bash
git -C ~/linkerbot_deps/linkerbot-transport remote set-url origin \
  https://gitea.linkerhub.work/linker-bot/linkerbot-transport.git
git -C ~/linkerbot_deps/linkerbot-transport switch main
git -C ~/linkerbot_deps/linkerbot-transport pull --ff-only origin main
git -C ~/linkerbot_deps/linkerbot-hand remote set-url origin \
  https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python.git
git -C ~/linkerbot_deps/linkerbot-hand switch main
git -C ~/linkerbot_deps/linkerbot-hand pull --ff-only origin main
git -C ~/linkerbot_ws/src/linkerbot-hand-ros remote set-url origin \
  https://gitea.linkerhub.work/linker-bot/linkerbot-hand-ros2.git
git -C ~/linkerbot_ws/src/linkerbot-hand-ros switch main
git -C ~/linkerbot_ws/src/linkerbot-hand-ros pull --ff-only origin main
python -m pip install -e "$HOME/linkerbot_deps/linkerbot-transport[all]" \
  -e "$HOME/linkerbot_deps/linkerbot-hand"
```

Rebuild the workspace and downstream message consumers:

```bash
cd ~/linkerbot_ws
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
rosdep check --from-paths src --ignore-src --rosdistro jazzy
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source ~/linkerbot_ws/install/setup.bash
python -c 'import linkerbot_transport, linkerbot_hand; print("Python dependencies: OK")'
ros2 pkg prefix linkerbot_hand_msgs
ros2 pkg prefix linkerbot_hand_ros
ros2 pkg prefix linkerbot_hand_gui
ros2 pkg executables linkerbot_hand_gui
ros2 interface show linkerbot_hand_msgs/msg/HandJointCommand
```

Confirm dependency checks pass, all three packages resolve to this workspace, and
the GUI executable list includes `o6_gui_bridge`. GUI users should also verify their
external `linker-sim-assets` checkout; follow [asset setup](../../linkerbot_hand_gui/README.md#准备模型资源)
for missing or incomplete Git LFS files. Rebuilding ROS does not download or update
that asset repository.

Open fresh terminals and [load the environment](getting_started.md#4-load-each-terminal).
Rediscover devices and verify their capabilities and current state before sending targets.
If generated ROS interfaces are inconsistent, remove only the affected build/install outputs
and rebuild the message package and its consumers together.

To record the exact sources used for a deployment:

```bash
git -C ~/linkerbot_deps/linkerbot-transport rev-parse HEAD
git -C ~/linkerbot_deps/linkerbot-hand rev-parse HEAD
git -C ~/linkerbot_ws/src/linkerbot-hand-ros rev-parse HEAD
```
