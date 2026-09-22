"""Repeated slider broadcasts cannot replay motion across control boundaries."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
import rclpy
from linkerbot_hand import get_declared_capabilities
from linkerbot_hand_gui.joint_mapping import JointLimit, O6JointMapping
from linkerbot_hand_ros.conversion import capabilities_to_message
from sensor_msgs.msg import JointState
from std_srvs.srv import SetBool

from linkerbot_hand_gui import bridge_node
from linkerbot_hand_msgs.msg import HandJointState, SampleMetadata


@pytest.fixture
def rig(monkeypatch):
    caps = get_declared_capabilities("o6", side="right")
    names = caps.joint_names
    mapping = O6JointMapping(
        names, names, {name: JointLimit(0.0, 1.0) for name in names}, names, "right"
    )
    clock = SimpleNamespace(now=100.0)
    readiness = SimpleNamespace(active=True, destroy=lambda: None)
    readiness.is_active = lambda _topic: readiness.active
    monkeypatch.setattr(bridge_node, "resolve_o6_assets", lambda *_: object())
    monkeypatch.setattr(bridge_node, "load_o6_decoder", lambda _: names)
    monkeypatch.setattr(O6JointMapping, "from_assets", lambda _: mapping)
    monkeypatch.setattr(bridge_node, "DriverReadiness", lambda *_: readiness)
    monkeypatch.setattr(
        bridge_node, "time", SimpleNamespace(monotonic=lambda: clock.now)
    )
    rclpy.init()
    bridge = bridge_node.O6GuiBridge()
    bridge._timer.cancel()
    bridge._initial_seed_timer.cancel()
    commands, previews = [], []
    bridge._command_publisher = SimpleNamespace(publish=commands.append)
    bridge._target_publisher = SimpleNamespace(publish=previews.append)
    capability = capabilities_to_message(
        replace(caps, identity=replace(caps.identity, verified=True))
    )
    bridge._on_capabilities(capability)

    def state(
        *, generation=1, valid=True, stale=False, percent_valid=True, percent=None
    ):
        bridge._on_state(
            HandJointState(
                joint_names=list(names),
                percent=[80.0] * 6 if percent is None else percent,
                percent_valid=[percent_valid] * 6,
                meta=SampleMetadata(
                    valid=valid, stale=stale, connection_generation=generation
                ),
            )
        )

    def target(value, *, reverse=False, stamp=0):
        positions = value if isinstance(value, list) else [value] * 6
        message = JointState(name=list(names), position=positions)
        message.header.stamp.sec = stamp
        if reverse:
            message.name = list(reversed(message.name))
            message.position = list(reversed(message.position))
        bridge._on_target(message)

    def enable(value=True):
        response = bridge._set_control_enabled(
            SetBool.Request(data=value), SetBool.Response()
        )
        assert response.success, response.message

    state()
    try:
        yield SimpleNamespace(
            bridge=bridge,
            clock=clock,
            readiness=readiness,
            capability=capability,
            commands=commands,
            previews=previews,
            target=target,
            state=state,
            enable=enable,
            publish=bridge._publish_latest_target,
        )
    finally:
        bridge.destroy_node()
        rclpy.try_shutdown()


def arm(rig):
    rig.target(0.2)
    rig.enable()
    rig.target(0.6)
    rig.publish()
    assert len(rig.commands) == 1
    assert rig.commands[-1].values == pytest.approx([40.0] * 6)
    rig.commands.clear()


@pytest.mark.parametrize("preview_before_enable", [False, True])
def test_first_or_unchanged_broadcast_after_enable_only_updates_preview(
    rig, preview_before_enable
):
    if preview_before_enable:
        rig.target(0.6)
    rig.enable()
    for index in range(3):
        rig.target(0.6, reverse=bool(index % 2), stamp=index + 1)
        rig.publish()
    assert not rig.commands
    assert len(rig.previews) == 3 + int(preview_before_enable)
    rig.target(0.7)
    rig.publish()
    rig.target(0.7)
    rig.publish()
    assert len(rig.commands) == 2
    assert rig.commands[0].values == pytest.approx([30.0] * 6)
    assert rig.commands[1].user_sequence == rig.commands[0].user_sequence + 1


@pytest.mark.parametrize("broadcast_while_disabled", [False, True])
def test_disable_enable_keeps_repeat_detection_even_when_no_slider_message_arrives(
    rig, broadcast_while_disabled
):
    arm(rig)
    rig.enable(False)
    if broadcast_while_disabled:
        rig.target(0.7)
    rig.enable()
    rig.target(0.7 if broadcast_while_disabled else 0.6)
    rig.publish()
    assert not rig.commands
    rig.target(0.8)
    rig.publish()
    assert len(rig.commands) == 1


@pytest.mark.parametrize(
    "boundary", ["generation", "stale", "invalid", "percent_invalid", "state_gap"]
)
def test_feedback_recovery_requires_new_target_change(rig, boundary):
    arm(rig)
    if boundary == "generation":
        rig.state(generation=2)
    elif boundary == "state_gap":
        # Fresh feedback arrives before the command timer notices the gap.
        rig.clock.now += 3.0
        rig.state()
    else:
        rig.state(
            stale=boundary == "stale",
            valid=boundary != "invalid",
            percent_valid=boundary != "percent_invalid",
        )
        rig.publish()
        assert not rig.commands
        rig.target(0.6)
        rig.state()
    rig.target(0.6)
    rig.publish()
    assert not rig.commands
    rig.target(0.7)
    rig.publish()
    assert len(rig.commands) == 1


@pytest.mark.parametrize("unavailable", ["driver", "feedback", "identity"])
def test_target_edited_while_unavailable_is_not_replayed_on_recovery(rig, unavailable):
    arm(rig)
    if unavailable == "driver":
        rig.readiness.active = False
    elif unavailable == "feedback":
        rig.clock.now += 3.0
    else:
        rig.capability.identity.verified = False
        rig.bridge._on_capabilities(rig.capability)
    rig.target(0.7)
    # Recover before the next publish tick; the input callback must gate arming.
    rig.readiness.active = True
    rig.capability.identity.verified = True
    rig.bridge._on_capabilities(rig.capability)
    rig.state()
    rig.target(0.7)
    rig.publish()
    assert not rig.commands
    rig.target(0.8)
    rig.publish()
    assert len(rig.commands) == 1


def test_driver_loss_detected_by_publish_disarms_static_target(rig):
    arm(rig)
    rig.readiness.active = False
    rig.publish()
    rig.readiness.active = True
    rig.target(0.6)
    rig.publish()
    assert not rig.commands
    rig.target(0.7)
    rig.publish()
    assert len(rig.commands) == 1


def test_feedback_timeout_detected_by_publish_disarms_static_target(rig):
    arm(rig)
    rig.clock.now += 3.0
    rig.publish()
    rig.state()
    rig.target(0.6)
    rig.publish()
    assert not rig.commands
    rig.target(0.7)
    rig.publish()
    assert len(rig.commands) == 1


@pytest.mark.parametrize("percent", [[80.0] * 5, [80.0] * 5 + [float("nan")]])
def test_malformed_feedback_cannot_leave_old_target_armed(rig, percent):
    arm(rig)
    rig.state(percent=percent)
    rig.publish()
    assert not rig.commands
    rig.state()
    rig.target(0.6)
    rig.publish()
    assert not rig.commands
    rig.target(0.7)
    rig.publish()
    assert len(rig.commands) == 1


def test_name_order_and_uncontrolled_joints_do_not_count_as_edit(rig):
    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    rig.target(values)
    rig.enable()
    rig.target(values, reverse=True, stamp=3)
    message = JointState(
        name=list(rig.bridge._mapping.urdf_names) + ["mimic_joint"],
        position=values + [0.9],
    )
    rig.bridge._on_target(message)
    rig.publish()
    assert not rig.commands
    values[0] = 0.2
    rig.target(values)
    rig.publish()
    assert rig.commands[-1].values == pytest.approx([80, 80, 70, 60, 50, 40])


def test_clamped_values_with_same_command_do_not_count_as_edit(rig):
    rig.target(1.0)
    rig.enable()
    rig.target(1.2)
    rig.publish()
    assert not rig.commands
    rig.target(0.9)
    rig.publish()
    assert len(rig.commands) == 1


def test_invalid_target_does_not_replace_comparison_baseline(rig):
    rig.target(0.6)
    rig.enable()
    rig.target(float("nan"))
    rig.target(0.6)
    rig.publish()
    assert not rig.commands
    rig.target(0.7)
    rig.publish()
    assert len(rig.commands) == 1
