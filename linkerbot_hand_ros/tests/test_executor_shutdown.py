"""Production entry points drain submitted ROS handlers before destroying guards."""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand_ros.executor import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.task import Future

from linkerbot_hand_ros import multi_device
from linkerbot_hand_ros import node as entry


@pytest.mark.parametrize("mode", ["single", "multi"])
def test_entry_point_finishes_queued_ros_handler_before_shutdown(monkeypatch, mode):
    tasks = []
    release, called = threading.Event(), threading.Event()
    timer = None
    thread_count = entry.CALLBACK_GROUPS_PER_HAND
    module = entry
    if mode == "multi":
        module = multi_device
        thread_count = multi_device.CONTAINER_CALLBACK_GROUPS + 2 * thread_count
        container_type = multi_device.MultiHandContainerNode
        monkeypatch.setattr(
            multi_device,
            "MultiHandContainerNode",
            lambda: container_type(
                parameter_overrides=[
                    Parameter("device_namespaces", value=["/left", "/right"]),
                    Parameter("autostart", value=False),
                ]
            ),
        )
        create_nodes = multi_device.create_hand_nodes
        monkeypatch.setattr(
            multi_device,
            "create_hand_nodes",
            lambda configuration: create_nodes(
                configuration,
                node_factory=lambda namespace: entry.LinkerbotHandNode(
                    device_factory=DeviceBuilder(), namespace=namespace
                ),
            ),
        )

    def spin(executor, logger):
        nonlocal timer
        for _ in range(thread_count):
            started = threading.Event()

            def occupy(event=started):
                event.set()
                assert release.wait(3.0)

            task = executor.create_task(occupy)
            tasks.append(task)
            deadline = time.monotonic() + 2.0
            while not started.is_set():
                assert time.monotonic() < deadline
                executor.spin_once(timeout_sec=0.01)
        node = executor.get_nodes()[0]
        ready_callbacks = executor.wait_for_ready_callbacks

        def capture(*args, **kwargs):
            ready = ready_callbacks(*args, **kwargs)
            tasks.append(ready[0])
            return ready

        monkeypatch.setattr(executor, "wait_for_ready_callbacks", capture)
        guard = node.create_guard_condition(called.set)
        guard.trigger()
        executor.spin_once(timeout_sec=1.0)
        assert not called.is_set()
        timer = threading.Timer(0.15, release.set)
        timer.start()

    monkeypatch.setattr(module, "spin_until_shutdown", spin)
    try:
        module.main(args=[])
        assert called.is_set()
        for task in tasks:
            assert task.done()
            assert task.exception() is None
    finally:
        release.set()
        if timer is not None:
            timer.join(2.0)


def test_executor_timeout_retains_handles_until_retry():
    rclpy.init(args=[])
    node = Node("executor_timeout")
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    entered, release, called = threading.Event(), threading.Event(), threading.Event()
    tasks = []

    def occupy():
        entered.set()
        assert release.wait(3.0)

    try:
        for _ in range(2):
            entered.clear()
            tasks.append(executor.create_task(occupy))
            deadline = time.monotonic() + 2.0
            while not entered.is_set():
                assert time.monotonic() < deadline
                executor.spin_once(timeout_sec=0.01)
        guard = node.create_guard_condition(called.set)
        guard.trigger()
        executor.spin_once(timeout_sec=1.0)
        assert not executor.shutdown(timeout_sec=0.01)
        assert node.get_name() == "executor_timeout"
        assert rclpy.ok()
        release.set()
        assert executor.shutdown(timeout_sec=2.0)
        assert called.is_set()
        assert all(task.done() and task.exception() is None for task in tasks)
        assert executor.shutdown(timeout_sec=0.0)
    finally:
        release.set()
        executor.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()


def test_shutdown_reports_last_callback_error_and_joins_threads(monkeypatch):
    import linkerbot_hand_ros.executor as executor_module

    before = set(threading.enumerate())
    rclpy.init(args=[])
    executor = MultiThreadedExecutor(num_threads=2)
    errors = []
    release = threading.Event()

    class Logger:
        def error(self, message):
            errors.append(message)

    monkeypatch.setattr(executor_module, "get_logger", lambda _name: Logger())

    def fail():
        assert release.wait(2.0)
        raise ValueError("last callback failure")

    task = executor.create_task(fail)
    try:
        executor.spin_once(timeout_sec=0.01)
        release.set()
        deadline = time.monotonic() + 2.0
        while not task.done():
            assert time.monotonic() < deadline
            threading.Event().wait(0.001)
        assert executor.shutdown(timeout_sec=2.0)
        assert errors == [
            "callback failed during shutdown: ValueError: last callback failure"
        ]
        assert not any(
            thread.is_alive() for thread in set(threading.enumerate()) - before
        )
    finally:
        release.set()
        executor.shutdown()
        rclpy.try_shutdown()


def test_executor_spins_until_public_future_completes():
    rclpy.init(args=[])
    executor = MultiThreadedExecutor(num_threads=2)
    try:
        future = executor.create_task(lambda: 42)
        executor.spin_until_future_complete(future, timeout_sec=2.0)
        assert future.done() and future.result() == 42
    finally:
        assert executor.shutdown(timeout_sec=2.0)
        rclpy.try_shutdown()


