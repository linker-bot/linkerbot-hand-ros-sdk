# linkerbot_hand_msgs

`linkerbot_hand_msgs` contains transport-neutral ROS 2 interfaces for the
Linkerbot Hand SDK 1.0 contract. It has no runtime dependency on `rclpy`, the Python
Hand SDK, or a specific hand model.

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

The unreleased capability schema is `1.2`. Adding this field changes the ROSIDL
types of `CommandCapability` and its enclosing `HandCapabilities`. Rebuild the
message package, driver, GUI and external capability consumers together; a schema
revision string cannot make old and new wire types compatible. Under this
repository's release policy, this requires a major release; package versions
remain at the last release until release preparation.

中文约定：普通 `raw` 字段始终表示设备协议原值，不做物理单位换算；`percent` 仅表示
SDK capability 定义的 `0..100` 映射。屈伸轴为 `0=弯曲，100=伸直`，侧摆和旋转轴的
两端方向由对应 `PercentMapping` 明确给出。

See [CHANGELOG.rst](CHANGELOG.rst) for interface changes. Every pull request
that changes a public message or service must update its `Unreleased` section.

`GetRawValues` reads the raw channel selected by its service endpoint:
`~/get_configured_speeds`, `~/get_configured_accelerations`,
`~/get_current_limits`, `~/get_effort_limits`, `~/get_motion_times`, or
`~/get_limit_compensations`. The driver creates each endpoint only if its
telemetry capability is declared. It accepts `timeout_s` and returns `success`,
a complete `HandTelemetry state`, and stable `error_code` / `message` fields.
The SDK `read_mode` determines whether the call queries the device or returns
the last valid command response/cache without I/O. Cached samples retain their
original sequence, source and collection time, and may already be stale;
`success=true` alone does not imply a fresh device measurement. Raw values,
units, confidence and sample metadata remain separate. These endpoints reuse
the same service fields; the command-capability wire change described above
still requires rebuilding all consumers.
