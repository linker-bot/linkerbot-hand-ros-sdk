"""ROS raw reads through the real SDK runtime and an in-memory protocol peer."""

import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
import rclpy
from linkerbot_hand import (
    SUPPORTED_MODELS,
    CommandSemantic,
    CommandStage,
    DataOrigin,
    DeviceInfo,
    ErrorCode,
    HandDevice,
    ReadMode,
    SampleMeta,
    TelemetrySemantic,
)
from linkerbot_hand.protocols import (
    IdentityResult,
    ProtocolTransaction,
    ResponseProgress,
    SamplePayload,
)
from linkerbot_hand_ros.node import LinkerbotHandNode
from linkerbot_hand_ros.qos import COMMAND_QOS, STATE_QOS, STATUS_QOS
from linkerbot_transport.testing import FakeTransport
from rclpy.executors import MultiThreadedExecutor
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.node import Node
from rclpy.parameter import Parameter

from linkerbot_hand_msgs.msg import (
    HandCommandStatus,
    HandCommandStatusBatch,
    HandJointCommand,
    HandRawCommand,
    HandTelemetry,
    SampleMetadata,
)
from linkerbot_hand_msgs.srv import GetRawValues, Recover

_CHANNELS = (
    TelemetrySemantic.CONFIGURED_SPEEDS,
    TelemetrySemantic.CONFIGURED_ACCELERATIONS,
    TelemetrySemantic.CURRENT_LIMITS,
    TelemetrySemantic.TORQUES_LIMITS,
    TelemetrySemantic.MOTION_TIMES,
    TelemetrySemantic.LIMIT_COMPENSATIONS,
    TelemetrySemantic.POSITION_KP,
    TelemetrySemantic.POSITION_KD,
    TelemetrySemantic.TORQUE_KD,
)


class RawReadPeer(FakeTransport):
    """A protocol test double; lifecycle, scheduling and cache use production SDK."""

    endpoint_id = "raw-read-test"
    route_keys = ("raw-read-rx",)

    def __init__(self):
        super().__init__(route_key_of=lambda _message: self.route_keys[0])
        self.value = 11
        self.drop_reads = False
        self.drop_writes = False
        self.echo_value = None

    def send(self, message):
        receipt = super().send(message)
        if not (
            (self.drop_reads and message[0] == "read")
            or (self.drop_writes and message[0] == "write")
        ):
            self.emit(message)
        return receipt

    def transaction(self, message, result, *, ack=False, publications=()):
        def consume(received):
            if received != message:
                return ResponseProgress(matched=False)
            return ResponseProgress(
                matched=True, complete=True, result=result, acknowledged=ack
            )

        return ProtocolTransaction(
            key=message[:2],
            correlation_key=message[:2],
            request_messages=(message,),
            response_timeout_s=0.15,
            estimated_duration_s=0.001,
            response_consumer=None if publications else consume,
            response_acknowledges_command=ack,
            dispatch_publications=publications,
        )

    def identity_transaction(self, capabilities):
        verified = replace(
            capabilities,
            identity=replace(capabilities.identity, verified=True, firmware="test"),
            # Make command-derived samples stale immediately to exercise the
            # service's preservation of age/staleness without a wall-clock sleep.
            telemetry=tuple(
                replace(channel, stale_after_s=1e-9)
                if channel.read_mode
                in (ReadMode.COMMAND_CACHE, ReadMode.COMMAND_RESPONSE)
                else channel
                for channel in capabilities.telemetry
            ),
        )
        info = DeviceInfo(
            model=verified.model,
            serial_number="raw-read-test",
            pcb_version=None,
            firmware_version=None,
            mechanical_version=None,
            product_code=None,
            sensor_variant=None,
            side=verified.side,
            raw_identity=b"raw-read-test",
            meta=SampleMeta.unavailable(),
        )
        return self.transaction(
            ("identity",), IdentityResult(verified, info, "raw-read-test")
        )

    def baseline_semantics(self, _capabilities):
        return (TelemetrySemantic.ANGLES,)

    def read_transaction(self, semantic, capabilities):
        capability = capabilities.telemetry_channel(semantic)
        payload = SamplePayload(
            semantic=semantic,
            raw=(self.value,) * len(capability.channels),
            origin=(
                DataOrigin.DEVICE_RESPONSE
                if capability.device_measured
                else DataOrigin.DEVICE_CONFIG_RESPONSE
            ),
        )
        return self.transaction(("read", semantic), payload)

    def command_transaction(self, semantic, values, capabilities):
        telemetry = {
            CommandSemantic.SPEEDS: TelemetrySemantic.CONFIGURED_SPEEDS,
            CommandSemantic.CURRENT_LIMITS: TelemetrySemantic.CURRENT_LIMITS,
            CommandSemantic.TORQUES: TelemetrySemantic.TORQUES,
            CommandSemantic.POSITION_KP: TelemetrySemantic.POSITION_KP,
            CommandSemantic.POSITION_KD: TelemetrySemantic.POSITION_KD,
            CommandSemantic.TORQUE_KD: TelemetrySemantic.TORQUE_KD,
        }[semantic]
        cached = (
            capabilities.telemetry_channel(telemetry).read_mode
            is ReadMode.COMMAND_CACHE
        )
        payload = SamplePayload(
            semantic=telemetry,
            raw=values if self.echo_value is None else (self.echo_value,) * len(values),
            origin=(
                DataOrigin.COMMAND_CACHE
                if cached
                else DataOrigin.DEVICE_CONFIG_RESPONSE
            ),
        )
        return self.transaction(
            ("write", semantic, values),
            payload,
            ack=not cached,
            publications=(payload,) if cached else (),
        )

    def operation_transaction(self, *_args):
        raise AssertionError("raw reads must not invoke management writes")

    def decode_report(self, *_args):
        return ()


