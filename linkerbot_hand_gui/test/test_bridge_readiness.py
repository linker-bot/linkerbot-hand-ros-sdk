"""GUI lifecycle gates using real ROS graph endpoints and synthetic assets."""

import time
from dataclasses import replace

import rclpy
from linkerbot_hand import get_declared_capabilities
from linkerbot_hand_gui.joint_mapping import JointLimit, O6JointMapping
from linkerbot_hand_ros.conversion import capabilities_to_message
from linkerbot_hand_ros.qos import COMMAND_QOS
from rclpy.executors import SingleThreadedExecutor
from rclpy.lifecycle import LifecycleNode
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_srvs.srv import SetBool

from linkerbot_hand_gui import bridge_node
from linkerbot_hand_msgs.msg import HandJointCommand


def _spin_until(executor, predicate):
    deadline = time.monotonic() + 4.0
    while not predicate() and time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.02)
    assert predicate()


def test_gui_rejects_observer_and_disarms_after_driver_deactivation(monkeypatch):
    capabilities = get_declared_capabilities("o6", side="right")
    names = tuple(joint.name for joint in capabilities.joints)
    mapping = O6JointMapping(
        names, names, {name: JointLimit(0.0, 1.0) for name in names}, names, "right"
    )
    monkeypatch.setattr(bridge_node, "resolve_o6_assets", lambda *_: object())
    monkeypatch.setattr(bridge_node, "load_o6_decoder", lambda _: names)
    monkeypatch.setattr(O6JointMapping, "from_assets", lambda _: mapping)
    rclpy.init()
    driver = LifecycleNode("linkerbot_hand")
    observer = Node("observer")
    bridge = bridge_node.O6GuiBridge()
    executor = SingleThreadedExecutor()
    received = []
    observer.create_subscription(
        HandJointCommand, "/linkerbot_hand/command/angles", received.append, COMMAND_QOS
    )
    for node in (driver, observer, bridge):
        executor.add_node(node)
    bridge._on_capabilities(
        capabilities_to_message(
            replace(
                capabilities, identity=replace(capabilities.identity, verified=True)
            )
        )
    )
    target = JointState(name=list(names), position=[0.5] * 6)
    enable = lambda: bridge._set_control_enabled(
        SetBool.Request(data=True), SetBool.Response()
    )
    try:
        _spin_until(
            executor, lambda: bridge._command_publisher.get_subscription_count() > 0
        )
        assert not enable().success
        driver.trigger_configure()
        driver.trigger_activate()
        command = driver.create_subscription(
            HandJointCommand,
            "/linkerbot_hand/command/angles",
            lambda _: None,
            COMMAND_QOS,
        )
        _spin_until(
            executor,
            lambda: bridge._readiness.is_active("/linkerbot_hand/command/angles"),
        )
        assert enable().success
        assert not bridge._target_armed
        bridge._last_valid_state = time.monotonic()
        bridge._on_target(target)
        _spin_until(executor, lambda: bool(received))
        driver.trigger_deactivate()
        driver.destroy_subscription(command)
        _spin_until(
            executor,
            lambda: not bridge._readiness.is_active("/linkerbot_hand/command/angles"),
        )
        received.clear()
        bridge._publish_latest_target()
        assert not bridge._target_armed
        assert bridge._latest_target is None
        assert not enable().success
        # The existing state-age guard remains independent of lifecycle.
        driver.trigger_activate()
        driver.create_subscription(
            HandJointCommand,
            "/linkerbot_hand/command/angles",
            lambda _: None,
            COMMAND_QOS,
        )
        _spin_until(
            executor,
            lambda: bridge._readiness.is_active("/linkerbot_hand/command/angles"),
        )
        assert enable().success
        bridge._on_target(target)
        bridge._last_valid_state = time.monotonic() - 3.0
        bridge._publish_latest_target()
        assert not bridge._target_armed
    finally:
        for node in (driver, observer, bridge):
            executor.remove_node(node)
        executor.shutdown()
        bridge.destroy_node()
        observer.destroy_node()
        driver.destroy_node()
        rclpy.try_shutdown()
