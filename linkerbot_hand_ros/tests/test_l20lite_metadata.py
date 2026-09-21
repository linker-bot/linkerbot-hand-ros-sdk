"""SDK extensions must not break existing ROS capability/state publication."""

from dataclasses import replace

import linkerbot_hand as sdk
import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand_ros.conversion import (
    capabilities_to_message,
    fault_statuses_to_message,
    stall_protection_to_message,
)
from linkerbot_hand_ros.node import LinkerbotHandNode
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.parameter import Parameter
from rclpy.serialization import deserialize_message, serialize_message
from test_force_fields import meta

from linkerbot_hand_msgs.msg import (
    HandCapabilities,
    HandFaultStatusState,
    HandStallProtectionState,
    SampleMetadata,
)


def test_l20lite_fault_layout_preserves_unsupported_flags_and_explanations():
    status_type = getattr(sdk, "L20LiteFaultStatus", None)
    if status_type is None:
        pytest.skip("requires SDK with L20Lite fault decoding")
    caps = sdk.get_declared_capabilities("L20Lite", side="left")
    raw = (0, 1, 2, 4, 8, 32, 16, 64, 128, 255)
    sample = sdk.FaultSample(
        raw=raw, meta=meta(), statuses=tuple(status_type(value) for value in raw)
    )
    message = fault_statuses_to_message(
        sample, caps.telemetry_channel(sdk.TelemetrySemantic.FAULTS), ros_now_ns=1
    )
    restored = deserialize_message(serialize_message(message), HandFaultStatusState)
    assert restored == message
    assert restored.statuses[1].voltage_abnormal
    assert not restored.statuses[1].hand_layer_stall
    assert "hand_layer_stall" not in restored.statuses[1].supported_flags
    assert "voltage_abnormal" in restored.statuses[1].supported_flags
    assert restored.statuses[-1].reserved_bits == 0xD0
    assert "Overvoltage or undervoltage" in restored.statuses[1].descriptions
    assert not capabilities_to_message(caps).operations.clear_faults


def test_l20lite_post_stall_current_has_write_only_capability():
    caps = sdk.get_declared_capabilities("L20Lite", side="left")
    if caps.stall_protection is None:
        pytest.skip("requires SDK with L20Lite stall settings")
    message = capabilities_to_message(caps)
    stall = message.stall_protection
    assert deserialize_message(serialize_message(message), HandCapabilities) == message
    assert stall.supported and stall.has_hold_current
    assert stall.hold_current.semantic == "stall_hold_currents"
    assert stall.hold_current.write_supported and not stall.hold_current.read_supported
    assert stall.hold_current.raw_unit == "count"
    assert not hasattr(stall, "hold_torque")


def test_l20lite_stall_write_echoes_preserve_raw_current_and_metadata():
    hand = sdk.HandDevice(model="L20Lite", side="left", transport=object())
    caps = hand.get_capabilities()
    echo_meta = replace(meta(), origin=sdk.DataOrigin.DEVICE_CONFIG_RESPONSE)
    snapshot = replace(
        hand.get_snapshot(),
        stall_detection_times=sdk.StallDetectionTimeSample(
            raw=(1,) * 10, meta=echo_meta
        ),
        stall_thresholds=sdk.StallThresholdSample(raw=(2,) * 10, meta=echo_meta),
        stall_hold_currents=sdk.StallHoldCurrentSample(
            raw=tuple(range(10)), meta=echo_meta
        ),
    )
    message = stall_protection_to_message(snapshot, caps, ros_now_ns=1)
    restored = deserialize_message(serialize_message(message), HandStallProtectionState)
    assert restored == message
    assert restored.hold_currents.semantic == "stall_hold_currents"
    assert list(restored.hold_currents.raw) == list(range(10))
    assert restored.hold_currents.raw_unit == "count"
    assert (
        restored.hold_currents.meta.origin
        == SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE
    )
    assert restored.hold_currents.meta.sequence == echo_meta.sequence
    assert not restored.hold_currents.device_queried
    assert not restored.hold_currents.device_measured


def test_l20lite_configure_only_exposes_supported_management_commands():
    caps = sdk.get_declared_capabilities("L20Lite", side="left")
    if caps.stall_protection is None:
        pytest.skip("requires SDK with L20Lite stall settings")
    rclpy.init()
    node = LinkerbotHandNode(device_factory=DeviceBuilder())
    try:
        assert node.set_parameters_atomically(
            [Parameter("model", value="L20Lite"), Parameter("side", value="left")]
        ).successful
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        services = {
            node.resolve_service_name(service.srv_name)
            for service in node._interfaces.management._services
        }
        assert node.resolve_service_name("~/set_stall_thresholds") in services
        assert node.resolve_service_name("~/set_stall_detection_times") in services
        assert node.resolve_service_name("~/set_stall_hold_currents") in services
        assert node.resolve_service_name("~/get_stall_protection") not in services
        assert node.resolve_service_name("~/clear_faults") not in services
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