@pytest.mark.parametrize("wait_for_future", [False, True])
def test_executor_serves_each_continuously_ready_timer(wait_for_future):
    rclpy.init(args=[])
    node = Node("executor_ready_fairness")
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    counts = [0, 0]
    completed = threading.Event()
    future = Future()

    def callback(index):
        counts[index] += 1
        completed.set()

    node.create_timer(0.005, lambda: callback(0))
    node.create_timer(0.005, lambda: callback(1))
    try:
        for _ in range(20):
            # Both timers are ready at every spin. Wait for the previous
            # callback so pool saturation cannot hide a scheduling defect.
            time.sleep(0.01)
            completed.clear()
            if wait_for_future:
                executor.spin_once_until_future_complete(future, timeout_sec=0.1)
            else:
                executor.spin_once(timeout_sec=0.1)
            assert completed.wait(1.0)
        assert counts == [10, 10], f"ready callbacks were skipped: {counts}"
    finally:
        executor.remove_node(node)
        assert executor.shutdown(timeout_sec=2.0)
        node.destroy_node()
        rclpy.try_shutdown()


def test_future_deadline_preserves_later_ready_callbacks(monkeypatch):
    rclpy.init(args=[])
    node = Node("executor_future_fairness")
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    future = Future()
    node.create_timer(0.005, lambda: None)
    node.create_timer(0.005, lambda: future.set_result(42))
    spin_once = executor.spin_once_until_future_complete

    def paced_spin(*args, **kwargs):
        # Keep both timers ready throughout a real finite-deadline wait.
        time.sleep(0.01)
        spin_once(*args, **kwargs)

    monkeypatch.setattr(executor, "spin_once_until_future_complete", paced_spin)
    try:
        executor.spin_until_future_complete(future, timeout_sec=0.5)
        assert future.done(), "the later ready timer never completed its future"
        assert future.result() == 42
    finally:
        executor.remove_node(node)
        assert executor.shutdown(timeout_sec=2.0)
        node.destroy_node()
        rclpy.try_shutdown()


@pytest.mark.parametrize("mode", ["single", "multi"])
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_default_signal_shutdown_drains_real_callbacks(mode, signum):
    source = r"""
import os
import signal
import sys
import threading
import time

sys.path.insert(0, TEST_HELPERS)
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand_ros import node as entry, multi_device
from rclpy.parameter import Parameter

module = entry if MODE == "single" else multi_device
if MODE == "multi":
    container_type = multi_device.MultiHandContainerNode
    multi_device.MultiHandContainerNode = lambda: container_type(
        parameter_overrides=[
            Parameter("device_namespaces", value=["/left", "/right"]),
            Parameter("autostart", value=False),
        ]
    )
    create_nodes = multi_device.create_hand_nodes
    multi_device.create_hand_nodes = lambda cfg: create_nodes(
        cfg, node_factory=lambda namespace: entry.LinkerbotHandNode(
            device_factory=DeviceBuilder(), namespace=namespace
        )
    )

count = 4 if MODE == "single" else 9
release, called = threading.Event(), threading.Event()
tasks = []
timers = []
before = set(threading.enumerate())

def spin(executor, logger):
    for _ in range(count):
        started = threading.Event()
        def occupy(event=started):
            event.set()
            assert release.wait(5.0)
        tasks.append(executor.create_task(occupy))
        deadline = time.monotonic() + 3.0
        while not started.is_set():
            assert time.monotonic() < deadline
            executor.spin_once(timeout_sec=0.01)
    ready_callback = executor.wait_for_ready_callbacks
    def capture(*args, **kwargs):
        ready = ready_callback(*args, **kwargs)
        tasks.append(ready[0])
        return ready
    executor.wait_for_ready_callbacks = capture
    guard = executor.get_nodes()[0].create_guard_condition(called.set)
    guard.trigger()
    executor.spin_once(timeout_sec=1.0)
    assert not called.is_set()
    timers.append(threading.Timer(0.1, lambda: os.kill(os.getpid(), SIGNUM)))
    timers.append(threading.Timer(0.25, release.set))
    for timer in timers:
        timer.start()
    executor.spin()

module.spin_until_shutdown = spin
try:
    module.main(args=[])
    assert not rclpy.ok()
    assert called.is_set()
    assert all(task.done() and task.exception() is None for task in tasks)
finally:
    release.set()
    for timer in timers:
        timer.join(2.0)
assert not any(thread.is_alive() for thread in set(threading.enumerate()) - before)
print("signal cleanup passed")
"""
    environment = os.environ.copy()
    # Each child is sequential and inherits the parent's isolated Docker domain.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"MODE={mode!r}\nSIGNUM={int(signum)}\n"
            f"TEST_HELPERS={str(Path(__file__).parent)!r}\n" + source,
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15.0,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "signal cleanup passed" in result.stdout
    assert "InvalidHandle" not in result.stderr
    assert "exception was never retrieved" not in result.stderr
