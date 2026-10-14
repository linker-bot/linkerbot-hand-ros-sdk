"""Run multiple Hand lifecycle drivers in one ROS 2 process."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.executors import ExternalShutdownException
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.validate_namespace import InvalidNamespaceException, validate_namespace

from .discovery_config import json_mapping, parse_discovery_config
from .discovery_deployment import (
    SelectedHand,
    deployment_from_selection,
    load_deployment,
    output_path,
    save_deployment,
    select_hands,
)
from .discovery_diagnostics import exception_details
from .executor import MultiThreadedExecutor
from .node import (
    CALLBACK_GROUPS_PER_HAND,
    LinkerbotHandNode,
    spin_until_shutdown,
)

CONTAINER_NODE_NAME = "linkerbot_hand_container"
EXECUTOR_SHUTDOWN_TIMEOUT_S = 2.0
# The container node only serves parameters, from its default callback group.
CONTAINER_CALLBACK_GROUPS = 1


class ManagedHandNode(Protocol):
    """Lifecycle surface required by the in-process driver group."""

    def get_fully_qualified_name(self) -> str: ...

    def trigger_configure(self) -> TransitionCallbackReturn: ...

    def trigger_activate(self) -> TransitionCallbackReturn: ...

    def trigger_deactivate(self) -> TransitionCallbackReturn: ...

    def trigger_cleanup(self) -> TransitionCallbackReturn: ...

    def destroy_node(self) -> None: ...


class ErrorLogger(Protocol):
    """Minimal ROS logger surface used during process cleanup."""

    def error(self, message: str) -> None: ...


HandNodeFactory = Callable[..., ManagedHandNode]


@dataclass(frozen=True, slots=True)
class MultiDeviceConfiguration:
    """Validated process-level configuration for a group of hand nodes."""

    device_namespaces: tuple[str, ...]
    autostart: bool


class MultiDeviceLifecycleError(RuntimeError):
    """Report an atomic multi-device lifecycle transition failure."""


class MultiHandContainerNode(Node):
    """Expose process-level parameters without owning device I/O."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(CONTAINER_NODE_NAME, **kwargs)
        self.declare_parameter("device_namespaces", Parameter.Type.STRING_ARRAY)
        self.declare_parameter("autostart", True)
        for name, value in {
            "discovery_mode": "",
            "discovery_config_json": "{}",
            "driver_parameters_json": "{}",
            "discovery_namespace": "/",
            "discovery_output": "",
            "deployment_config": "",
            "autostart_override": "",
        }.items():
            self.declare_parameter(name, value, ParameterDescriptor(read_only=True))

    def read_configuration(self) -> MultiDeviceConfiguration:
        """Return normalized container parameters without constructing a hand."""

        namespaces = _normalize_namespaces(
            self.get_parameter("device_namespaces").value
        )
        autostart = self.get_parameter("autostart").value
        if not isinstance(autostart, bool):
            raise TypeError("autostart must be a boolean")
        return MultiDeviceConfiguration(
            device_namespaces=namespaces,
            autostart=autostart,
        )


class HandLifecycleGroup:
    """Apply configure/activate and rollback as one ordered device group."""

    def __init__(self, nodes: Sequence[ManagedHandNode]) -> None:
        if not nodes:
            raise ValueError("at least one hand node is required")
        self._nodes = tuple(nodes)
        self._configured: list[ManagedHandNode] = []
        self._active: list[ManagedHandNode] = []

    def start(self) -> None:
        """Configure every node, then activate every node, or roll all back."""

        if self._configured or self._active:
            raise MultiDeviceLifecycleError("hand lifecycle group is already started")
        try:
            for node in self._nodes:
                self._transition(node, "configure", node.trigger_configure)
                self._configured.append(node)
            for node in self._nodes:
                self._transition(node, "activate", node.trigger_activate)
                self._active.append(node)
        except Exception as error:
            rollback_errors = self.stop()
            message = str(error)
            if rollback_errors:
                message = f"{message}; rollback failed: {'; '.join(rollback_errors)}"
            raise MultiDeviceLifecycleError(message) from error

    def stop(self) -> tuple[str, ...]:
        """Best-effort deactivate and cleanup in reverse startup order."""

        errors: list[str] = []
        for node in reversed(self._active):
            error = self._try_transition(node, "deactivate", node.trigger_deactivate)
            if error is not None:
                errors.append(error)
        self._active.clear()
        for node in reversed(self._configured):
            error = self._try_transition(node, "cleanup", node.trigger_cleanup)
            if error is not None:
                errors.append(error)
        self._configured.clear()
        return tuple(errors)

    @staticmethod
    def _transition(
        node: ManagedHandNode,
        operation: str,
        callback: Callable[[], TransitionCallbackReturn],
    ) -> None:
        result = callback()
        if result != TransitionCallbackReturn.SUCCESS:
            raise MultiDeviceLifecycleError(
                f"{node.get_fully_qualified_name()} {operation} returned {result.name}"
            )

    @classmethod
    def _try_transition(
        cls,
        node: ManagedHandNode,
        operation: str,
        callback: Callable[[], TransitionCallbackReturn],
    ) -> str | None:
        try:
            cls._transition(node, operation, callback)
        except BaseException as error:  # noqa: BLE001 - best-effort rollback boundary
            return str(error)
        return None


