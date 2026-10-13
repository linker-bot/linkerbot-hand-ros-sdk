# Linkerbot Hand ROS 2

[English](README.md) | [简体中文](README_zh.md)

ROS 2 Jazzy Lifecycle driver for Linkerbot O6, L6, L20Lite, L20, O20,
O30, and L30 hands. The driver targets the public `HandDevice` API on the latest SDK `main` and
uses the SDK capability object as its only model specification.

See the [unified tactile guide](docs/zh/force.md) for field topics, model support
and `force_<field>_hz` parameters. Install the latest Hand SDK `main` and build
ROS messages, the driver and consumers from consistent interface definitions.

The ownership boundary is strict:

- configure constructs descriptors and ROS entities without device I/O;
- activate calls `open()` and starts SDK-owned polling;
- command callbacks call non-blocking `set_*()` methods only;
- state publication reads `get_snapshot()` and emits each SDK sequence once;
- diagnostics reads `get_health()` only;
- deactivate stops polling while cleanup and shutdown close the device.

ROS exposes typed topics and uses SDK polling for device queries.
Protocol raw, percent, and physical-angle values remain separate in typed
messages. Flexion percent uses `0=flexed/closed` and `100=extended/open`;
directional axes use the endpoint labels published in `HandCapabilities`.
Runtime optional-query fallback is republished through
`firmware_unsupported_telemetry`; supported non-volatile configuration is
submitted through the capability-gated `save_parameters` service.

