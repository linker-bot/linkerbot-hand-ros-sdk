"""Launch routing and zero-I/O validation for manual/discovered configurations."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import yaml
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode, Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.utilities import make_namespace_absolute, prefix_namespace
from linkerbot_hand import ValidationError

from .discovery_config import (
    channel_filter,
    discovery_settings,
    load_yaml,
    parse_discovery_config,
    read_yaml_document,
)
from .discovery_deployment import SCHEMA, load_deployment


def _value(context, name: str, default: str = "") -> str:
    return LaunchConfiguration(name, default=default).perform(context)


def _boolean(value: str, name: str) -> bool:
    if value.lower() not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value.lower() == "true"


def _typed_strings(parameters: dict) -> dict:
    # JSON, empty strings and YAML-like paths must remain ROS string values.
    return {
        name: ParameterValue(value, value_type=str) if isinstance(value, str) else value
        for name, value in parameters.items()
    }


def _discovery_exit(event, context):
    if event.returncode != 0 and not context.is_shutdown:
        raise RuntimeError(f"hand startup failed (exit code {event.returncode})")
    return []


def check_hand_mode(context):
    """Run before manual defaults are declared, retaining explicit intent."""

    discover = _boolean(_value(context, "discover", "false"), "discover")
    if discover:
        conflicts = {
            "model",
            "side",
            "transport_json",
        } & context.launch_configurations.keys()
        if conflicts:
            raise ValueError(
                f"discover cannot use explicit manual parameters {sorted(conflicts)}; use channels or discovery_config"
            )
    elif _value(context, "channels") or _value(context, "discovery_config"):
        raise ValueError("channels/discovery_config require discover:=true")
    return []


def _settings(context) -> dict:
    path_value = _value(context, "discovery_config")
    if path_value:
        path = Path(path_value).expanduser().resolve()
        try:
            config = parse_discovery_config(load_yaml(path), base_dir=path.parent)
        except ValidationError as error:
            raise ValidationError(f"discovery_config={path}: {error}") from error
    else:
        config = parse_discovery_config({})
    channels = channel_filter(_value(context, "channels"))
    if channels is not None:
        if config.channels is not None and config.channels != channels:
            raise ValueError("channels conflicts with discovery_config.channels")
        config = replace(config, channels=channels)
    return discovery_settings(config)


def build_hand_launch(context, *, arguments):
    parameters = {
        name: ParameterValue(LaunchConfiguration(name), value_type=value_type)
        for name, _default, value_type in arguments
    }
    if not _boolean(_value(context, "discover"), "discover"):
        return [
            LifecycleNode(
                package="linkerbot_hand_ros",
                executable="hand_node",
                name="linkerbot_hand",
                namespace=LaunchConfiguration("namespace"),
                output="screen",
                autostart=LaunchConfiguration("autostart"),
                parameters=[parameters],
            )
        ]
    runtime = {
        name: value.evaluate(context)
        for name, value in parameters.items()
        if name not in {"model", "side", "transport_json"}
    }
    return [
        Node(
            package="linkerbot_hand_ros",
            executable="hand_container",
            output="screen",
            on_exit=_discovery_exit,
            parameters=[
                _typed_strings(
                    {
                        "discovery_mode": "single",
                        "discovery_config_json": json.dumps(_settings(context)),
                        "driver_parameters_json": json.dumps(runtime),
                        "discovery_namespace": make_namespace_absolute(
                            prefix_namespace(
                                context.launch_configurations.get("ros_namespace"),
                                _value(context, "namespace"),
                            )
                        ),
                        "autostart_override": str(
                            _boolean(_value(context, "autostart"), "autostart")
                        ).lower(),
                    }
                )
            ],
        )
    ]


def build_multi_launch(context, *, default_config):
    discover = _boolean(_value(context, "discover"), "discover")
    config_value = _value(context, "config")
    override = _value(context, "autostart")
    discovery_file = False
    if override:
        override = str(_boolean(override, "autostart")).lower()
    if discover:
        if config_value:
            raise ValueError("config and discover:=true are mutually exclusive")
        output = Path(_value(context, "output") or "hands.yaml").expanduser().absolute()
        parameters = [
            {
                "discovery_mode": "multi",
                "discovery_config_json": json.dumps(_settings(context)),
                "discovery_output": str(output),
                "autostart_override": override,
            }
        ]
    else:
        if any(
            _value(context, name) for name in ("channels", "discovery_config", "output")
        ):
            raise ValueError("channels/discovery_config/output require discover:=true")
        path = (
            Path(config_value or default_config.perform(context)).expanduser().resolve()
        )
        # A legacy file may only become valid YAML after launch substitutions.
        # New deployments are static and validated against their original path.
        try:
            document = read_yaml_document(path, strict=False)
        except ValidationError as error:
            if not isinstance(error.__cause__, yaml.YAMLError):
                raise
            document = None
        discovery_file = (
            isinstance(document, dict)
            and "schema" in document
            and not isinstance(document["schema"], dict)
        )
        if discovery_file:
            if document["schema"] != SCHEMA:
                raise ValueError(f"unsupported deployment schema: config={path}")
            load_deployment(path)
            parameters = [
                {
                    "discovery_mode": "file",
                    "deployment_config": str(path),
                    "autostart_override": override,
                }
            ]
        else:
            from launch_ros.parameter_descriptions import ParameterFile

            parameters = [ParameterFile(str(path), allow_substs=True)]
            if override:
                parameters.append({"autostart": override == "true"})
    return [
        Node(
            package="linkerbot_hand_ros",
            executable="hand_container",
            output="screen",
            parameters=[
                _typed_strings(value) if isinstance(value, dict) else value
                for value in parameters
            ],
            on_exit=_discovery_exit if discover or discovery_file else None,
        )
    ]
