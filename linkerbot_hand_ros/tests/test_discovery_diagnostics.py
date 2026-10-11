"""Error locations and original causes survive discovery and ROS activation."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import rclpy
import yaml
from fakes_v1 import DeviceBuilder
from launch import LaunchContext
from launch.substitutions import TextSubstitution
from linkerbot_hand import HandSide, IdentityMismatchError, ValidationError
from linkerbot_hand.discovery import DiscoveryConfig, DiscoveryFailure
from linkerbot_hand_ros.discovery_deployment import load_deployment, select_hands
from linkerbot_hand_ros.discovery_diagnostics import (
    candidate_context,
    exception_details,
    failure_context,
)
from linkerbot_hand_ros.discovery_launch import _settings
from linkerbot_hand_ros.node import LinkerbotHandNode
from rclpy.exceptions import InvalidNamespaceException
from rclpy.lifecycle import TransitionCallbackReturn
from test_discovery_startup import _candidate, _partial, _report, _save_one

from linkerbot_hand_ros import discovery_launch


def test_candidate_context_retains_nondefault_fd_endpoint_and_node_id():
    o30 = _candidate("O30", HandSide.RIGHT)
    assert "request_id=0x17" in candidate_context(o30)
    assert "response_id=0x417" in candidate_context(o30)
    assert "node_id=13" in candidate_context(_candidate("L30"))


@pytest.mark.parametrize(
    "code",
    ["unavailable", "busy", "layout", "unsupported_protocol", "scan_timeout"],
)
def test_enumeration_failure_keeps_backend_native_channel_and_code(code):
    failure = DiscoveryFailure(
        "enumerate_minicanfd",
        code,
        "native library detail",
        "OSError",
        backend="minicanfd",
        native_channel="3:0",
    )
    messages = []
    select_hands(
        DiscoveryConfig(),
        scan=lambda _: _report(_candidate(), failures=(failure,)),
        emit=messages.append,
    )
    diagnostic = next(m for m in messages if f"discovery {code}:" in m)
    for value in (
        "backend=minicanfd",
        "native_channel='3:0'",
        "enumerate_minicanfd",
        "OSError",
        "native library detail",
    ):
        assert value in diagnostic


def test_probe_cleanup_failure_identifies_protocol_channel_and_original_cause():
    candidate = _candidate("L30", channel="minicanfd:2:1", provider="minicanfd")
    cleanup = Mock(side_effect=OSError("USB close refused"))
    failure = DiscoveryFailure(
        "close_probe",
        "transport_error",
        "probe close failed",
        "OSError",
        channel=candidate.channel,
        wire_protocol=candidate.wire_protocol,
        cleanup=cleanup,
    )
    with pytest.raises(ValidationError) as caught:
        select_hands(
            DiscoveryConfig(),
            scan=lambda _: _report(candidate, failures=(failure,)),
            emit=lambda _: None,
        )
    for value in (
        "cleanup incomplete",
        "minicanfd:2:1",
        "backend=minicanfd",
        "protocol=can_fd",
        "USB close refused",
    ):
        assert value in str(caught.value)
    assert cleanup.call_count == 2
    assert "native_channel" not in failure_context(failure)


def test_partial_details_and_endpoint_do_not_construct_the_device():
    factory = Mock(side_effect=AssertionError("diagnostics must not construct"))
    candidate = _candidate("L30", channel="can8", factory=factory)
    messages = []
    select_hands(
        DiscoveryConfig(),
        scan=lambda _: _report(_candidate(), _partial(candidate)),
        emit=messages.append,
    )
    detail = next(m for m in messages if "can8: " in m)
    for value in (
        "missing_side: side unavailable",
        "node_id=13",
        "request_id=0x17",
        "protocol=can_fd",
    ):
        assert value in detail
    factory.assert_not_called()


def test_scan_exception_preserves_type_object_cause_and_selected_scope():
    error = RuntimeError("adapter enumeration failed")
    error.__cause__ = PermissionError("access denied")
    messages = []
    with pytest.raises(RuntimeError) as caught:
        select_hands(
            DiscoveryConfig(backends=("pcan",), channels=("pcan:PCAN_USBBUS1",)),
            scan=Mock(side_effect=error),
            emit=messages.append,
        )
    assert caught.value is error
    assert "pcan:PCAN_USBBUS1" in messages[0]
    assert "cause=PermissionError: access denied" in messages[-1]


def test_cause_formatter_handles_cycles_and_multiline_native_messages():
    error = IdentityMismatchError("wrong fingerprint")
    cause = OSError("line one\nline two")
    error.__cause__ = cause
    cause.__cause__ = error
    detail = exception_details(error)
    assert detail.startswith("[identity_mismatch]")
    assert "cause=OSError: line one\\nline two" in detail
    assert detail.count("wrong fingerprint") == 1


def test_sdk_cause_property_and_operation_context_are_retained():
    error = IdentityMismatchError(
        "identity changed",
        operation="open",
        model="O30",
        generation=7,
        cause=OSError("native USB error"),
    )
    detail = exception_details(error)
    for value in (
        "[identity_mismatch]",
        "operation='open'",
        "model='O30'",
        "generation=7",
        "cause=OSError: native USB error",
    ):
        assert value in detail


def test_deployment_error_identifies_file_list_index_and_role(tmp_path):
    path = tmp_path / "hands.yaml"
    _save_one(tmp_path)
    document = yaml.safe_load(path.read_text())
    document["hands"][0]["parameters"]["angles_hz"] = -1.0
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(ValidationError) as caught:
        load_deployment(path)
    detail = exception_details(caught.value)
    assert str(path) in detail
    assert "hands[0]" in detail and "namespace='/l6l'" in detail
    assert "angles_hz" in detail


@pytest.mark.parametrize("namespace", ["/right-hand", "/right hand"])
def test_invalid_namespace_keeps_file_role_index_and_rclpy_cause_before_launch(
    tmp_path, monkeypatch, namespace
):
    config_root = Path(__file__).parents[1] / "config"
    document = yaml.safe_load((config_root / "deployment-dual.yaml").read_text())
    document["hands"][1]["namespace"] = namespace
    path = tmp_path / "invalid-roles.yaml"
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(ValidationError) as caught:
        load_deployment(path)
    detail = exception_details(caught.value)
    for value in (
        str(path),
        "hands[1]",
        f"namespace={namespace!r}",
        "cause=InvalidNamespaceException",
    ):
        assert value in detail
    assert isinstance(
        caught.value.__cause__.__cause__.__cause__, InvalidNamespaceException
    )

    node = Mock(
        side_effect=AssertionError("invalid configuration must not create nodes")
    )
    monkeypatch.setattr(discovery_launch, "Node", node)
    context = LaunchContext()
    context.launch_configurations["config"] = str(path)
    context.launch_configurations["discover"] = "false"
    with pytest.raises(ValidationError) as launch_error:
        discovery_launch.build_multi_launch(
            context, default_config=TextSubstitution(text="unused")
        )
    assert str(path) in str(launch_error.value) and "hands[1]" in str(
        launch_error.value
    )
    node.assert_not_called()


def test_advanced_config_error_identifies_input_file(tmp_path):
    path = tmp_path / "pcan.yaml"
    path.write_text("pcan:\n  unknown_option: 1\n")
    context = LaunchContext()
    context.launch_configurations["discovery_config"] = str(path)
    with pytest.raises(ValidationError) as caught:
        _settings(context)
    assert f"discovery_config={path}" in str(caught.value)
    assert "unknown_option" in str(caught.value)


def test_missing_saved_role_reports_expected_endpoint_and_identity(tmp_path):
    path = tmp_path / "hands.yaml"
    _save_one(tmp_path)
    deployment = load_deployment(path)
    replacement = _candidate()
    replacement = replace(
        replacement, identity=replace(replacement.identity, serial_number="replacement")
    )
    with pytest.raises(ValidationError) as caught:
        select_hands(
            deployment.discovery,
            deployment=deployment,
            scan=lambda _: _report(replacement),
            emit=lambda _: None,
        )
    assert "/l6l matched 0" in str(caught.value)
    assert "serial-can0" in str(caught.value)
    assert "request_id" in str(caught.value)


def test_real_lifecycle_error_names_role_endpoint_code_and_cause(monkeypatch):
    rclpy.init()
    builder = DeviceBuilder()
    error = IdentityMismatchError("wrong fingerprint")
    error.__cause__ = OSError("native device changed")
    builder.next_open_error = error
    candidate = _candidate()
    node = LinkerbotHandNode(
        device_factory=builder, discovery_candidate=candidate, namespace="/left_hand"
    )
    messages = []
    logger = node.get_logger()
    monkeypatch.setattr(
        node,
        "get_logger",
        lambda: SimpleNamespace(info=logger.info, error=messages.append),
    )
    try:
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        assert node.trigger_activate() == TransitionCallbackReturn.FAILURE
        detail = next(m for m in messages if m.startswith("activate failed:"))
        for value in (
            "[identity_mismatch]",
            "node=/left_hand/linkerbot_hand",
            "channel='can0'",
            "request_id=0x17",
            "cause=OSError: native device changed",
        ):
            assert value in detail
        assert not node._active
    finally:
        node.trigger_cleanup()
        node.destroy_node()
        rclpy.try_shutdown()
