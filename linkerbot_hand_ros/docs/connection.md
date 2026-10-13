# Prepare interfaces and connect manually

[简体中文](zh/connection.md) · [Manual](../README.md)

Complete [installation](getting_started.md) first. Use one hand per physical CAN/CAN FD
channel; use a separate channel for each hand in a multi-hand deployment.
The ROS installation guide targets Ubuntu/Jazzy. Windows adapter configuration follows
SDK capabilities, but Windows ROS and hardware operation require platform validation.

## SocketCAN on Linux

Install the adapter's driver/firmware until Linux exposes a network interface such as `can0`.
A serial port alone does not provide a SocketCAN FD interface. Configure the link before
starting a driver; discovery does not bring links up or alter their bitrates.

L6, O6, L20Lite and L20 use classic CAN at 1 Mbit/s:

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
```

O20, L30 and O30 use CAN FD. The standard SDK setup uses 1 Mbit/s arbitration and
5 Mbit/s data:

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000 dbitrate 5000000 fd on
sudo ip link set can0 up
ip -details -statistics link show can0
```

O20/L30 require the declared data bitrate. O30 uses BRS off; when its capability does
not constrain data bitrate, ROS adopts the existing link's value if none is supplied,
falling back to 5 Mbit/s when it cannot inspect the link. The interface must still be
configured for FD at the correct arbitration rate.

## Manual single-hand launch

Supply the actual `model`, `side` and interface:

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=o6 side:=right \
  transport_json:='{"backend":"socketcan","channel":"can0"}'
```

The `socketcan` backend chooses classic CAN or FD from the model capability.
Models are case-insensitive: `l6`, `o6`, `l20lite` (also `l20-lite`), `l20`, `o20`, `l30`, `o30`.
Use `left` or `right` except for L30, whose configured side must be empty:

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=l30 side:='' \
  transport_json:='{"backend":"socketcan","channel":"can0"}'
```

## MiniCANFD

Install the vendor driver/library with matching process architecture: `libcanbus.so` on Linux,
`HCanbus.dll` on Windows. ROS and the SDK do not distribute these libraries.
O20, L30 and O30 can use the manual `vendor_canfd` backend:

```bash
ros2 launch linkerbot_hand_ros hand.launch.py \
  model:=o30 side:=right \
  transport_json:='{"backend":"vendor_canfd","device_index":0,"channel_index":0,"library_path":"/opt/minicanfd/libcanbus.so"}'
```

Linux indices are `(device_index, channel_index)`; Windows uses DLL `devNum` for
`device_index` and `channel_index=0`. Manual configuration uses exactly those indices.
Optional JSON fields are documented in [configuration](configuration.md#transport-json).

For automatic enumeration, save the following settings and pass
`discovery_config:=/absolute/path/settings.yaml` with `discover:=true`:

```yaml
backends: [minicanfd]
minicanfd:
  library_path: /opt/minicanfd/libcanbus.so
```

Without channel overrides, Linux checks channel 0 for each adapter, then channel 1 only
if no identity candidate was found and cleanup succeeded; a non-FD channel 0 is skipped.
Finding a candidate on 0 stops fallback for that adapter. Explicit global `channels` or
`minicanfd.linux_channels` disables fallback. Windows enumerates available FD channels.
The bundled templates deliberately select a fixed channel; omit their channel filters for automatic enumeration.

## PCAN and SLCAN

Linux adapters exposed as `can0` use SocketCAN. On Windows, classic PCAN can use manual
`python_can` JSON with `interface_name="PCAN_USBBUS1"` and `interface_type="pcan"`.
PCAN FD and SLCAN FD use [discovery settings](discovery_examples.md); manual `python_can`
JSON supports classic CAN only.

PCAN requires PCANBasic and its driver. SLCAN FD requires CANable 2.0 FD firmware;
default discovery enumerates USB `16D0:117E`, with serial speed 115200. Other devices use
explicit channels. Serial speed (`tty_baudrate`) is separate from CAN bitrate.

## Next steps

Read [first angles](getting_started.md#5-connect-one-hand), use [automatic/multi-hand discovery](discovery.md),
or set up [manual multi-hand YAML](configuration.md#multi-device).
Stop and cleanup a running driver before opening the same device from another ROS process or SDK script.
