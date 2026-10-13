# Commands and Python examples

English | [简体中文](zh/examples.md) | [Manual](../README.md)

Activate the driver using [Getting started](getting_started.md). Replace `/linkerbot_hand`
with the saved namespace when using multiple hands.

## Read capabilities and feedback

```bash
ros2 topic echo --once /linkerbot_hand/capabilities
ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/angles
ros2 topic echo /linkerbot_hand/command/status
```

Use verified capabilities for joint order, ranges and supported commands. Check state
validity, staleness, connection generation and per-axis validity; see [application integration](business_integration.md).

## Send one O6 angle target

This command moves a six-axis O6. Confirm clearance and the target before running it.
For other models use their capability order/count; L6 also requires the appropriate
[position mode](ros_api.md#l6-torque-outputmode).

```bash
ros2 topic pub --once /linkerbot_hand/command/angles \
  linkerbot_hand_msgs/msg/HandJointCommand \
  '{client_id: 1, user_sequence: 1, representation: 1, values: [50, 50, 50, 50, 50, 50]}'
```

Representation `1` is percent: flexion axes use `0=bent, 100=straight`; other axes
use their endpoint labels. Representation `2` is exact protocol raw and must satisfy
per-axis range and integer constraints. It performs no physical-unit conversion.
Use a new `user_sequence` for each command and a distinct nonzero `client_id` per publisher.

Iterate `statuses[]` in each status batch and match `(client_id, user_sequence)`.
Commands without ACK support finish successfully at `DISPATCHED`; those with ACK support
wait for `ACKNOWLEDGED`. `FAILED` and `SUPERSEDED` do not establish arrival.
Check `/diagnostics` for rejection before SDK admission.

## Read settings

The driver creates only capability-supported endpoints. For example, O6 actively queries configured speeds:

```bash
ros2 service list -t
ros2 service call /linkerbot_hand/get_configured_speeds \
  linkerbot_hand_msgs/srv/GetRawValues '{timeout_s: 0.5}'
```

Depending on model, a service queries the device, reads a device write response or
reads the local command cache. Success alone does not prove fresh measured feedback:
inspect `state.meta`, `raw_unit` and `raw_scale_note`.
See [raw reads](ros_api.md#on-demand-raw-reads) and [model features](models.md).
Configured speeds, current limits and torque limits are not measured feedback.

## Persistent Python client

Keep one `HandCommandClient` per driver and spin the owning node. Add these methods
to an application Node; supply a validated target from a low-rate ROS async callback:

```python
from linkerbot_hand_msgs.msg import HandCommandStatus
from linkerbot_hand_ros.client import HandCommandClient


def init_hand(self):
    self.hand = HandCommandClient(self, "/linkerbot_hand")


async def send_target(self, target_percent):
    if not await self.hand.wait_until_ready_async(2.0):
        return False
    publication = self.hand.set_percent_angles(target_percent)
    status = await self.hand.wait_for_terminal_status_async(
        publication.user_sequence, 1.0
    )
    return status is not None and status.stage in (
        HandCommandStatus.STAGE_DISPATCHED,
        HandCommandStatus.STAGE_ACKNOWLEDGED,
    )
```

The result describes protocol completion; evaluate mechanical arrival separately.
Invalid targets raise exceptions for the application to handle. Call `self.hand.destroy()`
before destroying the node. High-rate timers should use `is_ready("angles")`, publish,
and inspect `get_status(sequence)` on later ticks. Avoid blocking or nested spinning
inside callbacks; see [client waits](client_waits.md).

Bundled tools: `state_monitor` observes feedback, `angle_command --values ...` sends
an explicit target, and `angle_controller` provides persistent control. Use each tool's `--help`.

## Tactile, management and recovery

Enable polling as described in the [tactile guide](force.md). The six matrix models
publish `state/tactile`; O30 publishes `state/tactile_sensors`. Count complete samples,
not fingers, cells or CAN fragments.

```bash
ros2 service call /linkerbot_hand/get_device_info \
  linkerbot_hand_msgs/srv/GetDeviceInfo '{timeout_s: 0.2}'
ros2 service call /linkerbot_hand/recover \
  linkerbot_hand_msgs/srv/Recover '{timeout_s: 1.0}'
```

Stop application targets before recovery. Wait for valid feedback in the new generation
before producing a new target. See [model features](models.md) for stall protection,
gains, fault clearing and persistence. Track accepted service writes by the returned `command_id`.
