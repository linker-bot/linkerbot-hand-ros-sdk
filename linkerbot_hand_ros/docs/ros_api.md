# ROS 2 API Reference

The driver exposes the latest Hand SDK `main` contract through typed interfaces. Topic
arrays always follow channel names published in `~/capabilities`; there is no
ROS model table.

[简体中文](zh/ros_api.md) · [Manual](../README.md)

## Lifecycle

| Transition | Device behavior |
| --- | --- |
| configure | Construct one `HandDevice`; zero transport open and zero device I/O |
| activate | Open, verify identity/firmware, start SDK polling, enable commands |
| deactivate | Remove command subscriptions and stop SDK polling; keep connection |
| cleanup/shutdown | Bounded `close()` and ROS entity destruction |

## Parameters

Defaults, live update behavior, timeouts and recovery are specified in
[Lifecycle and parameters](configuration.md). Tactile polling uses `force_hz` or
`force_<field>_hz`; [tactile fields](force.md) explains shared queries.

## Multi-Device Process

Use [discovery](discovery.md) or [manual multi-hand YAML](configuration.md#multi-device).
Each hand has its own namespace and physical channel. Group startup configures every node
before activation; failures trigger reverse-order cleanup. ROS namespaces do not isolate device traffic.

## Command Topics

| Topic | Type | Meaning |
| --- | --- | --- |
| `~/command/angles` | `linkerbot_hand_msgs/msg/HandJointCommand` | Percent or protocol-raw angle target |
| `~/command/speeds` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw configured speed |
| `~/command/accelerations` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw configured acceleration |
| `~/command/current_limits` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw current limit |
| `~/command/torques_limits` | `linkerbot_hand_msgs/msg/HandRawCommand` | O30 0x06 raw torque limits, separate from 0x04 current limits |
| `~/command/torques` | `linkerbot_hand_msgs/msg/HandRawCommand` | Capability-declared raw torque output/mode; currently L6, not calibrated N·m |
| `~/command/motion_times` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw motion-time setting |
| `~/command/limit_compensations` | `linkerbot_hand_msgs/msg/HandRawCommand` | Protocol-raw per-joint limit compensation; currently L6 |
| `~/command/position_kp`, `~/command/position_kd`, `~/command/torque_kd` | `linkerbot_hand_msgs/msg/HandRawCommand` | L6 raw per-joint control gains |
| `~/command/status` | `linkerbot_hand_msgs/msg/HandCommandStatusBatch` | Bounded batch of changed SDK command histories |

Continuous command topics use best-effort, depth-one QoS. The active driver subscribes only to supported commands. `ACCEPTED` means admitted to the SDK;
`DISPATCHED` means transport send succeeded; `ACKNOWLEDGED` requires an explicit
device-protocol ACK. None of these means mechanical arrival.

Each command carries a non-zero `client_id`, a client-local `user_sequence`,
and `publisher_stamp`. Every `HandCommandStatusBatch.statuses[]` entry echoes
that composite key and adds `driver_received_stamp` plus the complete SDK
transition history. Clients must iterate every entry and match both ID fields;
a final `ACKNOWLEDGED` status does not replace the explicit `DISPATCHED`
transition when measuring actual sends.

### L6 torque output/mode

`HandCommandClient.set_torques(values)` publishes six integer raw values in
capability joint order on `~/command/torques`. L6 opcode `0x03` accepts `0..255`:
zero selects position mode for that joint; `1..255` selects torque mode and its
output. These are protocol counts, not calibrated N·m or current limits.

Once admitted, these commands share the SDK's bounded configuration/operation
FIFO: a zero returning a joint to position mode must not be replaced by a later
torque target. The ROS topic still uses best-effort depth-one QoS, so the FIFO
does not guarantee admission of every DDS publication. Observe command status
for accepted commands. The SDK guards mode changes with a 20 ms pre-dispatch
delay and a post-dispatch delay of 150 ms if any value is zero, otherwise 20 ms;
ROS does not implement a second timing loop.

A valid write reply can contain the previous output/mode values. ACK confirms
the exchange, not equality with the target. `~/state/torques` retains the actual
reply, and `torques_hz` controls fresh SDK polling. The SDK's `get_torques()` can
also query a fresh sample; no ROS `~/get_torques` service is exposed. L6 samples
retain `raw_unit="count"`, `device_measured=false`, `device_queried=true` and
`ORIGIN_DEVICE_CONFIG_RESPONSE`: `device_queried` describes the channel's query
capability, while `meta.origin` describes this sample. The output/mode readback
is not measured physical torque. Current limits (`0x02`) and live current
(`0x36`) remain separate channels.

## State Topics

| Topic | Type | Meaning |
| --- | --- | --- |
| `~/capabilities` | `HandCapabilities` | Declared, then verified capability metadata |
| `~/device_info` | `HandDeviceInfo` | Cached verified identity and version fields |
| `~/state/angles` | `HandJointState` | Raw, percent, and optional radians from one sample |
| `~/state/<semantic>` | `HandTelemetry` | Protocol-raw typed telemetry/configuration sample |
| `~/state/force` | `HandTelemetry` | Raw-vector projection when declared; no current model uses it |
| `~/state/tactile` | `HandTactileState` | One complete multi-finger tactile transaction |
| `~/state/tactile_sensors` | `HandTactileSensorState` | Complete descriptor tactile sample, including absent sensor identities |
| `~/state/normal_force_resultant` | `HandNormalForceResultant` | Five scalar FnS values derived from the same descriptor sample, when available |
| `~/state/stall_protection` | `HandStallProtectionState` | Three independent raw stall settings |
| `/diagnostics` | `diagnostic_msgs/msg/DiagnosticArray` | Zero-I/O SDK health and transport metrics |

Tactile fields use `HandForceField` on `~/state/force_fn`, `force_fns`, `force_ft`,
`force_fts`, `force_fd`, `force_fds` and `force_px`. Projection selection, descriptor
metadata and sampling rates are documented in [tactile fields](force.md).

<a id="o30-tashan_gather-scalar-fields"></a>
O30 TASHAN_GATHER exposes fn/ft/fd/px per-finger scalars; see the
[layout and validity rules](force.md#o30-tashan_gather).

Device info and identity capabilities include adapter/control/bootloader versions,
protocol name/version, supply range, MCU UID, build time, supported interfaces and
reported side. Optional values carry presence flags (or VersionField.available);
reported side is distinct from the configured/resolved side.

`<semantic>` can be `measured_speeds`, `configured_speeds`,
`configured_accelerations`, `currents`, `current_limits`, `torques_limits`,
`torques`, `temperatures`, `faults`, `voltages`, `motion_times`,
`limit_compensations`, `position_kp`, `position_kd`, or `torque_kd`, depending on
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

The decoded `~/state/fault_statuses` topic preserves the SDK's model-specific
flags, raw byte, reserved bits and explanations. Only names in `supported_flags`
have a defined meaning; other false values do not mean the device is healthy.
L6 keeps MCU/motor temperatures, both overload flags and A/C/B phase currents
separate. L20 keeps motor communication, self-test, soft lock, stall and rotor
lock separate. See the [message field reference](../../linkerbot_hand_msgs/README.md).
Build messages and all consumers from consistent `main` interface definitions.

## Services

| Service | Type | Result semantics |
| --- | --- | --- |
| `~/get_device_info` | `GetDeviceInfo` | Admin worker performs one fresh identity transaction |
| `~/get_stall_protection` | `GetStallProtection` | Freshly reads all three supported stall settings |
| `~/get_configured_speeds` | `GetRawValues` | Configured speeds; device query, write response or command cache according to capability |
| `~/get_configured_accelerations` | `GetRawValues` | Configured accelerations |
| `~/get_current_limits` | `GetRawValues` | Current limits; device query, write-response cache or command cache according to capability; absent on L20 |
| `~/get_torques_limits` | `GetRawValues` | O30 0x06 torque limit configuration, not measured torque |
| `~/get_motion_times` | `GetRawValues` | Motion-time configuration |
| `~/set_stall_detection_times` | `SetRawValues` | Asynchronous raw configuration acceptance |
| `~/set_stall_thresholds` | `SetRawValues` | Asynchronous raw configuration acceptance |
| `~/set_stall_hold_currents` | `SetRawValues` | Asynchronous raw configuration acceptance |
| `~/get_limit_compensations` | `GetRawValues` | Fresh raw limit configuration with units and sample metadata |
| `~/set_limit_compensations` | `SetRawValues` | Asynchronous FIFO admission; reports queue-full rejection |
| `~/get_position_kp`, `~/get_position_kd`, `~/get_torque_kd` | `GetRawValues` | Fresh L6 raw gain values, units and sample metadata |
| `~/set_position_kp`, `~/set_position_kd`, `~/set_torque_kd` | `SetRawValues` | L6 gain FIFO admission; protocol completion is reported asynchronously |
| `~/save_parameters` | `SubmitCommand` | Capability-gated non-volatile save; observe command status for protocol ACK |
| `~/clear_faults` | `SubmitCommand` | Asynchronous discrete command acceptance |
| `~/enable`, `~/disable`, `~/calibrate` | `SubmitCommand` | Capability-gated asynchronous acceptance |
| `~/recover` | `Recover` | Bounded identity-verified safe recovery |

Services are created according to command, telemetry or operation capabilities and require an
active driver. `SetRawValues`/`SubmitCommand` responses report admission through `accepted`;
follow the returned `command_id` in command status (`client_id=0` for service commands).
Topic commands use `(client_id, user_sequence)`; rejection before SDK admission can appear
only in diagnostics without a command handle. Use setter services when admission feedback is required.

Active reads run in one separate bounded admin worker. Control callbacks and
state publishers never wait for these transactions. Services return stable
`error_code` fields; clients must not parse error text.

Diagnostics expose each channel's requested and achieved rate, completed read
transactions, command-feedback samples, policy-counted feedback samples,
feedback policy, deadlines, timeouts, and cached data age. These counters let
benchmarks distinguish active angle queries from verified command feedback.

Examples: [commands and Python](examples.md).

## L6 Control Gains

`position_kp`, `position_kd` and `torque_kd` provide command topics, reliable setter
services, query services and cached state. See [L6 model features](models.md#l6) for
ranges and raw semantics. Setters report FIFO admission, not protocol completion;
there is no gain polling parameter or implicit mode change/save.

## On-Demand Raw Reads

`GetRawValues` endpoints are created during configure from telemetry capabilities and called
while active. Command support alone does not imply a readable channel. Service queries update
SDK caches and normal state publication; subscribing to a topic does not query the device,
enable polling or send configuration writes.

| `read_mode` | Behavior | Examples |
| --- | --- | --- |
| `query` | Request a fresh post-call device sample | O6 configured speeds/accelerations, O30 motion times |
| `command_response` | Read the last valid device write reply without I/O | L6 configured speeds, O6 current limits, L20Lite settings |
| `command_cache` | Read the last valid locally dispatched command without device confirmation | L30 configured speeds/current limits |

Check `success`, then `state.meta`, raw units, scale notes and confidence. Cache reads retain
original sequence and collection time and can succeed with `stale=true`. `device_queried`
describes channel capability; `meta.origin` identifies the particular sample. No physical-unit
conversion is performed. Use structured fields rather than response message text.

Current and torque interfaces remain independent:

- Live current uses `current_hz` and `state/currents`; it does not populate or replace current limits.
- O6 `get_current_limits` retains complete write replies, whose values may differ from the target.
  They use `ORIGIN_DEVICE_CONFIG_RESPONSE`, `device_measured=false`, `device_queried=false`.
  A later failed write in the same generation leaves the previous valid reply readable, without
  confirming the failed target. Recovery invalidates it until another complete write reply.
- L20 has no limit readback. L20Lite speed/current-limit commands require both valid write replies
  for ACK; their configuration caches are independent of measured speed/current.
- O30 current limits (`0x04`) and torque limits (`0x06`) have separate commands, getters and state.
  `torques_hz` reads measured torque and does not imply support for `command/torques`.
- L6 `command/torques` selects output/mode as described above.

See [model features](models.md) for each model's supported settings and operations.
L20Lite stall protection has three setters and confirmed write-response state, but no
`get_stall_protection`; `hold_current` is the common post-stall current field.

| Failure | Result |
| --- | --- |
| No valid command-derived sample | `unsupported_operation`, invalid state; no write is sent to manufacture a sample |
| Optional query disabled for this firmware | `unsupported_firmware`; declared endpoint remains |
| Inactive or closing | `device_not_ready` |
| Invalid timeout | `validation` |
| SDK timeout/protocol failure | Original stable SDK error code |

`timeout_s` must be finite and positive, with worker shutdown margin fitting inside
`shutdown_timeout_s`. Queries share device/bus scheduling with commands; use them on demand.

## L6 Limit Compensation

`limit_compensations` uses six 0..255 raw counts, with unknown physical scale/direction.
Use the command topic/client setter or reliable `set_limit_compensations` service;
`get_limit_compensations` performs an active query. State is configuration, not measured angles.
An exact six-byte echo is required for ACK; no implicit save is performed.
See [L6 features](models.md#l6) and [service semantics](#services).

## QoS and publication

| Interface | Reliability | Durability | Depth |
| --- | --- | --- | --- |
| Commands and state | Best effort | Volatile | 1 |
| Command status | Reliable | Volatile | 32 |
| Capabilities and identity | Reliable | Transient local | 1 |

Use compatible subscription QoS (for CLI state reads, `--qos-reliability best_effort`
can make the choice explicit). `~/` is relative to the driver node, normally `/linkerbot_hand`.
State is emitted when sequence or validity metadata changes; repeated sequences can describe
age/stale changes and do not count as new samples. Disabled polling does not erase existing cache
or prevent command feedback. `publish_rate_hz=0` pauses ROS state publication.

SDK cache changes wake a dedicated publisher; the production ROS process uses a
`MultiThreadedExecutor`. Capabilities are refreshed from SDK memory, without device queries.
For control-loop readiness, status correlation and waiting rules, use
[application integration](business_integration.md) and [client waits](client_waits.md).
