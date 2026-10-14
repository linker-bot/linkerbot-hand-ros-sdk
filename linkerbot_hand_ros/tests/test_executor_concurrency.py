"""Concurrency contracts for the multi-threaded driver executor."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from types import SimpleNamespace

import pytest
import rclpy
from diagnostic_msgs.msg import DiagnosticArray
from fakes_v1 import DeviceBuilder
from linkerbot_hand import LifecycleError
from linkerbot_hand_ros.executor import MultiThreadedExecutor
from linkerbot_hand_ros.management import _worker_timeout
from linkerbot_hand_ros.multi_device import CONTAINER_CALLBACK_GROUPS
from linkerbot_hand_ros.node import (
    CALLBACK_GROUPS_PER_HAND,
    LinkerbotHandNode,
    spin_until_shutdown,
)
from linkerbot_hand_ros.qos import COMMAND_QOS, STATE_QOS
from rclpy.exceptions import InvalidHandle
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.node import Node
from rclpy.parameter import Parameter

from linkerbot_hand_msgs.msg import HandJointCommand
from linkerbot_hand_msgs.srv import GetDeviceInfo

_DEADLINE_S = 5.0
# _worker_timeout() adds 10%, so this stays under the 2.0 s shutdown_timeout_s.
_SERVICE_TIMEOUT_S = 1.8


def _wait_until(
    predicate: Callable[[], bool],
    *,
    each: Callable[[], None] | None = None,
    timeout_s: float = _DEADLINE_S,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if each is not None:
            each()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _release_device_info_gates(builders) -> None:
    for builder in builders:
        for factory in builder.runtime_factories:
            runtime = factory.runtime
            if runtime is not None and runtime.device_info_gate is not None:
                runtime.device_info_gate.set()


def _assert_progress_during_read(
    pending,
    runtime,
    predicate,
    *,
    label: str,
    requested_at: float,
    each=None,
) -> None:
    entered_at = runtime.device_info_started_at
    assert entered_at is not None
    budget = _worker_timeout(_SERVICE_TIMEOUT_S)
    deadline = entered_at + budget
    finished_at = []
    pending.add_done_callback(lambda _future: finished_at.append(time.monotonic()))
    progressed = False
    while time.monotonic() < deadline and not pending.done():
        if each is not None:
            each()
        if predicate() and time.monotonic() < deadline:
            progressed = True
            break
        time.sleep(0.01)
    still_blocked = not pending.done()
    if not progressed or not still_blocked:
        # Keep the failed observation; waiting here only captures the response
        # for diagnosis, never turns a late callback into proof of isolation.
        _wait_until(pending.done)
    response = pending.result() if pending.done() else None
    result = (
        "pending"
        if response is None
        else f"success={response.success}, error_code={response.error_code}, "
        f"message={response.message!r}"
    )
    health_times = [
        round(timestamp - entered_at, 3)
        for timestamp in runtime.health_get_times
        if timestamp >= entered_at
    ]
    details = (
        f"request_to_read={entered_at - requested_at:.3f}s, "
        f"worker_budget={budget:.3f}s, "
        f"read_elapsed={time.monotonic() - entered_at:.3f}s, "
        f"health_times={health_times}, "
        f"response_at={[round(value - entered_at, 3) for value in finished_at]}, "
        f"response=({result})"
    )
    assert progressed, f"{label} made no progress during the blocked read; {details}"
    assert still_blocked, f"management read completed before proving {label}; {details}"


@pytest.fixture
def two_hand_rig(shutdown_ros_executor):
    """Run two activated hands and a client in one MultiThreadedExecutor."""

    rclpy.init()
    builders = {"left": DeviceBuilder(), "right": DeviceBuilder()}
    nodes: dict[str, LinkerbotHandNode] = {}
    client_node: Node | None = None
    executor: MultiThreadedExecutor | None = None
    spin_thread: threading.Thread | None = None
    stop_spin = threading.Event()
    spin_errors = []

    def spin():
        try:
            while not stop_spin.is_set():
                executor.spin_once(timeout_sec=0.05)
        except Exception as error:
            spin_errors.append(error)
            raise

    try:
        for side, builder in builders.items():
            node = LinkerbotHandNode(device_factory=builder, namespace=f"/{side}")
            nodes[side] = node
            assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
            assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
        client_node = Node("executor_concurrency_client")
        executor = MultiThreadedExecutor(
            num_threads=(
                CONTAINER_CALLBACK_GROUPS + CALLBACK_GROUPS_PER_HAND * len(nodes)
            )
        )
        for node in nodes.values():
            executor.add_node(node)
        executor.add_node(client_node)
        spin_thread = threading.Thread(
            target=spin,
            name="test-executor",
            daemon=True,
        )
        spin_thread.start()
        yield SimpleNamespace(
            nodes=nodes,
            builders=builders,
            client=client_node,
            spin_thread=spin_thread,
        )
    finally:
        _release_device_info_gates(builders.values())
        stop_spin.set()
        if spin_thread is not None:
            executor.wake()
            spin_thread.join(_DEADLINE_S)
            assert not spin_thread.is_alive(), "ROS executor spin thread did not stop"
        if executor is not None:
            shutdown_ros_executor(executor)
        for node in nodes.values():
            node.destroy_node()
        if client_node is not None:
            client_node.destroy_node()
        rclpy.try_shutdown()
        assert not spin_errors, f"ROS executor spin failed: {spin_errors}"


def test_slow_management_read_does_not_stall_the_other_hand(two_hand_rig):
    left_runtime = two_hand_rig.builders["left"].latest_runtime
    right_runtime = two_hand_rig.builders["right"].latest_runtime
    left_runtime.device_info_gate = threading.Event()

    client = two_hand_rig.client.create_client(
        GetDeviceInfo,
        "/left/linkerbot_hand/get_device_info",
    )
    assert client.wait_for_service(_DEADLINE_S)
    publisher = two_hand_rig.client.create_publisher(
        HandJointCommand,
        "/right/linkerbot_hand/command/angles",
        COMMAND_QOS,
    )
    assert _wait_until(lambda: publisher.get_subscription_count() > 0)
    message = HandJointCommand(
        client_id=1,
        user_sequence=7,
        representation=HandJointCommand.REPRESENTATION_PERCENT,
        values=[50.0] * 6,
    )
    # Complete DDS discovery before spending the management timeout budget.
    requested_at = time.monotonic()
    pending = client.call_async(GetDeviceInfo.Request(timeout_s=_SERVICE_TIMEOUT_S))
    try:
        assert left_runtime.device_info_entered.wait(_DEADLINE_S)
        assert two_hand_rig.nodes["left"]._interfaces._gate.in_flight >= 1
        # COMMAND_QOS is best effort, so resend only while the left read blocks.
        _assert_progress_during_read(
            pending,
            left_runtime,
            lambda: bool(right_runtime.submissions),
            each=lambda: publisher.publish(message),
            label="right-hand command",
            requested_at=requested_at,
        )
    finally:
        left_runtime.device_info_gate.set()
    assert left_runtime.device_info_threads == ["linkerbot_hand-admin"]


def test_diagnostics_keep_publishing_while_a_management_read_blocks(two_hand_rig):
    left_runtime = two_hand_rig.builders["left"].latest_runtime
    left_runtime.device_info_gate = threading.Event()
    received = []

    def diagnostic(message):
        if any(
            status.name == "/left/linkerbot_hand: hand_driver"
            for status in message.status
        ):
            received.append(time.monotonic())

    # The client node owns this subscription. The fixture destroys it only
    # after stopping the executor, so no callback races its destruction.
    two_hand_rig.client.create_subscription(
        DiagnosticArray, "/diagnostics", diagnostic, STATE_QOS
    )
    assert _wait_until(
        lambda: two_hand_rig.client.count_publishers("/diagnostics") == 2
    )
    assert _wait_until(lambda: bool(received))

    client = two_hand_rig.client.create_client(
        GetDeviceInfo,
        "/left/linkerbot_hand/get_device_info",
    )
    assert client.wait_for_service(_DEADLINE_S)
    requested_at = time.monotonic()
    pending = client.call_async(GetDeviceInfo.Request(timeout_s=_SERVICE_TIMEOUT_S))
    try:
        assert left_runtime.device_info_entered.wait(_DEADLINE_S)
        before = left_runtime.health_get_count
        observed_at = time.monotonic()
        # Both the health read and a newly received diagnostic must happen
        # after confirmation that management is blocked, within its budget.
        _assert_progress_during_read(
            pending,
            left_runtime,
            lambda: (
                left_runtime.health_get_count > before
                and any(timestamp > observed_at for timestamp in received)
            ),
            label="diagnostics",
            requested_at=requested_at,
        )
    finally:
        left_runtime.device_info_gate.set()


def test_pre_read_health_change_does_not_prove_concurrency(two_hand_rig, monkeypatch):
    runtime = two_hand_rig.builders["left"].latest_runtime
    runtime.device_info_gate = threading.Event()
    two_hand_rig.nodes["left"]._interfaces.diagnostic_timer.cancel()
    read = runtime.read_device_info
    health = runtime.get_health
    original_count = runtime.health_get_count

    def read_with_prior_health_change(timeout):
        health()
        return read(timeout)

    # Even a timer callback already queued before cancellation cannot produce
    # a post-entry health observation in this deliberately broken scenario.
    monkeypatch.setattr(runtime, "get_health", lambda: runtime.health)
    monkeypatch.setattr(runtime, "read_device_info", read_with_prior_health_change)
    client = two_hand_rig.client.create_client(
        GetDeviceInfo, "/left/linkerbot_hand/get_device_info"
    )
    assert client.wait_for_service(_DEADLINE_S)
    requested_at = time.monotonic()
    pending = client.call_async(GetDeviceInfo.Request(timeout_s=_SERVICE_TIMEOUT_S))
    try:
        assert runtime.device_info_entered.wait(_DEADLINE_S)
        before = runtime.health_get_count
        assert before > original_count
        with pytest.raises(AssertionError, match=r"diagnostics.*error_code=timeout"):
            _assert_progress_during_read(
                pending,
                runtime,
                lambda: runtime.health_get_count > before,
                label="diagnostics",
                requested_at=requested_at,
            )
        assert not pending.result().success
        assert pending.result().error_code == "timeout"
    finally:
        runtime.device_info_gate.set()


def test_executor_cleanup_drains_queued_ros_callbacks(shutdown_ros_executor):
    """A queued ROS handler must run before the executor destroys its guard."""

    rclpy.init()
    node = Node("executor_cleanup_client")
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    release = threading.Event()
    called = threading.Event()
    release_timer = None

    def occupy_worker(started):
        started.set()
        assert release.wait(_DEADLINE_S), "executor worker was not released"

    try:
        # Occupy both threads so the real ROS guard handler is still queued
        # when cleanup starts. Base shutdown first would invalidate its guard.
        for _ in range(2):
            started = threading.Event()
            executor.create_task(occupy_worker, started)
            assert _wait_until(
                started.is_set, each=lambda: executor.spin_once(timeout_sec=0.01)
            )
        guard = node.create_guard_condition(called.set)
        guard.trigger()
        executor.spin_once(timeout_sec=1.0)
        assert not called.is_set()
        release_timer = threading.Timer(0.05, release.set)
        release_timer.start()
        shutdown_ros_executor(executor)
        assert called.is_set(), "queued ROS callback was lost during cleanup"
    finally:
        release.set()
        if release_timer is not None:
            release_timer.join(_DEADLINE_S)
        shutdown_ros_executor(executor)
        node.destroy_node()
        rclpy.try_shutdown()


class _FlakyExecutor:
    """Fail ``failures`` spins with the exception rclpy raises for dead handles."""

    def __init__(self, *, failures: int) -> None:
        self.calls = 0
        self._failures = failures

    def spin(self) -> None:
        self.calls += 1
        if self.calls <= self._failures:
            raise InvalidHandle(
                "cannot use Destroyable because destruction was requested"
            )


def test_spin_tolerates_a_destroyed_entity_and_resumes() -> None:
    rclpy.init()
    warnings: list[str] = []
    executor = _FlakyExecutor(failures=1)
    try:
        spin_until_shutdown(executor, SimpleNamespace(warning=warnings.append))
    finally:
        rclpy.try_shutdown()

    assert executor.calls == 2, "spin did not resume after the destroyed entity"
    assert len(warnings) == 1
    assert "lifecycle transition" in warnings[0]


def test_spin_stops_retrying_once_the_context_is_shut_down() -> None:
    rclpy.init()
    rclpy.try_shutdown()
    executor = _FlakyExecutor(failures=5)

    spin_until_shutdown(executor, SimpleNamespace(warning=lambda _message: None))

    assert executor.calls == 1


@pytest.fixture
def configured_node():
    """Configure one hand with a short shutdown budget and no executor."""

    rclpy.init()
    builder = DeviceBuilder()
    node = LinkerbotHandNode(
        device_factory=builder,
        parameter_overrides=[Parameter("shutdown_timeout_s", value=0.3)],
    )
    try:
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        yield node, builder
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


def _hold_gate(gate) -> tuple[threading.Event, threading.Event, threading.Thread]:
    admitted = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with gate.admit() as ok:
            assert ok
            admitted.set()
            release.wait(_DEADLINE_S)

    worker = threading.Thread(target=hold, name="test-gate-holder", daemon=True)
    worker.start()
    assert admitted.wait(_DEADLINE_S)
    return admitted, release, worker


def test_destroy_waits_for_an_in_flight_callback(configured_node) -> None:
    node, _builder = configured_node
    interfaces = node._interfaces
    _admitted, release, worker = _hold_gate(interfaces._gate)
    held_s = 0.15
    threading.Timer(held_s, release.set).start()

    started_at = time.monotonic()
    interfaces.destroy()
    elapsed = time.monotonic() - started_at

    assert elapsed >= held_s * 0.8, "destruction did not wait for the callback"
    assert interfaces.management is None
    assert interfaces.diagnostic_timer is None
    release.set()
    worker.join(_DEADLINE_S)


def test_destroy_keeps_entities_when_a_callback_outlives_the_timeout(
    configured_node,
) -> None:
    node, _builder = configured_node
    interfaces = node._interfaces
    _admitted, release, worker = _hold_gate(interfaces._gate)
    try:
        # Destroying entities now could re-raise InvalidHandle out of spin(), so
        # destruction must fail and keep every entity alive instead.
        with pytest.raises(LifecycleError, match="kept alive"):
            interfaces.destroy()
        assert interfaces.management is not None
        assert interfaces.diagnostic_timer is not None
    finally:
        release.set()
        worker.join(_DEADLINE_S)

    # With the callback gone the same destruction is safe and completes.
    interfaces.destroy()
    assert interfaces.management is None
    assert interfaces.diagnostic_timer is None
