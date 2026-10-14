# Control and Python examples

Activate the driver with [quick start](quick_start.md). For multiple hands, replace `/linkerbot_hand` with the actual path. Array order and ranges come from device capabilities.

## Read capabilities and feedback

```bash
ros2 topic echo --once --qos-durability transient_local /linkerbot_hand/capabilities
ros2 topic echo --once --qos-reliability best_effort /linkerbot_hand/state/angles
ros2 topic echo /linkerbot_hand/command/status
```

Verify identity, angle `meta.valid=true`, `stale=false` and current generation. Check `percent_valid` per axis. L6 also requires the correct [position mode](l6.md#model-details-and-management).

## Send one O6 angle target

These commands move a six-joint O6. Check clearance, current angles and direction first:

```bash
ros2 run linkerbot_hand_ros angle_command --values 50 50 50 50 50 50
```

Default percent uses 0..100: flexion axes use 0 for flexed and 100 for extended; other axes follow capability endpoint labels. Use `--raw --values ...` for exact protocol integers. The tool waits for readiness and checks protocol-terminal status, not mechanical arrival.

For direct ROS publication, specify correlation IDs:

```bash
ros2 topic pub --once --qos-reliability best_effort \
  /linkerbot_hand/command/angles linkerbot_hand_msgs/msg/HandJointCommand \
  '{client_id: 1, user_sequence: 1, representation: 1, values: [50, 50, 50, 50, 50, 50]}'
```

Use a distinct nonzero `client_id` for each publisher and a new `user_sequence` for every command. This CLI example omits `publisher_stamp`, so it cannot measure publication latency. The client fills it automatically.

## Runnable Python client

Save as `hand_command_example.py` and run `python hand_command_example.py` in a ROS-configured terminal. It moves every joint to 50 percent. Complete the state checks above and replace target with your application target.

```python
import threading

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node

from linkerbot_hand_msgs.msg import HandCommandStatus
from linkerbot_hand_ros.client import HandCommandClient


def main():
    rclpy.init()
    node = Node("hand_command_example")
    hand = HandCommandClient(node, "/linkerbot_hand")
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def spin():
        try:
            executor.spin()
        except ExternalShutdownException:
            pass

    worker = threading.Thread(target=spin)
    worker.start()
    try:
        if not hand.wait_until_ready(2.0):
            raise RuntimeError("Driver is not ready")
        target = [50.0] * len(hand.joint_names)
        publication = hand.set_percent_angles(target)
        status = hand.wait_for_terminal_status(publication.user_sequence, 1.0)
        if status is None:
            raise RuntimeError("Command status timed out")
        if status.stage not in (
            HandCommandStatus.STAGE_DISPATCHED,
            HandCommandStatus.STAGE_ACKNOWLEDGED,
        ):
            raise RuntimeError(f"Command failed: {status.error_code}")
        print("Protocol stage:", status.stage)
    finally:
        executor.shutdown()
        worker.join()
        hand.destroy()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
```

A separate thread spins the node so the main thread can wait synchronously. Reuse one `HandCommandClient` in an application. A returned publication describes local DDS publication; subsequent status describes driver and protocol progress.

## Waiting in ROS callbacks

Async ROS callbacks use rclpy Futures:

```python
async def send_target(self, target):
    if not await self.hand.wait_until_ready_async(2.0):
        return None
    publication = self.hand.set_percent_angles(target)
    return await self.hand.wait_for_terminal_status_async(
        publication.user_sequence, 1.0
    )
```

Inspect the returned stage; receiving a terminal status alone does not prove success. High-rate timers use `is_ready("angles")` and `get_status(sequence)` in a nonblocking state machine. Do not synchronously wait or nest spinning in single-threaded callbacks. See [client waiting](client_waits.md).

## Configuration, management and recovery

```bash
ros2 service list -t
ros2 service call /linkerbot_hand/get_configured_speeds \
  linkerbot_hand_msgs/srv/GetRawValues '{timeout_s: 0.5}'
ros2 service call /linkerbot_hand/recover \
  linkerbot_hand_msgs/srv/Recover '{timeout_s: 1.0}'
```

Configuration reads can query the device, read device-reply caches or read local command caches. Inspect `state.meta`, units and [read modes](models.md#three-configuration-read-modes). Services are exposed only when supported.

Stop target production before recovery. Wait for valid new-generation state and explicitly submit new targets instead of replaying old ones. Dispatch and ACK do not prove mechanical arrival; the [application](business_integration.md) decides tolerance and settle time.

Other bundled tools are `state_monitor` (state reads), `angle_controller` (continuous control) and [frequency_benchmark](frequency_benchmark.md). Run each with `--help` for arguments.

[Back to overview](getting_started.md) · [简体中文](zh/examples.md)
