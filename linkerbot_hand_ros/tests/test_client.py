"""Typed persistent client contract tests."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest
import rclpy
from linkerbot_hand import CommandSemantic, get_declared_capabilities
from linkerbot_hand_ros.client import HandCommandClient
from linkerbot_hand_ros.conversion import capabilities_to_message
from rclpy.node import Node

from linkerbot_hand_msgs.msg import HandCommandStatus, HandCommandStatusBatch


class RecordingPublisher:
    def __init__(self, subscriptions: int = 1) -> None:
        self.messages: list[object] = []
        self.subscriptions = subscriptions

    def publish(self, message: object) -> None:
        self.messages.append(message)

    def get_subscription_count(self) -> int:
        return self.subscriptions


class FailingConstructionNode:
    def __init__(self) -> None:
        self.created: list[object] = []
        self.destroyed: list[object] = []

    def create_publisher(self, *_args, **_kwargs):
        if len(self.created) == 2:
            raise RuntimeError("publisher construction failed")
        publisher = object()
        self.created.append(publisher)
        return publisher

    def destroy_publisher(self, publisher) -> None:
        self.destroyed.append(publisher)

    def destroy_subscription(self, _subscription) -> None:
        raise AssertionError("no subscription should exist after publisher failure")


@pytest.fixture
def client_rig(monkeypatch):
    rclpy.init()
    node = Node("typed_hand_client_test")
    client = HandCommandClient(node, client_id=101)
    angle = RecordingPublisher()
    original_angle = client._angle_publisher
    client._angle_publisher = angle
    raw_originals = dict(client._raw_publishers)
    raw = {name: RecordingPublisher() for name in client._raw_publishers}
    client._raw_publishers.update(raw)
    # Publication tests isolate readiness; real lifecycle/graph evidence is
    # exercised by test_client_executor and test_driver_readiness.
    monkeypatch.setattr(
        client._readiness, "is_active", lambda _topic: angle.subscriptions > 0
    )
    capabilities = get_declared_capabilities("l6", side="left")
    capabilities = replace(
        capabilities,
        identity=replace(capabilities.identity, verified=True),
    )
    client._update_capabilities(capabilities_to_message(capabilities))
    try:
        yield client, angle, raw
    finally:
        client._angle_publisher = original_angle
        client._raw_publishers.update(raw_originals)
        client.destroy()
        node.destroy_node()
        rclpy.try_shutdown()


def test_force_field_capability_is_a_copied_zero_io_view(client_rig):
    client, _angle, _raw = client_rig
    field = client.force_field_capability("fn")
    assert field.support_known and field.supported
    assert field.query_channel == "force" and field.shared_fields == ["fn"]
    field.shared_fields.append("fns")
    assert client.force_field_capability("fn").shared_fields == ["fn"]
    assert not client.force_field_capability("fns").supported
    with pytest.raises(ValueError):
        client.force_field_capability("FN")


def test_percent_and_raw_angles_use_one_typed_topic(client_rig):
    client, angle, _raw = client_rig
    percent = client.set_percent_angles([100, 50, 100, 100, 100, 100])
    capabilities = get_declared_capabilities("l6", side="left")
    command = capabilities.command(CommandSemantic.ANGLES)
    assert command is not None
    raw_values = [command.range_for(index).minimum for index in range(6)]
    raw = client.set_angles(raw_values)

    assert percent.user_sequence == 1
    assert raw.user_sequence == 2
    assert percent.client_id == 101
    assert raw.client_id == 101
    assert percent.representation == "percent"
    assert raw.representation == "raw"
    assert angle.messages[0].representation == angle.messages[0].REPRESENTATION_PERCENT
    assert angle.messages[1].representation == angle.messages[1].REPRESENTATION_RAW
    assert angle.messages[0].client_id == 101
    assert angle.messages[0].publisher_stamp == percent.publisher_stamp
    assert angle.messages[0].publisher_stamp.sec > 0


def test_client_validates_from_published_capability_not_model_table(client_rig):
    client, _angle, _raw = client_rig

    with pytest.raises(ValueError, match="0..100"):
        client.set_percent_angles([101] * 6)
    with pytest.raises(ValueError, match="integer protocol"):
        client.set_angles([0.5] * 6)
    with pytest.raises(TypeError, match="bool"):
        client.set_percent_angles([True, 50, 50, 50, 50, 50])

    capabilities = get_declared_capabilities("l6", side="left")
    published = capabilities_to_message(
        replace(capabilities, identity=replace(capabilities.identity, verified=True))
    )
    assert any(command.semantic == "torques" for command in published.commands)
    published.commands = [
        command for command in published.commands if command.semantic != "torques"
    ]
    client._update_capabilities(published)
    assert published.identity.model == "L6"
    assert not client.is_ready("torques")
    with pytest.raises(RuntimeError, match="does not declare torques"):
        client.set_torques([0] * 6)


def test_l6_torque_client_preserves_mode_and_output_raw_values(client_rig):
    client, _angle, raw = client_rig
    assert client.is_ready("torques")
    publication = client.set_torques([0, 1, 255, 0, 1, 255])
    message = raw["torques"].messages[-1]
    assert list(message.raw) == [0, 1, 255, 0, 1, 255]
    assert publication.semantic == "torques" and publication.representation == "raw"
    assert message.client_id == publication.client_id
    assert message.user_sequence == publication.user_sequence
    assert message.publisher_stamp == publication.publisher_stamp


@pytest.mark.parametrize(
    "values,error",
    [
        ([-1] * 6, ValueError),
        ([256] * 6, ValueError),
        ([0.5] * 6, ValueError),
        ([float("nan")] * 6, ValueError),
        ([True] * 6, TypeError),
        ([0] * 5, ValueError),
    ],
)
def test_l6_torque_client_rejects_invalid_raw_before_publication(
    client_rig, values, error
):
    client, _angle, raw = client_rig
    with pytest.raises(error):
        client.set_torques(values)
    assert raw["torques"].messages == []


def test_raw_command_publication_uses_capability_channel_shape(client_rig):
    client, _angle, raw_publishers = client_rig
    capabilities = get_declared_capabilities("l6", side="left")
    command = capabilities.command(CommandSemantic.SPEEDS)
    assert command is not None
    values = [command.range_for(index).minimum for index in range(6)]

    publication = client.set_speeds(values)

    assert publication.semantic == "speeds"
    assert publication.representation == "raw"
    assert raw_publishers["speeds"].messages[0].client_id == 101
    assert raw_publishers["speeds"].messages[0].publisher_stamp == (
        publication.publisher_stamp
    )
    assert list(raw_publishers["speeds"].messages[0].raw) == values


def test_wait_for_terminal_status_uses_sdk_stage_not_mechanical_arrival(client_rig):
    client, _angle, _raw = client_rig
    publication = client.set_percent_angles([100] * 6)
    result: list[HandCommandStatus | None] = []
    waiter = threading.Thread(
        target=lambda: result.append(
            client.wait_for_terminal_status(publication.user_sequence, 0.5)
        )
    )
    waiter.start()
    client._update_status(
        HandCommandStatus(
            client_id=publication.client_id,
            user_sequence=publication.user_sequence,
            command_id=9,
            family="angle_target",
            stage=HandCommandStatus.STAGE_DISPATCHED,
            ack_support=HandCommandStatus.ACK_UNSUPPORTED,
            sent_frames=1,
        )
    )
    waiter.join(timeout=1)

    assert not waiter.is_alive()
    assert result[0] is not None
    assert result[0].stage == HandCommandStatus.STAGE_DISPATCHED


@pytest.mark.parametrize("model", ["L20", "L20Lite", "O20", "O30"])
def test_current_and_torque_limit_publications_follow_distinct_capabilities(
    client_rig, model
):
    client, _angle, publishers = client_rig
    capabilities = get_declared_capabilities(model, side="left")
    client._update_capabilities(
        capabilities_to_message(
            replace(
                capabilities, identity=replace(capabilities.identity, verified=True)
            )
        )
    )
    count = len(capabilities.joints)
    current = client.set_current_limits([40] * count)
    assert current.semantic == "current_limits"
    assert list(publishers["current_limits"].messages[-1].raw) == [40] * count
    assert not publishers["torques_limits"].messages
    if model == "O30":
        torque = client.set_torques_limits([60] * count)
        assert torque.semantic == "torques_limits"
        assert list(publishers["torques_limits"].messages[-1].raw) == [60] * count
        assert len(publishers["current_limits"].messages) == 1
    else:
        with pytest.raises(RuntimeError, match="does not declare torques_limits"):
            client.set_torques_limits([60] * count)
        assert not publishers["torques_limits"].messages
    assert not hasattr(client, "set_effort_limits")


def test_limit_compensation_client_preserves_raw_and_waits_for_ack(client_rig):
    client, _angle, raw = client_rig
    assert client.is_ready("limit_compensations")
    publication = client.set_limit_compensations([0, 1, 2, 3, 4, 255])
    message = raw["limit_compensations"].messages[-1]
    assert list(message.raw) == [0, 1, 2, 3, 4, 255]
    assert message.client_id == publication.client_id
    assert message.user_sequence == publication.user_sequence
    assert message.publisher_stamp == publication.publisher_stamp
    future = client.wait_for_terminal_status_async(publication.user_sequence, 1.0)
    for stage in (
        HandCommandStatus.STAGE_DISPATCHED,
        HandCommandStatus.STAGE_ACKNOWLEDGED,
    ):
        client._update_status(
            HandCommandStatus(
                client_id=publication.client_id,
                user_sequence=publication.user_sequence,
                command_id=1,
                family="limit_compensation",
                stage=stage,
                ack_support=HandCommandStatus.ACK_SUPPORTED,
            )
        )
        client._poll_waits()
        assert future.done() == (stage == HandCommandStatus.STAGE_ACKNOWLEDGED)
    assert future.result().stage == HandCommandStatus.STAGE_ACKNOWLEDGED


@pytest.mark.parametrize(
    "values", ([0] * 5, [256] * 6, [-1] * 6, [0.5] * 6, [float("nan")] * 6)
)
def test_limit_compensation_client_rejects_invalid_raw(client_rig, values):
    client, _angle, raw = client_rig
    with pytest.raises(ValueError):
        client.set_limit_compensations(values)
    assert not raw["limit_compensations"].messages


def test_limit_compensation_client_rejects_inactive_and_unsupported(client_rig):
    client, angle, raw = client_rig
    angle.subscriptions = 0
    assert not client.is_ready("limit_compensations")
    with pytest.raises(RuntimeError, match="not active"):
        client.set_limit_compensations([0] * 6)
    capability = get_declared_capabilities("o6", side="right")
    client._update_capabilities(
        capabilities_to_message(
            replace(capability, identity=replace(capability.identity, verified=True))
        )
    )
    angle.subscriptions = 1
    assert not client.is_ready("limit_compensations")
    with pytest.raises(RuntimeError, match="does not declare limit_compensations"):
        client.set_limit_compensations([0] * 6)
    assert not raw["limit_compensations"].messages


def test_status_cache_ignores_another_client_with_the_same_sequence(client_rig):
    client, _angle, _raw = client_rig
    other = HandCommandClient(client._node, client_id=202)
    publication = client.set_percent_angles([100] * 6)
    foreign = HandCommandStatus(
        client_id=202,
        user_sequence=publication.user_sequence,
        command_id=8,
        family="angle_target",
        stage=HandCommandStatus.STAGE_FAILED,
        ack_support=HandCommandStatus.ACK_UNSUPPORTED,
    )
    own = HandCommandStatus(
        client_id=publication.client_id,
        user_sequence=publication.user_sequence,
        command_id=9,
        family="angle_target",
        stage=HandCommandStatus.STAGE_DISPATCHED,
        ack_support=HandCommandStatus.ACK_UNSUPPORTED,
    )

    try:
        client._update_status(foreign)
        other._update_status(foreign)
        assert client.get_status(publication.user_sequence) is None
        assert other.get_status(publication.user_sequence) is foreign

        client._update_status(own)
        other._update_status(own)
        assert client.get_status(publication.user_sequence) is own
        assert other.get_status(publication.user_sequence) is foreign
    finally:
        other.destroy()


def test_status_batch_updates_all_matching_client_sequences(client_rig):
    client, _angle, _raw = client_rig
    first = client.set_percent_angles([100] * 6)
    second = client.set_percent_angles([100] * 6)
    statuses = [
        HandCommandStatus(
            client_id=client.client_id,
            user_sequence=publication.user_sequence,
            command_id=index,
            family="angle_target",
            stage=HandCommandStatus.STAGE_DISPATCHED,
            ack_support=HandCommandStatus.ACK_UNSUPPORTED,
            sent_frames=1,
        )
        for index, publication in enumerate((first, second), start=1)
    ]

    client._update_status_batch(HandCommandStatusBatch(statuses=statuses))

    assert client.get_status(first.user_sequence) is statuses[0]
    assert client.get_status(second.user_sequence) is statuses[1]


def test_readiness_requires_capability_and_active_driver(client_rig):
    client, angle, _raw = client_rig
    assert client.is_ready("angles")

    angle.subscriptions = 0
    assert not client.is_ready("angles")
    assert not client.is_ready("torques")
    with pytest.raises(RuntimeError, match="not active"):
        client.set_percent_angles([100] * 6)


def test_declared_capability_cannot_be_used_before_identity_verification(client_rig):
    client, _angle, _raw = client_rig
    client._update_capabilities(
        capabilities_to_message(get_declared_capabilities("l6", side="left"))
    )

    assert not client.is_ready("angles")
    with pytest.raises(RuntimeError, match="identity-verified"):
        client.set_percent_angles([100] * 6)


def test_client_destroy_is_idempotent_and_rejects_further_use(client_rig):
    client, _angle, _raw = client_rig
    client.destroy()
    client.destroy()

    with pytest.raises(RuntimeError, match="destroyed"):
        client.set_percent_angles([100] * 6)


def test_partial_publisher_construction_rolls_back_every_created_entity():
    node = FailingConstructionNode()

    with pytest.raises(RuntimeError, match="construction failed"):
        HandCommandClient(node)

    assert set(node.destroyed) == set(node.created)


@pytest.mark.parametrize("client_id", [0, True, -1, 1 << 64])
def test_client_id_must_be_a_nonzero_uint64(client_id):
    rclpy.init()
    node = Node("invalid_typed_hand_client_test")
    try:
        with pytest.raises(ValueError, match="non-zero uint64"):
            HandCommandClient(node, client_id=client_id)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
