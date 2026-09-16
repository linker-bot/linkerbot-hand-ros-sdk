"""Client waits must leave executor capacity for their incoming messages."""

from __future__ import annotations

import time

import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand_ros.client import HandCommandClient
from linkerbot_hand_ros.node import LinkerbotHandNode
from rclpy.executors import MultiThreadedExecutor, SingleThreadedExecutor
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.node import Node
from rclpy.parameter import Parameter


@pytest.mark.parametrize("asynchronous", [True, False])
def test_callback_can_wait_for_activation_and_new_terminal_status(asynchronous):
    rclpy.init()
    driver = LinkerbotHandNode(device_factory=DeviceBuilder())
    node = Node("waiting_controller")
    executor = (
        SingleThreadedExecutor()
        if asynchronous
        else MultiThreadedExecutor(num_threads=2)
    )
    client = HandCommandClient(node)
    result = []
    executor.add_node(driver)
    executor.add_node(node)

    def activate():
        activation.cancel()
        assert driver.trigger_activate() == TransitionCallbackReturn.SUCCESS

    async def async_callback():
        caller.cancel()
        assert await client.wait_until_ready_async(4.0)
        publication = client.set_percent_angles([50.0] * 6)
        result.append(
            await client.wait_for_terminal_status_async(publication.user_sequence, 4.0)
        )

    def sync_callback():
        caller.cancel()
        assert client.wait_until_ready(4.0)
        publication = client.set_percent_angles([50.0] * 6)
        result.append(client.wait_for_terminal_status(publication.user_sequence, 4.0))

    try:
        assert driver.trigger_configure() == TransitionCallbackReturn.SUCCESS
        activation = driver.create_timer(0.15, activate)
        caller = node.create_timer(
            0.001, async_callback if asynchronous else sync_callback
        )
        deadline = time.monotonic() + 9.0
        while not result and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.05)
        assert len(result) == 1
        assert result[0] is not None, "new status could not run during the wait"
        assert not client._pending_waits
    finally:
        executor.remove_node(driver)
        executor.remove_node(node)
        executor.shutdown(timeout_sec=5.0)
        client.destroy()
        driver.destroy_node()
        node.destroy_node()
        rclpy.try_shutdown()


def test_async_timeout_uses_wall_time_even_when_ros_time_is_paused():
    rclpy.init()
    node = Node(
        "paused_client", parameter_overrides=[Parameter("use_sim_time", value=True)]
    )
    client = HandCommandClient(node, "/absent_driver")
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        readiness = client.wait_until_ready_async(0.1)
        status = client.wait_for_terminal_status_async(1, 0.1)
        executor.spin_until_future_complete(readiness, timeout_sec=2.0)
        executor.spin_until_future_complete(status, timeout_sec=2.0)
        assert readiness.done() and readiness.result() is False
        assert status.done() and status.result() is None
        assert not client._pending_waits
    finally:
        executor.shutdown()
        client.destroy()
        node.destroy_node()
        rclpy.try_shutdown()


def test_cancel_and_destroy_release_pending_waits_and_entities():
    rclpy.init()
    node = Node("cancelled_client")
    client = HandCommandClient(node, "/absent_driver")
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        cancelled = client.wait_until_ready_async(20.0)
        cancelled.cancel()
        executor.spin_once(timeout_sec=1.0)
        assert cancelled.cancelled()
        assert not client._pending_waits
        readiness = client.wait_until_ready_async(20.0)
        status = client.wait_for_terminal_status_async(2, 20.0)
        client.destroy()
        for future in (readiness, status):
            assert future.done()
            with pytest.raises(RuntimeError, match="destroyed"):
                future.result()
        assert not list(node.timers)
        assert not list(node.subscriptions)
        assert not client._pending_waits
    finally:
        executor.shutdown()
        client.destroy()
        node.destroy_node()
        rclpy.try_shutdown()
