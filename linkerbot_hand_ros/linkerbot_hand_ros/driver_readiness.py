"""Bounded lifecycle evidence for the named driver, shared by client and GUI."""

from __future__ import annotations

import threading
import time

from lifecycle_msgs.msg import State, TransitionEvent
from lifecycle_msgs.srv import GetState
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.task import Future


class DriverReadiness:
    """Observe one driver's lifecycle without blocking the caller's executor.

    Active evidence expires one second after the request was sent. Lifecycle
    transitions invalidate outstanding replies, so a delayed active response
    cannot undo a newer deactivation. Command endpoints must belong to the
    named driver; an unrelated subscriber never establishes readiness.
    """

    MAX_STATE_AGE_S = 1.0

    def __init__(self, node: Node, driver_name: str) -> None:
        self._node = node
        self._root = node.resolve_service_name(f"{driver_name}/get_state").rsplit(
            "/", 1
        )[0]
        self._lock = threading.RLock()
        self._group = ReentrantCallbackGroup()
        self._active = False
        self._confirmed_at = 0.0
        self._requested_at = 0.0
        self._pending: Future | None = None
        self._destroyed = False
        self._client = None
        self._events = None
        self._timer = None
        try:
            self._client = node.create_client(
                GetState, f"{driver_name}/get_state", callback_group=self._group
            )
            self._events = node.create_subscription(
                TransitionEvent,
                f"{driver_name}/transition_event",
                self._on_transition,
                10,
                callback_group=self._group,
            )
            self._timer = node.create_timer(
                0.2,
                self._refresh,
                callback_group=self._group,
                clock=Clock(clock_type=ClockType.STEADY_TIME),
            )
        except Exception:
            self.destroy()
            raise

    def is_active(self, command_topic: str) -> bool:
        """Require fresh active state and a command endpoint of this driver."""

        with self._lock:
            if (
                self._destroyed
                or not self._active
                or time.monotonic() - self._confirmed_at >= self.MAX_STATE_AGE_S
                or not self._client.service_is_ready()
            ):
                return False
            topic = self._node.resolve_topic_name(command_topic)
            return any(
                f"{endpoint.node_namespace.rstrip('/')}/{endpoint.node_name}"
                == self._root
                for endpoint in self._node.get_subscriptions_info_by_topic(topic)
            )

    def _on_transition(self, _event: TransitionEvent) -> None:
        with self._lock:
            if self._destroyed:
                return
            self._active = False
            self._discard_request()

    def _discard_request(self) -> None:
        pending, self._pending = self._pending, None
        if pending is not None:
            self._client.remove_pending_request(pending)
            pending.cancel()

    def _refresh(self) -> None:
        with self._lock:
            if self._destroyed:
                return
            now = time.monotonic()
            if not self._client.service_is_ready():
                self._active = False
                self._discard_request()
                return
            if self._pending is not None:
                if now - self._requested_at < self.MAX_STATE_AGE_S:
                    return
                self._active = False
                self._discard_request()
            self._requested_at = now
            self._pending = self._client.call_async(GetState.Request())
            self._pending.add_done_callback(self._on_response)

    def _on_response(self, future: Future) -> None:
        with self._lock:
            if self._destroyed or future is not self._pending:
                return
            self._pending = None
            self._active = False
            if future.cancelled() or future.exception() is not None:
                return
            response = future.result()
            if time.monotonic() - self._requested_at < self.MAX_STATE_AGE_S:
                self._active = response.current_state.id == State.PRIMARY_STATE_ACTIVE
                self._confirmed_at = self._requested_at

    def destroy(self) -> None:
        with self._lock:
            if self._destroyed:
                return
            self._destroyed = True
            self._active = False
            self._discard_request()
            if self._timer is not None:
                self._node.destroy_timer(self._timer)
            if self._events is not None:
                self._node.destroy_subscription(self._events)
            if self._client is not None:
                self._node.destroy_client(self._client)
