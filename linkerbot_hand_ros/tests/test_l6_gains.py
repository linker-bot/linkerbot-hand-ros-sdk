"""L6 control gains use the same raw command, service and state contracts."""

import time

import pytest
import test_limit_compensations
import test_raw_reads
from linkerbot_hand import (
    AckSupport,
    CommandSemantic,
    ErrorCode,
    TelemetrySemantic,
    TimeoutError,
    UnsupportedFirmwareError,
)
from linkerbot_hand.runtime.command_scheduler import CommandIngress
from linkerbot_hand_ros.client import HandCommandClient
from linkerbot_hand_ros.qos import STATE_QOS
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.parameter import Parameter

from linkerbot_hand_msgs.msg import HandTelemetry, SampleMetadata
from linkerbot_hand_msgs.srv import GetRawValues, SetRawValues

GAINS = ("position_kp", "position_kd", "torque_kd")
rig = test_limit_compensations.rig
sdk_rig = test_raw_reads.rig
activate = test_limit_compensations.activate


@pytest.mark.parametrize(
    "model,side",
    [
        ("L6", "left"),
        ("O6", "right"),
        ("L20Lite", "left"),
        ("L20", "right"),
        ("L30", ""),
        ("O20", "left"),
        ("O30", "right"),
    ],
)
def test_gain_entities_follow_capability_and_lifecycle(rig, model, side):
    node, builder = rig
    assert node.set_parameters_atomically(
        [Parameter("model", value=model), Parameter("side", value=side)]
    ).successful
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert builder.runtime_factories[-1].calls == 0
    services = {
        node.resolve_service_name(service.srv_name)
        for service in node._interfaces.management._services
    }
    for name in GAINS:
        for operation in ("get", "set"):
            assert (f"/linkerbot_hand/{operation}_{name}" in services) == (
                model == "L6"
            )
        assert (
            TelemetrySemantic(name) in node._interfaces.snapshot._telemetry_publishers
        ) == (model == "L6")
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    topics = {sub.topic_name for sub in node._interfaces.commands._subscriptions}
    assert all(
        (f"/linkerbot_hand/command/{name}" in topics) == (model == "L6")
        for name in GAINS
    )
    assert node.trigger_deactivate() == TransitionCallbackReturn.SUCCESS
    assert node._interfaces.commands._subscriptions == []
    if model == "L6":
        for name in GAINS:
            response = node._interfaces.management._get_raw_values(
                TelemetrySemantic(name),
                GetRawValues.Request(timeout_s=0.2),
                GetRawValues.Response(),
            )
            assert (
                not response.success
                and response.error_code == ErrorCode.DEVICE_NOT_READY.value
            )
            write = node._interfaces.management._set_raw_values(
                name,
                SetRawValues.Request(raw=[1.0] * 6),
                SetRawValues.Response(),
            )
            assert (
                not write.accepted
                and write.error_code == ErrorCode.DEVICE_NOT_READY.value
            )
        assert builder.latest_runtime.read_count == 0
        assert builder.latest_runtime.submissions == []


@pytest.mark.parametrize("name", GAINS)
@pytest.mark.parametrize(
    "bad_values", ([1.0] * 5, [-1.0] * 6, [0.5] * 6, [float("nan")] * 6)
)
def test_gain_service_rejects_invalid_raw_vectors(rig, name, bad_values):
    node, builder = rig
    activate(node)
    response = node._interfaces.management._set_raw_values(
        name, SetRawValues.Request(raw=bad_values), SetRawValues.Response()
    )
    assert not response.accepted and response.error_code == ErrorCode.VALIDATION.value
    assert not builder.latest_runtime.submissions


@pytest.mark.parametrize(
    "name,maximum", [("position_kp", 200), ("position_kd", 255), ("torque_kd", 255)]
)
def test_gain_boundaries_come_from_sdk_without_scaling(rig, name, maximum):
    node, builder = rig
    activate(node)
    management = node._interfaces.management
    accepted = management._set_raw_values(
        name,
        SetRawValues.Request(raw=[0.0, float(maximum)] * 3),
        SetRawValues.Response(),
    )
    assert accepted.accepted
    assert builder.latest_runtime.submissions[-1] == (
        CommandSemantic(name),
        (0, maximum) * 3,
    )
    rejected = management._set_raw_values(
        name,
        SetRawValues.Request(raw=[float(maximum + 1)] * 6),
        SetRawValues.Response(),
    )
    assert not rejected.accepted and rejected.error_code == ErrorCode.VALIDATION.value
    assert len(builder.latest_runtime.submissions) == 1


