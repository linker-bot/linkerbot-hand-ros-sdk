# Model features and ROS usage

[简体中文](zh/models.md) · [Manual](../README.md)

[Connect the hand](connection.md) first. All models support identity, capabilities, angles,
speed settings, current limits, live current, temperature, faults and tactile data;
actual availability follows the connected device's capabilities and sensors.

| Model | Joints | Bus | SDK features and joint order |
| --- | ---: | --- | --- |
| [L6](#l6) | 6 | CAN | [L6 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/en/src/reference/tutorials/l6.md) |
| [O6](#o6) | 6 | CAN | [O6 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/en/src/reference/tutorials/o6.md) |
| [L20Lite](#l20lite) | 10 | CAN | [L20Lite SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/en/src/reference/tutorials/l20lite.md) |
| [L20](#l20) | 16 | CAN | [L20 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/en/src/reference/tutorials/l20.md) |
| [O20](#o20) | 16 | CAN FD | [O20 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/en/src/reference/tutorials/o20.md) |
| [L30](#l30) | 17 | CAN FD | [L30 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/en/src/reference/tutorials/l30.md) |
| [O30](#o30) | 20 | CAN FD | [O30 SDK](https://gitea.linkerhub.work/linker-bot/linkerbot-hand-python/src/branch/main/docs/en/src/reference/tutorials/o30.md) |

## Common usage

- `~/capabilities`: read joint order/count, raw ranges, percent directions, commands and read modes.
- `~/state/angles`: subscribe to angles; publish raw/percent targets via `~/command/angles` or `HandCommandClient`.
- `~/command/speeds`: configure speed; `measured_speeds` is live speed, `configured_speeds` is a setting.
- Enable live telemetry with `current_hz`, `temperature_hz`, `faults_hz`; see [tactile fields](force.md).

Raw values are protocol counts. Flexion percent is 0=flexed, 100=extended; directional joints use
`percent_mapping`. ROS does not expose every SDK getter as a service: live data uses polling/topics,
while on-demand configuration reads use services. See [examples](examples.md) and [ROS API](ros_api.md).

## L6

Six-joint angle and speed control. `get_configured_speeds` returns a valid device speed-write reply;
perform a successful write first. `torques` is raw output/mode: 0 selects position mode,
1..255 selects torque mode/output level, not measured N·m. Returning to position mode sends
no angle target. Confirm the returned mode before sending angles; `torques_hz` polls it.

Also supports current-limit queries, stall settings/reads, fault clearing, `save_parameters`,
control gains and limit compensation:

| Name | Raw | Meaning |
| --- | --- | --- |
| `position_kp` | 0..200 | Kp = raw × 10; default 50 |
| `position_kd` | 0..255 | Default 21; recommended ≤40 |
| `torque_kd` | 0..255 | Default 1; physical scale unknown |
| `limit_compensations` | 0..255 | Protocol count; physical scale/direction unknown |

All four provide `command/<name>`, `set_<name>`, `get_<name>` and `state/<name>`.
Writes share a bounded FIFO without implicit mode switching or nonvolatile saving.
Limit compensation requires an exact six-byte echo for acknowledgement. Use capability
ranges/conflict notes; recommendations are not certified safety limits. There are no gain/compensation polling parameters.

## O6

Six-joint angles, speeds and accelerations. Configured speed is queryable; acceleration raw range
is 0..254, where 0 means the device-defined maximum. Current-limit reads use complete device-write
reply caches, separate from live current. Recovery requires a new valid write reply before reading limits.
Supports stall reads/settings and `save_parameters`, but no fault-clear command. fn is five 10×4 matrices.

## L20Lite

Ten-joint angles, speeds, accelerations and current limits. Speed/acceleration/current-limit settings
read back device-write reply caches; live speed/current remain independent. Stall settings expose
writes and confirmed write-response state, with no `get_stall_protection`. No fault clear or nonvolatile save.

fn is five 12×6 matrices; fns, fts, fds and px are separately queried five-finger scalar fields.
fns is supplied by the device rather than summed from cells; fds retains direction codes and validity,
without angle conversion.

## L20

Sixteen-joint angles, speed/current-limit settings, live speed/current, temperature, faults, fn matrices
and fault clearing. No configured-speed or current-limit readback service; live current is not a limit readback.

## O20

Sixteen-joint CAN FD hand with angles, speed/current-limit settings, live speed/current, temperature,
faults, fn matrices and fault clearing. Configured speed and current limits are queryable. No acceleration setting.

## L30

Seventeen-joint CAN FD hand; configure an empty `side`. Supports angles, speed/current-limit settings
and live speed/current. Configured-speed/current-limit getters use locally dispatched command caches;
these are not device acknowledgements and are invalidated on recovery.

`enable`, `disable` and `calibrate` use `SubmitCommand` services. Observe command status for protocol
completion. Calibration is explicit; startup and recovery never run it automatically.

## O30

Twenty-joint CAN FD hand. Supports angles, speeds, accelerations, current limits, torque limits and
motion times, with queryable settings. Live current, measured torque and voltage can be polled.
Stall reads and settings are supported.

`current_limits` and `torques_limits` are distinct settings. `torques_hz` polls measured torque;
it does not make `command/torques` available. Read `returns_current_state` to determine angle-write feedback support.

Tactile support follows the actual descriptor. Check `force_fields.support_known/supported` before
selecting fn/fns/ft/fts/fd/fds/px. TASHAN_GATHER exposes one fn/ft/fd/px value per fingertip;
without FnS it publishes no five-finger normal resultant. See [tactile fields](force.md).

## Three configuration read modes

`query` requests the device, `command_response` returns a device-write reply cache, and
`command_cache` returns a locally dispatched command cache. Cache reads preserve collection time and
sequence and can succeed with stale data. Always check `state.meta`.
See [ROS API](ros_api.md#on-demand-raw-reads) for current/torque limit endpoints.
