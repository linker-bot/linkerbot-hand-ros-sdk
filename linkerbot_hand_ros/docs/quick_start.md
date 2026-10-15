# Quick start

## 1. Choose a ROS distribution and prepare the environment

Humble and Jazzy are two ROS 2 distributions. The same `main` sources support both;
there is no separate SDK branch to select. Connection, topics, services and the
Python client use the same interfaces. Choose the option matching your OS, then
follow the shared installation and build steps.

### Ubuntu 22.04: Humble

Use system Python 3.10. Configure apt with the
[Humble installation guide](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html),
then select the distribution in the current terminal:

```bash
export LINKERBOT_ROS_DISTRO=humble
```

### Ubuntu 24.04: Jazzy

Use system Python 3.12. Configure apt with the
[Jazzy installation guide](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html),
then select the distribution in the current terminal:

```bash
export LINKERBOT_ROS_DISTRO=jazzy
```

### Shared installation

Use the distribution matching the host OS; ROS binary packages must match the Ubuntu release.
Use system Python and `--system-site-packages` to load that distribution's ROS packages.
The commands below reuse your selection and keep a separate venv and workspace for each distribution.

```bash
sudo apt update
sudo apt install -y git can-utils python3-venv python3-rosdep \
  python3-colcon-common-extensions python3-setuptools python3-wheel \
  "ros-${LINKERBOT_ROS_DISTRO}-ros-base"
if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
  sudo rosdep init
fi
rosdep update --rosdistro "${LINKERBOT_ROS_DISTRO}"
source "/opt/ros/${LINKERBOT_ROS_DISTRO}/setup.bash"
/usr/bin/python3 -m venv --system-site-packages "$HOME/venvs/linkerbot-hand-${ROS_DISTRO}"
source "$HOME/venvs/linkerbot-hand-${ROS_DISTRO}/bin/activate"
python -m pip install --upgrade pip
```

colcon reuses Ubuntu-provided setuptools/wheel. Do not upgrade setuptools with pip in this build environment.

## 2. Install the latest main sources

Clone the sources from GitHub. Install Transport before Hand Python, then build ROS messages,
driver and GUI together. Existing checkouts use the [update guide](update.md).

```bash
mkdir -p ~/linkerbot_deps
cd ~/linkerbot_deps
git clone --branch main --depth 1 \
  https://github.com/linker-bot/linkerbot-transport.git linkerbot-transport
git clone --branch main --depth 1 \
  https://github.com/linker-bot/linkerbot-hand-python-sdk.git linkerbot-hand
python -m pip install -e './linkerbot-transport[all]' -e ./linkerbot-hand

mkdir -p "$HOME/linkerbot_${ROS_DISTRO}_ws/src"
cd "$HOME/linkerbot_${ROS_DISTRO}_ws/src"
git clone --branch main --depth 1 \
  https://github.com/linker-bot/linkerbot-hand-ros-sdk.git linkerbot-hand-ros
```

The local directory `linkerbot-hand` contains the `linkerbot-hand-python-sdk` repository;
its Python distribution is named `linkerbot-hand`.

## 3. Build and verify

Build in a terminal with ROS and the venv loaded. rosdep installs system dependencies
from all three package manifests, including RViz, Joint State Publisher GUI and
Robot State Publisher. URDF and mesh assets are separate; prepare them using the GUI
resource instructions below.

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

Confirm rosdep succeeds and all three package prefixes point to this workspace.
The GUI executable list should include `linkerbot_hand_gui o6_gui_bridge`, and the
message definition should display successfully. These checks perform no device I/O
and open no graphical windows. Resolve every rosdep error; a `pkg_resources` deprecation warning alone is not a failure.
CMake explicitly uses the active Python interpreter to match the ROS ABI.

## 4. Load each terminal

After installation and build, run the matching group in every fresh terminal.

**Humble (Ubuntu 22.04)**:

```bash
export LINKERBOT_ROS_DISTRO=humble
source /opt/ros/humble/setup.bash
source ~/venvs/linkerbot-hand-humble/bin/activate
source ~/linkerbot_humble_ws/install/setup.bash
```

**Jazzy (Ubuntu 24.04)**:

```bash
export LINKERBOT_ROS_DISTRO=jazzy
source /opt/ros/jazzy/setup.bash
source ~/venvs/linkerbot-hand-jazzy/bin/activate
source ~/linkerbot_jazzy_ws/install/setup.bash
```

Check with `echo "$ROS_DISTRO"` and `python --version`: expect `humble` / Python 3.10
or `jazzy` / Python 3.12. Load only one distribution per terminal. Open a fresh
terminal when switching, and keep separate venvs, workspaces and build outputs.
After loading either environment, use the same driver and state commands below.

For O6 visualization, follow [O6 GUI](gui.md) to prepare model assets. Command-line use needs no model assets.

## 5. Connect one hand

[Prepare the communication interface](connection.md), power the hand and connect exactly one
hand in the selected scope. Start the driver:

```bash
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true
```

To restrict scanning, append `channels:=can0`. Zero, multiple or incomplete candidates
cause an error. See [discovery](discovery.md) for multiple hands or vendor adapters.
Discovery and activation read identity and state; these commands send no motion targets.

In another terminal, load the same environment and read:

```bash
ros2 lifecycle get /linkerbot_hand
ros2 topic echo --once --qos-durability transient_local /linkerbot_hand/capabilities
ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/angles
```

Expect `active`, `identity.verified=true` and angle `meta.valid=true`, `stale=false`.
`joint_names` defines vector order; raw, percent and physical radians have separate validity masks.

## 6. Finish or continue

Stop applications producing targets, then release the driver connection:

```bash
ros2 lifecycle set /linkerbot_hand deactivate
ros2 lifecycle set /linkerbot_hand cleanup
```

Exit launch with Ctrl+C. Deactivation alone retains the connection; cleanup closes it.
Continue with [model features](models.md), [command examples](examples.md), or the
[O6 GUI](gui.md).

[Back to overview](getting_started.md) · [简体中文](zh/quick_start.md)
