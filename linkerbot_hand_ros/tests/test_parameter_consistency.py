"""Real rclpy parameter boundaries with a fake SDK and injected failures."""

import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand_ros.node import LinkerbotHandNode
from rcl_interfaces.msg import SetParametersResult
from rcl_interfaces.srv import SetParameters, SetParametersAtomically
from rclpy.exceptions import ParameterNotDeclaredException
from rclpy.executors import SingleThreadedExecutor
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.node import Node
from rclpy.parameter import Parameter

PRE_SET_SUPPORTED = pytest.mark.skipif(
    not hasattr(Node, "add_pre_set_parameters_callback"),
    reason="This rclpy distribution does not expose pre-set callbacks",
)
POST_SET_SUPPORTED = pytest.mark.skipif(
    not hasattr(Node, "add_post_set_parameters_callback"),
    reason="This rclpy distribution does not expose post-set callbacks",
)


@pytest.fixture
def rig():
    rclpy.init()
    builder = DeviceBuilder()
    node = LinkerbotHandNode(device_factory=builder)
    try:
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        yield node, builder
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


@pytest.mark.parametrize("active", [False, True])
def test_later_validator_rejection_never_changes_runtime(rig, active):
    node, builder = rig
    if active:
        node.trigger_activate()
    before = node._configuration
    polls = list(builder.latest_runtime.polling_plans) if active else []
    seen = []

    def reject(_parameters):
        # Check during the actual later callback, not just after rollback.
        seen.append(node._configuration)
        assert node._interfaces._configuration == before
        if active:
            assert builder.latest_runtime.polling_plans == polls
        return SetParametersResult(successful=False, reason="application veto")

    # rclpy prepends validators: reinstall driver validation before the veto.
    node.remove_on_set_parameters_callback(node._on_set_parameters)
    node.add_on_set_parameters_callback(reject)
    node.add_on_set_parameters_callback(node._on_set_parameters)
    result = node.set_parameters_atomically(
        [Parameter("angles_hz", value=50.0), Parameter("publish_rate_hz", value=20.0)]
    )
    assert not result.successful and result.reason == "application veto"
    assert seen == [before]
    assert node._configuration == before
    assert node.get_parameter("angles_hz").value == 100.0


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize(
    "pre_set", [False, pytest.param(True, marks=PRE_SET_SUPPORTED)]
)
def test_commit_precedes_runtime_application_and_keeps_effective_parameters(
    rig, active, pre_set, monkeypatch
):
    node, builder = rig
    if active:
        node.trigger_activate()
    original = node._interfaces.apply_rates
    observations = []

    def apply(configuration):
        observations.append(node.get_parameter("angles_hz").value)
        original(configuration)

    monkeypatch.setattr(node._interfaces, "apply_rates", apply)
    parameters = [Parameter("angles_hz", value=50.0)]
    if pre_set:
        node.add_pre_set_parameters_callback(
            lambda parameters: [*parameters, Parameter("publish_rate_hz", value=25.0)]
        )
    else:
        parameters.append(Parameter("publish_rate_hz", value=25.0))
    result = node.set_parameters_atomically(parameters)
    assert result.successful
    assert observations == [50.0]
    assert node._configuration.polling_plan.angles_hz == 50.0
    assert node._configuration.publish_rate_hz == 25.0
    assert node.get_parameter("publish_rate_hz").value == 25.0
    assert node._interfaces._state_worker.rate_hz == 25.0
    if active:
        assert (
            builder.latest_runtime.polling_plans[-1] == node._configuration.polling_plan
        )