def create_hand_nodes(
    configuration: MultiDeviceConfiguration,
    *,
    node_factory: HandNodeFactory = LinkerbotHandNode,
) -> tuple[ManagedHandNode, ...]:
    """Construct one driver per namespace and clean up partial construction."""

    nodes: list[ManagedHandNode] = []
    try:
        for namespace in configuration.device_namespaces:
            nodes.append(node_factory(namespace=namespace))
    except BaseException:
        destroy_hand_nodes(nodes)
        raise
    return tuple(nodes)


def destroy_hand_nodes(nodes: Sequence[ManagedHandNode]) -> tuple[str, ...]:
    """Destroy all nodes in reverse order while preserving every failure."""

    errors: list[str] = []
    for node in reversed(nodes):
        try:
            node.destroy_node()
        except BaseException as error:  # noqa: BLE001 - final resource boundary
            errors.append(f"{node.get_fully_qualified_name()} destroy failed: {error}")
    return tuple(errors)


def _normalize_namespaces(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("device_namespaces must be a non-empty string array")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("device_namespaces must contain non-empty strings")
        namespace = item.strip()
        if not namespace.startswith("/"):
            namespace = f"/{namespace}"
        namespace = namespace.rstrip("/")
        if not namespace:
            raise ValueError("the root namespace cannot identify a hand device")
        try:
            validate_namespace(namespace)
        except InvalidNamespaceException as error:
            raise ValueError(f"invalid hand namespace {item!r}: {error}") from error
        if namespace in normalized:
            raise ValueError(f"duplicate hand namespace: {namespace}")
        normalized.append(namespace)
    return tuple(normalized)


def prepare_discovery_startup(
    container: MultiHandContainerNode,
) -> tuple[MultiDeviceConfiguration, tuple[SelectedHand, ...]]:
    """Resolve an explicitly requested mode in the owning runtime process."""

    read = lambda name: container.get_parameter(name).value
    mode = read("discovery_mode")
    container.get_logger().info(
        f"preparing discovery mode={mode} "
        f"deployment_config={read('deployment_config')!r} "
        f"output={read('discovery_output')!r}"
    )
    if mode not in {"single", "multi", "file"}:
        raise ValueError("unknown discovery startup mode")
    override = read("autostart_override")
    if override not in {"", "true", "false"}:
        raise ValueError("autostart override must be true or false")
    deployment = None
    target = None
    if mode == "file":
        deployment = load_deployment(read("deployment_config"))
        config = deployment.discovery
        autostart = deployment.autostart
    else:
        config = parse_discovery_config(json_mapping(read("discovery_config_json")))
        autostart = True
        if mode == "multi":
            # Refuse existing output before accessing any adapters.
            target = output_path(read("discovery_output"))
    if override:
        autostart = override == "true"
    selected = select_hands(
        config,
        single_namespace=read("discovery_namespace") if mode == "single" else None,
        deployment=deployment,
        parameters=json_mapping(read("driver_parameters_json")),
        namespace_prefix=container.get_namespace() if mode == "multi" else "",
        emit=container.get_logger().info,
    )
    if target is not None:
        save_deployment(target, deployment_from_selection(config, selected, autostart))
        container.get_logger().info(f"configuration saved: {target}")
    return MultiDeviceConfiguration(
        tuple(hand.binding.namespace for hand in selected), autostart
    ), selected


def create_discovered_nodes(
    configuration: MultiDeviceConfiguration, selected: tuple[SelectedHand, ...]
) -> tuple[ManagedHandNode, ...]:
    hands = {hand.binding.namespace: hand for hand in selected}

    def factory(*, namespace: str) -> LinkerbotHandNode:
        hand = hands[namespace]
        return LinkerbotHandNode(
            namespace=namespace,
            # Local identity rules outrank __ns/__node from the container
            # process, while retaining global parameters and topic remappings.
            cli_args=[
                "--ros-args",
                "-r",
                f"__ns:={namespace}",
                "-r",
                "__node:=linkerbot_hand",
            ],
            discovery_candidate=hand.candidate,
            parameter_overrides=[
                Parameter(name, value=value)
                for name, value in hand.binding.parameters.items()
            ],
        )

    return create_hand_nodes(configuration, node_factory=factory)


def main(args: list[str] | None = None) -> None:
    """Run all configured hand drivers in one shared Python process."""

    rclpy.init(args=args)
    container: MultiHandContainerNode | None = None
    nodes: tuple[ManagedHandNode, ...] = ()
    lifecycle: HandLifecycleGroup | None = None
    executor: MultiThreadedExecutor | None = None
    stage = "container_configuration"
    try:
        container = MultiHandContainerNode()
        if container.get_parameter("discovery_mode").value:
            configuration, selected = prepare_discovery_startup(container)
            nodes = create_discovered_nodes(configuration, selected)
        else:
            configuration = container.read_configuration()
            nodes = create_hand_nodes(configuration)
        stage = "executor_configuration"
        lifecycle = HandLifecycleGroup(nodes)
        executor = MultiThreadedExecutor(
            num_threads=(
                CONTAINER_CALLBACK_GROUPS + CALLBACK_GROUPS_PER_HAND * len(nodes)
            )
        )
        executor.add_node(container)
        for node in nodes:
            executor.add_node(node)
        if configuration.autostart:
            stage = "group_activation"
            lifecycle.start()
        stage = "running"
        container.get_logger().info(
            f"running {len(nodes)} hand lifecycle nodes in one process: "
            f"{', '.join(configuration.device_namespaces)}"
        )
        spin_until_shutdown(executor, container.get_logger())
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except Exception as error:
        _log_cleanup_error(
            None if container is None else container.get_logger(),
            f"startup failed: stage={stage} {exception_details(error)}",
        )
        raise SystemExit(1) from error
    finally:
        logger = None if container is None else container.get_logger()
        if executor is not None:
            for owned_node in executor.get_nodes():
                executor.remove_node(owned_node)
            if not executor.shutdown(timeout_sec=EXECUTOR_SHUTDOWN_TIMEOUT_S):
                raise RuntimeError(
                    "executor cleanup incomplete; ROS resources retained"
                )
            executor = None
        if lifecycle is not None and rclpy.ok():
            try:
                for error in lifecycle.stop():
                    _log_cleanup_error(logger, error)
            except BaseException as error:  # noqa: BLE001 - final resource boundary
                _log_cleanup_error(logger, f"lifecycle group stop failed: {error}")
        cleanup_errors = destroy_hand_nodes(nodes)
        for error in cleanup_errors:
            _log_cleanup_error(logger, error)
        if cleanup_errors:
            raise RuntimeError("driver cleanup incomplete; ROS context retained")
        try:
            if container is not None:
                container.destroy_node()
        except BaseException as error:
            _log_cleanup_error(logger, f"container destruction failed: {error}")
            raise
        rclpy.try_shutdown()


def _log_cleanup_error(logger: ErrorLogger | None, message: str) -> None:
    if logger is None:
        return
    try:
        logger.error(message)
    except Exception:  # noqa: BLE001 - cleanup logging must not block shutdown
        return


__all__ = [
    "CALLBACK_GROUPS_PER_HAND",
    "CONTAINER_CALLBACK_GROUPS",
    "CONTAINER_NODE_NAME",
    "EXECUTOR_SHUTDOWN_TIMEOUT_S",
    "HandLifecycleGroup",
    "MultiDeviceConfiguration",
    "MultiDeviceLifecycleError",
    "MultiHandContainerNode",
    "create_hand_nodes",
    "destroy_hand_nodes",
    "main",
]


if __name__ == "__main__":
    main()
