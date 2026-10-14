# Manual connection

[Prepare the interface](connection.md) and [load the ROS environment](quick_start.md#4-load-each-terminal) in every terminal. Use a separate physical channel for each hand.

## SocketCAN

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


After connecting, follow [quick start](quick_start.md#5-connect-one-hand) to check active state, identity and angles. Continue with [model features](getting_started.md#device-features). Manual multi-hand setup is in [configuration](configuration.md#multi-device).

[Back to overview](getting_started.md) · [简体中文](zh/manual_connection.md)
