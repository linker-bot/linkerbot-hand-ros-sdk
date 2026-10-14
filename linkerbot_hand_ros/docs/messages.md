# Message fields

`linkerbot_hand_msgs` defines ROS messages and services independently of hand models. Build the message package, driver, GUI and application nodes with the same interface version.

## Inspect complete definitions

```bash
ros2 interface show linkerbot_hand_msgs/msg/HandCapabilities
ros2 interface show linkerbot_hand_msgs/msg/HandJointState
ros2 interface show linkerbot_hand_msgs/msg/HandCommandStatusBatch
ros2 interface show linkerbot_hand_msgs/srv/GetRawValues
```

Endpoint names and QoS are in [ROS 2 API](ros_api.md).

## Capabilities and identity

`HandCapabilities.identity` describes model, side and identity verification. `joints` defines array order, raw ranges and percent mappings. `commands`, `telemetry` and `operations` determine available interfaces; `force_fields` describes current tactile fields.

Capabilities published during configure are declared metadata. After activate, wait for `identity.verified=true`. Optional-query firmware degradation republishes capabilities; keep the latest copy. Check `has_*` or `VersionField.available` for optional identity values. `reported_side` is the side reported by the device.

## Sample metadata

Angles, telemetry and tactile samples carry `SampleMetadata`:

| Field | Meaning |
| --- | --- |
| `collected_at` | Acquisition time projected into the ROS clock |
| `sequence` | SDK sample sequence; repeated publication can describe validity changes |
| `age_s`, `stale` | Sample age and staleness |
| `valid`, `within_declared_range` | Sample validity and declared-range check |
| `connection_generation` | Connection generation; rebuild the baseline after recovery |
| `origin` | Device query, report, configuration reply, command feedback or local command cache |

Cache reads retain original acquisition time and sequence. Service success and message reception time alone do not establish freshness.

## Angles and telemetry

`HandJointState.joint_names`, `raw`, `percent` and `physical_rad` align. Check `percent_valid` and `physical_rad_valid` separately; placeholder zeros are not valid angles.

`HandTelemetry` retains `semantic`, `channel_names`, `raw`, `raw_unit`, `raw_scale_note`, `unit_confidence`, `device_measured` and `device_queried`. `device_queried` describes channel capability; `meta.origin` identifies the sample source. Configuration values are not measured feedback.

## Commands and status

`HandJointCommand` uses `representation=1` (percent) or `2` (raw). Other per-axis commands use `HandRawCommand.raw`. Correlate topic commands by nonzero `client_id` and `user_sequence`.

Each `HandCommandStatusBatch.statuses[]` entry retains its command key, driver reception time and complete `transitions[]` history. Iterate the whole batch and match both IDs; `ACKNOWLEDGED` does not prove mechanical arrival. Service writes use their returned `command_id`; see [application integration](business_integration.md).

## Faults and tactile data

`HandJointFaultStatus` retains the raw byte, `supported_flags`, reserved bits and explanations. Only supported flags have defined meaning; false unsupported flags do not prove normal operation. L6 MCU/motor temperatures, overloads and phase-current flags remain separate. L20 communication, self-test, soft lock, stall and rotor lock remain separate.

Tactile data uses `HandTactileState` (matrices), `HandTactileSensorState` (descriptors) and `HandForceField` (named fields). Missing sensors retain identity and empty arrays. Do not insert zeros or sum cells to manufacture FnS. See [tactile data](force.md) for complete layouts.

[Back to overview](getting_started.md) · [简体中文](zh/messages.md)