L6 control gains `position_kp`, `position_kd` and `torque_kd` have raw command
topics, `HandCommandClient` setters, setter/getter services and cached state
topics. See [L6 control gains](docs/ros_api.md#l6-control-gains) for ranges, units
and FIFO behavior. Reading these parameters is on demand, without extra polling.

## Requirements

- Ubuntu 24.04 and ROS 2 Jazzy
- Python 3.10 or newer
- `linkerbot-transport` (`main`)
- `linkerbot-hand` (`main`)
- a configured SocketCAN/CAN FD interface or supported vendor adapter

First-time users can run the repository
[quick start](../README.md#quick-start). For a manual installation, create an
isolated environment that can read the system ROS packages and explicitly
install both Transport and Hand from their latest `main` branches:

```bash
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 -m venv --system-site-packages ~/venvs/linkerbot-hand-ros
source ~/venvs/linkerbot-hand-ros/bin/activate
mkdir -p ~/linkerbot_deps
cd ~/linkerbot_deps
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-transport.git linkerbot-transport
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-hand.git linkerbot-hand
python -m pip install -e './linkerbot-transport[all]' -e ./linkerbot-hand
```

For existing clones, update both `main` branches before reinstalling:

```bash
git -C ~/linkerbot_deps/linkerbot-transport switch main
git -C ~/linkerbot_deps/linkerbot-transport pull --ff-only origin main
git -C ~/linkerbot_deps/linkerbot-hand switch main
git -C ~/linkerbot_deps/linkerbot-hand pull --ff-only origin main
python -m pip install -e "$HOME/linkerbot_deps/linkerbot-transport[all]" \
  -e "$HOME/linkerbot_deps/linkerbot-hand"
```

## Build

`linkerbot_hand_msgs` contains ROSIDL interfaces and must be generated for the
installed ROS distribution. Build the ROS packages together from the same
latest `main` checkout:

```bash
mkdir -p ~/linkerbot_ws/src
cd ~/linkerbot_ws/src
git clone --branch main --depth 1 \
  https://gitea.linkerhub.work/zhuzhixiang/linkerbot-hand-ros2.git linkerbot-hand-ros
cd ~/linkerbot_ws
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source ~/linkerbot_ws/install/setup.bash

python -c 'import linkerbot_transport, linkerbot_hand; print("Python dependencies: OK")'
ros2 pkg prefix linkerbot_hand_msgs
ros2 pkg prefix linkerbot_hand_ros
ros2 interface show linkerbot_hand_msgs/msg/HandJointCommand >/dev/null
ros2 pkg executables linkerbot_hand_ros
```

For an existing ROS workspace, update its `main` checkout and rebuild all
packages and downstream consumers after updating the SDK sources:

```bash
git -C ~/linkerbot_ws/src/linkerbot-hand-ros switch main
git -C ~/linkerbot_ws/src/linkerbot-hand-ros pull --ff-only origin main
cd ~/linkerbot_ws
rosdep install --from-paths src --ignore-src -y --rosdistro jazzy
python -m colcon build --symlink-install \
  --cmake-args -DPython3_EXECUTABLE="$(command -v python)"
source ~/linkerbot_ws/install/setup.bash
```

Any unresolved rosdep key is an error. A `pkg_resources is deprecated` line
from Ubuntu's rosdep launcher is only a warning.
This verification checks dependencies, ROSIDL interfaces, the ament index, and
program entry points without opening a device or sending a CAN frame.

## Run

Automatic single-hand startup accepts one unique verified hand:

```bash
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true
```

Automatic multi-hand startup prints a summary, saves `./hands.yaml` without
overwriting, and activates all verified hands in scope. Reuse the saved file:

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py discover:=true
ros2 launch linkerbot_hand_ros multi_hand.launch.py config:=./hands.yaml
```

Use `channels:=can0` to limit discovery and `output:=./hands-lab.yaml` to choose
a new multi-hand output. See [automatic discovery](docs/discovery.md) for
selection, fixed roles, lifecycle and advanced settings. Manual startup follows.

Start a left L6 on `can0`:

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l6 side:=left \
  transport_json:='{"backend":"socketcan","channel":"can0"}'
```

L30 has no left/right variant, so pass an empty side:

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l30 side:='' \
  transport_json:='{"backend":"socketcan","channel":"can0"}'
```

Run multiple hands in one process with a ROS parameter file:

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py
```

The installed `config/multi_hand.yaml` example creates
`/l6_left/linkerbot_hand` on `can0` and `/o6_right/linkerbot_hand` on `can1`.
The maintained topology is one hand per physical CAN/CAN FD channel. Connect
each hand to its own interface and configure both before autostart. Pass
`config:=/absolute/path/to/hands.yaml` for your actual wiring.

The container provides group startup and rollback in one process; separate
channels still use separate transport runtimes. The SDK can share a runtime,
RX reactor and TX arbiter for equal physical keys, but that resource mechanism
does not establish support for multiple hands on one channel. ROS namespaces
do not isolate device traffic. Separate `hand.launch.py` processes do not
provide the container's group startup/rollback or shared in-memory arbitration.

Inspect the verified metadata and state:

```bash
ros2 lifecycle get /linkerbot_hand
ros2 topic echo --once /linkerbot_hand/capabilities
ros2 topic echo --once /linkerbot_hand/device_info
ros2 topic echo --once /linkerbot_hand/state/angles
ros2 topic echo /linkerbot_hand/command/status
```

`/command/status` uses `HandCommandStatusBatch`; consumers must iterate every
changed status in `statuses[]` and correlate both `client_id` and
`user_sequence`.

Send one percent target with the typed message:

```bash
ros2 topic pub --once /linkerbot_hand/command/angles \
  linkerbot_hand_msgs/msg/HandJointCommand \
  '{client_id: 1, user_sequence: 1, representation: 1, values: [50, 50, 50, 50, 50, 50]}'
```

`representation=1` means percent and `representation=2` means exact protocol
raw. The values always follow the capability joint order. Use the persistent
Python client for control loops:

```bash
ros2 run linkerbot_hand_ros angle_controller
```

The frequency tool evaluates publish, driver receive, SDK acceptance, actual
dispatch, terminal stages, device sample sequences, and optional complete
tactile transactions separately:

```bash
ros2 run linkerbot_hand_ros frequency_benchmark \
  --angle-feedback query_only --angle-rates 50 100 150 200 \
  --duration 180 --repetitions 3
```

The production driver uses a single-threaded executor to avoid Python GIL
contention between short callbacks. SDK cache revisions wake a dedicated state
publisher immediately, so equal-rate timer aliasing does not discard feedback.
`publish_rate_hz` controls idle cache checks for age/stale transitions; zero
pauses ROS state publication. An unchanged sequence is never republished.
In `query_only`, command feedback remains in SDK cache and metrics but
`~/state/angles` publishes active-query responses only.

See [ROS API](docs/ros_api.md), the
[Chinese integration guide](docs/zh/business_integration.md), and the
[frequency benchmark guide](docs/zh/frequency_benchmark.md).

## Safety

`ACCEPTED`, `DISPATCHED`, protocol `ACKNOWLEDGED`, and mechanical arrival are
different states. A successful service response for a command means accepted,
not delivered. Determine arrival from valid, non-stale feedback in the current
connection generation. Recovery never replays pre-disconnect targets.

## Development

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
colcon test --event-handlers console_direct+
colcon test-result --verbose
```
