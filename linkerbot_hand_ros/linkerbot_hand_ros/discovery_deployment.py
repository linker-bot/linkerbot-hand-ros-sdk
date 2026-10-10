"""Discovery selection, stable deployment bindings and no-overwrite YAML export."""

from __future__ import annotations

import os
import shlex
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path

import yaml
from linkerbot_hand import (
    HandSide,
    TransportKind,
    ValidationError,
    get_declared_capabilities,
)
from linkerbot_hand.discovery import (
    DiscoveryAddress,
    DiscoveryCandidate,
    DiscoveryConfig,
    DiscoveryReport,
    discover_hands,
)
from rclpy.validate_namespace import validate_namespace

from .discovery_config import (
    discovery_settings,
    load_yaml,
    mapping,
    parse_discovery_config,
)
from .driver_config import read_driver_configuration
from .parameter_updates import PARAMETER_DEFAULTS

SCHEMA = "linkerbot_hand_ros.discovery"
IDENTITY_PARAMETERS = {"model", "side", "transport_json"}
RUNTIME_PARAMETERS = set(PARAMETER_DEFAULTS).difference(IDENTITY_PARAMETERS)
MATCH_REQUIRED = {"backend", "channel", "model", "side", "wire_protocol", "address"}
MATCH_OPTIONAL = {"reported_side", "serial_number", "product_code", "sensor_variant"}


@dataclass(frozen=True, slots=True)
class HandBinding:
    namespace: str
    match: dict
    parameters: dict


@dataclass(frozen=True, slots=True)
class Deployment:
    discovery: DiscoveryConfig
    hands: tuple[HandBinding, ...]
    autostart: bool


@dataclass(frozen=True, slots=True)
class SelectedHand:
    binding: HandBinding
    candidate: DiscoveryCandidate


def normalize_namespace(value: str, *, allow_root: bool = False) -> str:
    if not isinstance(value, str):
        raise ValidationError("namespace must be a string")
    result = "/" + value.strip().strip("/")
    validate_namespace(result)
    if result == "/" and not allow_root:
        raise ValidationError("root namespace requires a single hand")
    return result


def runtime_parameters(model: str, side: str, values: object) -> dict:
    supplied = mapping(values, RUNTIME_PARAMETERS, "hand parameters")
    parameters = {
        name: value
        for name, value in PARAMETER_DEFAULTS.items()
        if name in RUNTIME_PARAMETERS
    }
    for name, value in supplied.items():
        default = parameters[name]
        if type(default) is float and type(value) in (int, float):
            value = float(value)
        if type(value) is not type(default):
            raise ValidationError(f"{name} must be {type(default).__name__}")
        parameters[name] = value
    caps = get_declared_capabilities(
        model, side=None if side == "not_applicable" else side
    )
    all_parameters = {
        **parameters,
        "model": model,
        "side": "" if caps.side is HandSide.NOT_APPLICABLE else caps.side.value,
        "transport_json": "",
    }
    read_driver_configuration(all_parameters.__getitem__, discovered_capabilities=caps)
    return parameters


def candidate_match(candidate: DiscoveryCandidate) -> dict:
    result = {
        "backend": candidate.channel.provider,
        "channel": candidate.channel.name,
        "model": candidate.model,
        "side": candidate.side.value,
        "wire_protocol": candidate.wire_protocol.value,
        "address": {
            f.name: getattr(candidate.address, f.name)
            for f in fields(candidate.address)
        },
    }
    if candidate.reported_side is not None:
        result["reported_side"] = candidate.reported_side.value
    for name in ("serial_number", "product_code", "sensor_variant"):
        value = getattr(candidate.identity, name)
        if value is not None:
            result[name] = value
    return result


