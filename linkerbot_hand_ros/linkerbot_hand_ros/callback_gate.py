"""Bounded gate that closes executor callbacks out before entity destruction."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from linkerbot_hand import LifecycleError, ValidationError


class CallbackGate:
    """Admit executor callbacks and drain them before ROS entities are destroyed.

    Callbacks that run outside the lifecycle control group can execute while a
    lifecycle transition destroys the entities they use. Admission is shared, so
    concurrent callbacks never wait for each other, while :meth:`close` is
    exclusive and waits for every admitted callback body to leave.
    """

    def __init__(self, *, name: str) -> None:
        if not isinstance(name, str) or not name:
            raise ValidationError("callback gate name must be a non-empty string")
        self._name = name
        self._condition = threading.Condition()
        self._open = True
        self._in_flight = 0

    @contextmanager
    def admit(self) -> Iterator[bool]:
        """Yield whether the callback may run; a closed gate never raises.

        Raising instead of yielding ``False`` would skip the response rclpy sends
        after a service callback returns, turn into an executor task exception,
        and end ``spin()``.
        """

        with self._condition:
            admitted = self._open
            if admitted:
                self._in_flight += 1
        try:
            yield admitted
        finally:
            if admitted:
                with self._condition:
                    self._in_flight -= 1
                    if self._in_flight == 0:
                        self._condition.notify_all()

    def close(self, timeout_s: float) -> None:
        """Reject new callbacks and wait boundedly for admitted ones to leave."""

        timeout = _positive_timeout(timeout_s)
        deadline = time.monotonic() + timeout
        with self._condition:
            self._open = False
            while self._in_flight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LifecycleError(
                        f"{self._in_flight} callback(s) admitted by {self._name} "
                        f"did not finish within {timeout:.3f}s",
                        operation="close_callback_gate",
                    )
                self._condition.wait(remaining)

    @property
    def open(self) -> bool:
        with self._condition:
            return self._open

    @property
    def in_flight(self) -> int:
        with self._condition:
            return self._in_flight


def _positive_timeout(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValidationError("timeout_s must be finite and positive")
    return float(value)


__all__ = ["CallbackGate"]