def test_gain_services_share_bounded_fifo_without_replacing_each_other(
    rig, monkeypatch
):
    node, builder = rig
    activate(node)
    ingress = CommandIngress(
        discrete_capacity=2, monotonic=time.monotonic, wake=lambda: None
    )
    ingress.activate(generation=1)
    monkeypatch.setattr(
        builder.latest_runtime,
        "submit",
        lambda semantic, values: ingress.submit(
            semantic, values, ack_support=AckSupport.SUPPORTED
        ),
    )
    responses = [
        node._interfaces.management._set_raw_values(
            name, SetRawValues.Request(raw=[float(index)] * 6), SetRawValues.Response()
        )
        for index, name in enumerate(GAINS, start=1)
    ]
    assert [response.accepted for response in responses] == [True, True, False]
    assert responses[-1].error_code == ErrorCode.QUEUE_FULL.value
    first, second = ingress.take_next(), ingress.take_next()
    assert first.semantic == CommandSemantic.POSITION_KP and first.values == (1,) * 6
    assert second.semantic == CommandSemantic.POSITION_KD and second.values == (2,) * 6
    assert ingress.take_next() is None


@pytest.mark.parametrize("name", GAINS)
@pytest.mark.parametrize(
    "error",
    [TimeoutError("read timed out"), UnsupportedFirmwareError("unsupported gain")],
)
def test_gain_getters_preserve_sdk_failures(rig, monkeypatch, name, error):
    node, builder = rig
    activate(node)

    def fail(_semantic, _timeout):
        raise error

    monkeypatch.setattr(builder.latest_runtime, "read", fail)
    response = node._interfaces.management._get_raw_values(
        TelemetrySemantic(name),
        GetRawValues.Request(timeout_s=0.2),
        GetRawValues.Response(),
    )
    assert not response.success and response.error_code == error.code.value
    assert not response.state.meta.valid


@pytest.mark.parametrize("sdk_rig", ["L6"], indirect=True)
@pytest.mark.parametrize("name", GAINS)
def test_gain_client_service_query_and_state_over_dds(sdk_rig, name):
    rig = sdk_rig
    client = HandCommandClient(rig.consumer)
    setter = rig.consumer.create_client(SetRawValues, f"/linkerbot_hand/set_{name}")
    states = []
    subscription = rig.consumer.create_subscription(
        HandTelemetry, f"/linkerbot_hand/state/{name}", states.append, STATE_QOS
    )
    try:
        rig.spin_until(
            lambda: (
                client.is_ready(name)
                and setter.service_is_ready()
                and rig.consumer.count_publishers(subscription.topic_name)
            )
        )
        publication = getattr(client, f"set_{name}")([1, 2, 3, 4, 5, 6])
        completed = client.wait_for_terminal_status_async(
            publication.user_sequence, 4.0
        )
        rig.spin_until(completed.done)
        status = completed.result()
        assert status is not None and status.stage == status.STAGE_ACKNOWLEDGED
        assert status.family == "control_gain"
        assert rig.peer.sent[-1] == ("write", CommandSemantic(name), (1, 2, 3, 4, 5, 6))
        rig.spin_until(
            lambda: any(
                s.meta.valid and list(s.raw) == [1, 2, 3, 4, 5, 6] for s in states
            )
        )
        state = next(s for s in states if s.meta.valid)
        assert state.meta.origin == SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE
        assert not state.device_measured and state.device_queried
        assert state.raw_scale_note
        written = setter.call_async(SetRawValues.Request(raw=[7.0] * 6))
        rig.spin_until(written.done)
        assert written.result().accepted and written.result().command_id > 0
        rig.spin_until(
            lambda: any(s.meta.valid and list(s.raw) == [7.0] * 6 for s in states)
        )
        rig.peer.value = 13
        response = rig.call(TelemetrySemantic(name))
        assert response.success
        assert list(response.state.raw) == [13.0] * 6
        assert response.state.meta.sequence > state.meta.sequence
        assert response.state.raw_unit == state.raw_unit
        assert response.state.raw_scale_note == state.raw_scale_note
        assert all(
            channel.requested_hz == 0
            for channel in rig.driver._require_device().get_health().channels
        )
    finally:
        client.destroy()
        rig.consumer.destroy_client(setter)
        rig.consumer.destroy_subscription(subscription)
