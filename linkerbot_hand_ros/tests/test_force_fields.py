"""Cross-model tactile publications retain physical-query identity and age."""

from dataclasses import replace
from struct import pack

import pytest
from linkerbot_hand import (
    AngleFeedbackPolicy,
    DataOrigin,
    ForceFieldSample,
    HandDevice,
    PollingPlan,
    SampleMeta,
    TactileMatrix,
    TactileSensorMetadata,
    TactileSensorSample,
    TelemetrySemantic,
    UnsupportedOperationError,
    get_declared_capabilities,
)
from linkerbot_hand.api._force import merge_force_samples
from linkerbot_hand.capabilities.polling import resolve_poll_rates
from linkerbot_hand.protocols.base import SamplePayload
from linkerbot_hand.protocols.o30.sensors import (
    decode_tactile_fields,
    parse_tactile_descriptor,
)
from linkerbot_hand.runtime._force_samples import build_force_sample
from linkerbot_hand_ros.conversion import (
    capabilities_to_message,
    force_field_to_message,
    force_sample_to_messages,
)
from linkerbot_hand_ros.state_publisher import SnapshotPublisher
from rclpy.serialization import deserialize_message, serialize_message
from test_state_publisher import _o30_force_sample

from linkerbot_hand_msgs.msg import HandForceField, HandTactileSensorState


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
    publisher = SnapshotPublisher(node, caps).create()
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
    publisher = SnapshotPublisher(node, caps).create()
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
    publish(SnapshotPublisher(Node(), caps).create(), snapshot(caps, fns))


def test_o30_single_native_sample_publishes_fn_and_fns_with_same_metadata():
    caps = get_declared_capabilities("O30", side="left")
    native = _o30_force_sample(meta())
    force = build_force_sample(
        SamplePayload(semantic=TelemetrySemantic.FORCE, sensors=native.sensors),
        meta(),
        caps,
    )
    node = Node()
    publisher = SnapshotPublisher(node, caps).create()
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


def o30_tashan_sample(metadata, *, side="left", missing=()):
    """Use production descriptor decoding for one-value TASHAN fields."""
    caps = get_declared_capabilities("O30", side=side)
    descriptor = "Fn_F32_1;Ft_F32_1;Fd_U16_1;Px_U32_1"
    descriptors = parse_tactile_descriptor(descriptor, total_data_length=14)
    sensors = []
    values = (
        (0.0, 0.0, 0, 0),
        (0.0, 0.0, 65535, 0),
        (1.25, 0.5, 281, 129),
        (2.5, 0.25, 90, 7),
        (3.75, 1.0, 360, 4294967295),
    )
    for selected, (name, scalars) in enumerate(
        zip(("thumb", "index", "middle", "ring", "pinky"), values, strict=True),
        start=1,
    ):
        present = name not in missing
        raw = pack("<ffHI", *scalars) if present else b""
        sensor = TactileSensorMetadata(
            selected_sensor=selected,
            sensor_name=name,
            sensor_type="TASHAN_GATHER" if present else "NO_SENSOR",
            data_unit="N" if present else None,
            data_range=20 if present else 0,
            maximum_rows=0,
            maximum_columns=0,
            requested_rows=0,
            requested_columns=0,
            valid_data_position_mode=False,
            rectangle_fill=False,
            descriptor_text=descriptor if present else None,
            field_descriptors=descriptors if present else (),
            total_data_length=len(raw),
        )
        sensors.append(
            TactileSensorSample(
                metadata=sensor,
                raw_data=raw,
                fields=decode_tactile_fields(descriptors, raw) if present else (),
            )
        )
    observed = replace(
        caps, tactile_sensors=tuple(sensor.metadata for sensor in sensors)
    )
    force = build_force_sample(
        SamplePayload(semantic=TelemetrySemantic.FORCE, sensors=tuple(sensors)),
        metadata,
        observed,
    )
    return observed, force