@pytest.fixture
def rig(request):
    model = getattr(request, "param", "O6")
    rclpy.init()
    peer = RawReadPeer()

    def device_factory(configuration):
        return HandDevice(
            model=configuration.model,
            side=configuration.side,
            transport=peer,
            protocol_backend=peer,
            config=configuration.device_config,
        )

    driver = LinkerbotHandNode(
        device_factory=device_factory,
        parameter_overrides=[
            Parameter("model", value=model),
            Parameter("side", value="" if model == "L30" else "left"),
            Parameter("angles_hz", value=0.0),
        ],
    )
    consumer = Node("raw_read_consumer")
    executor = MultiThreadedExecutor(num_threads=5)
    executor.add_node(driver)
    executor.add_node(consumer)

    def spin_until(predicate, each=None):
        deadline = time.monotonic() + 5.0
        while not predicate() and time.monotonic() < deadline:
            if each is not None:
                each()
            executor.spin_once(timeout_sec=0.01)
        assert predicate()

    def call(semantic, timeout=0.5):
        client = consumer.create_client(
            GetRawValues, f"/linkerbot_hand/get_{semantic.value}"
        )
        try:
            spin_until(client.service_is_ready)
            future = client.call_async(GetRawValues.Request(timeout_s=timeout))
            spin_until(future.done)
            return future.result()
        finally:
            consumer.destroy_client(client)

    try:
        assert driver.trigger_configure() == TransitionCallbackReturn.SUCCESS
        assert peer.sent == ()
        assert driver.trigger_activate() == TransitionCallbackReturn.SUCCESS
        yield SimpleNamespace(
            driver=driver,
            peer=peer,
            consumer=consumer,
            call=call,
            spin_until=spin_until,
        )
    finally:
        executor.remove_node(driver)
        executor.remove_node(consumer)
        executor.shutdown(timeout_sec=5.0)
        driver.destroy_node()
        consumer.destroy_node()
        rclpy.try_shutdown()


