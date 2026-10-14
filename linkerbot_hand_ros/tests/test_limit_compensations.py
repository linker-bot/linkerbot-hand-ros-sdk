"""L6 limit configuration through ROS admission, active reads and state output."""

import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand import (
    AckSupport,
    AngleFeedbackPolicy,
    CommandSemantic,
    CommandStage,
    DataOrigin,
    ErrorCode,
    LimitCompensationSample,
    SampleMeta,
    TelemetrySemantic,
    TimeoutError,
    UnsupportedFirmwareError,
)
from linkerbot_hand.runtime.command_scheduler import CommandIngress
from linkerbot_hand_ros.client import HandCommandClient
from linkerbot_hand_ros.node import LinkerbotHandNode
from linkerbot_hand_ros.qos import STATE_QOS
from rclpy.executors import MultiThreadedExecutor
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.node import Node
from rclpy.parameter import Parameter

from linkerbot_hand_msgs.msg import HandRawCommand, HandTelemetry
from linkerbot_hand_msgs.srv import GetRawValues, SetRawValues


@pytest.fixture
def rig():
    rclpy.init()
    builder = DeviceBuilder()
    node = LinkerbotHandNode(device_factory=builder)
    try:
        yield node, builder
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


def activate(node):
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS


def limit_sample(*, sequence=7, origin=DataOrigin.DEVICE_RESPONSE):
    return LimitCompensationSample(
        raw=(0, 1, 2, 3, 4, 255),
        meta=SampleMeta(
            sequence=sequence,
            collected_at=time.monotonic(),
            age_s=0.0,
            valid=True,
            stale=False,
            connection_generation=1,
            origin=origin,
            within_declared_range=True,
        ),
    )


@pytest.mark.parametrize(
    "model,side",
    [
        ("l6", "left"),
        ("o6", "right"),
        ("l20lite", "right"),
        ("l20", "right"),
        ("o20", "right"),
        ("l30", ""),
        ("o30", "right"),
    ],
)
def test_limit_interfaces_follow_model_capability_and_lifecycle(rig, model, side):
    node, builder = rig
    assert node.set_parameters_atomically(
        [Parameter("model", value=model), Parameter("side", value=side)]
    ).successful
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    declared = model == "l6"
    services = {
        node.resolve_service_name(service.srv_name)
        for service in node._interfaces.management._services
    }
    for suffix in ("get_limit_compensations", "set_limit_compensations"):
        assert (f"/linkerbot_hand/{suffix}" in services) == declared
    assert (
        TelemetrySemantic.LIMIT_COMPENSATIONS
        in node._interfaces.snapshot._telemetry_publishers
    ) == declared
    assert builder.runtime_factories[-1].calls == 0
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    subscriptions = {sub.topic_name for sub in node._interfaces.commands._subscriptions}
    assert ("/linkerbot_hand/command/limit_compensations" in subscriptions) == declared
    assert node.trigger_deactivate() == TransitionCallbackReturn.SUCCESS
    assert not node._interfaces.commands._subscriptions
    if declared:
        before = builder.latest_runtime.read_count
        read = node._interfaces.management._get_raw_values(
            TelemetrySemantic.LIMIT_COMPENSATIONS,
            GetRawValues.Request(timeout_s=0.2),
            GetRawValues.Response(),
        )
        write = node._interfaces.management._set_raw_values(
            "limit_compensations",
            SetRawValues.Request(raw=[0.0] * 6),
            SetRawValues.Response(),
        )
        assert not read.success and read.error_code == ErrorCode.DEVICE_NOT_READY.value
        assert (
            not write.accepted and write.error_code == ErrorCode.DEVICE_NOT_READY.value
        )
        assert builder.latest_runtime.read_count == before
        assert not builder.latest_runtime.submissions
    assert node.trigger_cleanup() == TransitionCallbackReturn.SUCCESS


