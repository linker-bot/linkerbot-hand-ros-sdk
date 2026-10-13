# linkerbot_hand_msgs

Transport-neutral ROS 2 interfaces for the latest Hand Python `main`.
This package has no runtime dependency on `rclpy`, the Hand SDK or a particular model.
Build messages, driver, GUI and downstream consumers with the same ROSIDL definitions.

## Interfaces

| Group | Main definitions | Contract |
| --- | --- | --- |
| Capabilities and identity | [HandCapabilities](msg/HandCapabilities.msg), [HandDeviceInfo](msg/HandDeviceInfo.msg) | Joint order, ranges, operations, query modes and optional identity fields |
| Commands | [HandJointCommand](msg/HandJointCommand.msg), [HandRawCommand](msg/HandRawCommand.msg) | Explicit percent/raw representation; nonzero publisher client ID |
| Command status | [HandCommandStatusBatch](msg/HandCommandStatusBatch.msg), [HandCommandStatus](msg/HandCommandStatus.msg) | Batched protocol progress and complete transition history |
| Angles and telemetry | [HandJointState](msg/HandJointState.msg), [HandTelemetry](msg/HandTelemetry.msg) | Raw, percent and optional radians remain distinct; settings are not measured feedback |
| Tactile | [HandTactileState](msg/HandTactileState.msg), [HandTactileSensorState](msg/HandTactileSensorState.msg), [HandForceField](msg/HandForceField.msg) | Complete matrix/descriptor transactions and named per-sensor fields |
| Faults | [HandJointFaultStatus](msg/HandJointFaultStatus.msg) | Exact raw byte, supported named flags, reserved bits and descriptions |
| Reads and writes | [GetRawValues](srv/GetRawValues.srv), [SetRawValues](srv/SetRawValues.srv), [SubmitCommand](srv/SubmitCommand.srv) | Read success versus asynchronous write admission |

All [messages](msg) and [services](srv) are defined in source.
Endpoint names, service availability, QoS and errors are documented in the
[ROS API](../linkerbot_hand_ros/docs/ros_api.md) / [中文 API](../linkerbot_hand_ros/docs/zh/ros_api.md).

## Data semantics

Every sample's [SampleMetadata](msg/SampleMetadata.msg) retains collection time, sequence,
age, valid/stale state, connection generation, origin and range status. Cache reads preserve
original acquisition metadata; success alone does not establish freshness. Disabling polling
does not fabricate samples or prevent write-response cache updates.

Raw values are protocol values without physical-unit conversion. Percent is the capability's
0..100 mapping; flexion uses 0=bent and 100=straight, while other axes use endpoint labels.
Only valid physical-radian fields may be treated as calibrated angles.

`returns_current_state` describes command feedback, independently of ACK support.
`ORIGIN_DEVICE_COMMAND_FEEDBACK` is actual state returned by a command, not a target echo.
Neither acceptance, dispatch nor ACK proves mechanical arrival.

Capability schema `1.5` includes tactile fields, payload projections and extended identity.
`firmware_unsupported_telemetry` disables optional queries for the current generation without
removing their protocol metadata. Use current verified capabilities instead of a model table.

Fault flags are meaningful only when listed in `supported_flags`; false unsupported flags
cannot prove normal operation. Preserve model-specific flags rather than merging their meanings.

Tactile projection, descriptor dimensions, field units, missing sensors and shared-query
metadata are explained in the [tactile guide](../linkerbot_hand_ros/docs/force.md) /
[中文触觉指南](../linkerbot_hand_ros/docs/zh/force.md). Missing fields are empty, not zero-force measurements.