@pytest.mark.parametrize("rig", SUPPORTED_MODELS, indirect=True)
def test_declared_raw_services_query_fresh_samples_over_dds(rig):
    device = rig.driver._require_device()
    capabilities = device.get_capabilities()
    services = {
        rig.driver.resolve_service_name(service.srv_name)
        for service in rig.driver._interfaces.management._services
    }
    for semantic in _CHANNELS:
        capability = capabilities.telemetry_channel(semantic)
        assert (f"/linkerbot_hand/get_{semantic.value}" in services) == (
            capability is not None
        )
        if capability is None or not capability.device_queried:
            continue
        states = []
        subscription = rig.consumer.create_subscription(
            HandTelemetry,
            f"/linkerbot_hand/state/{semantic.value}",
            states.append,
            STATE_QOS,
        )
        try:
            rig.spin_until(
                lambda subscription=subscription: rig.consumer.count_publishers(
                    subscription.topic_name
                )
            )
            for value in (12, 13):
                before = len(rig.peer.sent)
                old = getattr(device.get_snapshot(), semantic.value)
                rig.peer.value = value
                response = rig.call(semantic)
                assert response.success, response.message
                assert len(rig.peer.sent) == before + 1
                assert rig.peer.sent[-1] == ("read", semantic)
                state = response.state
                assert state.semantic == semantic.value
                assert list(state.raw) == [value] * len(capability.channels)
                assert state.meta.sequence > old.meta.sequence
                assert state.meta.valid and state.meta.connection_generation == 1
                assert state.device_queried
                assert state.device_measured is capability.device_measured
                assert state.raw_unit == (capability.raw_unit or "")
                assert state.raw_scale_note == (capability.raw_scale_note or "")
                assert state.unit_confidence == capability.unit_confidence.value
                rig.spin_until(
                    lambda states=states, sequence=state.meta.sequence: any(
                        s.meta.sequence == sequence for s in states
                    )
                )
        finally:
            rig.consumer.destroy_subscription(subscription)
    # Management queries never enable extra polling channels or send setters.
    assert not any(message[0] == "write" for message in rig.peer.sent)
    assert all(metrics.requested_hz == 0 for metrics in device.get_health().channels)


@pytest.mark.parametrize(
    "rig,semantic,setter,origin",
    [
        (
            "L6",
            TelemetrySemantic.CONFIGURED_SPEEDS,
            "set_speeds",
            SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE,
        ),
        (
            "O6",
            TelemetrySemantic.CURRENT_LIMITS,
            "set_current_limits",
            SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE,
        ),
        (
            "L30",
            TelemetrySemantic.CONFIGURED_SPEEDS,
            "set_speeds",
            SampleMetadata.ORIGIN_COMMAND_CACHE,
        ),
        (
            "L30",
            TelemetrySemantic.CURRENT_LIMITS,
            "set_current_limits",
            SampleMetadata.ORIGIN_COMMAND_CACHE,
        ),
        (
            "L20Lite",
            TelemetrySemantic.CONFIGURED_SPEEDS,
            "set_speeds",
            SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE,
        ),
        (
            "L20Lite",
            TelemetrySemantic.CURRENT_LIMITS,
            "set_current_limits",
            SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE,
        ),
    ],
    indirect=["rig"],
)
def test_command_derived_reads_preserve_cache_without_device_io(
    rig, semantic, setter, origin
):
    device = rig.driver._require_device()
    before = len(rig.peer.sent)
    missing = rig.call(semantic)
    assert not missing.success
    assert missing.error_code == ErrorCode.UNSUPPORTED_OPERATION.value
    assert not missing.state.meta.valid
    assert len(rig.peer.sent) == before

    count = len(device.get_capabilities().telemetry_channel(semantic).channels)
    command_capability = device.get_capabilities().command(
        CommandSemantic(setter.removeprefix("set_"))
    )
    values = [command_capability.range_for(index).minimum for index in range(count)]
    command = getattr(device, setter)(values)
    assert command.wait(1.0) in (CommandStage.DISPATCHED, CommandStage.ACKNOWLEDGED)
    first_sample = getattr(device.get_snapshot(), semantic.value)
    before = len(rig.peer.sent)
    for _ in range(2):
        response = rig.call(semantic)
        assert response.success, response.message
        assert list(response.state.raw) == values
        assert response.state.meta.origin == origin
        assert response.state.meta.sequence == first_sample.meta.sequence
        assert response.state.meta.age_s >= first_sample.meta.age_s
        assert response.state.meta.valid and response.state.meta.stale
        assert not response.state.device_queried
        assert not response.state.device_measured
        assert "no device query performed" in response.message
        cached = getattr(device.get_snapshot(), semantic.value)
        assert cached.meta.collected_at == first_sample.meta.collected_at
    assert len(rig.peer.sent) == before


