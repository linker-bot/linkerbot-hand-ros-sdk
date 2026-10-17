# O6 GUI

Preview O6 with URDF sliders and control a real hand through the ROS bridge. The GUI uses the driver for device I/O. It supports left and right O6; other models and fingertip dragging/IK are not provided.

## Prepare model assets

URDF, decoder and meshes come from [linker-sim-assets](https://github.com/linker-bot/linker-sim-assets). Download complete Git LFS assets:

```bash
sudo apt install -y git-lfs
git lfs install
git clone --branch main https://github.com/linker-bot/linker-sim-assets.git ~/linker-sim-assets
git -C ~/linker-sim-assets lfs pull
export LINKERBOT_HAND_ASSETS_ROOT=~/linker-sim-assets/src/linker_robot_assets/assets
```

An installed `linker_robot_assets` package can also supply `asset_root()`; explicit `assets_root` takes priority. The GUI does not copy model assets. Both modes prefer complete visual GLB files, then same-name OBJ and collision OBJ fallbacks. Fallback appearance may be incomplete; download Git LFS assets for full visuals. Missing O6 right-thumb GLB color slots are repaired in a user-cache copy without editing the asset repository.

## Preview only

[Load the environment](quick_start.md#4-load-each-terminal) in every terminal. Preview starts URDF, a separate slider window and RViz; it needs a graphical desktop but no device, SDK connection or bridge.

```bash
ros2 launch linkerbot_hand_gui hand_gui.launch.py \
  side:=right \
  assets_root:="$HOME/linker-sim-assets/src/linker_robot_assets/assets" \
  preview_only:=true
```

This mode publishes `/linkerbot_hand_gui/preview_joint_states` and exposes no command publisher or control-enable service.

## Connect a real O6

Start the driver in the first terminal with the actual model, side and channel:

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=o6 side:=right \
  transport_json:='{"backend":"socketcan","channel":"can1"}'
```

Start the GUI in a second terminal:

```bash
ros2 launch linkerbot_hand_gui hand_gui.launch.py \
  side:=right \
  assets_root:="$HOME/linker-sim-assets/src/linker_robot_assets/assets" \
  driver_name:=/linkerbot_hand
```

Control starts disabled. Sliders update the target model; the actual model displays feedback. Check clearance, O6 identity/side, active state and fresh angles, then enable control in a third terminal:

```bash
ros2 service call /o6_gui_bridge/set_control_enabled std_srvs/srv/SetBool '{data: true}'
```

**Move a slider again after enabling to produce a real target.** Accepted targets repeat at `command_rate_hz`, keeping only the latest target. The first slider message establishes a baseline. Timestamp changes, array reordering, non-control joints and equivalent out-of-range values are not new control targets; stationary broadcasts still update preview.

Disable control with:

```bash
ros2 service call /o6_gui_bridge/set_control_enabled std_srvs/srv/SetBool '{data: false}'
```

Disabling clears the target; enabling again requires another slider edit. Inactive drivers, expired readiness evidence, invalid angles, more than two seconds without feedback or generation changes disarm sending. Edits during faults affect preview only and are not replayed after recovery. Readiness follows [client waiting rules](client_waits.md). Close the GUI, then [stop and cleanup the driver](configuration.md#lifecycle).

## Topics and display semantics

| Topic | Purpose |
| --- | --- |
| `/linkerbot_hand_gui/raw_target_joint_states` | Raw URDF slider radians |
| `/linkerbot_hand_gui/target_joint_states` | Target-model TF |
| `/linkerbot_hand_gui/actual_joint_states` | Feedback-model TF |
| `<driver>/capabilities`, `<driver>/state/angles` | Capability and actual-percent validation |
| `<driver>/command/angles` | Percent targets while explicitly enabled, ready and feedback-valid |

The bridge validates O6, side and six joint names/order. URDF limits define display and percent mapping; command ranges come from capabilities. Without valid `physical_rad`, the displayed pose maps percent to URDF limits and is not a measured physical angle.

## Display troubleshooting

For blank RViz, inspect mesh errors and run `git -C ~/linker-sim-assets lfs pull`. Missing materials or collision-only geometry can indicate an OBJ fallback after incomplete GLB downloads. Sliders appear in a separate Joint State Publisher window; check other screens. The launcher uses the Qt XCB backend.

[Back to overview](getting_started.md) · [简体中文](zh/gui.md)