@pytest.mark.parametrize("failure", ["polling", "rates"])
def test_apply_failure_restores_atomic_parameters_and_runtime(
    rig, monkeypatch, failure
):
    node, builder = rig
    node.trigger_activate()
    previous = node._configuration
    if hasattr(node, "add_pre_set_parameters_callback"):
        # Keep the Jazzy regression case: compensation must compare parameter
        # values even when a pre-set callback creates fresh Parameter objects.
        node.add_pre_set_parameters_callback(
            lambda parameters: [Parameter(p.name, p.type_, p.value) for p in parameters]
        )
    original = (
        node._interfaces.apply_rates
        if failure == "rates"
        else node._device.start_polling
    )

    def fail_new(value):
        original(value)  # Deliberately fail after a partial effect.
        rate = value.publish_rate_hz if failure == "rates" else value.angles_hz
        if rate == 50.0:
            raise RuntimeError("injected apply failure")

    owner, method = (
        (node._interfaces, "apply_rates")
        if failure == "rates"
        else (node._device, "start_polling")
    )
    monkeypatch.setattr(owner, method, fail_new)
    result = node.set_parameters_atomically(
        [Parameter("angles_hz", value=50.0), Parameter("publish_rate_hz", value=50.0)]
    )
    assert not result.successful and "injected apply failure" in result.reason
    assert node.get_parameter("angles_hz").value == 100.0
    assert node.get_parameter("publish_rate_hz").value == 100.0
    assert node._configuration == previous
    assert node._interfaces._configuration == previous
    assert node._interfaces._state_worker.rate_hz == 100.0
    assert builder.latest_runtime.polling_plans[-1] == previous.polling_plan
    assert node._active
    assert node._parameter_fault is None


def test_parameter_compensation_veto_stops_control_until_cleanup(rig, monkeypatch):
    node, builder = rig
    node.trigger_activate()
    original = node._interfaces.apply_rates

    def apply(configuration):
        if configuration.polling_plan.angles_hz == 50.0:
            raise RuntimeError("apply failed")
        original(configuration)

    monkeypatch.setattr(node._interfaces, "apply_rates", apply)

    def veto_restore(parameters):
        if any(p.name == "angles_hz" and p.value == 100.0 for p in parameters):
            return SetParametersResult(successful=False, reason="restore veto")
        return SetParametersResult(successful=True)

    node.add_on_set_parameters_callback(veto_restore)
    result = node.set_parameters_atomically([Parameter("angles_hz", value=50.0)])
    assert not result.successful
    assert "parameter rollback failed" in result.reason
    assert "cleanup required" in result.reason
    assert node.get_parameter("angles_hz").value == 50.0
    assert node._configuration.polling_plan.angles_hz == 50.0
    assert not node._active
    assert not builder.latest_runtime._polling
    assert node._interfaces is None
    assert node.trigger_activate() == TransitionCallbackReturn.FAILURE
    assert not node.set_parameters_atomically(
        [Parameter("angles_hz", value=60.0)]
    ).successful
    assert node.trigger_cleanup() == TransitionCallbackReturn.SUCCESS
    node.remove_on_set_parameters_callback(veto_restore)
    assert node._parameter_fault is None
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    assert builder.latest_runtime.polling_plans[-1].angles_hz == 50.0


def test_individual_updates_keep_successful_predecessors(rig, monkeypatch):
    node, _builder = rig
    original = node._interfaces.apply_rates

    def apply(configuration):
        if configuration.publish_rate_hz == 50.0:
            raise RuntimeError("rates failed")
        original(configuration)

    monkeypatch.setattr(node._interfaces, "apply_rates", apply)
    results = node.set_parameters(
        [Parameter("angles_hz", value=50.0), Parameter("publish_rate_hz", value=50.0)]
    )
    assert [result.successful for result in results] == [True, False]
    assert node.get_parameter("angles_hz").value == 50.0
    assert node.get_parameter("publish_rate_hz").value == 100.0
    assert node._configuration.polling_plan.angles_hz == 50.0
    assert node._configuration.publish_rate_hz == 100.0


@POST_SET_SUPPORTED
def test_post_set_failure_restores_parameters_without_touching_runtime(rig):
    node, builder = rig
    node.trigger_activate()
    previous = node._configuration
    polls = list(builder.latest_runtime.polling_plans)

    def post_set(parameters):
        if any(p.name == "angles_hz" and p.value == 50.0 for p in parameters):
            raise RuntimeError("post-set failed")

    node.add_post_set_parameters_callback(post_set)
    result = node.set_parameters_atomically([Parameter("angles_hz", value=50.0)])
    assert not result.successful and "post-set failed" in result.reason
    assert node.get_parameter("angles_hz").value == 100.0
    assert node._configuration == previous
    assert builder.latest_runtime.polling_plans == polls


