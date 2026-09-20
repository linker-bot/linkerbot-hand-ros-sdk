"""Cross-model tactile publications retain physical-query identity and age."""

from dataclasses import replace

import pytest
from linkerbot_hand import (
    AngleFeedbackPolicy,
    DataOrigin,
    ForceFieldSample,
    HandDevice,
    SampleMeta,
    TactileMatrix,
    TelemetrySemantic,
    get_declared_capabilities,
)
from linkerbot_hand.api._force import merge_force_samples
from linkerbot_hand.protocols.base import SamplePayload
from linkerbot_hand.runtime._force_samples import build_force_sample
from linkerbot_hand_ros.conversion import (
    capabilities_to_message,
    force_field_to_message,
)
from linkerbot_hand_ros.state_publisher import SnapshotPublisher
from rclpy.serialization import deserialize_message, serialize_message
from test_state_publisher import _o30_force_sample

from linkerbot_hand_msgs.msg import HandForceField


def meta(sequence=1, *, age=0.0):
    return SampleMeta(
        sequence=sequence,
        collected_at=float(sequence),
        age_s=age,
        valid=True,
        stale=age > 0.1,
        connection_generation=1,
        origin=DataOrigin.DEVICE_RESPONSE,
        within_declared_range=True,
    )


class Recorder:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class Node:
    def __init__(self):
        self.publishers = {}

    def create_publisher(self, _type, topic, *_args, **_kwargs):
        publisher = Recorder()
        self.publishers[topic] = publisher
        return publisher

    create_lifecycle_publisher = create_publisher


def snapshot(caps, force):
    # HandDevice construction does no I/O.
    initial = HandDevice(
        model=caps.model,
        side=None if caps.model == "L30" else caps.side,
        transport=object(),
    ).get_snapshot()
    return replace(initial, force=force)


def publish(publisher, value):
    return publisher.publish_snapshot(
        value,
        ros_now_ns=10_000_000_000,
        angle_feedback_policy=AngleFeedbackPolicy.ADAPTIVE,
    )


@pytest.mark.parametrize("model", ["L6", "O6", "L20", "L20Lite", "L30", "O20"])
def test_all_matrix_models_publish_fn_without_fabricating_a_resultant(model):
    caps = get_declared_capabilities(model, side=None if model == "L30" else "left")
    telemetry = caps.telemetry_channel(TelemetrySemantic.FORCE)
    fingers, rows, columns = telemetry.shape
    matrices = tuple(
        TactileMatrix(
            name=name,
            rows=rows,
            columns=columns,
            raw=tuple((7,) * columns for _ in range(rows)),
        )
        for name in telemetry.channels
    )
    force = build_force_sample(
        SamplePayload(semantic=TelemetrySemantic.FORCE, tactile=matrices), meta(), caps
    )
    node = Node()
    publisher = SnapshotPublisher(node, caps)
    publish(publisher, snapshot(caps, force))
    message = node.publishers["~/state/force_fn"].messages[-1]
    assert message.name == "fn" and message.query_channel == "force"
    assert len(message.sensors) == fingers
    assert len(message.sensors[0].raw) == rows * columns
    assert set(message.sensors[0].raw) == {7}
    assert message.meta.sequence == force.fn.meta.sequence
    fns_publisher = node.publishers.get("~/state/force_fns")
    assert fns_publisher is None or not fns_publisher.messages


def test_lite_scalar_update_does_not_republish_or_restamp_matrix():
    caps = get_declared_capabilities("L20Lite", side="left")
    matrices = tuple(
        TactileMatrix(name=name, rows=12, columns=6, raw=((7,) * 6,) * 12)
        for name in caps.force_field("fn").sensor_names
    )
    fn = build_force_sample(
        SamplePayload(semantic=TelemetrySemantic.FORCE, tactile=matrices),
        meta(age=0.05),
        caps,
    )
    fns = build_force_sample(
        SamplePayload(semantic=TelemetrySemantic.FORCE_FNS, raw=(1, 2, 3, 4, 5)),
        meta(2),
        caps,
    )
    node = Node()
    publisher = SnapshotPublisher(node, caps)
    publish(publisher, snapshot(caps, fn))
    old = node.publishers["~/state/tactile"].messages[-1].meta
    aggregate = merge_force_samples(fn, fns)
    publish(publisher, snapshot(caps, aggregate))
    assert len(node.publishers["~/state/tactile"].messages) == 1
    assert len(node.publishers["~/state/force_fn"].messages) == 1
    scalar = node.publishers["~/state/force_fns"].messages[-1]
    assert [sensor.raw[0] for sensor in scalar.sensors] == [1, 2, 3, 4, 5]
    assert scalar.meta.sequence == 2 and old.sequence == 1
    publisher.reset()
    publish(publisher, snapshot(caps, aggregate))
    assert node.publishers["~/state/tactile"].messages[-1].meta == old
    # A scalar arriving before the first matrix must not fail legacy conversion.
    publish(SnapshotPublisher(Node(), caps), snapshot(caps, fns))


def test_o30_single_native_sample_publishes_fn_and_fns_with_same_metadata():
    caps = get_declared_capabilities("O30", side="left")
    native = _o30_force_sample(meta())
    force = build_force_sample(
        SamplePayload(semantic=TelemetrySemantic.FORCE, sensors=native.sensors),
        meta(),
        caps,
    )
    node = Node()
    publisher = SnapshotPublisher(node, caps)
    publish(publisher, snapshot(caps, force))
    fn = node.publishers["~/state/force_fn"].messages[-1]
    fns = node.publishers["~/state/force_fns"].messages[-1]
    assert fn.meta == fns.meta and fn.query_channel == fns.query_channel == "force"
    assert len(fn.sensors[0].raw) == 70 and len(fns.sensors[0].raw) == 1
    assert fn.sensors[0].unit == fns.sensors[0].unit == "g"
    assert publish(publisher, snapshot(caps, force)) == 0
    declared = capabilities_to_message(caps)
    assert all(not field.support_known for field in declared.force_fields)
    observed = replace(
        caps, tactile_sensors=tuple(sensor.metadata for sensor in native.sensors)
    )
    known = {
        field.name: field for field in capabilities_to_message(observed).force_fields
    }
    assert known["fn"].supported and known["fns"].supported
    assert not known["px"].supported and known["px"].support_known
    assert set(known["fn"].shared_fields) == {"fn", "fns"}


def test_missing_sensor_and_invalid_direction_are_not_replaced_with_zero():
    field = ForceFieldSample(
        name="fds",
        sensor_names=("thumb", "index"),
        raw=((255,), None),
        units=(None, None),
        encodings=("u8", None),
        valid_values=((False,), None),
        meta=meta(),
        query_channel="force_fds",
    )
    message = force_field_to_message(field, ros_now_ns=1)
    restored = deserialize_message(serialize_message(message), HandForceField)
    assert restored == message
    assert list(restored.sensors[0].raw) == [255]
    assert list(restored.sensors[0].valid_values) == [False]
    assert not restored.sensors[1].present and not restored.sensors[1].raw
