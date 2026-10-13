# linkerbot_hand_msgs

`linkerbot_hand_msgs` contains transport-neutral ROS 2 interfaces for the
latest Linkerbot Hand SDK `main` contract. It has no runtime dependency on
`rclpy`, the Python Hand SDK, or a specific hand model.

The value representation is always explicit:

- `HandJointCommand` selects `REPRESENTATION_PERCENT` or
  `REPRESENTATION_RAW`.
- `HandJointState` keeps protocol raw, percent, and optional physical radians
  in separate fields with validity masks.
- `HandTelemetry` identifies configured and measured channels through its
  semantic and capability metadata.
- `HandTactileState` represents one complete multi-finger tactile transaction.
- `HandFaultStatusState` carries the decoded per-joint fault bits as
  `HandJointFaultStatus` records, for models whose protocol profile documents
  them. Each record keeps the exact protocol byte in `raw` next to the named
  flags, and the raw `~/state/faults` channel is unaffected.
- `HandCommandStatusBatch` carries changed `HandCommandStatus` records in one
  bounded publication. Each record still distinguishes accepted, dispatched,
  acknowledged, failed, and superseded commands. A non-zero `client_id` combined with
  `user_sequence` identifies one publisher's command without colliding with
  another publisher, while publisher and driver-receive timestamps expose the
  ROS admission latency.

Every state sample carries `SampleMetadata`: collection time, per-channel
sequence, age, validity, staleness, connection generation, origin, and range
status. A disabled SDK polling channel therefore produces no synthetic ROS
sample.

`ORIGIN_DEVICE_COMMAND_FEEDBACK` means current state returned in response to a
command; it is neither a target echo nor an acknowledgement stage.

`HandCapabilities` is the ROS projection of the SDK capability object. ROS
clients must use it instead of maintaining a separate model specification.
Its `firmware_unsupported_telemetry` field reports optional queries disabled
for the current connection generation while retaining their protocol metadata.
`OperationCapabilities.save_parameters` explicitly gates the corresponding
management service.

`CommandCapability.returns_current_state` tells a client whether a command's
response contains current device state usable as feedback. It is independent of
`ack_support`, is not a target echo, and does not indicate mechanical arrival.
The `angles` command's flag gates the SDK's `command_feedback_only` policy.

The capability schema is `1.5`. It includes named tactile field capabilities,
command feedback support, `TelemetryCapability.payload_projection` and extended
identity metadata. Build the message package, driver, GUI and external consumers
with consistent ROSIDL definitions from the latest `main`.

`HandTactileSensor` provides `maximum_rows/maximum_columns`,
`selected_sensor`, `available`, requested rows/columns,
position mode and rectangle fill. Neither maximum nor requested dimensions imply
the size/order of a descriptor field: use `descriptor`, `fields` and `raw_bytes`.
Unavailable sensors retain their finger identity with empty fields/bytes; they are
not zero-force measurements. Five-finger resultants are published only when all
five expose a scalar `FnS`. No additional device read is performed to derive them.

For the force capability, `payload_projection` selects the publication contract:

| Projection | Topic suffix | Message |
| --- | --- | --- |
| `tactile_matrix` | `state/tactile` | `HandTactileState` |
| `tactile_descriptor` | `state/tactile_sensors` | `HandTactileSensorState` |
| `tactile_descriptor` with five scalar FnS values | `state/normal_force_resultant` | `HandNormalForceResultant` |
| `raw_vector` | `state/force` | `HandTelemetry` |

Six current models use matrices; O30 uses descriptors. No current model declares
the `raw_vector` force projection. L20Lite also exposes independent fns/fts/fds/px
scalar fields. All projections retain their own physical query's metadata.

`HandForceField` carries one named fn/fns/ft/fts/fd/fds/px field with per-sensor
raw arrays, presence, validity, unit and encoding. Its metadata and query_channel
identify the actual acquisition; missing sensors are empty, not zero-filled.
`ForceFieldCapability` distinguishes unknown descriptor support from absent
features and reports shared queries and runtime firmware degradation.
All seven fields are covered by the [force interface guide](../linkerbot_hand_ros/docs/zh/force.md).

`HandJointFaultStatus.supported_flags` lists the flags defined by the protocol;
false flags outside that list do not assert normal device state. L20Lite exposes
load overload, overcurrent, overtemperature, magnetic encoder abnormality and
over/undervoltage with explanations. It has no clear-fault command.

L6 additionally exposes `mcu_over_temperature`, `motor_over_temperature`,
`overload_2`, `overload_1`, `phase_a_over_current`, `phase_c_over_current`,
and `phase_b_over_current`. L20 exposes `motor_communication_abnormal`,
`soft_rotor_lock`, `motor_self_test_abnormal`, `motor_stall`, and
`motor_rotor_lock` alongside its existing temperature, voltage and current flags.
These are separate meanings, not aliases of generic overtemperature or stall.
The flags use the SDK names; `raw`, `reserved_bits` and `descriptions` preserve
the protocol byte, unassigned bits and explanations.

`StallProtectionCapability.hold_current/has_hold_current` describe the shared
post-stall current setting, including L20Lite C7. L20Lite exposes confirmed write
echoes only; `read_supported=false` does not remove the available setter.

中文约定：普通 `raw` 字段始终表示设备协议原值，不做物理单位换算；`percent` 仅表示
SDK capability 定义的 `0..100` 映射。屈伸轴为 `0=弯曲，100=伸直`，侧摆和旋转轴的
两端方向由对应 `PercentMapping` 明确给出。

`GetRawValues` reads the raw channel selected by its service endpoint:
`~/get_configured_speeds`, `~/get_configured_accelerations`,
`~/get_current_limits`, `~/get_torques_limits`, `~/get_motion_times`, or
`~/get_limit_compensations`. The driver creates each endpoint only if its
telemetry capability is declared. It accepts `timeout_s` and returns `success`,
a complete `HandTelemetry state`, and stable `error_code` / `message` fields.
The SDK `read_mode` determines whether the call queries the device or returns
the last valid command response/cache without I/O. Cached samples retain their
original sequence, source and collection time, and may already be stale;
`success=true` alone does not imply a fresh device measurement. Raw values,
units, confidence and sample metadata remain separate.
