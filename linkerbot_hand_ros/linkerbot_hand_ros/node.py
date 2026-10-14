"""Lifecycle ROS 2 driver for the single Hand SDK 1.0 facade."""

# Lifecycle callbacks must contain and report transport/backend failures.
# ruff: noqa: BLE001

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Protocol

import rclpy
from linkerbot_hand import HandDevice, HandSide, ValidationError
from linkerbot_hand.discovery import DiscoveryCandidate, DiscoveryStatus
from rcl_interfaces.msg import SetParametersResult
from rclpy.exceptions import InvalidHandle
from rclpy.executors import (
    Executor,
    ExternalShutdownException,
)
from rclpy.lifecycle import LifecycleNode, LifecycleState, TransitionCallbackReturn
from rclpy.parameter import Parameter

from .discovery_diagnostics import candidate_context, exception_details
from .driver_config import (
    DriverConfiguration,
    read_driver_configuration,
    validate_polling_plan,
)
from .driver_interfaces import DriverInterfaces
from .executor import MultiThreadedExecutor
from .parameter_updates import declare_driver_parameters, prepare_parameter_update
from .transport_factory import create_hand_device

DeviceFactory = Callable[[DriverConfiguration], HandDevice]

# One thread per mutually exclusive callback group of a hand node: the lifecycle
# control group shared by transitions and commands, plus the management,
# capability and diagnostic groups. A management service occupies its own group
# while the SDK answers, so every other group needs a thread of its own.
CALLBACK_GROUPS_PER_HAND = 4


