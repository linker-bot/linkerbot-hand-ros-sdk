# Linkerbot Hand ROS 2

This repository contains two independently discoverable ROS 2 packages:

- [`linkerbot_hand_msgs`](./linkerbot_hand_msgs): typed messages and services.
- [`linkerbot_hand_ros`](./linkerbot_hand_ros): the Lifecycle driver and tools.

## Quick Start

The [unified tactile guide](linkerbot_hand_ros/docs/zh/force.md) describes field topics
and model capabilities on the latest `main`. Use `current_limits` for electrical
limits and O30-only `torques_limits` for its separate torque-limit object. See the
[current/torque API](linkerbot_hand_ros/docs/ros_api.md#on-demand-raw-reads).
The commands below install the latest `main` branches of all three repositories.

The complete dependency chain is
`linkerbot-transport -> linkerbot-hand -> linkerbot_hand_msgs/linkerbot_hand_ros`.
Transport and Hand are installed from source, while the ROS packages are
built together with `colcon` from the same `main` checkout. On Ubuntu 24.04 with the
ROS 2 apt repository configured, run:

Use Ubuntu’s system Python to create the environment so it matches the ROS
Python ABI; the build command also selects that interpreter explicitly.

```bash
sudo apt update
sudo apt install -y \
  git can-utils python3-venv python3-rosdep \
  python3-colcon-common-extensions ros-jazzy-ros-base

if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
  sudo rosdep init
fi
rosdep update

source /opt/ros/jazzy/setup.bash
/usr/bin/python3 -m venv --system-site-packages ~/venvs/linkerbot-hand-ros
source ~/venvs/linkerbot-hand-ros/bin/activate
python -m pip install --upgrade pip
mkdir -p ~/linkerbot_deps
cd ~/linkerbot_deps
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-transport.git linkerbot-transport
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-hand.git linkerbot-hand
python -m pip install -e './linkerbot-transport[all]' -e ./linkerbot-hand

mkdir -p ~/linkerbot_ws/src
cd ~/linkerbot_ws/src
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-hand-ros2.git linkerbot-hand-ros

cd ~/linkerbot_ws
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source ~/linkerbot_ws/install/setup.bash

python - <<'PY'
from importlib.metadata import version

import linkerbot_hand
import linkerbot_transport

print("linkerbot-transport", version("linkerbot-transport"))
print("linkerbot-hand", version("linkerbot-hand"))
print("python imports: OK")
PY
ros2 pkg prefix linkerbot_hand_msgs
ros2 pkg prefix linkerbot_hand_ros
ros2 interface show linkerbot_hand_msgs/msg/HandJointCommand >/dev/null
ros2 pkg executables linkerbot_hand_ros
```

Verification should report the installed Transport and Hand versions, workspace
prefixes for both ROS packages, and executables including `hand_node`.
The displayed version numbers are informational; source must come from `main`.
These checks do not open a device or send CAN frames. In each new terminal, source the environments in
this order:

```bash
source /opt/ros/jazzy/setup.bash
source ~/venvs/linkerbot-hand-ros/bin/activate
source ~/linkerbot_ws/install/setup.bash
```

See the
[official ROS 2 Jazzy installation guide](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)
to configure the ROS apt repository for the first time. The driver guide below
covers real-device CAN setup, launch parameters, and runtime checks.

See the [driver README](./linkerbot_hand_ros/README.md) for installation and
usage. The [Chinese documentation](./linkerbot_hand_ros/README_zh.md) is also
available.