def _validate_match(value: object) -> dict:
    match = mapping(value, MATCH_REQUIRED | MATCH_OPTIONAL, "hand match")
    if not MATCH_REQUIRED.issubset(match):
        raise ValidationError("hand match is missing endpoint/identity fields")
    if match["backend"] not in {"socketcan", "pcan", "slcan", "minicanfd"}:
        raise ValidationError("unsupported discovery backend")
    for name in {"channel", "model", "side", "wire_protocol"} | (
        set(match) & MATCH_OPTIONAL
    ):
        if not isinstance(match[name], str) or not match[name]:
            raise ValidationError(f"match.{name} must be a non-empty string")
    side = HandSide(match["side"])
    capabilities = get_declared_capabilities(
        match["model"], side=None if side is HandSide.NOT_APPLICABLE else side
    )
    match["model"] = capabilities.model
    wire = TransportKind(match["wire_protocol"])
    if wire not in {TransportKind.CAN, TransportKind.CAN_FD}:
        raise ValidationError("wire_protocol must be can or can_fd")
    if "reported_side" in match and HandSide(match["reported_side"]) not in {
        HandSide.LEFT,
        HandSide.RIGHT,
    }:
        raise ValidationError("reported_side must be left or right")
    address = mapping(
        match["address"], {f.name for f in fields(DiscoveryAddress)}, "address"
    )
    resolved_address = DiscoveryAddress(**address)
    match["address"] = {
        f.name: getattr(resolved_address, f.name) for f in fields(resolved_address)
    }
    return match


def load_deployment(path: str | Path) -> Deployment:
    path = Path(path).expanduser().resolve()
    document = mapping(
        load_yaml(path),
        {"schema", "version", "discovery", "hands", "autostart"},
        "deployment",
    )
    if (
        document.get("schema") != SCHEMA
        or type(document.get("version")) is not int
        or document["version"] != 1
    ):
        raise ValidationError("unsupported discovery deployment schema/version")
    autostart = document.get("autostart", True)
    if type(autostart) is not bool:
        raise ValidationError("autostart must be bool")
    values = document.get("hands")
    if not isinstance(values, list) or not values:
        raise ValidationError("hands must be a non-empty list")
    hands = []
    namespaces = set()
    endpoints = set()
    for value in values:
        hand = mapping(value, {"namespace", "match", "parameters"}, "hand")
        namespace = normalize_namespace(
            hand.get("namespace"), allow_root=len(values) == 1
        )
        match = _validate_match(hand.get("match"))
        endpoint = (match["backend"], match["channel"])
        if namespace in namespaces or endpoint in endpoints:
            raise ValidationError(
                "duplicate namespace or physical channel in deployment"
            )
        namespaces.add(namespace)
        endpoints.add(endpoint)
        hands.append(
            HandBinding(
                namespace,
                match,
                runtime_parameters(
                    match["model"], match["side"], hand.get("parameters", {})
                ),
            )
        )
    return Deployment(
        parse_discovery_config(document.get("discovery", {}), base_dir=path.parent),
        tuple(hands),
        autostart,
    )


