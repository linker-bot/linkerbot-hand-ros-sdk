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

`identity_timeout_s` defaults to `0.2` seconds per identity response stage,
including L30/O30 follow-up stages. `transaction_timeout_s` defaults to `0.0`,
which maps to SDK `None` and preserves each protocol's response window. Positive
values override each ordinary response stage for baseline reads, getters,
polling and commands requiring a reply. Use a Hand SDK with optional transaction
timeout support. These windows start after the stage's request batch is sent;
complete replies finish the wait immediately. Protocol pacing, dispatch-only
commands and retry behavior are unchanged. Service `timeout_s` remains a
separate caller wait budget, not a response-window override or recovery cancel.

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

To determine whether angle writes can provide feedback, find the `angles` entry
in `~/capabilities.commands` and read `returns_current_state`. A true value means
the response contains current state usable as feedback; it does not mean target
echo, protocol ACK or mechanical arrival. The SDK rejects `command_feedback_only`
with a nonzero angle rate if this flag is false. Use the connected SDK's declaration;
the O30 command-feedback fix in Hand issue #148 also changes this value.

Capability schema `1.5` includes this field, `force_fields`, `payload_projection`, and extended
identity metadata, changing the ROSIDL types. Rebuild messages, driver, GUI and all
external capability consumers together. Old and new message builds must not be
mixed; checking the revision string does not provide wire compatibility.

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
| `~/command/torques_limits` | `linkerbot_hand_msgs/msg/HandRawCommand` | O30 0x06 raw torque limits, separate from 0x04 current limits |
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
| `~/state/tactile_sensors` | `HandTactileSensorState` | Complete descriptor tactile sample, including absent sensor identities |
| `~/state/normal_force_resultant` | `HandNormalForceResultant` | Five scalar FnS values derived from the same descriptor sample, when available |
| `~/state/stall_protection` | `HandStallProtectionState` | Three independent raw stall settings |
| `/diagnostics` | `diagnostic_msgs/msg/DiagnosticArray` | Zero-I/O SDK health and transport metrics |

Read the force capability's `payload_projection`: `tactile_matrix` selects
`state/tactile`, `tactile_descriptor` selects `state/tactile_sensors` and the
optional resultant projection, and `raw_vector` selects `state/force`. Six current
models use matrices; O30 uses descriptors; none uses the legacy scalar projection.
`HandCommandClient.telemetry_capability("force")` returns copied metadata or None
when absent/disabled; it does not query the device or prove driver readiness.

Named raw tactile quantities publish as `HandForceField` on
`~/state/force_fn`, `force_fns`, `force_ft`, `force_fts`, `force_fd`, `force_fds`
and `force_px`. Each sensor retains presence, raw arrays, validity, units and
encoding; each field retains its own acquisition metadata and query channel.
L20Lite adds scalar fns/fts/fds/px besides matrices. O30 support remains unknown
until descriptor discovery; `capabilities.force_fields` and
`HandCommandClient.force_field_capability(name)` expose that distinction.

Set `force_<field>_hz` for individual rates. `force_hz` remains shorthand for
available fn + fns, and cannot combine with positive fn/fns-specific rates.
O30 fn and fns share one physical query at the maximum requested rate; both
are returned. Independent models query separately. ROS adds no CAN queries and
never sums matrix values to manufacture resultants. See the
[complete force guide](zh/force.md). Install the SDK source with unified force
support until the next package release, and rebuild all ROS message consumers.
Sensor `maximum_rows/maximum_columns` replace the old `rows/columns` fields.
They and `requested_rows/requested_columns` preserve device metadata without
reshaping fields. Actual byte ranges and element counts come from the descriptor.
Selector, availability, position mode and rectangle-fill flag are preserved.
An absent sensor has empty fields/bytes, not fabricated zero measurements. FnS is
not recomputed by summing matrix cells and is not converted to newtons.

Device info and identity capabilities include adapter/control/bootloader versions,
protocol name/version, supply range, MCU UID, build time, supported interfaces and
reported side. Optional values carry presence flags (or VersionField.available);
reported side is distinct from the configured/resolved side.

