# Troubleshooting

English | [简体中文](zh/troubleshooting.md) | [Manual](../README.md)

## Discovery and saved deployments

See [discovery troubleshooting](discovery_troubleshooting.md) for missing/ambiguous
candidates, libraries, permissions, channel selection, files and identity matching.
Keep the scan summary, original cause, configuration path and lifecycle error from one attempt.

## Missing packages or wrong Python environment

Load ROS, the venv and the workspace in order in each terminal:

```bash
source /opt/ros/jazzy/setup.bash
source ~/venvs/linkerbot-hand-ros/bin/activate
source ~/linkerbot_ws/install/setup.bash
ros2 pkg executables linkerbot_hand_ros
python -c 'import sys, linkerbot_hand; print(sys.executable); print(linkerbot_hand.__file__)'
```

Do not mix ROS distributions or Python environments. Follow [installation](getting_started.md)
for missing packages and [updates](update.md) for incorrect SDK paths or inconsistent ROSIDL consumers.

## Configure or activate fails

Configure validates model/side, transport JSON, rates, capacities, timeouts and polling
capabilities. L30 requires an empty side. Activate opens the transport, verifies identity
and reads the baseline.

```bash
ros2 param dump /linkerbot_hand
ip -details -statistics link show can0
ros2 topic echo --once /diagnostics
```

Check power, wiring, termination, UP state, CAN/FD mode, bitrates and device addresses.
Investigate `identity_mismatch` using the actual connected identity. For `unsupported_firmware`,
read the operation and error details; the code alone does not prove that no device profile exists.
Resolve cleanup failures before retrying. Deactivate and cleanup before changing static
parameters; see [configuration](configuration.md).

## Active but no feedback, or low feedback rate

```bash
ros2 lifecycle get /linkerbot_hand
ros2 topic echo --once /linkerbot_hand/capabilities
ros2 param get /linkerbot_hand angles_hz
ros2 param get /linkerbot_hand angle_feedback
ros2 param get /linkerbot_hand force_hz
ros2 param get /linkerbot_hand publish_rate_hz
```

Use compatible best-effort subscriptions. Most channels except angles default to no polling,
but command responses can still update caches. `publish_rate_hz=0` pauses publication;
a positive value controls idle validity checks while new cache revisions wake publication
immediately. A validity change with the same sequence is not a new device sample.

Inspect requested/achieved rates, completed reads, feedback samples, timeouts, age,
route misses and bus errors in diagnostics. The [benchmark guide](zh/frequency_benchmark.md)
(Chinese) distinguishes transport, device and ROS rates.

## Missing query, service or angle representation

Inspect current capabilities and `firmware_unsupported_telemetry`. Repeated optional-query
failures can disable that telemetry while retaining the connection; reconnecting probes it
again. If every request fails, check the bus and power first. Service availability follows
model capabilities, and successful cached reads still require source/validity/time checks.

False `percent_valid` or `physical_rad_valid` means there is no trusted mapping for
that representation. A placeholder zero is not a measurement; raw retains the original response.

## Rejected, superseded or nonmoving commands

Check active/recovering state, supported semantics, client ID/sequence, array length,
finite numbers and raw integer ranges. Inspect `statuses[].error_code`; pre-admission
rejection may appear only in diagnostics.

`ACCEPTED` is SDK admission. Inspect dispatch, ACK, failure and supersession, then
use fresh current-generation angles for arrival. Check position/torque mode on L6.
Continuous targets are latest-wins; reduce overload instead of enlarging a FIFO to
retain a trajectory. See [application integration](business_integration.md).

## Service timeout, recovery or cleanup failure

Queries and recover use a bounded admin worker and [timeout constraints](configuration.md).
Reduce concurrent management calls on `queue_full`. Never synchronously wait inside a
single-threaded executor callback.

Recovery does not replay targets. Wait for valid new-generation feedback and submit a
new target explicitly. Stop application and service producers before deactivate/cleanup.
For close timeouts or surviving threads, retain the cause, backend and thread/FD evidence,
and confirm release before reopening the same physical interface.