@pytest.mark.parametrize("rig", ["O6", "L20", "L20Lite"], indirect=True)
def test_live_current_polling_is_separate_from_configuration(rig):
    device = rig.driver._require_device()
    has_echo_cache = device.get_capabilities().model in {"O6", "L20Lite"}
    services = {
        rig.driver.resolve_service_name(service.srv_name)
        for service in rig.driver._interfaces.management._services
    }
    for name in ("get_current_limits", "get_configured_speeds"):
        assert (
            rig.driver.resolve_service_name(f"~/{name}") in services
        ) is has_echo_cache
    for name in ("get_torques_limits", "get_effort_limits"):
        assert rig.driver.resolve_service_name(f"~/{name}") not in services

    states = []
    subscription = rig.consumer.create_subscription(
        HandTelemetry, "/linkerbot_hand/state/currents", states.append, STATE_QOS
    )
    try:
        rig.spin_until(lambda: rig.consumer.count_publishers(subscription.topic_name))
        assert rig.driver.set_parameters_atomically(
            [Parameter("current_hz", value=10.0)]
        ).successful
        rig.spin_until(lambda: any(state.meta.valid for state in states))
        state = next(state for state in states if state.meta.valid)
        assert state.semantic == "currents"
        assert state.device_measured and state.device_queried
        assert state.meta.origin == SampleMetadata.ORIGIN_DEVICE_RESPONSE
        assert list(state.raw) == [rig.peer.value] * len(state.channel_names)
        assert state.raw_unit == "count"
        limit_sample = device.get_snapshot().current_limits
        if has_echo_cache:
            assert limit_sample is not None and not limit_sample.meta.valid
        else:
            assert limit_sample is None
        assert not any(message[0] == "write" for message in rig.peer.sent)
    finally:
        rig.consumer.destroy_subscription(subscription)


_WRITE_RESPONSE_CASES = (
    (
        "L20Lite",
        CommandSemantic.SPEEDS,
        TelemetrySemantic.CONFIGURED_SPEEDS,
        "get_speeds",
    ),
    (
        "L20Lite",
        CommandSemantic.CURRENT_LIMITS,
        TelemetrySemantic.CURRENT_LIMITS,
        "get_currents",
    ),
    (
        "O6",
        CommandSemantic.CURRENT_LIMITS,
        TelemetrySemantic.CURRENT_LIMITS,
        "get_currents",
    ),
)


