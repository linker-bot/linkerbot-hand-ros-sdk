import math

import pytest
from linkerbot_hand import (
    AngleFeedbackPolicy,
    HandSide,
    UnsupportedFirmwareError,
    UnsupportedOperationError,
    ValidationError,
)
from linkerbot_hand_ros.driver_config import (
    DriverConfiguration,
    read_driver_configuration,
)
from linkerbot_hand_ros.transport_config import (
    PythonCANConfiguration,
    SocketCANConfiguration,
    VendorCANFDConfiguration,
    parse_transport_configuration,
)


def _parameters(**overrides):
    values = {
        "model": "l6",
        "side": "left",
        "transport_json": '{"backend":"socketcan","channel":"can0"}',
        "command_rate_hz": 250.0,
        "discrete_queue_capacity": 16,
        "mailbox_capacity": 256,
        "route_queue_capacity": 256,
        "identity_timeout_s": 0.2,
        "transaction_timeout_s": 0.0,
        "shutdown_timeout_s": 2.0,
        "auto_reconnect": False,
        "reconnect_initial_delay_s": 0.1,
        "reconnect_max_delay_s": 2.0,
        "recovery_max_attempts": 3,
        "recovery_timeout_s": 5.0,
        "recovery_retry_delay_s": 0.2,
        "publish_rate_hz": 100.0,
        "diagnostic_rate_hz": 1.0,
        "angles_hz": 100.0,
        "angle_feedback": "adaptive",
        "speeds_hz": 0.0,
        "force_hz": 0.0,
        **{
            f"force_{name}_hz": 0.0
            for name in ("fn", "fns", "ft", "fts", "fd", "fds", "px")
        },
        "temperature_hz": 0.0,
        "current_hz": 0.0,
        "faults_hz": 0.0,
        "torques_hz": 0.0,
        "voltage_hz": 0.0,
    }
    values.update(overrides)
    return values


def test_configuration_uses_declared_sdk_capabilities_as_source_of_truth():
    configuration = read_driver_configuration(
        _parameters(model="O6", side="right", force_hz=30.0).__getitem__
    )

    assert isinstance(configuration, DriverConfiguration)
    assert configuration.model == "O6"
    assert configuration.side == "right"
    assert configuration.declared_capabilities.side is HandSide.RIGHT
    assert configuration.declared_capabilities.identity.verified is False
    assert configuration.polling_plan.angles_hz == 100.0
    assert configuration.polling_plan.force_hz == 30.0
    assert configuration.polling_plan.angle_feedback is AngleFeedbackPolicy.ADAPTIVE
    assert configuration.device_config.transaction_timeout_s is None
    assert configuration.device_config.recovery_max_attempts == 3
    assert configuration.device_config.recovery_timeout_s == 5.0
    assert configuration.device_config.recovery_retry_delay_s == 0.2


@pytest.mark.parametrize(
    "name, value",
    [
        ("recovery_max_attempts", 1),
        ("recovery_timeout_s", 2.5),
        ("recovery_retry_delay_s", 0.1),
    ],
)
def test_recovery_policy_values_reach_sdk(name, value):
    configuration = read_driver_configuration(_parameters(**{name: value}).__getitem__)
    assert getattr(configuration.device_config, name) == value


@pytest.mark.parametrize(
    "name", ("recovery_max_attempts", "recovery_timeout_s", "recovery_retry_delay_s")
)
@pytest.mark.parametrize("value", (0, -1, True, math.nan, math.inf, None))
def test_recovery_policy_rejects_invalid_values(name, value):
    with pytest.raises(ValidationError, match=name):
        read_driver_configuration(_parameters(**{name: value}).__getitem__)


@pytest.mark.parametrize(
    "value, expected", [(0.0, None), (0, None), (0.1, 0.1), (1, 1.0)]
)
def test_transaction_timeout_preserves_protocol_defaults_or_explicit_override(
    value, expected
):
    configuration = read_driver_configuration(
        _parameters(transaction_timeout_s=value).__getitem__
    )

    assert configuration.device_config.transaction_timeout_s == expected
    assert configuration.device_config.identity_timeout_s == 0.2


@pytest.mark.parametrize("value", [True, False, -1.0, math.nan, math.inf, "0.1", None])
def test_transaction_timeout_rejects_invalid_values(value):
    with pytest.raises(ValidationError, match="transaction_timeout_s"):
        read_driver_configuration(_parameters(transaction_timeout_s=value).__getitem__)


@pytest.mark.parametrize(
    "model, canonical, joint_count",
    [
        ("L20", "L20", 16),
        ("l20", "L20", 16),
        ("O30", "O30", 20),
        ("o30", "O30", 20),
        ("l20-lite", "L20Lite", 10),
    ],
)
def test_configuration_normalizes_public_model_spellings(model, canonical, joint_count):
    configuration = read_driver_configuration(
        _parameters(model=model, side="left").__getitem__
    )

    assert configuration.model == canonical
    assert configuration.declared_capabilities.model == canonical
    assert len(configuration.declared_capabilities.joints) == joint_count


@pytest.mark.parametrize("model", ("O30i", "o30i", "L25", "l25"))
def test_configuration_rejects_historical_model_names(model):
    with pytest.raises(ValidationError, match="unsupported hand model"):
        read_driver_configuration(_parameters(model=model).__getitem__)