@PRE_SET_SUPPORTED
def test_pre_set_changes_are_checked_during_compensation(rig, monkeypatch):
    node, _builder = rig
    node.trigger_activate()
    # This callback always rewrites the proposed value, including on rollback.
    node.add_pre_set_parameters_callback(lambda _: [Parameter("angles_hz", value=50.0)])
    original = node._interfaces.apply_rates

    def apply(configuration):
        if configuration.polling_plan.angles_hz == 50.0:
            raise RuntimeError("apply failed")
        original(configuration)

    monkeypatch.setattr(node._interfaces, "apply_rates", apply)
    result = node.set_parameters_atomically([Parameter("angles_hz", value=60.0)])
    assert not result.successful
    assert "callbacks changed the restored parameter values" in result.reason
    assert not node._active
    assert node.get_parameter("angles_hz").value == 50.0
    assert node._configuration.polling_plan.angles_hz == 50.0


@pytest.mark.parametrize(
    "stage", ["on", pytest.param("post", marks=POST_SET_SUPPORTED)]
)
def test_nested_parameter_update_is_rejected_without_corrupting_outer_update(
    rig, stage
):
    node, _builder = rig
    nested = []

    def callback(_parameters):
        nested.append(
            node.set_parameters_atomically([Parameter("angles_hz", value=75.0)])
        )
        return SetParametersResult(successful=True)

    if stage == "on":
        node.add_on_set_parameters_callback(callback)
    else:
        node.add_post_set_parameters_callback(callback)
    result = node.set_parameters_atomically([Parameter("angles_hz", value=50.0)])
    assert result.successful
    assert len(nested) == 1 and not nested[0].successful
    assert "nested parameter updates" in nested[0].reason
    assert node.get_parameter("angles_hz").value == 50.0
    assert node._configuration.polling_plan.angles_hz == 50.0


def test_ros_undeclared_parameter_error_keeps_original_contract(rig):
    node, _builder = rig
    with pytest.raises(ParameterNotDeclaredException):
        node.set_parameters_atomically([Parameter("not_a_parameter", value=50.0)])
    assert node.set_parameters_atomically(
        [Parameter("angles_hz", value=50.0)]
    ).successful


def test_error_transition_cleanup_allows_reconfiguration(rig, monkeypatch):
    node, _builder = rig
    node.trigger_activate()

    def failed_apply(_configuration):
        raise RuntimeError("apply and rollback failed")

    monkeypatch.setattr(node._interfaces, "apply_rates", failed_apply)
    # Deactivation fails, so rclpy runs on_error and releases the whole runtime.
    original_stop = node._stop_polling
    attempts = 0

    def fail_first_stop():
        nonlocal attempts
        attempts += 1
        return False if attempts == 1 else original_stop()

    monkeypatch.setattr(node, "_stop_polling", fail_first_stop)
    result = node.set_parameters_atomically([Parameter("angles_hz", value=50.0)])
    assert not result.successful
    assert not node._active
    assert node._device is None and node._interfaces is None
    assert node._parameter_fault is None
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS


@pytest.mark.parametrize("atomic", [False, True])
def test_real_parameter_services_report_apply_failure(rig, monkeypatch, atomic):
    node, _builder = rig
    node.trigger_activate()
    original = node._interfaces.apply_rates

    def apply(configuration):
        if configuration.polling_plan.angles_hz == 50.0:
            raise RuntimeError("service apply failed")
        original(configuration)

    monkeypatch.setattr(node._interfaces, "apply_rates", apply)
    caller = Node("parameter_service_client")
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    executor.add_node(caller)
    service_type = SetParametersAtomically if atomic else SetParameters
    suffix = "set_parameters_atomically" if atomic else "set_parameters"
    client = caller.create_client(service_type, f"/linkerbot_hand/{suffix}")
    try:
        assert client.wait_for_service(timeout_sec=3.0)
        pending = client.call_async(
            service_type.Request(
                parameters=[Parameter("angles_hz", value=50.0).to_parameter_msg()]
            )
        )
        executor.spin_until_future_complete(pending, timeout_sec=3.0)
        assert pending.done()
        response = pending.result()
        result = response.result if atomic else response.results[0]
        assert not result.successful and "service apply failed" in result.reason
        assert node.get_parameter("angles_hz").value == 100.0
        assert node._configuration.polling_plan.angles_hz == 100.0
    finally:
        executor.remove_node(node)
        executor.remove_node(caller)
        executor.shutdown()
        caller.destroy_node()