@pytest.mark.parametrize(
    "rig,command_semantic,feedback_semantic,live_getter",
    _WRITE_RESPONSE_CASES,
    indirect=["rig"],
)
def test_echo_topics_and_services_do_not_replace_live_measurements(
    rig, command_semantic, feedback_semantic, live_getter
):
    device = rig.driver._require_device()
    feedback_capability = device.get_capabilities().telemetry_channel(feedback_semantic)
    # The matching SDK source is required; an older SDK must fail, not skip.
    assert feedback_capability is not None
    assert feedback_capability.read_mode is ReadMode.COMMAND_RESPONSE
    count = len(feedback_capability.channels)
    actual = getattr(device, live_getter)(timeout=1)
    live_attribute = "measured_speeds" if live_getter == "get_speeds" else "currents"
    assert actual.raw == (11,) * count
    states, statuses = [], []
    state_subscription = rig.consumer.create_subscription(
        HandTelemetry,
        f"/linkerbot_hand/state/{feedback_semantic.value}",
        states.append,
        STATE_QOS,
    )
    status_subscription = rig.consumer.create_subscription(
        HandCommandStatusBatch,
        "/linkerbot_hand/command/status",
        lambda batch: statuses.extend(batch.statuses),
        STATUS_QOS,
    )
    publisher = rig.consumer.create_publisher(
        HandRawCommand, f"/linkerbot_hand/command/{command_semantic.value}", COMMAND_QOS
    )
    try:
        rig.spin_until(
            lambda: (
                publisher.get_subscription_count()
                and rig.consumer.count_publishers(state_subscription.topic_name)
                and rig.consumer.count_publishers(status_subscription.topic_name)
            )
        )
        rig.peer.echo_value = 190
        publisher.publish(
            HandRawCommand(client_id=41, user_sequence=7, raw=[200.0] * count)
        )
        rig.spin_until(
            lambda: any(
                status.client_id == 41
                and status.stage == HandCommandStatus.STAGE_ACKNOWLEDGED
                for status in statuses
            )
        )
        rig.spin_until(lambda: any(state.meta.valid for state in states))
        feedback = next(state for state in states if state.meta.valid)
        assert list(feedback.raw) == [190] * count
        assert feedback.meta.origin == SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE
        assert not feedback.device_measured and not feedback.device_queried
        assert feedback.raw_unit == "count"
        assert feedback.channel_names == list(feedback_capability.channels)
        assert feedback.meta.connection_generation == actual.meta.connection_generation
        unchanged = getattr(device.get_snapshot(), live_attribute)
        assert unchanged.raw == actual.raw
        assert unchanged.meta.sequence == actual.meta.sequence
        assert unchanged.meta.collected_at == actual.meta.collected_at
        assert rig.peer.sent[-1] == ("write", command_semantic, (200,) * count)
        cached = getattr(device.get_snapshot(), feedback_semantic.value)
        before = len(rig.peer.sent)
        response = rig.call(feedback_semantic)
        assert response.success
        assert list(response.state.raw) == [190] * count
        assert response.state.meta.sequence == feedback.meta.sequence
        assert response.state.meta.origin == feedback.meta.origin
        assert not response.state.device_measured and not response.state.device_queried
        assert (
            getattr(device.get_snapshot(), feedback_semantic.value).meta.collected_at
            == cached.meta.collected_at
        )
        assert len(rig.peer.sent) == before
        rig.peer.value = 12
        new_actual = getattr(device, live_getter)(timeout=1)
        assert new_actual.raw == (12,) * count
        assert new_actual.meta.origin is DataOrigin.DEVICE_RESPONSE
        assert new_actual.meta.sequence > actual.meta.sequence
        assert rig.peer.sent[-1] == ("read", TelemetrySemantic(live_attribute))
        assert (
            getattr(device.get_snapshot(), feedback_semantic.value).raw
            == (190,) * count
        )
        assert (
            getattr(device.get_snapshot(), feedback_semantic.value).meta.collected_at
            == cached.meta.collected_at
        )
    finally:
        rig.consumer.destroy_publisher(publisher)
        rig.consumer.destroy_subscription(state_subscription)
        rig.consumer.destroy_subscription(status_subscription)


@pytest.mark.parametrize(
    "rig,command_semantic,feedback_semantic,live_getter",
    _WRITE_RESPONSE_CASES,
    indirect=["rig"],
)
def test_failed_echo_keeps_cache_service_unavailable_without_querying(
    rig, command_semantic, feedback_semantic, live_getter
):
    device = rig.driver._require_device()
    capability = device.get_capabilities().telemetry_channel(feedback_semantic)
    assert capability is not None and capability.read_mode is ReadMode.COMMAND_RESPONSE
    rig.peer.drop_writes = True
    handle = getattr(device, "set_" + command_semantic.value)(
        [200] * len(capability.channels)
    )
    assert handle.wait(1) is CommandStage.FAILED
    assert handle.error.code is ErrorCode.TIMEOUT
    before = len(rig.peer.sent)
    response = rig.call(feedback_semantic)
    assert not response.success
    assert response.error_code == ErrorCode.UNSUPPORTED_OPERATION.value
    assert not response.state.meta.valid
    assert len(rig.peer.sent) == before
    assert getattr(device, live_getter)(timeout=1).raw == (11,) * len(
        capability.channels
    )


