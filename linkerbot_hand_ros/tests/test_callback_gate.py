"""Admission and drain contracts for the executor callback gate."""

from __future__ import annotations

import threading

import pytest
from linkerbot_hand import LifecycleError, ValidationError
from linkerbot_hand_ros.callback_gate import CallbackGate


def test_gate_admits_concurrently_and_counts_in_flight_callbacks() -> None:
    gate = CallbackGate(name="test")

    with gate.admit() as first:
        with gate.admit() as second:
            assert first and second
            assert gate.in_flight == 2
        assert gate.in_flight == 1
    assert gate.in_flight == 0
    assert gate.open


def test_closed_gate_refuses_admission_without_raising() -> None:
    gate = CallbackGate(name="test")
    gate.close(0.1)

    with gate.admit() as admitted:
        assert not admitted
    assert gate.in_flight == 0
    assert not gate.open


def test_close_waits_for_admitted_callback_to_leave() -> None:
    gate = CallbackGate(name="test")
    admitted = threading.Event()
    release = threading.Event()
    left = threading.Event()

    def callback() -> None:
        with gate.admit() as ok:
            assert ok
            admitted.set()
            release.wait(5.0)
        left.set()

    worker = threading.Thread(target=callback)
    worker.start()
    try:
        assert admitted.wait(5.0)
        closer_returned = threading.Event()

        def closer() -> None:
            gate.close(5.0)
            closer_returned.set()

        closing = threading.Thread(target=closer)
        closing.start()
        try:
            # The gate must still be held while the callback body runs.
            assert not closer_returned.wait(0.2)
            release.set()
            assert closer_returned.wait(5.0)
            assert left.is_set()
        finally:
            closing.join(5.0)
    finally:
        release.set()
        worker.join(5.0)

    assert gate.in_flight == 0


def test_close_reports_callbacks_that_outlive_the_timeout() -> None:
    gate = CallbackGate(name="stuck-hand")
    admitted = threading.Event()
    release = threading.Event()

    def callback() -> None:
        with gate.admit() as ok:
            assert ok
            admitted.set()
            release.wait(5.0)

    worker = threading.Thread(target=callback)
    worker.start()
    try:
        assert admitted.wait(5.0)
        with pytest.raises(LifecycleError, match="stuck-hand"):
            gate.close(0.05)
    finally:
        release.set()
        worker.join(5.0)


def test_close_is_idempotent() -> None:
    gate = CallbackGate(name="test")

    gate.close(0.1)
    gate.close(0.1)

    assert not gate.open


@pytest.mark.parametrize("timeout", (0, -1.0, float("inf"), True, "1"))
def test_close_rejects_unusable_timeouts(timeout) -> None:
    gate = CallbackGate(name="test")

    with pytest.raises(ValidationError, match="timeout_s"):
        gate.close(timeout)


@pytest.mark.parametrize("name", ("", None, 5))
def test_gate_requires_a_name(name) -> None:
    with pytest.raises(ValidationError, match="name"):
        CallbackGate(name=name)
