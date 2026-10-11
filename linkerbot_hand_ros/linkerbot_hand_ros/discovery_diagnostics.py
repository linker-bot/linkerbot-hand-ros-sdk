"""Readable discovery context without inspecting factories or opening devices."""

from __future__ import annotations

from linkerbot_hand import HandError
from linkerbot_hand.discovery import DiscoveryCandidate, DiscoveryFailure


def _text(value: object) -> str:
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


def candidate_context(candidate: DiscoveryCandidate) -> str:
    """Identify the observed channel and endpoint, never infer native names."""

    address = candidate.address
    fields = [
        f"backend={candidate.channel.provider}",
        f"channel={candidate.channel.name!r}",
        f"protocol={candidate.wire_protocol.value}",
        f"scheme={address.scheme}",
        f"request_id={address.request_id:#x}",
        f"response_id={address.response_id:#x}",
        f"extended_id={address.is_extended_id}",
    ]
    if address.node_id is not None:
        fields.append(f"node_id={address.node_id}")
    return _text(" ".join(fields))


def failure_context(failure: DiscoveryFailure) -> str:
    """Keep SDK failure codes and all available enumeration/probe locations."""

    fields = [f"operation={failure.operation}", f"error_type={failure.error_type}"]
    backend = failure.backend
    if backend is None and failure.channel is not None:
        backend = failure.channel.provider
    if backend is not None:
        fields.append(f"backend={backend}")
    if failure.channel is not None:
        fields.append(f"channel={failure.channel.name!r}")
    if failure.native_channel is not None:
        fields.append(f"native_channel={failure.native_channel!r}")
    if failure.wire_protocol is not None:
        fields.append(f"protocol={failure.wire_protocol.value}")
    return _text(f"discovery {failure.code}: {failure.message} ({' '.join(fields)})")


def exception_details(error: BaseException) -> str:
    """Retain SDK codes and explicit causes, including cyclic cause protection."""

    parts = []
    seen = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current) or type(current).__name__
        if isinstance(current, HandError):
            message = f"[{current.code.value}] {message}"
            context = " ".join(
                f"{name}={getattr(current, name)!r}"
                for name in ("operation", "model", "generation")
                if getattr(current, name) is not None
            )
            if context:
                message += f" ({context})"
        if parts:
            message = f"cause={type(current).__name__}: {message}"
        parts.append(_text(message))
        cause = current.__cause__
        if cause is None and isinstance(current, HandError):
            cause = current.cause
        current = cause
    return "; ".join(parts)