@pytest.mark.parametrize("rig", ["O6"], indirect=True)
def test_o6_failed_limit_write_preserves_the_last_complete_echo(rig):
    device = rig.driver._require_device()
    rig.peer.echo_value = 190
    handle = device.set_current_limits([200] * 6)
    assert handle.wait(1) is CommandStage.ACKNOWLEDGED
    cached = device.get_snapshot().current_limits
    rig.peer.drop_writes = True
    failed = device.set_current_limits([210] * 6)
    assert failed.wait(1) is CommandStage.FAILED
    assert failed.error.code is ErrorCode.TIMEOUT

    before = len(rig.peer.sent)
    response = rig.call(TelemetrySemantic.CURRENT_LIMITS)
    assert response.success
    assert list(response.state.raw) == [190] * 6
    assert response.state.meta.sequence == cached.meta.sequence
    assert (
        response.state.meta.connection_generation == cached.meta.connection_generation
    )
    assert response.state.meta.origin == SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE
    assert (
        device.get_snapshot().current_limits.meta.collected_at
        == cached.meta.collected_at
    )
    assert len(rig.peer.sent) == before


@pytest.mark.parametrize("rig", ["O6"], indirect=True)
def test_o6_recovery_invalidates_limit_cache_until_a_new_write_echo(rig):
    device = rig.driver._require_device()
    rig.peer.echo_value = 190
    handle = device.set_current_limits([200] * 6)
    assert handle.wait(1) is CommandStage.ACKNOWLEDGED
    old = device.get_snapshot().current_limits
    assert old.meta.valid and old.raw == (190,) * 6

    states = []
    subscription = rig.consumer.create_subscription(
        HandTelemetry, "/linkerbot_hand/state/current_limits", states.append, STATE_QOS
    )
    recovery = rig.consumer.create_client(Recover, "/linkerbot_hand/recover")
    try:
        rig.spin_until(
            lambda: (
                rig.consumer.count_publishers(subscription.topic_name)
                and recovery.service_is_ready()
            )
        )
        future = recovery.call_async(Recover.Request(timeout_s=1.0))
        rig.spin_until(future.done)
        assert future.result().success, future.result().message
        snapshot = device.get_snapshot()
        generation = snapshot.connection_generation
        assert generation > old.meta.connection_generation
        assert snapshot.current_limits is not None
        assert not snapshot.current_limits.meta.valid
        assert snapshot.current_limits.meta.connection_generation == generation
        before = len(rig.peer.sent)
        missing = rig.call(TelemetrySemantic.CURRENT_LIMITS)
        assert not missing.success
        assert missing.error_code == ErrorCode.UNSUPPORTED_OPERATION.value
        assert not missing.state.meta.valid
        assert len(rig.peer.sent) == before

        # Live current can refresh without making the new limit cache valid.
        rig.peer.value = 12
        measured = device.get_currents(timeout=1)
        assert measured.raw == (12,) * 6
        assert measured.meta.connection_generation == generation
        assert not device.get_snapshot().current_limits.meta.valid
        rig.spin_until(
            lambda: any(
                s.meta.connection_generation == generation and not s.meta.valid
                for s in states
            )
        )
        assert not any(
            s.meta.connection_generation == generation and s.meta.valid for s in states
        )

        rig.peer.echo_value = 180
        handle = device.set_current_limits([200] * 6)
        assert handle.wait(1) is CommandStage.ACKNOWLEDGED
        response = rig.call(TelemetrySemantic.CURRENT_LIMITS)
        assert response.success
        assert list(response.state.raw) == [180] * 6
        assert response.state.meta.connection_generation == generation
        assert (
            response.state.meta.origin == SampleMetadata.ORIGIN_DEVICE_CONFIG_RESPONSE
        )
        assert not response.state.device_measured and not response.state.device_queried
        rig.spin_until(
            lambda: any(
                s.meta.connection_generation == generation
                and s.meta.valid
                and list(s.raw) == [180] * 6
                for s in states
            )
        )
        unchanged = device.get_snapshot().currents
        assert unchanged.raw == measured.raw
        assert unchanged.meta.sequence == measured.meta.sequence
        assert unchanged.meta.collected_at == measured.meta.collected_at
    finally:
        rig.consumer.destroy_client(recovery)
        rig.consumer.destroy_subscription(subscription)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf"), 1.9])