def output_path(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("output must be a non-empty path")
    path = Path(value).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise ValidationError(
            f"output already exists: {path}; use config:={path} or a new output path"
        )
    if not path.parent.is_dir():
        raise ValidationError(f"output directory does not exist: {path.parent}")
    return path


def save_deployment(path: Path, deployment: Deployment) -> None:
    document = {
        "schema": SCHEMA,
        "version": 1,
        "autostart": deployment.autostart,
        "discovery": discovery_settings(deployment.discovery),
        "hands": [
            {
                "namespace": hand.namespace,
                "match": hand.match,
                "parameters": hand.parameters,
            }
            for hand in deployment.hands
        ],
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(document, stream, sort_keys=False, allow_unicode=True)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic publication with EEXIST, even if another process won the race.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _cleanup_report(report: DiscoveryReport, emit: Callable[[str], None]) -> None:
    errors = []
    for failure in report.failures:
        emit(
            f"discovery {failure.code}: {failure.message} ({failure.operation}, {failure.error_type})"
        )
        if failure.cleanup is None:
            continue
        for attempt in range(2):
            try:
                failure.cleanup()
                emit("discovery probe cleanup completed")
                break
            except Exception as error:  # noqa: BLE001 - retain cleanup diagnostics
                emit(f"discovery cleanup attempt {attempt + 1} failed: {error}")
                if attempt == 1:
                    errors.append(str(error))
    if errors:
        raise ValidationError(
            f"discovery cleanup incomplete; startup refused: {errors}"
        )


def select_hands(
    config: DiscoveryConfig,
    *,
    single_namespace: str | None = None,
    deployment: Deployment | None = None,
    parameters: Mapping[str, object] | None = None,
    namespace_prefix: str = "",
    scan: Callable[[DiscoveryConfig], DiscoveryReport] | None = None,
    emit: Callable[[str], None] = print,
) -> tuple[SelectedHand, ...]:
    emit("scanning hand identities; SDK scan budget is a soft deadline")
    report = (scan or discover_hands)(config)
    # Clear retained probe connections before selecting, saving or activating.
    _cleanup_report(report, emit)
    for candidate in report.candidates:
        physical_side = candidate.reported_side or candidate.side
        side = "unknown" if physical_side is None else physical_side.value
        problems = ", ".join(p.code for p in candidate.problems)
        emit(
            f"{candidate.channel.name}: {candidate.model or 'unknown'}, {side}, {candidate.channel.provider} [{candidate.status.value}] {problems}".rstrip()
        )
    if single_namespace is not None:
        if len(report.candidates) > 1:
            emit("single-hand mode requires one target; limit the interfaces:")
            for channel in sorted({c.channel.name for c in report.candidates}):
                emit(
                    "ros2 launch linkerbot_hand_ros hand.launch.py discover:=true "
                    + shlex.quote("channels:=" + channel)
                )
            emit(
                "all verified hands: ros2 launch linkerbot_hand_ros multi_hand.launch.py discover:=true"
            )
        candidate = report.require_one()
        # SDK validates identity consistency and physical-side naming too.
        report.named_candidates()
        selected = (
            SelectedHand(
                HandBinding(
                    normalize_namespace(single_namespace, allow_root=True),
                    candidate_match(candidate),
                    runtime_parameters(
                        candidate.model, candidate.side.value, parameters or {}
                    ),
                ),
                candidate,
            ),
        )
    elif deployment is not None:
        named = report.named_candidates()
        selected_list = []
        for binding in deployment.hands:
            matches = [
                candidate
                for candidate in named.values()
                if all(
                    candidate_match(candidate).get(key) == value
                    for key, value in binding.match.items()
                )
            ]
            if len(matches) != 1:
                raise ValidationError(
                    f"binding {binding.namespace} matched {len(matches)} verified hands; expected exactly one"
                )
            selected_list.append(SelectedHand(binding, matches[0]))
        selected = tuple(selected_list)
    else:
        named = report.named_candidates()
        if not named:
            raise ValidationError("no verified hands available for multi-hand startup")
        selected = tuple(
            SelectedHand(
                HandBinding(
                    normalize_namespace(namespace_prefix.rstrip("/") + "/" + name),
                    candidate_match(candidate),
                    runtime_parameters(
                        candidate.model, candidate.side.value, parameters or {}
                    ),
                ),
                candidate,
            )
            for name, candidate in named.items()
        )
    channels = set()
    recipes = set()
    for hand in selected:
        candidate = hand.candidate
        channel = (candidate.channel.provider, candidate.channel.name)
        observed = sum(
            (c.channel.provider, c.channel.name) == channel for c in report.candidates
        )
        if observed > 1:
            raise ValidationError("one physical channel cannot control multiple hands")
        if channel in channels or candidate.transport.connection_key in recipes:
            raise ValidationError("one physical channel cannot control multiple hands")
        channels.add(channel)
        recipes.add(candidate.transport.connection_key)
        emit(
            f"binding namespace={hand.binding.namespace} -> {candidate.channel.name} ({candidate.model})"
        )
    return selected


def deployment_from_selection(
    config: DiscoveryConfig, selected: tuple[SelectedHand, ...], autostart: bool
) -> Deployment:
    # Subsequent loads scan only the saved resources, not new ambient devices.
    narrowed = replace(
        config,
        channels=tuple(sorted({h.candidate.channel.name for h in selected})),
        backends=tuple(sorted({h.candidate.channel.provider for h in selected})),
    )
    return Deployment(narrowed, tuple(h.binding for h in selected), autostart)