def test_limit_topic_preserves_raw_values_and_ack_status(rig, monkeypatch):
    node, builder = rig
    activate(node)
    commands = node._interfaces.commands
    messages = []
    with monkeypatch.context() as patch:
        patch.setattr(
            commands, "_status_publisher", SimpleNamespace(publish=messages.append)
        )
        commands._handle_raw(
            CommandSemantic.LIMIT_COMPENSATIONS,
            HandRawCommand(
                client_id=17, user_sequence=42, raw=[0.0, 1.0, 2.0, 3.0, 4.0, 255.0]
            ),
        )
        commands.publish_updates()
    assert builder.latest_runtime.submissions == [
        (CommandSemantic.LIMIT_COMPENSATIONS, (0, 1, 2, 3, 4, 255))
    ]
    status = messages[-1].statuses[-1]
    assert (status.client_id, status.user_sequence) == (17, 42)
    assert status.family == "limit_compensation"
    assert status.ack_support == status.ACK_SUPPORTED
    assert status.stage == status.STAGE_ACKNOWLEDGED


def test_limit_service_admission_preserves_fifo_and_reports_full(rig, monkeypatch):
    node, builder = rig
    activate(node)
    runtime = builder.latest_runtime
    ingress = CommandIngress(
        discrete_capacity=2, monotonic=time.monotonic, wake=lambda: None
    )
    ingress.activate(generation=1)
    monkeypatch.setattr(
        runtime,
        "submit",
        lambda semantic, values: ingress.submit(
            semantic, values, ack_support=AckSupport.SUPPORTED
        ),
    )
    responses = [
        node._interfaces.management._set_raw_values(
            "limit_compensations",
            SetRawValues.Request(user_sequence=i, raw=[float(i)] * 6),
            SetRawValues.Response(),
        )
        for i in (1, 2, 3)
    ]
    assert [r.accepted for r in responses] == [True, True, False]
    assert responses[2].error_code == ErrorCode.QUEUE_FULL.value
    assert responses[2].command_id == 0
    queued = [ingress.take_next(), ingress.take_next()]
    assert [c.values for c in queued] == [(1,) * 6, (2,) * 6]
    assert all(c.handle.stage == CommandStage.ACCEPTED for c in queued)
    assert [c.handle.command_id for c in queued] == [
        r.command_id for r in responses[:2]
    ]
    assert ingress.take_next() is None


@pytest.mark.parametrize("raw", ([0.0] * 5, [256.0] * 6, [-1.0] * 6, [0.5] * 6))
def test_limit_service_rejects_invalid_values_before_sdk_admission(rig, raw):
    node, builder = rig
    activate(node)
    response = node._interfaces.management._set_raw_values(
        "limit_compensations", SetRawValues.Request(raw=raw), SetRawValues.Response()
    )
    assert not response.accepted
    assert response.error_code == ErrorCode.VALIDATION.value
    assert builder.latest_runtime.submissions == []


def test_limit_read_runs_on_worker_and_preserves_metadata(rig, monkeypatch):
    node, builder = rig
    activate(node)
    runtime = builder.latest_runtime
    runtime.snapshot = replace(runtime.snapshot, limit_compensations=limit_sample())
    threads = []
    read = runtime.read

    def record_read(semantic, timeout):
        assert semantic is TelemetrySemantic.LIMIT_COMPENSATIONS
        assert timeout == 0.2
        threads.append(threading.current_thread().name)
        return read(semantic, timeout)

    monkeypatch.setattr(runtime, "read", record_read)
    response = node._interfaces.management._get_raw_values(
        TelemetrySemantic.LIMIT_COMPENSATIONS,
        GetRawValues.Request(timeout_s=0.2),
        GetRawValues.Response(),
    )
    assert response.success
    assert threads == ["linkerbot_hand-admin"]
    assert list(response.state.raw) == [0, 1, 2, 3, 4, 255]
    assert response.state.semantic == "limit_compensations"
    assert list(response.state.channel_names) == list(runtime.capabilities.joint_names)
    assert response.state.raw_unit == "count"
    assert response.state.unit_confidence == "unknown"
    assert response.state.raw_scale_note
    assert not response.state.device_measured and response.state.device_queried
    assert response.state.meta.sequence == 7
    assert response.state.meta.valid and not response.state.meta.stale
    assert response.state.meta.connection_generation == 1


@pytest.mark.parametrize(
    "error",
    [TimeoutError("read timed out"), UnsupportedFirmwareError("unsupported firmware")],
)
def test_limit_read_keeps_sdk_error_codes(rig, monkeypatch, error):
    node, builder = rig
    activate(node)

    def fail_read(_semantic, _timeout):
        raise error

    monkeypatch.setattr(builder.latest_runtime, "read", fail_read)
    response = node._interfaces.management._get_raw_values(
        TelemetrySemantic.LIMIT_COMPENSATIONS,
        GetRawValues.Request(timeout_s=0.2),
        GetRawValues.Response(),
    )
    assert not response.success
    assert response.error_code == error.code.value
    assert not response.state.meta.valid


