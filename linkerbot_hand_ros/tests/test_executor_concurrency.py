"""Concurrency contracts for the multi-threaded driver executor."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from types import SimpleNamespace

import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand import LifecycleError
from linkerbot_hand_ros.multi_device import CONTAINER_CALLBACK_GROUPS
from linkerbot_hand_ros.node import (
    CALLBACK_GROUPS_PER_HAND,
    LinkerbotHandNode,
    spin_until_shutdown,
)
from linkerbot_hand_ros.qos import COMMAND_QOS
from rclpy.exceptions import InvalidHandle
from rclpy.executors import MultiThreadedExecutor
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


@pytest.fixture
def two_hand_rig():
    """Run two activated hands and a client in one MultiThreadedExecutor."""

    rclpy.init()
    builders = {"left": DeviceBuilder(), "right": DeviceBuilder()}
    nodes: dict[str, LinkerbotHandNode] = {}
    client_node: Node | None = None
    executor: MultiThreadedExecutor | None = None
    spin_thread: threading.Thread | None = None
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
            target=spin_until_shutdown,
            args=(executor, client_node.get_logger()),
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
        if executor is not None:
            # Detach entities before shutting the pool down, matching the
            # multi_device entry point, so no handler races destruction.
            for node in nodes.values():
                executor.remove_node(node)
            if client_node is not None:
                executor.remove_node(client_node)
            executor.shutdown(timeout_sec=_DEADLINE_S)
        if spin_thread is not None:
            spin_thread.join(_DEADLINE_S)
        for node in nodes.values():
            node.destroy_node()
        if client_node is not None:
            client_node.destroy_node()
        rclpy.try_shutdown()


def test_slow_management_read_does_not_stall_the_other_hand(two_hand_rig):
    left_runtime = two_hand_rig.builders["left"].latest_runtime
    right_runtime = two_hand_rig.builders["right"].latest_runtime
    left_runtime.device_info_gate = threading.Event()

    client = two_hand_rig.client.create_client(
        GetDeviceInfo,
        "/left/linkerbot_hand/get_device_info",
    )
    assert client.wait_for_service(_DEADLINE_S)
    pending = client.call_async(GetDeviceInfo.Request(timeout_s=_SERVICE_TIMEOUT_S))

    # The left hand is now inside read_device_info, so its management callback
    # holds the executor thread of its own callback group and the gate with it.
    assert left_runtime.device_info_entered.wait(_DEADLINE_S)
    assert two_hand_rig.nodes["left"]._interfaces._gate.in_flight == 1

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
    # COMMAND_QOS is best effort, so keep resending while waiting for delivery.
    delivered = _wait_until(
        lambda: bool(right_runtime.submissions),
        each=lambda: publisher.publish(message),
    )
    left_still_blocked = not pending.done()
    left_runtime.device_info_gate.set()

    assert delivered, "the right hand never received a command while left blocked"
    assert left_still_blocked, "the left read finished too early to prove isolation"
    assert left_runtime.device_info_threads == ["linkerbot_hand-admin"]


def test_diagnostics_keep_publishing_while_a_management_read_blocks(two_hand_rig):
    left_runtime = two_hand_rig.builders["left"].latest_runtime
    left_runtime.device_info_gate = threading.Event()
    before = left_runtime.health_get_count

    client = two_hand_rig.client.create_client(
        GetDeviceInfo,
        "/left/linkerbot_hand/get_device_info",
    )
    assert client.wait_for_service(_DEADLINE_S)
    pending = client.call_async(GetDeviceInfo.Request(timeout_s=_SERVICE_TIMEOUT_S))
    assert left_runtime.device_info_entered.wait(_DEADLINE_S)

    # The diagnostic group has a thread of its own, so get_health() keeps running
    # on the very hand whose management group is blocked.
    published = _wait_until(lambda: left_runtime.health_get_count > before)
    left_still_blocked = not pending.done()
    left_runtime.device_info_gate.set()

    assert published, "diagnostics stopped while the management read blocked"
    assert left_still_blocked, "the left read finished too early to prove isolation"


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