@pytest.mark.parametrize("side", ["left", "right"])
def test_tashan_scalar_fields_share_metadata_and_preserve_native_values(side):
    caps, force = o30_tashan_sample(meta(7, age=0.05), side=side)
    node = Node()
    publisher = SnapshotPublisher(node, caps).create()
    publish(publisher, snapshot(caps, force))
    messages = [
        node.publishers[f"~/state/force_{name}"].messages[-1]
        for name in ("fn", "ft", "fd", "px")
    ]
    for message in messages:
        restored = deserialize_message(serialize_message(message), HandForceField)
        assert restored == message
        assert message.query_channel == "force"
        assert message.meta == messages[0].meta
        assert message.meta.sequence == 7 and message.meta.connection_generation == 1
        assert message.meta.valid and not message.meta.stale
        assert len(message.sensors) == 5
        assert all(
            sensor.present and len(sensor.raw) == 1 for sensor in message.sensors
        )
    fn, ft, fd, px = messages
    assert (
        list(fn.sensors[0].raw)
        == list(ft.sensors[0].raw)
        == list(px.sensors[0].raw)
        == [0.0]
    )
    assert (
        list(fn.sensors[0].valid_values) == list(ft.sensors[0].valid_values) == [True]
    )
    assert fn.sensors[0].unit == ft.sensors[0].unit == "N"
    assert list(fd.sensors[1].raw) == [65535.0] and fd.sensors[1].encoding == "U16"
    assert all(sensor.unit == "" for message in (fd, px) for sensor in message.sensors)
    assert list(px.sensors[-1].raw) == [4294967295.0]
    assert px.sensors[-1].encoding == "U32"
    # Direction validity comes from the SDK, not an invented ROS angle/sentinel rule.
    assert list(fd.sensors[1].valid_values) == list(force.fd.valid_values[1])
    native = node.publishers["~/state/tactile_sensors"].messages[-1]
    native = deserialize_message(serialize_message(native), HandTactileSensorState)
    assert native.meta == fn.meta
    for sensor, original in zip(native.sensors, force.sensors, strict=True):
        assert bytes(sensor.raw_bytes) == original.raw_data
        assert sensor.descriptor == original.metadata.descriptor_text
        assert all(
            field.element_count == field.component_count == 1 for field in sensor.fields
        )
    assert force.fns is None
    assert not node.publishers["~/state/normal_force_resultant"].messages
    fns_publisher = node.publishers.get("~/state/force_fns")
    assert fns_publisher is None or not fns_publisher.messages
    assert publish(publisher, snapshot(caps, force)) == 0


def test_tashan_descriptor_capabilities_and_shared_polling_follow_actual_fields():
    declared = capabilities_to_message(get_declared_capabilities("O30", side="left"))
    assert all(not field.support_known for field in declared.force_fields)
    caps, force = o30_tashan_sample(meta())
    known = {field.name: field for field in capabilities_to_message(caps).force_fields}
    supported = {"fn", "ft", "fd", "px"}
    for name, field in known.items():
        assert field.support_known
        assert field.supported == (name in supported)
        assert set(field.shared_fields) == supported
        if field.supported:
            assert field.sensor_names == [
                sensor.metadata.sensor_name for sensor in force.sensors
            ]
    rates = resolve_poll_rates(
        PollingPlan(force_fn_hz=10, force_ft_hz=20, force_fd_hz=15, force_px_hz=5), caps
    )
    assert rates == {TelemetrySemantic.FORCE: 20}
    with pytest.raises(UnsupportedOperationError):
        resolve_poll_rates(PollingPlan(force_fns_hz=1), caps)


@pytest.mark.parametrize("missing", [("index",), ("thumb", "ring")])
def test_tashan_missing_sensor_stays_absent_in_field_and_descriptor_messages(missing):
    caps, force = o30_tashan_sample(meta(), missing=missing)
    node = Node()
    publish(SnapshotPublisher(node, caps).create(), snapshot(caps, force))
    native = node.publishers["~/state/tactile_sensors"].messages[-1]
    native = deserialize_message(serialize_message(native), HandTactileSensorState)
    for name in ("fn", "ft", "fd", "px"):
        message = node.publishers[f"~/state/force_{name}"].messages[-1]
        for sensor, descriptor_sensor in zip(
            message.sensors, native.sensors, strict=True
        ):
            assert sensor.sensor_name == descriptor_sensor.finger_name
            assert sensor.present == descriptor_sensor.available
            if sensor.sensor_name in missing:
                assert not sensor.present and not sensor.raw and not sensor.valid_values
                assert not descriptor_sensor.raw_bytes and not descriptor_sensor.fields
            else:
                assert sensor.present and len(sensor.raw) == 1
                assert descriptor_sensor.sensor_type == "TASHAN_GATHER"
                assert len(descriptor_sensor.raw_bytes) == 14
                assert len(descriptor_sensor.fields) == 4
                assert all(
                    field.element_count == 1 for field in descriptor_sensor.fields
                )
    assert (
        force_sample_to_messages(
            force,
            caps.telemetry_channel(TelemetrySemantic.FORCE),
            ros_now_ns=10_000_000_000,
        ).force_resultant
        is None
    )


def test_tashan_after_matrix_sample_does_not_republish_old_fns_or_reshape_scalars():
    caps = get_declared_capabilities("O30", side="left")
    native = _o30_force_sample(meta())
    matrix = build_force_sample(
        SamplePayload(semantic=TelemetrySemantic.FORCE, sensors=native.sensors),
        meta(),
        caps,
    )
    node = Node()
    publisher = SnapshotPublisher(node, caps).create()
    publish(publisher, snapshot(caps, matrix))
    assert len(node.publishers["~/state/force_fns"].messages) == 1
    assert len(node.publishers["~/state/normal_force_resultant"].messages) == 1
    observed, scalar = o30_tashan_sample(meta(2))
    merged = merge_force_samples(matrix, scalar)
    assert merged.fns is None
    publisher.publish_capabilities(observed)
    publish(publisher, snapshot(observed, merged))
    assert len(node.publishers["~/state/force_fns"].messages) == 1
    assert len(node.publishers["~/state/normal_force_resultant"].messages) == 1
    fn = node.publishers["~/state/force_fn"].messages[-1]
    assert fn.meta.sequence == 2
    assert all(len(sensor.raw) == 1 for sensor in fn.sensors)


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