@pytest.mark.parametrize("timeout", (0.0, -1.0, float("nan"), 1.9))
def test_limit_read_rejects_invalid_timeout_before_io(rig, timeout):
    node, builder = rig
    activate(node)
    response = node._interfaces.management._get_raw_values(
        TelemetrySemantic.LIMIT_COMPENSATIONS,
        GetRawValues.Request(timeout_s=timeout),
        GetRawValues.Response(),
    )
    assert not response.success and response.error_code == ErrorCode.VALIDATION.value
    assert builder.latest_runtime.read_count == 0


@pytest.mark.parametrize(
    "origin", (DataOrigin.DEVICE_RESPONSE, DataOrigin.DEVICE_CONFIG_RESPONSE)
)
def test_limit_state_uses_cached_sample_and_suppresses_duplicates(
    rig, monkeypatch, origin
):
    node, builder = rig
    activate(node)
    runtime = builder.latest_runtime
    publisher = node._interfaces.snapshot
    messages = []
    with monkeypatch.context() as patch:
        patch.setitem(
            publisher._telemetry_publishers,
            TelemetrySemantic.LIMIT_COMPENSATIONS,
            SimpleNamespace(publish=messages.append),
        )
        snapshot = replace(
            runtime.snapshot, limit_compensations=limit_sample(origin=origin)
        )
        for _ in range(2):
            publisher.publish_snapshot(
                snapshot,
                ros_now_ns=node.get_clock().now().nanoseconds,
                angle_feedback_policy=AngleFeedbackPolicy.QUERY_ONLY,
            )
    assert len(messages) == 1
    assert list(messages[0].raw) == [0, 1, 2, 3, 4, 255]
    assert messages[0].raw_unit == "count"
    assert runtime.read_count == 0


def test_limit_public_client_services_and_state_over_ros(rig, shutdown_ros_executor):
    driver, builder = rig
    node = Node("limit_compensation_consumer")
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(driver)
    executor.add_node(node)
    client = HandCommandClient(node)
    get_client = node.create_client(
        GetRawValues, "/linkerbot_hand/get_limit_compensations"
    )
    set_client = node.create_client(
        SetRawValues, "/linkerbot_hand/set_limit_compensations"
    )
    states = []
    node.create_subscription(
        HandTelemetry,
        "/linkerbot_hand/state/limit_compensations",
        states.append,
        STATE_QOS,
    )

    def spin_until(condition):
        deadline = time.monotonic() + 5.0
        while not condition() and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.02)
        assert condition()

    try:
        activate(driver)
        spin_until(
            lambda: (
                client.is_ready("limit_compensations")
                and get_client.service_is_ready()
                and set_client.service_is_ready()
            )
        )
        publication = client.set_limit_compensations([0, 1, 2, 3, 4, 255])
        status = client.wait_for_terminal_status_async(publication.user_sequence, 4.0)
        spin_until(status.done)
        assert status.result().stage == status.result().STAGE_ACKNOWLEDGED
        assert builder.latest_runtime.submissions[-1] == (
            CommandSemantic.LIMIT_COMPENSATIONS,
            (0, 1, 2, 3, 4, 255),
        )
        written = set_client.call_async(
            SetRawValues.Request(user_sequence=12, raw=[1.0] * 6)
        )
        spin_until(written.done)
        assert written.result().accepted and written.result().command_id > 0
        runtime = builder.latest_runtime
        runtime.snapshot = replace(runtime.snapshot, limit_compensations=limit_sample())
        received = get_client.call_async(GetRawValues.Request(timeout_s=0.2))
        spin_until(received.done)
        assert received.result().success
        assert list(received.result().state.raw) == [0, 1, 2, 3, 4, 255]
        spin_until(
            lambda: any(
                message.meta.valid and message.meta.sequence == 7 for message in states
            )
        )
        assert driver.trigger_deactivate() == TransitionCallbackReturn.SUCCESS
        rejected = get_client.call_async(GetRawValues.Request(timeout_s=0.2))
        spin_until(rejected.done)
        assert rejected.result().error_code == ErrorCode.DEVICE_NOT_READY.value
    finally:
        shutdown_ros_executor(executor)
        client.destroy()
        node.destroy_node()