def test_l30_requires_an_empty_side_parameter():
    configuration = read_driver_configuration(
        _parameters(model="l30", side="").__getitem__
    )

    assert configuration.model == "L30"
    assert configuration.side is None
    assert configuration.declared_capabilities.side is HandSide.NOT_APPLICABLE

    with pytest.raises(ValidationError, match="L30 must not specify side"):
        read_driver_configuration(_parameters(model="l30", side="left").__getitem__)


def test_configuration_rejects_polling_not_supported_by_capability():
    with pytest.raises(UnsupportedOperationError, match="cannot poll speeds"):
        read_driver_configuration(_parameters(speeds_hz=1.0).__getitem__)


def test_runtime_rate_update_is_atomic_and_capability_checked():
    configuration = read_driver_configuration(_parameters().__getitem__)
    updated = configuration.with_runtime_rates(
        {
            "angles_hz": 60.0,
            "angle_feedback": "query_only",
            "current_hz": 10.0,
            "publish_rate_hz": 120.0,
            "diagnostic_rate_hz": 2.0,
        }
    )

    assert configuration.polling_plan.angles_hz == 100.0
    assert updated.polling_plan.angles_hz == 60.0
    assert updated.polling_plan.current_hz == 10.0
    assert updated.polling_plan.angle_feedback is AngleFeedbackPolicy.QUERY_ONLY
    assert updated.publish_rate_hz == 120.0
    assert updated.diagnostic_rate_hz == 2.0

    with pytest.raises(UnsupportedOperationError):
        configuration.with_runtime_rates({"speeds_hz": 1.0})
    with pytest.raises(ValidationError, match="not runtime-adjustable"):
        configuration.with_runtime_rates({"model": "o6"})


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            ('{"backend":"socketcan","channel":"can3","nominal_bitrate":1000000}'),
            SocketCANConfiguration(channel="can3", nominal_bitrate=1_000_000),
        ),
        (
            (
                '{"backend":"python_can","interface_name":"PCAN_USBBUS1",'
                '"interface_type":"pcan"}'
            ),
            PythonCANConfiguration("PCAN_USBBUS1", "pcan"),
        ),
        (
            '{"backend":"vendor_canfd","device_index":1,"channel_index":2}',
            VendorCANFDConfiguration(device_index=1, channel_index=2),
        ),
    ],
)
def test_transport_json_parses_to_typed_configuration(raw, expected):
    assert parse_transport_configuration(raw) == expected


@pytest.mark.parametrize(
    "raw, error",
    [
        ("[]", "JSON object"),
        ("{}", "backend must be one of"),
        ('{"backend":"serial"}', "backend must be one of"),
        ('{"backend":"socketcan"}', "requires channel"),
        (
            '{"backend":"socketcan","channel":"can0","model":"l6"}',
            "unknown keys: model",
        ),
    ],
)
def test_transport_json_rejects_ambiguous_or_unowned_fields(raw, error):
    with pytest.raises(ValidationError, match=error):
        parse_transport_configuration(raw)


@pytest.mark.parametrize(
    "name, value",
    [
        ("angles_hz", math.nan),
        ("publish_rate_hz", math.inf),
        ("diagnostic_rate_hz", True),
    ],
)
def test_configuration_rejects_invalid_rates(name, value):
    with pytest.raises(ValidationError, match=f"{name} must be finite"):
        read_driver_configuration(_parameters(**{name: value}).__getitem__)


@pytest.mark.parametrize("value", ("", "echo", 1))
def test_configuration_rejects_invalid_angle_feedback(value):
    with pytest.raises(ValidationError, match="angle_feedback"):
        read_driver_configuration(_parameters(angle_feedback=value).__getitem__)


def test_configuration_delegates_runtime_limits_to_sdk_device_config():
    with pytest.raises(ValidationError, match="mailbox_capacity"):
        read_driver_configuration(_parameters(mailbox_capacity=0).__getitem__)

    with pytest.raises(ValidationError, match="auto_reconnect"):
        read_driver_configuration(_parameters(auto_reconnect="false").__getitem__)


def test_polling_validation_rejects_a_runtime_disabled_channel():
    """A channel the firmware turned out not to answer must not be pollable.

    ``telemetry_channel(...) is not None`` stays true after runtime degradation,
    so validating with it alone accepted a rate that then silently produced no
    data. ``telemetry_supported()`` is what excludes the degraded channel.
    """

    import dataclasses

    from linkerbot_hand import PollingPlan, TelemetrySemantic, get_declared_capabilities
    from linkerbot_hand_ros.driver_config import validate_polling_plan

    capabilities = get_declared_capabilities("o6", side="right")
    plan = PollingPlan(angles_hz=30.0, force_hz=10.0)

    # Declared profile: polling force is fine.
    validate_polling_plan(capabilities, plan)

    degraded = dataclasses.replace(
        capabilities,
        firmware_unsupported_telemetry=(TelemetrySemantic.FORCE,),
    )
    # The channel is still declared, so the old check would have passed.
    assert degraded.telemetry_channel(TelemetrySemantic.FORCE) is not None
    assert not degraded.telemetry_supported(TelemetrySemantic.FORCE)

    with pytest.raises(UnsupportedFirmwareError, match="cannot poll force"):
        validate_polling_plan(degraded, plan)