class LinkerbotHandNode(LifecycleNode):
    """Map one ROS lifecycle to one SDK ``HandDevice`` owner."""

    def __init__(
        self,
        device_factory: DeviceFactory | None = None,
        *,
        discovery_candidate: DiscoveryCandidate | None = None,
        **kwargs: Any,
    ) -> None:
        if discovery_candidate is not None and (
            not isinstance(discovery_candidate, DiscoveryCandidate)
            or discovery_candidate.status is not DiscoveryStatus.VERIFIED
        ):
            raise ValidationError("ROS discovery requires a verified SDK candidate")
        super().__init__("linkerbot_hand", **kwargs)
        self._parameter_lock = threading.RLock()
        self._parameter_update_in_progress = False
        self._parameter_fault: str | None = None
        self._discovered_capabilities = (
            None if discovery_candidate is None else discovery_candidate.capabilities
        )
        self._discovery_location = (
            None
            if discovery_candidate is None
            else candidate_context(discovery_candidate)
        )
        identity_defaults = {}
        if discovery_candidate is not None:
            identity_defaults = {
                "model": discovery_candidate.model,
                "side": (
                    ""
                    if discovery_candidate.side is HandSide.NOT_APPLICABLE
                    else discovery_candidate.side.value
                ),
                "transport_json": "",
            }
        declare_driver_parameters(self, defaults=identity_defaults)
        if device_factory is not None:
            self._device_factory = device_factory
        elif discovery_candidate is not None:
            self._device_factory = lambda configuration: (
                discovery_candidate.create_hand_device(
                    config=configuration.device_config
                )
            )
        else:
            self._device_factory = create_hand_device
        self._configuration: DriverConfiguration | None = None
        self._device: HandDevice | None = None
        self._interfaces: DriverInterfaces | None = None
        self._active = False
        self._cleanup_incomplete = False
        self._destroying = False
        self._driver_destroyed = False
        self._parameter_callback_handle = self.add_on_set_parameters_callback(
            self._on_set_parameters
        )

    def on_configure(self, state: LifecycleState) -> TransitionCallbackReturn:
        """Construct configuration, transport, SDK facade, and ROS entities only."""

        # Failed configuration may still own entities or an SDK lease. Never
        # replace those owners until their cleanup has actually succeeded.
        if (
            self._configuration is not None
            or self._device is not None
            or self._interfaces is not None
        ):
            if not self._release_runtime():
                return TransitionCallbackReturn.FAILURE
            self._device = None
            self._configuration = None
        try:
            configuration = read_driver_configuration(
                lambda name: self.get_parameter(name).value,
                discovered_capabilities=self._discovered_capabilities,
            )
            self._configuration = configuration
            self._device = self._device_factory(configuration)
            self._interfaces = DriverInterfaces(
                self,
                configuration,
                device=self._require_device,
                is_active=lambda: self._active,
                error_text=self._error_text,
            )
            self._interfaces.create()
            result = super().on_configure(state)
            if result != TransitionCallbackReturn.SUCCESS:
                raise RuntimeError("managed ROS entity configuration failed")
            self._interfaces.publish_capabilities(
                self._require_device().get_capabilities()
            )
            self.get_logger().info(
                f"configured model={configuration.model}; device remains disconnected"
            )
            return TransitionCallbackReturn.SUCCESS
        except Exception as error:
            self._log_device_failure("configure", error)
            if self._release_runtime():
                self._device = None
                self._configuration = None
            return TransitionCallbackReturn.FAILURE

    def on_activate(self, state: LifecycleState) -> TransitionCallbackReturn:
        """Open, verify, start SDK polling, then enable ROS control surfaces."""

        if self._parameter_fault is not None or self._cleanup_incomplete:
            self.get_logger().error(
                "activate refused: incomplete recovery requires cleanup"
            )
            return TransitionCallbackReturn.FAILURE
        device = self._device
        configuration = self._configuration
        interfaces = self._interfaces
        if device is None or configuration is None or interfaces is None:
            self.get_logger().error("activate failed: hand is not configured")
            return TransitionCallbackReturn.FAILURE
        try:
            device.open()
            capabilities = device.get_capabilities()
            validate_polling_plan(capabilities, configuration.polling_plan)
            device.start_polling(configuration.polling_plan)
            result = super().on_activate(state)
            if result != TransitionCallbackReturn.SUCCESS:
                raise RuntimeError("managed ROS entity activation failed")
            self._active = True
            interfaces.activate(capabilities)
            identity = capabilities.identity
            self.get_logger().info(
                f"activated model={capabilities.model} side={identity.side.value} "
                f"firmware={identity.firmware or 'unknown'}"
            )
            return TransitionCallbackReturn.SUCCESS
        except Exception as error:
            self._log_device_failure("activate", error)
            self._rollback_activation(state)
            return TransitionCallbackReturn.FAILURE

    def on_deactivate(self, state: LifecycleState) -> TransitionCallbackReturn:
        """Stop accepting commands and SDK polling without closing the lease."""

        self._active = False
        success = self._deactivate_interfaces()
        success = self._stop_polling() and success
        if not success:
            self._cleanup_incomplete = True
            return TransitionCallbackReturn.ERROR
        try:
            result = super().on_deactivate(state)
            success = success and result == TransitionCallbackReturn.SUCCESS
        except Exception as error:
            success = False
            self.get_logger().error(
                f"managed ROS deactivate failed: {self._error_text(error)}"
            )
        if not success:
            return TransitionCallbackReturn.ERROR
        self.get_logger().info("deactivated; SDK polling stopped")
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: LifecycleState) -> TransitionCallbackReturn:
        """Close the SDK runtime and destroy all configured ROS entities."""

        if not self._release_runtime():
            return TransitionCallbackReturn.ERROR
        success = True
        try:
            result = super().on_cleanup(state)
            success = success and result == TransitionCallbackReturn.SUCCESS
        except Exception as error:
            success = False
            self.get_logger().error(
                f"managed ROS cleanup failed: {self._error_text(error)}"
            )
        if success:
            self._device = None
            self._configuration = None
            self._parameter_fault = None
            self.get_logger().info("cleaned up; SDK connection closed")
            return TransitionCallbackReturn.SUCCESS
        return TransitionCallbackReturn.ERROR

    def on_shutdown(self, state: LifecycleState) -> TransitionCallbackReturn:
        return self._final_transition(super().on_shutdown, state, "shutdown")

    def on_error(self, state: LifecycleState) -> TransitionCallbackReturn:
        return self._final_transition(super().on_error, state, "error cleanup")

    def _final_transition(
        self,
        managed_callback: Callable[[LifecycleState], TransitionCallbackReturn],
        state: LifecycleState,
        description: str,
    ) -> TransitionCallbackReturn:
        if not self._release_runtime():
            return TransitionCallbackReturn.ERROR
        success = True
        try:
            result = managed_callback(state)
            success = success and result == TransitionCallbackReturn.SUCCESS
        except Exception as error:
            success = False
            self.get_logger().error(
                f"managed ROS {description} failed: {self._error_text(error)}"
            )
        if success:
            self._device = None
            self._configuration = None
            self._parameter_fault = None
            return TransitionCallbackReturn.SUCCESS
        return TransitionCallbackReturn.ERROR

    def _on_set_parameters(self, parameters: list[Parameter]) -> SetParametersResult:
        """Validate only; another on-set callback can still reject this update."""

        if self._parameter_fault is not None or self._cleanup_incomplete:
            return SetParametersResult(
                successful=False, reason="incomplete recovery requires cleanup"
            )
        prepared = prepare_parameter_update(
            parameters,
            self._configuration,
            read_parameter=lambda name: self.get_parameter(name).value,
            error_text=self._error_text,
            discovered_capabilities=self._discovered_capabilities,
        )
        if not prepared.result.successful or prepared.configuration is None:
            return prepared.result
        try:
            if self._active and self._device is not None:
                validate_polling_plan(
                    self._device.get_capabilities(), prepared.configuration.polling_plan
                )
        except Exception as error:
            return SetParametersResult(successful=False, reason=self._error_text(error))
        return prepared.result

    def set_parameters(
        self, parameter_list: list[Parameter]
    ) -> list[SetParametersResult]:
        """Preserve ROS per-parameter semantics using the same commit boundary."""

        return [
            self.set_parameters_atomically([parameter]) for parameter in parameter_list
        ]

    def set_parameters_atomically(
        self, parameter_list: list[Parameter]
    ) -> SetParametersResult:
        """Apply runtime changes after ROS validation and compensate on failure.

        Use public rclpy APIs, including for restoration, so all validators and
        parameter event observers remain involved. Parameter events can expose
        the committed proposal followed by its compensating restoration.
        """

        # rclpy may set its own parameters during base-node construction.
        if not hasattr(self, "_parameter_lock"):
            return super().set_parameters_atomically(parameter_list)
        with self._parameter_lock:
            if self._parameter_update_in_progress:
                return SetParametersResult(
                    successful=False,
                    reason="nested parameter updates are not supported",
                )
            self._parameter_update_in_progress = True
            try:
                return self._commit_parameter_update(parameter_list)
            finally:
                self._parameter_update_in_progress = False

    def _parameter_snapshot(self) -> dict[str, Parameter]:
        # An empty prefix returns all declared parameters on Humble and Jazzy.
        return self.get_parameters_by_prefix("")

    @staticmethod
    def _restoration_parameters(
        before: dict[str, Parameter], current: dict[str, Parameter]
    ) -> list[Parameter]:
        restored = []
        for name in sorted(before.keys() | current.keys()):
            old, new = before.get(name), current.get(name)
            if old is new:
                continue
            # Parameter compares by object identity. Pre-set callbacks may
            # rebuild equivalent Parameter objects during recovery.
            if (
                old is None
                or new is None
                or old.to_parameter_msg() != new.to_parameter_msg()
            ):
                restored.append(before.get(name, Parameter(name)))
        return restored

    def _commit_parameter_update(
        self, parameters: list[Parameter]
    ) -> SetParametersResult:
        before = self._parameter_snapshot()
        previous = self._configuration
        runtime_attempted = False
        try:
            result = super().set_parameters_atomically(parameters)
            if not result.successful or previous is None:
                return result
            updated = read_driver_configuration(
                lambda name: self.get_parameter(name).value,
                discovered_capabilities=self._discovered_capabilities,
            )
            if updated != previous:
                runtime_attempted = True
                self._apply_runtime_configuration(updated)
            return result
        except Exception as error:
            if not runtime_attempted and not self._restoration_parameters(
                before, self._parameter_snapshot()
            ):
                # Preserve rclpy errors such as undeclared/ill-typed parameters.
                raise
            reason = self._error_text(error)
            recovery_errors = []
            if runtime_attempted and previous is not None:
                try:
                    self._apply_runtime_configuration(previous)
                except Exception as recovery_error:
                    recovery_errors.append(
                        f"runtime rollback failed: {self._error_text(recovery_error)}"
                    )
            restore = self._restoration_parameters(before, self._parameter_snapshot())
            try:
                if restore:
                    restored = super().set_parameters_atomically(restore)
                    if not restored.successful:
                        raise RuntimeError(restored.reason)
                if self._restoration_parameters(before, self._parameter_snapshot()):
                    raise RuntimeError(
                        "callbacks changed the restored parameter values"
                    )
            except Exception as recovery_error:
                recovery_errors.append(
                    f"parameter rollback failed: {self._error_text(recovery_error)}"
                )
            if recovery_errors:
                reason = f"{reason}; {'; '.join(recovery_errors)}; cleanup required"
                self._fail_parameter_recovery(reason)
            self.get_logger().error(f"parameter update failed: {reason}")
            return SetParametersResult(successful=False, reason=reason)

    def _apply_runtime_configuration(self, configuration: DriverConfiguration) -> None:
        if self._active and self._device is not None:
            self._device.start_polling(configuration.polling_plan)
        if self._interfaces is not None:
            self._interfaces.apply_rates(configuration)
        self._configuration = configuration

    def _fail_parameter_recovery(self, reason: str) -> None:
        """Disable command admission even if compensation cannot restore state."""

        self._parameter_fault = reason
        was_active, self._active = self._active, False
        if was_active:
            try:
                self.trigger_deactivate()
            except Exception as error:
                self.get_logger().error(
                    f"parameter failure deactivation failed: {self._error_text(error)}"
                )
        self._release_runtime()
        # Retain the parameters that actually committed as the desired config;
        # runtime is stopped and activation remains blocked until cleanup.
        if self._configuration is not None:
            try:
                self._configuration = read_driver_configuration(
                    lambda name: self.get_parameter(name).value,
                    discovered_capabilities=self._discovered_capabilities,
                )
            except Exception as error:
                self.get_logger().error(
                    f"parameter failure configuration unavailable: {self._error_text(error)}"
                )
        self._parameter_fault = (
            reason if self._device is not None or self._interfaces is not None else None
        )

    def _rollback_activation(self, state: LifecycleState) -> None:
        self._active = False
        success = self._deactivate_interfaces()
        success = self._stop_polling() and success
        if not success:
            self._cleanup_incomplete = True
            return
        try:
            if super().on_deactivate(state) != TransitionCallbackReturn.SUCCESS:
                raise RuntimeError("managed ROS entity activation rollback failed")
        except Exception as error:
            self._cleanup_incomplete = True
            self.get_logger().error(
                f"activate rollback failed: {self._error_text(error)}"
            )
            return
        self._cleanup_incomplete = not self._close_device()

    def _release_runtime(self) -> bool:
        self._cleanup_incomplete = True
        self._active = False
        success = self._deactivate_interfaces()
        success = self._stop_polling() and success
        # SDK and ROS entities remain dependencies of outstanding workers and
        # admitted callbacks. Destruction must not run after a drain timeout.
        if not success or not self._destroy_interfaces() or not self._close_device():
            return False
        self._cleanup_incomplete = False
        return True

    def _deactivate_interfaces(self) -> bool:
        if self._interfaces is None:
            return True
        try:
            self._interfaces.deactivate()
            return True
        except Exception as error:
            self.get_logger().error(
                f"ROS interface deactivate failed: {self._error_text(error)}"
            )
            return False

    def _destroy_interfaces(self) -> bool:
        if self._interfaces is None:
            return True
        try:
            self._interfaces.destroy()
            self._interfaces = None
            return True
        except Exception as error:
            self.get_logger().error(
                f"ROS interface destruction failed: {self._error_text(error)}"
            )
            return False

    def _stop_polling(self) -> bool:
        if self._device is None:
            return True
        try:
            self._device.stop_polling()
            return True
        except Exception as error:
            self._log_device_failure("SDK stop_polling", error)
            return False

    def _close_device(self) -> bool:
        if self._device is None:
            return True
        try:
            self._device.close()
            return True
        except Exception as error:
            self._log_device_failure("SDK close", error)
            return False

    def _require_device(self) -> HandDevice:
        if self._device is None:
            raise RuntimeError("hand is not configured")
        return self._device

    def _publish_cached_state(self) -> None:
        if self._interfaces is not None:
            self._interfaces.publish_cached_state()

    def _publish_command_status(self) -> None:
        if self._interfaces is not None:
            self._interfaces.publish_command_status()

    def _publish_diagnostics(self) -> None:
        if self._interfaces is not None:
            self._interfaces.publish_diagnostics()

    @staticmethod
    def _error_text(error: BaseException) -> str:
        return exception_details(error)

    def _log_device_failure(self, stage: str, error: BaseException) -> None:
        location = f"node={self.get_fully_qualified_name()}"
        if self._discovery_location is not None:
            location += f" {self._discovery_location}"
        self.get_logger().error(
            f"{stage} failed: {exception_details(error)} ({location})"
        )

    def destroy_node(self) -> None:
        if self._destroying or self._driver_destroyed:
            return
        self._destroying = True
        try:
            released = self._release_runtime()
            if not released:
                raise RuntimeError(
                    "driver cleanup incomplete; retry cleanup/destroy_node before reusing resources"
                )
            self._device = None
            self._configuration = None
            super().destroy_node()
            self._driver_destroyed = True
        finally:
            self._destroying = False


