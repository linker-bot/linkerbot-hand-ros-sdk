# ROS 2 API Reference

The driver exposes the Hand SDK 1.x contract through typed interfaces. Topic
arrays always follow channel names published in `~/capabilities`; there is no
ROS model table.

## Lifecycle

| Transition | Device behavior |
| --- | --- |
| configure | Construct one `HandDevice`; zero transport open and zero device I/O |
| activate | Open, verify identity/firmware, start SDK polling, enable commands |
| deactivate | Remove command subscriptions and stop SDK polling; keep connection |
| cleanup/shutdown | Bounded `close()` and ROS entity destruction |

## Parameters

Static parameters are accepted only while unconfigured:

`model`, `side`, `transport_json`, `command_rate_hz`,
`discrete_queue_capacity`, `mailbox_capacity`, `route_queue_capacity`,
`identity_timeout_s`, `transaction_timeout_s`, `shutdown_timeout_s`,
`auto_reconnect`, `reconnect_initial_delay_s`, and
`reconnect_max_delay_s`.

Runtime parameters are `publish_rate_hz`, `diagnostic_rate_hz`, `angles_hz`,
`speeds_hz`, `force_hz`, `temperature_hz`, `current_hz`, `faults_hz`,
`torques_hz`, `voltage_hz`, and `angle_feedback`. The feedback policy accepts
`query_only`, `command_feedback_only`, or `adaptive`. Zero disables that SDK
polling channel; `publish_rate_hz=0` only pauses ROS state publication. Runtime capability
fallback is still checked from SDK memory and republished at 10 Hz without
performing device I/O. The production process uses a `MultiThreadedExecutor`;
SDK cache revisions wake the state publisher immediately. `publish_rate_hz`
controls idle cache checks for age/stale transitions, and zero pauses ROS state
publication. An unchanged sequence is never republished.

With `query_only`, verified angle-command feedback remains available in the SDK
snapshot and metrics but is not published on `~/state/angles`; that topic then
contains active-query responses only. The other feedback policies publish
verified command feedback normally.

Runtime rate changes apply only after all ROS parameter validators accept and
ROS commits the values. Later validation rejection has no SDK/timer side
effects. If application fails, the driver compensates by restoring parameters
and runtime configuration and returns `successful=false`. Parameter events may
show both the proposal and restoration; use the final service response to judge
application. A failed restoration disables control and closes the runtime;
perform cleanup, configure and activate before resuming. If the lifecycle error
path already completed cleanup, configure and activate are sufficient. Nested
parameter updates from callbacks are rejected. Direct application calls to
parameter/lifecycle methods must be serialized like the standard ROS services.

The default transport is:

```json
{"backend":"socketcan","channel":"can0"}
```

## Multi-Device Process

`multi_hand.launch.py` loads multiple `/namespace/linkerbot_hand` Lifecycle
nodes into one Python process from a ROS parameter file. The process-level
parameters are `device_namespaces` and `autostart`. With
autostart enabled, all nodes configure before any node activates; a failure
rolls the group back in reverse order. Identical physical transport keys share
one process-local runtime. Separate driver processes cannot share that arbiter.

## Command Topics

| Topic | Type | Meaning |
| --- | --- | --- |
| `~/command/angles` | `linkerbot_hand_msgs/msg/HandJointCommand` | Percent or protocol-raw angle target |
| `~/command/speeds` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw configured speed |
| `~/command/accelerations` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw configured acceleration |
| `~/command/current_limits` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw current limit |
| `~/command/effort_limits` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw dimensionless effort limit |
| `~/command/torques` | `linkerbot_hand_msgs/msg/HandRawCommand` | True torque only when capability supports it |
| `~/command/motion_times` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw motion-time setting |
| `~/command/limit_compensations` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw per-joint limit compensation; currently L6 |
| `~/command/status` | `linkerbot_hand_msgs/msg/HandCommandStatusBatch` | Bounded batch of changed SDK command histories |

Continuous command topics use best-effort, depth-one QoS. Unsupported command
topics are not subscribed while active. `ACCEPTED` means admitted to the SDK;
`DISPATCHED` means transport send succeeded; `ACKNOWLEDGED` requires an explicit
device-protocol ACK. None of these means mechanical arrival.

Each command carries a non-zero `client_id`, a client-local `user_sequence`,
and `publisher_stamp`. Every `HandCommandStatusBatch.statuses[]` entry echoes
that composite key and adds `driver_received_stamp` plus the complete SDK
transition history. Clients must iterate every entry and match both ID fields;
a final `ACKNOWLEDGED` status does not replace the explicit `DISPATCHED`
transition when measuring actual sends.

## State Topics

| Topic | Type | Meaning |
| --- | --- | --- |
| `~/capabilities` | `HandCapabilities` | Declared, then verified capability metadata |
| `~/device_info` | `HandDeviceInfo` | Cached verified identity and version fields |
| `~/state/angles` | `HandJointState` | Raw, percent, and optional radians from one sample |
| `~/state/<semantic>` | `HandTelemetry` | Protocol-raw typed telemetry/configuration sample |
| `~/state/force` | `HandTelemetry` | Scalar force when the profile provides it |
| `~/state/tactile` | `HandTactileState` | One complete multi-finger tactile transaction |
| `~/state/stall_protection` | `HandStallProtectionState` | Three independent raw stall settings |
| `/diagnostics` | `diagnostic_msgs/msg/DiagnosticArray` | Zero-I/O SDK health and transport metrics |

