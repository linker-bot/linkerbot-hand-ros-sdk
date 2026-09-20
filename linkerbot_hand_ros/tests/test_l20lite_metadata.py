"""SDK extensions must not break existing ROS capability/state publication."""

import linkerbot_hand as sdk
import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand_ros.conversion import (
    capabilities_to_message,
    fault_statuses_to_message,
)
from linkerbot_hand_ros.node import LinkerbotHandNode
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.parameter import Parameter
from rclpy.serialization import deserialize_message, serialize_message
from test_force_fields import meta

from linkerbot_hand_msgs.msg import HandFaultStatusState


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


def test_l20lite_post_stall_torque_does_not_claim_current_support():
    caps = sdk.get_declared_capabilities("L20Lite", side="left")
    if caps.stall_protection is None:
        pytest.skip("requires SDK with L20Lite stall settings")
    message = capabilities_to_message(caps)
    stall = message.stall_protection
    assert stall.supported and stall.has_hold_torque and not stall.has_hold_current
    assert stall.hold_torque.semantic == "stall_hold_torques"
    assert stall.hold_torque.write_supported and not stall.hold_torque.read_supported
    assert not stall.hold_current.write_supported


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
        assert node.resolve_service_name("~/set_stall_hold_currents") not in services
        assert node.resolve_service_name("~/get_stall_protection") not in services
        assert node.resolve_service_name("~/clear_faults") not in services
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
