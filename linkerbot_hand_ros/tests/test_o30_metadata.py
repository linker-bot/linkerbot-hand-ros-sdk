"""SDK metadata must survive ROSIDL conversion and serialization."""

from dataclasses import replace

import pytest
from linkerbot_hand import (
    DeviceInfo,
    HandSide,
    TactileSensorSample,
    TelemetrySemantic,
    VersionField,
)
from linkerbot_hand_ros.conversion import (
    capabilities_to_message,
    device_info_to_message,
    force_sample_to_messages,
)
from rclpy.serialization import deserialize_message, serialize_message
from test_message_conversion import ROS_NOW_NS, _capabilities, _meta, _o30_force_sample


def roundtrip(message):
    return deserialize_message(serialize_message(message), type(message))


@pytest.mark.parametrize("present", [False, True])
def test_extended_identity_presence_values_and_version_bytes_are_preserved(present):
    values = {
        "protocol_name": "HOP",
        "protocol_version": "0.0.4",
        "power_supply_range": "12V~24V",
        "microcontroller_uid": "TEST-UID",
        "build_time": "2026-09-17 10:00:00",
        "supported_interfaces": "CAN、串口",
    }
    versions = {
        "adapter_board_version": "V1.1.0",
        "control_board_version": "V1.2.0",
        "bootloader_version": "V1.3.0",
    }
    if not present:
        values = dict.fromkeys(values)
        versions = dict.fromkeys(versions)
    reported_side = HandSide.LEFT if present else None
    capabilities = _capabilities("O30")
    capabilities = replace(
        capabilities,
        identity=replace(
            capabilities.identity, **values, **versions, reported_side=reported_side
        ),
    )
    capability_msg = roundtrip(capabilities_to_message(capabilities)).identity
    for field, expected in {**values, **versions}.items():
        assert getattr(capability_msg, f"has_{field}") is present
        assert getattr(capability_msg, field) == (expected or "")
    assert capability_msg.has_reported_side is present
    assert capability_msg.reported_side == ("left" if present else "")

    info = DeviceInfo(
        model="O30",
        serial_number=None,
        pcb_version=None,
        firmware_version=None,
        mechanical_version=None,
        product_code=None,
        sensor_variant=None,
        side=HandSide.LEFT,
        raw_identity=b"identity",
        meta=_meta(),
        **values,
        reported_side=reported_side,
        **{
            field: None
            if value is None
            else VersionField(raw=value.encode(), text=value)
            for field, value in versions.items()
        },
    )
    info_msg = roundtrip(device_info_to_message(info, ros_now_ns=ROS_NOW_NS))
    for field, expected in values.items():
        assert getattr(info_msg, f"has_{field}") is present
        assert getattr(info_msg, field) == (expected or "")
    for field, expected in versions.items():
        version = getattr(info_msg, field)
        assert version.available is present
        assert version.text == (expected or "")
        assert bytes(version.raw_bytes) == (expected.encode() if expected else b"")
    assert info_msg.has_reported_side is present
    assert info_msg.reported_side == ("left" if present else "")


def test_window_metadata_does_not_reshape_actual_fields_and_absence_is_explicit():
    sample = _o30_force_sample()
    sensors = list(sample.sensors)
    sensors[0] = replace(
        sensors[0],
        metadata=replace(
            sensors[0].metadata,
            requested_rows=5,
            requested_columns=3,
            valid_data_position_mode=True,
            rectangle_fill=True,
        ),
    )
    sensors[1] = TactileSensorSample(
        metadata=replace(
            sensors[1].metadata,
            sensor_type="NO_SENSOR",
            descriptor_text=None,
            field_descriptors=(),
            total_data_length=0,
        ),
        raw_data=b"",
        fields=(),
    )
    messages = force_sample_to_messages(
        replace(sample, sensors=tuple(sensors)),
        _capabilities("O30").telemetry_channel(TelemetrySemantic.FORCE),
        ros_now_ns=ROS_NOW_NS,
    )
    state = roundtrip(messages.tactile_sensors)
    thumb, index = state.sensors[:2]
    assert thumb.available and thumb.selected_sensor == 1
    assert (thumb.maximum_rows, thumb.maximum_columns) == (10, 7)
    assert (thumb.requested_rows, thumb.requested_columns) == (5, 3)
    assert thumb.valid_data_position_mode and thumb.rectangle_fill
    assert len(thumb.fields[1].values) == 70
    assert bytes(thumb.raw_bytes) == sample.sensors[0].raw_data
    assert not index.available and index.selected_sensor == 2
    assert not index.raw_bytes and not index.fields
    assert index.finger_name == "index"
    assert messages.force_resultant is None
