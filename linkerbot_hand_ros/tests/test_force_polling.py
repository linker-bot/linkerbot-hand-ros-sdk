"""ROS tactile rates follow SDK physical-query scheduling and validation."""

from dataclasses import replace

import pytest
from linkerbot_hand import (
    PollingPlan,
    TelemetrySemantic,
    UnsupportedOperationError,
    ValidationError,
    get_declared_capabilities,
)
from linkerbot_hand.capabilities.polling import resolve_poll_rates
from linkerbot_hand_ros.driver_config import (
    read_driver_configuration,
    validate_polling_plan,
)
from linkerbot_hand_ros.parameter_updates import PARAMETER_DEFAULTS


def test_rates_use_sdk_shared_query_and_independent_query_rules():
    o30 = get_declared_capabilities("O30", side="left")
    lite = get_declared_capabilities("L20Lite", side="left")
    plan = PollingPlan(force_fn_hz=20, force_fns_hz=10)
    validate_polling_plan(o30, plan)
    assert resolve_poll_rates(plan, o30) == {TelemetrySemantic.FORCE: 20}
    assert resolve_poll_rates(plan, lite) == {
        TelemetrySemantic.FORCE: 20,
        TelemetrySemantic.FORCE_FNS: 10,
    }
    fallback = replace(lite, firmware_unsupported_telemetry=(TelemetrySemantic.FORCE,))
    validate_polling_plan(fallback, PollingPlan(force_hz=10))
    with pytest.raises(UnsupportedOperationError):
        validate_polling_plan(lite, PollingPlan(force_ft_hz=10))
    with pytest.raises(ValidationError):
        PollingPlan(force_hz=10, force_fn_hz=10)
    values = dict(
        PARAMETER_DEFAULTS, model="L20Lite", force_fn_hz=20.0, force_px_hz=10.0
    )
    config = read_driver_configuration(values.__getitem__)
    updated = config.with_runtime_rates({"force_fns_hz": 5.0})
    assert updated.polling_plan.force_fn_hz == 20
    assert updated.polling_plan.force_fns_hz == 5
    assert updated.polling_plan.force_px_hz == 10
