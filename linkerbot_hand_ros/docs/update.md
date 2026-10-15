# Update SDK and ROS

Stop target publishers, deactivate/cleanup drivers and exit their processes before updating.
Keep local changes; if switching or fast-forwarding fails, resolve the branch state before continuing.
Do not reset a working tree to bypass the error.

Choose the distribution matching your OS using the [installation guide](quick_start.md#1-choose-a-ros-distribution-and-prepare-the-environment).
The commands below use separate venvs and workspaces per distribution; adjust paths for existing installations.
Use a separate workspace when changing ROS distributions; generated build/install artifacts cannot be shared.

Open a fresh terminal and load the build environment:
First set `export LINKERBOT_ROS_DISTRO=humble` or `export LINKERBOT_ROS_DISTRO=jazzy`.

```bash
source "/opt/ros/${LINKERBOT_ROS_DISTRO}/setup.bash"
source "$HOME/venvs/linkerbot-hand-${ROS_DISTRO}/bin/activate"
```

Set Transport, Hand and ROS origins to their current repository URLs, update all three
`main` branches and reinstall the editable dependencies:

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

Rebuild the workspace and downstream message consumers:

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

Confirm dependency checks pass, all three packages resolve to this workspace, and
the GUI executable list includes `o6_gui_bridge`. GUI users should also verify their
external `linker-sim-assets` checkout; follow [asset setup](gui.md)
for missing or incomplete Git LFS files. Rebuilding ROS does not download or update
that asset repository.

Open fresh terminals and [load the environment](quick_start.md#4-load-each-terminal).
Rediscover devices and verify their capabilities and current state before sending targets.
If generated ROS interfaces are inconsistent, remove only the affected build/install outputs
and rebuild the message package and its consumers together.

To record the exact sources used for a deployment:

```bash
git -C ~/linkerbot_deps/linkerbot-transport rev-parse HEAD
git -C ~/linkerbot_deps/linkerbot-hand rev-parse HEAD
git -C "$HOME/linkerbot_${ROS_DISTRO}_ws/src/linkerbot-hand-ros" rev-parse HEAD
```

[Back to overview](getting_started.md) · [简体中文](zh/update.md)
