# Application integration

English | [简体中文](zh/business_integration.md) | [Manual](../README.md)

Applications use `HandCommandClient` and `linkerbot_hand_msgs`; the driver's
`HandDevice` owns device I/O. Do not reopen CAN or maintain a second model/range table.

## Startup and readiness

1. Configure the driver and read declared capabilities.
2. Activate; wait for verified identity, device information and operational diagnostics.
3. Obtain a valid angle baseline from the current connection generation; check faults and application safety conditions.
4. Enable target production.

Use capabilities for joint names/order, percent endpoints, raw ranges and supported
commands/telemetry. `is_ready("angles")` also checks the specified driver's active state
and command endpoint ownership. Readiness does not establish device health or mechanical
safety; see [client waits](client_waits.md) for expiry and executor requirements.

## Control loop

```text
publish target → observe SDK admission/dispatch/ACK → inspect fresh angles → apply tolerance and settle time → arrival
```

Continuous commands use best-effort depth 1 and latest-wins scheduling. Design around
the latest target; historical setpoints need not all reach the bus. `SUPERSEDED` means
confirmed unsent before transport claim. Use a nonblocking state machine for high-rate
control and the [async example](examples.md#persistent-python-client) for occasional commands.

| Stage | Evidence |
| --- | --- |
| `CommandPublication` | Message handed to the local DDS publisher |
| `driver_received_stamp` | Driver callback received the message |
| `ACCEPTED` | SDK validation and admission succeeded |
| `DISPATCHED` | All request frames were sent successfully |
| `ACKNOWLEDGED` | Explicit protocol acknowledgement, when supported |
| Arrival | Fresh current-generation feedback meets application criteria |

Correlate topic status by `(client_id, user_sequence)` and service writes by returned
`command_id`. Direct subscribers iterate batch `statuses[]`; the client expands batches
and filters its own client ID. `transitions[]` preserves stage history for latency analysis.

## Feedback and arrival

For each `HandJointState`, require:

- Valid, non-stale metadata in the current connection generation.
- Joint names matching verified capabilities exactly.
- Appropriate per-axis `percent_valid` or `physical_rad_valid` masks.
- A new `meta.sequence` for a new device sample; validity changes may publish the same sequence.

Evaluate tolerance and settle time only with fresh valid samples. Reset the arrival
window on missing/stale feedback, disconnection or a generation change. Raw, percent
and physical radians are distinct representations. See [model features](models.md)
for configured values, limits and measured feedback.

## Errors and recovery

Branch on stable `error_code`, not translated messages. Correct `validation` inputs,
disable unsupported operations, and reduce submission pressure for `queue_full`.
Identity mismatches, repeated transport errors and device faults should stop application
control for diagnosis. Rejection before SDK admission may appear only in diagnostics.

On disconnect, recovery or generation change, stop targets and clear pending commands
and arrival windows. Do not queue targets for replay. After identity verification and
a fresh baseline, recheck faults/safety and explicitly produce a new target. Recovery
does not replay targets or automatically clear faults, enable or calibrate the hand.

## Shutdown and multiple devices

Stop target producers, deactivate the driver, then cleanup/shutdown to release the
connection. Deactivation does not implicitly hold, open or close the hand; define any
required stopping action with an explicit target, feedback and timeout. Resolve cleanup
failures before opening another driver on the same interface.

Each hand needs a separate physical channel, namespace, client and feedback state machine.
`multi_hand.launch.py` supports group startup/rollback; see [configuration](configuration.md#multi-device).
Namespaces do not isolate bus traffic or make capabilities identical across models.
