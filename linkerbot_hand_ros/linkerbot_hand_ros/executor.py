"""Public rclpy executor extension with an owned, bounded callback pool."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait

from rclpy.context import Context
from rclpy.executors import (
    ConditionReachedException,
    Executor,
    ExternalShutdownException,
    ShutdownException,
    TimeoutException,
    TimeoutObject,
)
from rclpy.logging import get_logger
from rclpy.task import Future as ROSFuture
from rclpy.task import Task


class MultiThreadedExecutor(Executor):
    """Run driver callbacks concurrently, joining the pool before ROS teardown.

    Humble's standard executor does not join its pool. Jazzy joins it after
    destroying the guard queued handlers need. Owning the pool and dispatching
    via public ``wait_for_ready_callbacks`` avoids both version-specific paths.
    Driver callbacks are synchronous; suspended coroutine tasks are rejected at
    shutdown rather than silently discarding unfinished work.
    """

    def __init__(self, num_threads: int, *, context: Context | None = None) -> None:
        super().__init__(context=context)
        self._pool = ThreadPoolExecutor(max_workers=num_threads)
        self._dispatch_lock = threading.Lock()
        self._closing = False
        self._submitted: dict[Future, Task] = {}
        self._wait_future: ROSFuture | None = None
        # rclpy caches its ready generator by argument equality. Keep this
        # callable stable so later entities in the ready set are not skipped.
        self._wait_condition = self._should_stop_waiting

    def spin_once(self, timeout_sec: float | None = None) -> None:
        self._spin_once(timeout_sec)

    def spin(self) -> None:
        while self.context.ok() and not self._closing:
            self.spin_once()

    def spin_until_future_complete(
        self, future: ROSFuture, timeout_sec: float | None = None
    ) -> None:
        future.add_done_callback(lambda _future: self.wake())
        deadline = (
            None
            if timeout_sec is None or timeout_sec < 0
            else time.monotonic() + timeout_sec
        )
        # Keep the timeout argument stable too; mutating TimeoutObject is the
        # public rclpy pattern for a deadline across several spin iterations.
        timeout = None if deadline is None else TimeoutObject(timeout_sec)
        while (
            self.context.ok()
            and not self._closing
            and not future.done()
            and not future.cancelled()
        ):
            if timeout is not None:
                timeout.timeout = _remaining(deadline)
            self.spin_once_until_future_complete(future, timeout)
            if deadline is not None and time.monotonic() >= deadline:
                return

    def spin_once_until_future_complete(
        self,
        future: ROSFuture,
        timeout_sec: float | TimeoutObject | None = None,
    ) -> None:
        self._spin_once(timeout_sec, future=future)

    def _should_stop_waiting(self) -> bool:
        future = self._wait_future
        return self._closing or (
            future is not None and (future.done() or future.cancelled())
        )

    def _spin_once(self, timeout_sec, *, future: ROSFuture | None = None) -> None:
        with self._dispatch_lock:
            if self._closing:
                return
        self._wait_future = future
        try:
            handler, _, _ = self.wait_for_ready_callbacks(
                timeout_sec=timeout_sec, condition=self._wait_condition
            )
        except (
            ConditionReachedException,
            ExternalShutdownException,
            ShutdownException,
            TimeoutException,
        ):
            pass
        else:
            with self._dispatch_lock:
                if self._closing:
                    return
                self._submitted[self._pool.submit(handler)] = handler
        self._collect_finished()

    def _collect_finished(self) -> None:
        with self._dispatch_lock:
            completed = [
                (future, task)
                for future, task in self._submitted.items()
                if future.done() and (task.done() or task.cancelled())
            ]
        for future, task in completed:
            try:
                future.result()
                if not task.cancelled():
                    task.result()
            finally:
                with self._dispatch_lock:
                    del self._submitted[future]

    def shutdown(self, timeout_sec: float | None = None) -> bool:
        """Retain ROS handles on timeout; a later shutdown can finish cleanup.

        Stop the spin thread before calling this method. Nodes and context must
        remain alive if False is returned. Both entry points enforce that order.
        """

        deadline = (
            None
            if timeout_sec is None or timeout_sec < 0
            else time.monotonic() + timeout_sec
        )
        with self._dispatch_lock:
            self._closing = True
            submitted = dict(self._submitted)
        self.wake()
        if submitted:
            _, unfinished = wait(submitted, timeout=_remaining(deadline))
            if unfinished or any(
                not task.done() and not task.cancelled() for task in submitted.values()
            ):
                return False
        # No callback still uses its node or the executor guard. Join our own
        # threads before delegating ROS handle destruction to the public API.
        self._pool.shutdown(wait=True)
        errors = [
            future.exception() or (None if task.cancelled() else task.exception())
            for future, task in submitted.items()
        ]
        for error in errors:
            if error is not None:
                get_logger("linkerbot_hand_executor").error(
                    f"callback failed during shutdown: {type(error).__name__}: {error}"
                )
        stopped = super().shutdown(timeout_sec=_remaining(deadline))
        if stopped:
            self._submitted.clear()
        return stopped


def _remaining(deadline: float | None) -> float | None:
    return None if deadline is None else max(0.0, deadline - time.monotonic())


__all__ = ["MultiThreadedExecutor"]