def test_raw_read_rejects_invalid_timeout_before_device_io(rig, timeout):
    before = len(rig.peer.sent)
    response = rig.call(TelemetrySemantic.CONFIGURED_SPEEDS, timeout)
    assert not response.success
    assert response.error_code == ErrorCode.VALIDATION.value
    assert len(rig.peer.sent) == before


def test_raw_read_reports_timeout_without_successful_state(rig):
    rig.peer.drop_reads = True
    response = rig.call(TelemetrySemantic.CONFIGURED_SPEEDS, 0.05)
    assert not response.success
    assert response.error_code == ErrorCode.TIMEOUT.value
    assert not response.state.meta.valid


def test_firmware_disabled_read_is_rejected_without_io(rig, monkeypatch):
    device = rig.driver._require_device()
    capabilities = replace(
        device.get_capabilities(),
        firmware_unsupported_telemetry=(TelemetrySemantic.CONFIGURED_SPEEDS,),
    )
    monkeypatch.setattr(device, "get_capabilities", lambda: capabilities)
    before = len(rig.peer.sent)
    response = rig.call(TelemetrySemantic.CONFIGURED_SPEEDS)
    assert not response.success
    assert response.error_code == ErrorCode.UNSUPPORTED_FIRMWARE.value
    assert len(rig.peer.sent) == before


@pytest.mark.parametrize("closed_gate", [False, True])
def test_raw_read_rejects_inactive_or_closing_driver(rig, closed_gate):
    if closed_gate:
        rig.driver._interfaces._gate.close(0.5)
    else:
        assert rig.driver.trigger_deactivate() == TransitionCallbackReturn.SUCCESS
    before = len(rig.peer.sent)
    response = rig.call(TelemetrySemantic.CONFIGURED_SPEEDS)
    assert not response.success
    assert response.error_code == ErrorCode.DEVICE_NOT_READY.value
    assert len(rig.peer.sent) == before


def test_slow_raw_read_does_not_block_same_hand_command_admission(rig, monkeypatch):
    device = rig.driver._require_device()
    entered = threading.Event()
    release = threading.Event()
    getter = device.get_configured_speeds
    threads = []
    admitted = []

    def slow_read(timeout):
        threads.append(threading.current_thread().name)
        entered.set()
        assert release.wait(5.0)
        return getter(timeout)

    monkeypatch.setattr(device, "get_configured_speeds", slow_read)

    # Observe ROS admission separately from the SDK's serial device transactions.
    def record_command(_values):
        admitted.append(True)
        raise RuntimeError("test stops after proving command callback admission")

    monkeypatch.setattr(device, "set_angles", record_command)
    client = rig.consumer.create_client(
        GetRawValues, "/linkerbot_hand/get_configured_speeds"
    )
    publisher = rig.consumer.create_publisher(
        HandJointCommand, "/linkerbot_hand/command/angles", COMMAND_QOS
    )
    try:
        rig.spin_until(
            lambda: client.service_is_ready() and publisher.get_subscription_count()
        )
        future = client.call_async(GetRawValues.Request(timeout_s=1.8))
        rig.spin_until(entered.is_set)
        command = HandJointCommand(
            client_id=1,
            user_sequence=1,
            representation=HandJointCommand.REPRESENTATION_RAW,
            values=[12.0] * 6,
        )
        rig.spin_until(lambda: bool(admitted), each=lambda: publisher.publish(command))
        assert not future.done()
        assert threads == ["linkerbot_hand-admin"]
        release.set()
        rig.spin_until(future.done)
        assert future.result().success
    finally:
        release.set()
        rig.consumer.destroy_client(client)
        rig.consumer.destroy_publisher(publisher)
