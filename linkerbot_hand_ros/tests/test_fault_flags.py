"""Preserve each protocol's distinct fault meanings through ROS serialization."""

from dataclasses import replace

import pytest
from linkerbot_hand import (
    AngleFeedbackPolicy,
    DataOrigin,
    FaultSample,
    HandDevice,
    JointFaultStatus,
    L6FaultStatus,
    L20FaultStatus,
    L20LiteFaultStatus,
    O6FaultStatus,
    SampleMeta,
    TelemetrySemantic,
    get_declared_capabilities,
)
from linkerbot_hand_ros.conversion import fault_statuses_to_message
from linkerbot_hand_ros.state_publisher import SnapshotPublisher
from rclpy.serialization import deserialize_message, serialize_message
from test_state_publisher import _RecordingNode

from linkerbot_hand_msgs.msg import HandFaultStatusState

L6_FLAGS = {
    "mcu_over_temperature": 0x40,
    "motor_over_temperature": 0x20,
    "overload_2": 0x10,
    "overload_1": 0x08,
    "phase_a_over_current": 0x04,
    "phase_c_over_current": 0x02,
    "phase_b_over_current": 0x01,
}
L20_FLAGS = {
    "motor_communication_abnormal": 0x80,
    "soft_rotor_lock": 0x40,
    "over_temperature": 0x20,
    "motor_self_test_abnormal": 0x10,
    "voltage_abnormal": 0x08,
    "motor_stall": 0x04,
    "over_current": 0x02,
    "motor_rotor_lock": 0x01,
}
SERVO_FLAGS = {
    "load_overload": 0x20,
    "over_current": 0x08,
    "over_temperature": 0x04,
    "magnetic_encoder_abnormal": 0x02,
    "voltage_abnormal": 0x01,
}
O30_FLAGS = {
    "hand_layer_stall": 0x01,
    "actuator_layer_stall": 0x02,
    "over_current": 0x04,
    "over_temperature": 0x08,
    "actuator_abnormal": 0x40,
    "actuator_offline": 0x80,
}


def o30_status(raw):
    return JointFaultStatus(
        raw=raw,
        reserved_bits=raw & 0x30,
        **{name: bool(raw & mask) for name, mask in O30_FLAGS.items()},
    )


def fault_sample(caps, status_type, raw):
    return FaultSample(
        raw=(raw,) * len(caps.joints),
        statuses=tuple(status_type(raw) for _ in caps.joints),
        meta=SampleMeta(
            sequence=7,
            collected_at=1.0,
            age_s=0.25,
            valid=True,
            stale=True,
            connection_generation=3,
            origin=DataOrigin.DEVICE_RESPONSE,
            within_declared_range=True,
        ),
    )


@pytest.mark.parametrize("raw", [0, *(1 << bit for bit in range(8)), 0xFF])
@pytest.mark.parametrize(
    "model,status_type,flags,reserved_mask",
    [
        ("L6", L6FaultStatus, L6_FLAGS, 0x80),
        ("L20", L20FaultStatus, L20_FLAGS, 0),
        ("L20Lite", L20LiteFaultStatus, SERVO_FLAGS, 0xD0),
        ("O6", O6FaultStatus, SERVO_FLAGS, 0xD0),
        ("O30", o30_status, O30_FLAGS, 0x30),
    ],
)
def test_fault_bits_round_trip_without_collapsing_model_meanings(
    raw, model, status_type, flags, reserved_mask
):
    caps = get_declared_capabilities(model, side="left")
    sample = fault_sample(caps, status_type, raw)
    message = fault_statuses_to_message(
        sample, caps.telemetry_channel(TelemetrySemantic.FAULTS), ros_now_ns=10**9
    )
    restored = deserialize_message(serialize_message(message), HandFaultStatusState)
    assert restored == message
    assert restored.joint_names == list(caps.joint_names)
    assert restored.meta.sequence == 7 and restored.meta.connection_generation == 3
    assert restored.meta.stale and restored.meta.valid
    for status in restored.statuses:
        assert status.raw == raw and status.reserved_bits == raw & reserved_mask
        assert set(status.supported_flags) == set(flags)
        assert status.descriptions == list(
            getattr(status_type(raw), "descriptions", ())
        )
        for name, kind in status.get_fields_and_field_types().items():
            if kind == "boolean":
                assert getattr(status, name) is bool(raw & flags.get(name, 0))


@pytest.mark.parametrize(
    "model,status_type,flags",
    [("L6", L6FaultStatus, L6_FLAGS), ("L20", L20FaultStatus, L20_FLAGS)],
)
def test_structured_fault_topic_preserves_raw_topic_and_change_detection(
    model, status_type, flags
):
    hand = HandDevice(model=model, side="left", transport=object())
    caps = hand.get_capabilities()
    sample = fault_sample(caps, status_type, 0xFF)
    snapshot = replace(hand.get_snapshot(), faults=sample)
    publisher = SnapshotPublisher(_RecordingNode(), caps).create()
    publisher.publish_snapshot(
        hand.get_snapshot(),
        ros_now_ns=10**9,
        angle_feedback_policy=AngleFeedbackPolicy.ADAPTIVE,
    )
    assert (
        publisher.publish_snapshot(
            snapshot,
            ros_now_ns=10**9,
            angle_feedback_policy=AngleFeedbackPolicy.ADAPTIVE,
        )
        == 2
    )
    raw = publisher._telemetry_publishers[TelemetrySemantic.FAULTS].messages[-1]
    decoded = publisher._fault_status_publisher.messages[-1]
    assert list(raw.raw) == [255.0] * len(caps.joints)
    assert all(set(status.supported_flags) == set(flags) for status in decoded.statuses)
    assert decoded.meta == raw.meta
    assert (
        publisher.publish_snapshot(
            snapshot,
            ros_now_ns=2 * 10**9,
            angle_feedback_policy=AngleFeedbackPolicy.ADAPTIVE,
        )
        == 0
    )
