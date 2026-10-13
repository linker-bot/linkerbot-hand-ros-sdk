# Discovery configuration examples

English | [简体中文](zh/discovery_examples.md) | [Manual](../README.md)

The driver installs these templates under `share/linkerbot_hand_ros/config`; sources are in this package's `config` directory. Adjust ports, timing, firmware and native libraries for your hardware. Passing software validation does not constitute adapter acceptance.

## Platform scope

Use the SDK's actual platform sources: Linux supports SocketCAN (classic CAN/CAN FD) and MiniCANFD; Windows supports PCAN (classic CAN/CAN FD), MiniCANFD and SLCAN (CAN FD). Explicit `backends` only filters sources available on that platform. No Linux SLCAN/PCAN discovery template is provided. Simulating Windows source selection does not establish Windows ROS or adapter acceptance.

## Quick start and editable templates

A single hand needs no file; explicitly limit its interface:

```bash
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true channels:=can0
```

On Linux, copy the SocketCAN template to a writable location and edit the actual interface. Relative vendor-library paths resolve from the copied YAML directory:

```bash
hand_share="$(ros2 pkg prefix linkerbot_hand_ros)/share/linkerbot_hand_ros"
mkdir -p ~/hand-config
cp "$hand_share/config/discovery-socketcan.yaml" ~/hand-config/
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true \
  discovery_config:="$HOME/hand-config/discovery-socketcan.yaml"
```

Use `discovery_config` for scan settings and `config` for deployments. If the settings already define channels, an additional `channels` argument must match exactly; edit the file to narrow scope.

On Windows, choose the matching PCAN, MiniCANFD or SLCAN template. In a ROS-configured PowerShell, copy SLCAN FD settings, edit the actual COM port, then start:

```powershell
$handShare = Join-Path (ros2 pkg prefix linkerbot_hand_ros) "share\linkerbot_hand_ros"
$handConfig = Join-Path $HOME "hand-config"
New-Item -ItemType Directory -Force $handConfig | Out-Null
Copy-Item (Join-Path $handShare "config\discovery-slcan-windows.yaml") $handConfig
$handSettings = Join-Path $handConfig "discovery-slcan-windows.yaml"
# Edit COM5; confirm CANable 2.0 FD firmware and CAN/data bitrates.
ros2 launch linkerbot_hand_ros hand.launch.py discover:=true "discovery_config:=$handSettings"
```

## Adapter templates

- [discovery-socketcan.yaml](../config/discovery-socketcan.yaml): explicit `can0`, already configured by the host. Read its UP state, CAN/FD mode and bitrates with `ip -details link show can0`; discovery does not configure links.
- [discovery-pcan-classic.yaml](../config/discovery-pcan-classic.yaml): Windows classic CAN, native `PCAN_USBBUS1`; match the actual adapter channel and device bitrate.
- [discovery-pcan-fd.yaml](../config/discovery-pcan-fd.yaml): Windows FD-only policy and a complete `BitTimingFd` recipe. The example assumes an 80 MHz clock, 1 Mbit/s arbitration and 5 Mbit/s data. Confirm FD support and adjust clock/timing for the adapter and bus.
- [discovery-slcan-windows.yaml](../config/discovery-slcan-windows.yaml): Windows explicit `COM5`, for verified CANable 2.0 FD firmware. `tty_baudrate` is serial speed, separate from CAN bitrate; arbitrary serial devices/firmware are not implied to support FD.
- [discovery-minicanfd-linux.yaml](../config/discovery-minicanfd-linux.yaml): replace the `libcanbus.so` path and confirmed Linux device/channel layout. `{0: [0]}` is a template, not a channel count inferred from enumerated devices.
- [discovery-minicanfd-windows.yaml](../config/discovery-minicanfd-windows.yaml): replace the `HCanbus.dll` path; omit Linux layouts. The first index in `minicanfd:0:0` is DLL `devNum`, with channel index 0.

Both MiniCANFD templates explicitly set `config: 6` (0x06, built-in termination disabled), retaining other SDK defaults. Verify the physical termination arrangement before editing. Native libraries are not distributed with ROS or the SDK.

## Fixed single/dual deployments

[deployment-single.yaml](../config/deployment-single.yaml) binds L6 left/can0 to `/left_hand`. [deployment-dual.yaml](../config/deployment-dual.yaml) adds O6 right/can1 at `/right_hand`. They use the actual classic CAN left/right addresses, but are not a record of your devices and omit serial identities. Endpoint-only matching cannot guarantee the original physical hand after a same-model/side replacement. Prefer generating a deployment from the installation.

Templates use `autostart: false`; loading still scans and creates unconfigured nodes awaiting lifecycle management. It is not a zero-I/O validation command. Check wiring/bindings before running:

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py config:=/actual/path/deployment-dual.yaml
```

Recommended flow for real bindings:

```bash
ros2 launch linkerbot_hand_ros multi_hand.launch.py discover:=true \
  channels:=can0,can1 output:=./hands-lab.yaml
# Orderly deactivate, cleanup and exit before starting the next process.
ros2 launch linkerbot_hand_ros multi_hand.launch.py config:=./hands-lab.yaml
```

Generated files retain available identity constraints, observed endpoints, namespaces and per-hand parameters. New devices are not added and existing output is not overwritten. For another backend, generate using its settings template, e.g. `discover:=true discovery_config:=/actual/path/discovery-pcan-fd.yaml output:=./hands-pcan.yaml`.

The templates fix explicit channels. To use automatic MiniCANFD enumeration, omit
global channel filters and Linux channel layouts as described in [connection](connection.md#minicanfd).
For startup failures see [discovery troubleshooting](discovery_troubleshooting.md).