class WarningLogger(Protocol):
    """Minimal ROS logger surface used while spinning."""

    def warning(self, message: str) -> None: ...


def spin_until_shutdown(executor: Executor, logger: WarningLogger) -> None:
    """Spin until shutdown, tolerating the destroyed-entity response race.

    A lifecycle transition can destroy a service entity between an in-flight
    callback returning and rclpy sending its response, and rclpy re-raises that
    ``InvalidHandle`` out of ``spin()``. The client sees a timeout; the process
    must keep serving every other hand. Resuming is safe because the failed task
    was already dropped from the executor before the exception surfaced.
    """

    while True:
        try:
            executor.spin()
            return
        except InvalidHandle as error:
            logger.warning(
                "an in-flight callback response met an entity destroyed by a "
                f"lifecycle transition: {error}"
            )
            if not rclpy.ok():
                return


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node: LinkerbotHandNode | None = None
    executor: MultiThreadedExecutor | None = None
    try:
        executor = MultiThreadedExecutor(num_threads=CALLBACK_GROUPS_PER_HAND)
        node = LinkerbotHandNode()
        executor.add_node(node)
        spin_until_shutdown(executor, node.get_logger())
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if executor is not None:
            for owned_node in executor.get_nodes():
                executor.remove_node(owned_node)
            if not executor.shutdown(timeout_sec=5.0):
                raise RuntimeError(
                    "executor cleanup incomplete; ROS resources retained"
                )
        executor = None
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
