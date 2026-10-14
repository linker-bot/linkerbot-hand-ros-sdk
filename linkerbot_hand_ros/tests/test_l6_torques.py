"""L6 torque output/mode commands retain raw values, FIFO and sample origins."""

import time

import pytest
import test_limit_compensations
import test_raw_reads
from linkerbot_hand import (
    AckSupport,
    CommandSemantic,
    CommandStage,
    QueueFullError,
    TelemetrySemantic,
)
from linkerbot_hand.runtime.command_scheduler import CommandIngress
from linkerbot_hand_ros.client import HandCommandClient
from linkerbot_hand_ros.command_router import route_raw_command
from linkerbot_hand_ros.qos import STATE_QOS
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.parameter import Parameter

from linkerbot_hand_msgs.msg import HandRawCommand, HandTelemetry, SampleMetadata

rig = test_limit_compensations.rig
sdk_rig = test_raw_reads.rig
activate = test_limit_compensations.activate


@pytest.mark.parametrize(
    "model,side",
    [
        ("L6", "left"),
        ("L6", "right"),
        ("O6", "right"),
        ("L20Lite", "left"),
        ("L20", "right"),
        ("L30", ""),
        ("O20", "left"),
        ("O30", "right"),
    ],
)
def test_torque_entities_follow_separate_command_and_telemetry_capabilities(
    rig, model, side
):
    node, builder = rig
    assert node.set_parameters_atomically(
        [Parameter("model", value=model), Parameter("side", value=side)]
    ).successful
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    device = node._require_device()
    capabilities = device.get_capabilities()
    assert builder.runtime_factories[-1].calls == 0
    assert (
        TelemetrySemantic.TORQUES in node._interfaces.snapshot._telemetry_publishers
    ) == (capabilities.telemetry_channel(TelemetrySemantic.TORQUES) is not None)
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    topics = {sub.topic_name for sub in node._interfaces.commands._subscriptions}
    assert ("/linkerbot_hand/command/torques" in topics) == (
        capabilities.command(CommandSemantic.TORQUES) is not None
    )
    assert node.trigger_deactivate() == TransitionCallbackReturn.SUCCESS
    assert node._interfaces.commands._subscriptions == []


def test_l6_torque_modes_keep_fifo_order_and_report_queue_full(rig, monkeypatch):
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
    routed = [
        route_raw_command(
            node._require_device(),
            CommandSemantic.TORQUES,
            HandRawCommand(client_id=7, user_sequence=index, raw=[value] * 6),
        )
        for index, value in enumerate((255, 0), start=1)
    ]
    with pytest.raises(QueueFullError):
        route_raw_command(
            node._require_device(),
            CommandSemantic.TORQUES,
            HandRawCommand(client_id=7, user_sequence=3, raw=[1] * 6),
        )
    queued = [ingress.take_next(), ingress.take_next()]
    assert [command.values for command in queued] == [(255,) * 6, (0,) * 6]
    assert [command.handle.command_id for command in queued] == [
        command.handle.command_id for command in routed
    ]
    assert all(command.handle.stage == CommandStage.ACCEPTED for command in queued)
    assert ingress.take_next() is None


@pytest.mark.parametrize("sdk_rig", ["L6"], indirect=True)
def test_l6_torque_write_echo_and_fresh_sdk_query_project_over_dds(sdk_rig):
    rig = sdk_rig
    device = rig.driver._require_device()
    capability = device.get_capabilities().telemetry_channel(TelemetrySemantic.TORQUES)
    assert not capability.device_measured and capability.device_queried
    client = HandCommandClient(rig.consumer)
    states = []
    subscription = rig.consumer.create_subscription(
        HandTelemetry, "/linkerbot_hand/state/torques", states.append, STATE_QOS
    )
    try:
        rig.spin_until(
            lambda: (
                client.is_ready("torques")
                and rig.consumer.count_publishers(subscription.topic_name)
            )
        )
        # A valid ACK may carry the previous output, not the submitted target.
        rig.peer.echo_value = 17
        target = [0, 1, 255, 0, 1, 255]
        publication = client.set_torques(target)
        completed = client.wait_for_terminal_status_async(
            publication.user_sequence, 4.0
        )
        rig.spin_until(completed.done)
        status = completed.result()
        assert status is not None and status.stage == status.STAGE_ACKNOWLEDGED
        assert status.family == "torque_target"
        assert rig.peer.sent[-1] == ("write", CommandSemantic.TORQUES, tuple(target))
        assert not any(
            message == ("read", TelemetrySemantic.TORQUES) for message in rig.peer.sent
        )
        rig.spin_until(lambda: any(s.meta.valid for s in states))
        echo = next(s for s in states if s.meta.valid)
        assert list(echo.raw) == [17] * 6
        assert echo.meta.origin == SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE
        assert not echo.device_measured and echo.device_queried
        assert echo.raw_unit == "count"
        assert echo.raw_scale_note == capability.raw_scale_note
        assert echo.unit_confidence == capability.unit_confidence.value
        assert echo.meta.connection_generation == 1

        # There is no ROS get_torques service; use the SDK query to refresh its
        # cache and verify the ROS state publisher consumes that same sample.
        rig.peer.value = 255
        sample = device.get_torques(timeout=0.5)
        assert rig.peer.sent[-1] == ("read", TelemetrySemantic.TORQUES)
        assert sample.meta.sequence > echo.meta.sequence
        rig.spin_until(
            lambda: any(s.meta.sequence == sample.meta.sequence for s in states)
        )
        state = next(s for s in states if s.meta.sequence == sample.meta.sequence)
        assert list(state.raw) == [255] * 6
        assert list(state.channel_names) == list(capability.channels)
        assert not state.device_measured and state.device_queried
        assert state.meta.origin == SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE
        assert state.meta.valid and not state.meta.stale
        assert state.meta.connection_generation == sample.meta.connection_generation
        assert all(
            channel.requested_hz == 0 for channel in device.get_health().channels
        )
    finally:
        client.destroy()
        rig.consumer.destroy_subscription(subscription)
