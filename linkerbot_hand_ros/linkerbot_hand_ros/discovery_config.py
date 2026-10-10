"""Parse and persist SDK discovery settings without adapter or device I/O."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path

import can
import yaml
from linkerbot_hand import TransportKind, ValidationError
from linkerbot_hand.discovery import (
    DiscoveryConfig,
    MiniCANFDDiscoveryConfig,
    PythonCANDiscoveryConfig,
)
from linkerbot_transport.canfd import CANFDConfigOptions


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise ValidationError(f"duplicate YAML key: {key}")
            result[key] = loader.construct_object(value_node, deep=deep)
        except TypeError as error:
            raise ValidationError("YAML keys must be scalars") from error
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def read_yaml_document(path: str | Path, *, strict: bool = True) -> object:
    """Read a safe YAML document without requiring its root to be a mapping."""
    try:
        loader = _UniqueSafeLoader if strict else yaml.SafeLoader
        return yaml.load(Path(path).read_text(encoding="utf-8"), loader)
    except (OSError, yaml.YAMLError) as error:
        raise ValidationError(f"cannot read YAML {path}: {error}") from error


def load_yaml(path: str | Path, *, strict: bool = True) -> dict:
    """Read a plain mapping, rejecting duplicate keys and executable tags."""

    value = read_yaml_document(path, strict=strict)
    if not isinstance(value, dict):
        raise ValidationError(f"YAML {path} must contain a mapping")
    return value


def mapping(value: object, allowed: set[str], label: str) -> dict:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a mapping")
    unknown = set(value).difference(allowed)
    if unknown:
        raise ValidationError(f"unknown {label} keys: {sorted(map(str, unknown))}")
    return dict(value)


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def json_mapping(value: str) -> dict:
    try:
        result = json.loads(value, object_pairs_hook=_json_pairs)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"invalid configuration JSON: {error}") from error
    if not isinstance(result, dict):
        raise ValidationError("configuration JSON must contain a mapping")
    return result


def channel_filter(value: str) -> tuple[str, ...] | None:
    """Launch exposes a comma-separated list of SDK report channel names."""

    if not isinstance(value, str):
        raise ValidationError("channels must be a comma-separated string")
    if not value.strip():
        return None
    channels = tuple(item.strip() for item in value.split(","))
    # Let the SDK enforce uniqueness and nonempty names.
    return DiscoveryConfig(channels=channels).channels


def _sequence(value: object, label: str) -> tuple:
    if not isinstance(value, (list, tuple)):
        raise ValidationError(f"{label} must be a list")
    return tuple(value)


def _python_can(value: object, label: str) -> PythonCANDiscoveryConfig:
    options = mapping(value, {f.name for f in fields(PythonCANDiscoveryConfig)}, label)
    if options.get("channels") is not None:
        options["channels"] = _sequence(options["channels"], f"{label}.channels")
    if options.get("probe_protocols") is not None:
        options["probe_protocols"] = tuple(
            TransportKind(item)
            for item in _sequence(options["probe_protocols"], "probe_protocols")
        )
    if options.get("fd_timing") is not None:
        timing = mapping(
            options["fd_timing"],
            {
                "f_clock",
                "nom_brp",
                "nom_tseg1",
                "nom_tseg2",
                "nom_sjw",
                "data_brp",
                "data_tseg1",
                "data_tseg2",
                "data_sjw",
                "strict",
            },
            f"{label}.fd_timing",
        )
        options["fd_timing"] = can.BitTimingFd(**timing)
    return PythonCANDiscoveryConfig(**options)


def parse_discovery_config(
    value: object, *, base_dir: Path | None = None
) -> DiscoveryConfig:
    """Use SDK immutable contracts as the final backend validation boundary."""

    options = mapping(value, {f.name for f in fields(DiscoveryConfig)}, "discovery")
    try:
        for name in ("channels", "backends", "l30_node_ids", "o30_request_ids"):
            if name in options and options[name] is not None:
                options[name] = _sequence(options[name], name)
        for name in ("pcan", "slcan"):
            if name in options:
                options[name] = _python_can(options[name], name)
        if "minicanfd" in options:
            mini = mapping(
                options["minicanfd"],
                {f.name for f in fields(MiniCANFDDiscoveryConfig)},
                "minicanfd",
            )
            library = mini.get("library_path")
            if library is not None:
                if not isinstance(library, str) or not library:
                    raise ValidationError("library_path must be a non-empty string")
                path = Path(library).expanduser()
                mini["library_path"] = str(
                    (base_dir or Path.cwd()).joinpath(path).resolve()
                )
            if mini.get("linux_channels") is not None:
                layouts = mini["linux_channels"]
                if not isinstance(layouts, Mapping):
                    raise ValidationError("linux_channels must be a mapping")
                converted = {}
                for key, channels in layouts.items():
                    if type(key) is int:
                        index = key
                    elif isinstance(key, str) and key.isascii() and key.isdecimal():
                        index = int(key)
                    else:
                        raise ValidationError("MiniCANFD indices must be integers")
                    if index in converted:
                        raise ValidationError("duplicate MiniCANFD device index")
                    converted[index] = _sequence(channels, "linux_channels")
                mini["linux_channels"] = converted
            if "config" in mini:
                mini["config"] = CANFDConfigOptions(
                    **mapping(
                        mini["config"],
                        {f.name for f in fields(CANFDConfigOptions)},
                        "minicanfd.config",
                    )
                )
            options["minicanfd"] = MiniCANFDDiscoveryConfig(**mini)
        return DiscoveryConfig(**options)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"invalid discovery settings: {error}") from error


def discovery_settings(config: DiscoveryConfig) -> dict:
    """Persist validated inputs, never try to serialize a candidate factory."""

    result = {}
    for item in fields(DiscoveryConfig):
        value = getattr(config, item.name)
        if item.name in {"pcan", "slcan"}:
            result[item.name] = {
                "channels": None if value.channels is None else list(value.channels),
                "bitrate": value.bitrate,
                "data_bitrate": value.data_bitrate,
                "probe_protocols": (
                    None
                    if value.probe_protocols is None
                    else [protocol.value for protocol in value.probe_protocols]
                ),
                "bus_options": dict(value.bus_options),
                "fd_timing": None if value.fd_timing is None else dict(value.fd_timing),
            }
        elif item.name == "minicanfd":
            result[item.name] = {
                "library_path": value.library_path,
                "linux_channels": (
                    None
                    if value.linux_channels is None
                    else {str(k): list(v) for k, v in value.linux_channels.items()}
                ),
                "config": {
                    f.name: getattr(value.config, f.name) for f in fields(value.config)
                },
            }
        else:
            result[item.name] = list(value) if isinstance(value, tuple) else value
    return result