`<semantic>` can be `measured_speeds`, `configured_speeds`,
`configured_accelerations`, `currents`, `current_limits`, `effort_limits`,
`torques`, `temperatures`, `faults`, `voltages`, `motion_times`, or
`limit_compensations`, depending on
verified capability. A state message is published only when its SDK sequence or
validity signature changes.

When an optional query is rejected by the connected firmware, the SDK retains
the declared protocol metadata and adds its semantic to
`HandCapabilities.firmware_unsupported_telemetry`. The driver republishes that
runtime change with transient-local durability; consumers should treat the
latest capability message as authoritative for the current connection
generation.

Every state carries collection time, sequence, age, validity, staleness,
connection generation, origin, and range status. Protocol raw values are not
converted to RPM, mA, N.m, or other physical units by ROS.
`ORIGIN_DEVICE_COMMAND_FEEDBACK` identifies verified current state returned by
a command; it is neither a target echo nor a command acknowledgement.

## Services

| Service | Type | Result semantics |
| --- | --- | --- |
| `~/get_device_info` | `GetDeviceInfo` | Admin worker performs one fresh identity transaction |
| `~/get_stall_protection` | `GetStallProtection` | Freshly reads all three supported stall settings |
| `~/set_stall_detection_times` | `SetRawValues` | Asynchronous raw configuration acceptance |
| `~/set_stall_thresholds` | `SetRawValues` | Asynchronous raw configuration acceptance |
| `~/set_stall_hold_currents` | `SetRawValues` | Asynchronous raw configuration acceptance |
| `~/get_limit_compensations` | `GetRawValues` | Fresh raw limit configuration with units and sample metadata |
| `~/set_limit_compensations` | `SetRawValues` | Asynchronous FIFO admission; reports queue-full rejection |
| `~/save_parameters` | `SubmitCommand` | Capability-gated non-volatile save; observe command status for protocol ACK |
| `~/clear_faults` | `SubmitCommand` | Asynchronous discrete command acceptance |
| `~/enable`, `~/disable`, `~/calibrate` | `SubmitCommand` | Capability-gated asynchronous acceptance |
| `~/recover` | `Recover` | Bounded identity-verified safe recovery |

Active reads run in one separate bounded admin worker. Control callbacks and
state publishers never wait for these transactions. Services return stable
`error_code` fields; clients must not parse error text.

Diagnostics expose each channel's requested and achieved rate, completed read
transactions, command-feedback samples, policy-counted feedback samples,
feedback policy, deadlines, timeouts, and cached data age. These counters let
benchmarks distinguish active angle queries from verified command feedback.

See the [Chinese API reference](zh/ros_api.md) for examples and QoS details.

## L6 Limit Compensation

These endpoints are created from command/telemetry capabilities; currently only
L6 declares them. Protocol `0x38` carries six integers in `0..255`, ordered as
`thumb_flex`, `thumb_abd`, `index`, `middle`, `ring`, `pinky`. The unit is `count`;
the physical scale and direction are undocumented. ROS performs no conversion.

`HandCommandClient.set_limit_compensations(values)` publishes the raw command
topic after checking the verified capability and active driver. The returned
`CommandPublication` means published, not accepted. As with other command
topics, transport QoS is best-effort, keep-last(1); it does not guarantee every
publication reaches SDK admission. Rejection before admission is reported in
diagnostics and has no command handle/status. For low-frequency configuration
that needs an explicit admission result, prefer the reliable
`~/set_limit_compensations` service.

Once accepted, `CommandFamily.LIMIT_COMPENSATION` uses the SDK's shared bounded
configuration/operation FIFO (`discrete_queue_capacity`), not latest-wins.
Accepted pending configurations retain their order instead of being superseded
by a newer value. A full queue returns `accepted=false`, `error_code=queue_full`
from the setter service. `accepted=true` only means queued; observe
`~/command/status` until `ACKNOWLEDGED` or `FAILED`. L6 requires an exact six-byte
echo to acknowledge this write. No implicit `save_parameters` is performed.
Service commands use `client_id=0`; correlate their statuses by the returned
`command_id`. Topic/client commands retain `(client_id, user_sequence)`.

`~/get_limit_compensations` uses `GetRawValues(timeout_s)` on the bounded admin
worker. On success, `state` is `HandTelemetry` including raw values, joint names,
`raw_unit`, `raw_scale_note`, `unit_confidence` and `meta`. Failures retain SDK
error codes, including timeout, protocol errors and `unsupported_firmware` after
optional-read degradation. These read failures do not introduce a firmware
version gate. Inactive services return `device_not_ready`.

`~/state/limit_compensations` publishes changed cached configuration samples and
validity, including successful queries and verified write responses; subscribing
does not trigger device I/O or enable a new polling rate. Check `meta.valid`,
`meta.stale`, `meta.origin` and connection generation before using the sample.
The configuration is not a physical measurement (`device_measured=false`).

The new `GetRawValues` service requires rebuilding `linkerbot_hand_msgs` and its
dependent driver. Existing message and service field definitions are unchanged.
