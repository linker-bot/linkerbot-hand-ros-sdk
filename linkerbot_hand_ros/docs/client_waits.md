# Waiting for a ROS hand client

English | [简体中文](zh/client_waits.md) | [Manual](../README.md)

Readiness requires verified capability metadata, a fresh `get_state` response
reporting **active** from the specified driver, and that driver's command
subscription in the ROS graph. A recorder or another observer on the command
topic cannot make the client ready. Lifecycle transitions invalidate outstanding
state queries; queries refresh every 0.2 seconds, and evidence expires one
second after the request was sent, even if an old response arrives late. A dead
or unresponsive driver therefore cannot leave readiness cached indefinitely.
This is ROS graph identity, not authentication against a node impersonating the
same name. It also does not prove device health or mechanical safety. The driver
still validates lifecycle and device state when admitting each command.

`HandCommandClient` has its own callback group for metadata, command status and
wait timeouts. The node still needs to be spinning.

| Caller | Supported waiting pattern |
| --- | --- |
| Async ROS callback, including SingleThreadedExecutor | `await wait_until_ready_async(...)`, `await wait_for_terminal_status_async(...)` |
| Synchronous ROS callback | Prefer a state machine or Future done callback; blocking waits require a MultiThreadedExecutor with at least one spare thread |
| Application thread outside executor callbacks | Synchronous waits while a separate thread spins the node |

The async methods return **rclpy Futures**, intended for ROS executor coroutines
or `add_done_callback`, not an independently running asyncio event loop. Do not
call `spin_until_future_complete` or nest executor spinning inside a callback.
Synchronous waiting inside a SingleThreadedExecutor callback prevents message
delivery until the wait times out. Even with multiple threads, blocking all
workers has the same effect.

For an occasional command from an async callback:

```python
async def send_target(self, target):
    if not await self.hand.wait_until_ready_async(2.0):
        return  # False means readiness timeout.
    publication = self.hand.set_percent_angles(target)
    status = await self.hand.wait_for_terminal_status_async(
        publication.user_sequence, 1.0
    )
    if status is None:
        self.get_logger().warning("No terminal status before timeout")
```

Keep high-rate control loops nonblocking: use `is_ready`, publish the latest
target and inspect `get_status` on subsequent ticks. Awaiting inside a mutually
exclusive callback still occupies that callback group, although it releases
the executor thread. Client reception is isolated from that group.

Timeouts use elapsed wall time, including when ROS simulation time is paused.
Cancelling a returned Future cancels only that wait. Destroy the client before
destroying its node; pending waits then fail with `RuntimeError`. Neither a
timeout nor cancellation retracts a published command. A terminal SDK status
describes protocol progress, not mechanical target arrival.

Inspect the returned stage for failure or supersession; receiving a terminal status alone does not prove success.
