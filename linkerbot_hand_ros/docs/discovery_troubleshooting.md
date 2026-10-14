# Discovery troubleshooting

First check platform scope: Linux uses SocketCAN (classic CAN/CAN FD) and MiniCANFD; Windows uses PCAN (classic CAN/CAN FD), MiniCANFD and SLCAN (CAN FD). `backends` does not enable sources from another platform. For `backend ... is unavailable on this platform`, use a supported template. A Linux adapter exposed as a SocketCAN network interface uses SocketCAN; serial SLCAN mode is outside this entry point.

Keep the scan summary, failure lines and final lifecycle error from one attempt. Read `operation` (SDK operation), `backend`, `channel`/`native_channel`, `protocol`, role namespace and configuration path. `stage` names the container phase and `cause` retains the original exception. Missing SDK fields are not inferred; `backend=selection` denotes filtering, not an adapter. See [configuration examples](discovery_examples.md).

Illustrative log format, not hardware observations:

```text
discovery unavailable: requested discovery channel was not enumerated (operation=enumerate_selection_unavailable error_type=DiscoveryError backend=selection native_channel='can0')
activate failed: [identity_mismatch] ... (node=/left_hand/linkerbot_hand backend=socketcan channel='can0' protocol=can scheme=classic_can_id request_id=0x28 response_id=0x28 extended_id=False)
```

## Configuration and file errors

`discovery_config=...` identifies advanced settings; `deployment_config=...` identifies a deployment. `hands[0]` is a zero-based list index followed by the affected namespace. Check unknown/duplicate keys, parameter types and namespace/interface conflicts.

Settings use `discovery_config`; schema/version 1 deployments use `config`, not ROS `--params-file`. Existing ROS parameter files retain their launch-substitution behavior. An existing output is refused before scanning: reuse it with `config` or select a new output. For write failures check the parent directory and permissions; retain the original file.

## `unavailable`: an explicitly requested interface was not enumerated

Use the failure line to identify the interface. On Linux, inspect SocketCAN without modifying it:

```bash
ip -details link show can0
```

Check name, UP state, CAN/FD and bitrates. PCAN backend settings use native `PCAN_USBBUS1`, while global filters use `pcan:PCAN_USBBUS1`. Check actual serial/COM ports or MiniCANFD indices. A missing explicit interface does not fall back to another one; the host owns link configuration.

## No candidates, ambiguity or `partial`

Resolve backend failures first; they are not proof that no hand exists. With an available interface check power, wiring, termination, protocol and bitrates. Limit a single-hand request to the intended channels or use multi-hand mode. PARTIAL `problem code: message` describes incomplete identity; no side is guessed and the hand is not activated. Configure known L30 Node IDs/O30 request IDs when needed.

## Library, driver or permission failures

Enumeration codes may name a stage; inspect error type, message and cause for the actual reason. Check native-library path, process/library architecture and dependencies. Linux MiniCANFD requires the real `libcanbus.so` and USB access; Windows needs the proper `HCanbus.dll`, vendor USB driver and runtime dependencies. Windows PCAN requires its PCANBasic/driver; check SLCAN COM ports and ownership in Device Manager. Linux MiniCANFD USB checks are read-only:

```bash
id
lsusb
ls -l /dev/bus/usb
```

Resolve access through the host's device-permission mechanism rather than granting unrestricted permissions or forcing administrator execution. Relative library paths are based on the settings/deployment directory. Libraries are not shipped with ROS/SDK.

## `busy`: resources are still held

Deactivation stops commands and polling but retains the lease until cleanup. Orderly deactivate, cleanup and exit your own old nodes before scanning; MiniCANFD enumeration also requires closing this process's connections to the same vendor library. Other applications must release their own resources; do not kill unrelated processes. There is no runtime rescan API.

## MiniCANFD channel selection

Without global `channels` or `minicanfd.linux_channels`, Linux probes channel 0,
then tries channel 1 only if no identity candidate was found and probe cleanup succeeded.
If channel 0 is not FD, it is skipped and channel 1 is checked. Any identity candidate on channel 0 stops
fallback. Explicit channels disable automatic fallback. Supply a confirmed
`linux_channels` layout only to fix the scope; device count does not imply channel count.
Windows uses DLL devNum as device_index and channel_index 0, without Linux layouts.
See [connection details](manual_connection.md#minicanfd).

## `unsupported_protocol` or invalid FD timing

Check adapter FD capability, the device protocol, clock and bus timing/data rate. Classic and FD PCAN templates serve different hardware policies. USB identification does not prove SLCAN firmware FD support; use verified CANable 2.0 FD firmware. Do not bypass SDK rejection by forcing a protocol flag.

## `scan_timeout`: the cooperative budget is exhausted

Inspect earlier backend errors and the requested scope. Restrict known interfaces/Node IDs/request IDs and adjust `total_timeout_s` if appropriate. Native blocking calls and cleanup can extend elapsed time; the budget is not a hard deadline. Do not abandon a still-running task. Send/response budgets are separate from runtime transaction budgets.

## Probe close or runtime cleanup failures

Diagnostics retain the original interface/protocol and each cleanup cause. Unreleased probe resources block saving/starting. After runtime close failure, confirm the connection state and release resources according to the SDK/adapter requirements. Process exit alone does not establish that a native resource was released.

## `identity_mismatch` or a saved role that does not match

Activation/recovery refuse the changed identity. Inspect node/namespace, interface, request/response IDs, L30 Node ID and cause. Saved-role errors also show the expected `match`. Check hand/wiring/firmware changes or edited constraints, then orderly cleanup and explicitly rediscover/reconfirm the role. Do not remove identity conditions to accept the wrong device. Generate a new output path and retain the original for comparison.

Templates without serial identities constrain model/side/interface/endpoint only; they do not guarantee permanent physical identity. Prefer deployments generated from the installation. Verify bindings against the connected hardware.

[Back to overview](getting_started.md) · [简体中文](zh/discovery_troubleshooting.md)