`<semantic>` can be `measured_speeds`, `configured_speeds`,
`configured_accelerations`, `currents`, `current_limits`, `torques_limits`,
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
| `~/get_configured_speeds` | `GetRawValues` | Configured speeds; device query, write response or command cache according to capability |
| `~/get_configured_accelerations` | `GetRawValues` | Configured accelerations |
| `~/get_current_limits` | `GetRawValues` | Current limits; device query or command cache according to capability; absent on L20/L20Lite |
| `~/get_torques_limits` | `GetRawValues` | O30 0x06 torque limit configuration, not measured torque |
| `~/get_motion_times` | `GetRawValues` | Motion-time configuration |
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

## On-Demand Raw Reads

Stall output uses `hold_current` for every supported model, including L20Lite C7.
The old `hold_torque/has_hold_torque` fields are removed in schema 1.5; rebuild
messages, driver, GUI and external consumers together. L20Lite exposes all three
stall setter services using the shared FIFO. Its state contains confirmed write
echoes with original metadata, and no `get_stall_protection` read service exists.

The six `GetRawValues` endpoints above are registered during configure when the
corresponding telemetry capability exists. Call them while active. They reuse
the SDK getters; subscribing to `~/state/<semantic>` only observes the cache
and does not query the device. A successful query updates that cache, and normal
state publication emits the changed sample when publication is enabled. Service
reads do not enable polling or send configuration writes.

Read `~/capabilities.telemetry` to select the supported endpoint and its
`read_mode`; command support alone does not imply a readable channel:

| `read_mode` | Getter behavior | Current examples |
| --- | --- | --- |
| `query` | Request a post-call fresh device sample | O6 configured speeds/accelerations/current limits; O30 motion times |
| `command_response` | Return the last valid device write response, without a new query | L6 configured speeds |
| `command_cache` | Return the last valid locally dispatched command sample, without device confirmation or a new query | L30 configured speeds/current limits |

L20/L20Lite publish live current on `~/state/currents`, polled with `current_hz`,
and retain `device_measured=true`. They have no current-limit readback service.
O30 publishes measured current and torque on `~/state/currents` and
`~/state/torques`, using `current_hz` and `torques_hz` respectively. Its two limit
objects use `~/get_current_limits` and `~/get_torques_limits`, updating the
corresponding limit state topics. All values and scale metadata come from the SDK.

The old `effort_limits` names are removed:

| Model | Former effort command/client method | Former effort state/read service |
| --- | --- | --- |
| L20 / L20Lite | `current_limits` / `set_current_limits()` | `currents` with `current_hz`; no limit readback |
| O20 | `current_limits` / `set_current_limits()` | `current_limits` / `get_current_limits` |
| O30 | `torques_limits` / `set_torques_limits()` | `torques_limits` / `get_torques_limits` |

O30's existing 0x04 current interfaces remain independent of 0x06 torque.
No current model declares a `set_torques()` command; setting a torque limit does
not enable a live torque-target control API.

`state` retains raw values, channel names, units, scale notes, confidence and
`meta`. For cache/response modes, collection time and sequence remain those of
the original sample; age and staleness describe it at read time. A successful
cached read may have `meta.stale=true`. `device_queried` describes the channel's
capability, not the origin of every published sample; use `meta.origin` for the
particular sample. In command-response/cache modes the success message states
that no device query was performed; branch on structured metadata, not that text.

Check `success` before consuming `state`. An unavailable command-derived sample
returns `unsupported_operation`; the service never sends a write to manufacture
a sample. Runtime firmware rejection keeps the declared endpoint but returns
`unsupported_firmware` once the SDK disables that optional query. An inactive
or closing driver returns `device_not_ready`; invalid timeouts return
`validation`; SDK timeout/protocol errors retain their stable codes. `timeout_s`
must be finite and positive, with the management-worker margin fitting inside
`shutdown_timeout_s`. No firmware-version gate is added. Queries still share SDK
device/bus scheduling with commands, so use them on demand within the bus budget.

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

The `GetRawValues` service requires rebuilding `linkerbot_hand_msgs` and its
dependent driver. Adding its endpoints does not change service fields; the
separate command-capability wire change described above requires rebuilding all
capability consumers as well.
