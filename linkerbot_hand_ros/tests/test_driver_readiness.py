"""Readiness needs the named live driver, even with compatible observers."""

import time

import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from lifecycle_msgs.msg import State, TransitionEvent
from lifecycle_msgs.srv import GetState
from linkerbot_hand_ros.client import HandCommandClient
from linkerbot_hand_ros.node import LinkerbotHandNode
from linkerbot_hand_ros.qos import COMMAND_QOS
from rclpy.executors import SingleThreadedExecutor
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.node import Node

from linkerbot_hand_msgs.msg import HandJointCommand


def spin_until(executor, predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.02)
    assert predicate()


@pytest.fixture
def readiness_rig():
    rclpy.init()
    driver = LinkerbotHandNode(device_factory=DeviceBuilder(), namespace="/left")
    # Same basename as the driver, different namespace: also not the driver.
    observer = Node("linkerbot_hand", namespace="/observer")
    node = Node("readiness_client")
    client = HandCommandClient(node, "/left/linkerbot_hand")
    observer.create_subscription(
        HandJointCommand,
        "/left/linkerbot_hand/command/angles",
        lambda _: None,
        COMMAND_QOS,
    )
    executor = SingleThreadedExecutor()
    for current in (driver, observer, node):
        executor.add_node(current)
    try:
        assert driver.trigger_configure() == TransitionCallbackReturn.SUCCESS
        assert driver.trigger_activate() == TransitionCallbackReturn.SUCCESS
        spin_until(executor, client.is_ready)
        yield driver, client, executor
    finally:
        for current in (driver, observer, node):
            executor.remove_node(current)
        executor.shutdown()
        client.destroy()
        driver.destroy_node()
        observer.destroy_node()
        node.destroy_node()
        rclpy.try_shutdown()


def test_observer_cannot_keep_inactive_driver_ready(readiness_rig):
    driver, client, executor = readiness_rig
    assert driver.trigger_deactivate() == TransitionCallbackReturn.SUCCESS
    spin_until(executor, lambda: not client.is_ready())
    # Old logic passed with exactly this verified cache and third-party count.
    assert client._capabilities.identity.verified
    assert client._angle_publisher.get_subscription_count() > 0
    with pytest.raises(RuntimeError, match="not active"):
        client.set_percent_angles([50.0] * 6)

    assert driver.trigger_activate() == TransitionCallbackReturn.SUCCESS
    spin_until(executor, client.is_ready)


def test_unresponsive_driver_loses_readiness_with_live_graph_endpoints(readiness_rig):
    driver, client, executor = readiness_rig
    executor.remove_node(driver)
    # Entities still exist, but lifecycle queries no longer get responses.
    assert client._readiness._client.service_is_ready()
    spin_until(executor, lambda: not client.is_ready(), timeout=2.0)
    assert client._angle_publisher.get_subscription_count() > 0
    assert client.wait_until_ready(0.05) is False


def test_transition_invalidates_delayed_active_response(readiness_rig):
    driver, client, executor = readiness_rig
    monitor = client._readiness
    executor.remove_node(driver)
    spin_until(executor, lambda: monitor._pending is not None)
    old_response = monitor._pending
    monitor._on_transition(
        TransitionEvent(goal_state=State(id=State.PRIMARY_STATE_INACTIVE))
    )
    old_response.set_result(
        GetState.Response(current_state=State(id=State.PRIMARY_STATE_ACTIVE))
    )
    executor.spin_once(timeout_sec=0.1)
    assert not client.is_ready()
    assert old_response not in monitor._client._pending_requests.values()


def test_shutdown_cannot_be_hidden_by_observer(readiness_rig):
    driver, client, executor = readiness_rig
    assert driver.trigger_shutdown() == TransitionCallbackReturn.SUCCESS
    spin_until(executor, lambda: not client.is_ready())
    assert client._angle_publisher.get_subscription_count() > 0
