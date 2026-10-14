"""Failed shutdown retains the resources that ROS workers still use."""

import threading
import time
from dataclasses import replace

import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand import AngleSample, DataOrigin, LifecycleError, SampleMeta
from linkerbot_hand_ros.driver_interfaces import DriverInterfaces
from linkerbot_hand_ros.node import LinkerbotHandNode
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.parameter import Parameter

from linkerbot_hand_msgs.msg import HandJointCommand


@pytest.fixture
def rig():
    rclpy.init(args=[])
    builder = DeviceBuilder()
    node = LinkerbotHandNode(
        device_factory=builder,
        parameter_overrides=[Parameter("shutdown_timeout_s", value=0.05)],
    )
    try:
        yield node, builder
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


@pytest.mark.parametrize("worker", ["state", "status"])
def test_destroy_keeps_worker_dependencies_until_worker_exits(rig, monkeypatch, worker):
    node, builder = rig
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    interfaces = node._interfaces
    snapshot = interfaces.snapshot
    commands = interfaces.commands
    owner, method = (
        (snapshot, "publish_snapshot")
        if worker == "state"
        else (commands, "publish_updates")
    )
    original = getattr(owner, method)
    entered, release = threading.Event(), threading.Event()
    errors = []

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(3.0)
        try:
            return original(*args, **kwargs)
        except Exception as error:
            errors.append(error)
            raise

    monkeypatch.setattr(owner, method, held)
    runtime = builder.latest_runtime
    runtime.snapshot = replace(
        runtime.snapshot,
        angles=AngleSample(
            raw=(0,) * 6,
            percent=(0.0,) * 6,
            physical_rad=(None,) * 6,
            meta=SampleMeta(
                sequence=1,
                collected_at=time.time(),
                age_s=0,
                valid=True,
                stale=False,
                connection_generation=1,
                origin=DataOrigin.DEVICE_RESPONSE,
                within_declared_range=True,
            ),
        ),
    )
    try:
        assert entered.wait(2.0)
        with pytest.raises(RuntimeError, match="cleanup incomplete"):
            node.destroy_node()
        assert node._interfaces is interfaces
        assert interfaces.snapshot is snapshot and interfaces.commands is commands
        assert runtime.close_count == 0
        assert not node._driver_destroyed
        release.set()
        node.destroy_node()
        assert not errors
        assert runtime.close_count == 1
        assert node._driver_destroyed and node._interfaces is None
    finally:
        release.set()


@pytest.mark.parametrize("operation", ["deactivate", "destroy"])
def test_cleanup_times_out_while_status_publisher_holds_lock(
    rig, monkeypatch, operation
):
    node, builder = rig
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    interfaces = node._interfaces
    commands = interfaces.commands
    publisher = commands._status_publisher
    publish = publisher.publish
    entered, release, completed = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    cleanup_errors, publication_errors = [], []

    def held(message):
        entered.set()
        assert release.wait(3.0)
        try:
            publish(message)
        except Exception as error:
            publication_errors.append(error)
            raise

    monkeypatch.setattr(publisher, "publish", held)

    def cleanup():
        try:
            if operation == "deactivate":
                interfaces.deactivate()
            else:
                node.destroy_node()
        except (RuntimeError, LifecycleError) as error:
            cleanup_errors.append(error)
        finally:
            completed.set()

    thread = threading.Thread(target=cleanup, name="test-bounded-cleanup")
    commands._handle_angles(
        HandJointCommand(
            client_id=1,
            user_sequence=1,
            representation=HandJointCommand.REPRESENTATION_PERCENT,
            values=[50.0] * 6,
        )
    )
    try:
        assert entered.wait(1.0)
        thread.start()
        # The rig sets 50 ms per drain. Keep publication blocked beyond the
        # whole cleanup budget to distinguish timeout from eventual completion.
        assert completed.wait(0.5), "cleanup waited without a publication deadline"
        assert len(cleanup_errors) == 1
        if operation == "deactivate":
            assert isinstance(cleanup_errors[0], LifecycleError)
        else:
            assert "cleanup incomplete" in str(cleanup_errors[0])
            assert node._cleanup_incomplete
        assert node._interfaces is interfaces
        assert interfaces.commands is commands
        assert publisher in node.publishers
        assert builder.latest_runtime.close_count == 0
        assert not commands._subscriptions and commands.tracked_count == 0
        assert interfaces._status_worker.active
        assert rclpy.ok()
        release.set()
        thread.join(1.0)
        node.destroy_node()
        assert not publication_errors
        assert builder.latest_runtime.close_count == 1
        assert node._driver_destroyed
    finally:
        release.set()
        if thread.ident is not None:
            thread.join(2.0)
            assert not thread.is_alive()


@pytest.mark.parametrize("stage", ["create", "publish"])
def test_failed_configure_keeps_owner_and_retries_cleanup_before_replacement(
    rig, monkeypatch, stage
):
    node, builder = rig
    cleanup_allowed = False
    fail_configuration = True
    captured = []
    original_create = DriverInterfaces._create
    original_publish = DriverInterfaces.publish_capabilities
    original_destroy = DriverInterfaces.destroy

    def create(self):
        original_create(self)
        if stage == "create" and fail_configuration:
            captured.append(self)
            raise RuntimeError("interface creation failed")

    def publish(self, capabilities):
        if stage == "publish" and fail_configuration:
            captured.append(self)
            raise RuntimeError("capability publication failed")
        original_publish(self, capabilities)

    def destroy(self):
        if not cleanup_allowed:
            raise RuntimeError("interface cleanup failed")
        original_destroy(self)

    monkeypatch.setattr(DriverInterfaces, "_create", create)
    monkeypatch.setattr(DriverInterfaces, "publish_capabilities", publish)
    monkeypatch.setattr(DriverInterfaces, "destroy", destroy)
    try:
        assert node.trigger_configure() == TransitionCallbackReturn.FAILURE
        interfaces = captured[0]
        device, configuration = node._device, node._configuration
        assert node._interfaces is interfaces
        assert device is not None and configuration is not None
        assert node.trigger_configure() == TransitionCallbackReturn.FAILURE
        assert node._interfaces is interfaces and node._device is device
        assert node._configuration is configuration
        assert len(builder.calls) == 1
        assert interfaces.diagnostic_timer is not None

        cleanup_allowed = True
        fail_configuration = False
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        assert node._interfaces is not interfaces
        assert interfaces.diagnostic_timer is None
        assert len(builder.calls) == 2
    finally:
        cleanup_allowed = True
        fail_configuration = False
        for interfaces in captured:
            original_destroy(interfaces)


def test_failed_device_close_keeps_configure_owner_until_retry(rig, monkeypatch):
    node, builder = rig
    original_factory = node._device_factory
    close_allowed = False
    fail_configuration = True
    original_publish = DriverInterfaces.publish_capabilities

    def factory(configuration):
        device = original_factory(configuration)
        close = device.close

        def fail_close():
            if not close_allowed:
                raise RuntimeError("device cleanup failed")
            close()

        monkeypatch.setattr(device, "close", fail_close)
        return device

    def publish(self, capabilities):
        if fail_configuration:
            raise RuntimeError("capability publication failed")
        original_publish(self, capabilities)

    monkeypatch.setattr(node, "_device_factory", factory)
    monkeypatch.setattr(DriverInterfaces, "publish_capabilities", publish)
    try:
        assert node.trigger_configure() == TransitionCallbackReturn.FAILURE
        device, configuration = node._device, node._configuration
        assert device is not None and configuration is not None
        assert node.trigger_configure() == TransitionCallbackReturn.FAILURE
        assert node._device is device and node._configuration is configuration
        assert len(builder.calls) == 1
        close_allowed = True
        fail_configuration = False
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        assert len(builder.calls) == 2
    finally:
        close_allowed = True
        fail_configuration = False


@pytest.mark.parametrize("child", ["snapshot", "management"])
def test_failed_child_creation_retains_entities_when_rollback_also_fails(
    rig, monkeypatch, child
):
    node, builder = rig
    create_name, destroy_name = (
        ("create_lifecycle_publisher", "destroy_lifecycle_publisher")
        if child == "snapshot"
        else ("create_service", "destroy_service")
    )
    create, destroy = getattr(node, create_name), getattr(node, destroy_name)
    created = []
    allowed = False

    def fail_create(*args, **kwargs):
        if created and not allowed:
            raise RuntimeError("child creation failed")
        entity = create(*args, **kwargs)
        created.append(entity)
        return entity

    def fail_destroy(entity):
        if not allowed:
            raise RuntimeError("child rollback failed")
        return destroy(entity)

    monkeypatch.setattr(node, create_name, fail_create)
    monkeypatch.setattr(node, destroy_name, fail_destroy)
    try:
        assert node.trigger_configure() == TransitionCallbackReturn.FAILURE
        interfaces = node._interfaces
        assert getattr(interfaces, child) is not None
        assert node.trigger_configure() == TransitionCallbackReturn.FAILURE
        assert node._interfaces is interfaces and len(builder.calls) == 1
        old_entities = list(created)
        allowed = True
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        entities = node.publishers if child == "snapshot" else node.services
        assert not set(old_entities).intersection(entities)
    finally:
        allowed = True


@pytest.mark.parametrize("mode", ["single", "multi"])
def test_entry_cleanup_failure_keeps_context_and_sdk_until_worker_retry(
    monkeypatch, mode
):
    from linkerbot_hand_ros import multi_device
    from linkerbot_hand_ros import node as entry

    nodes, builders, containers = [], [], []
    entered, release = threading.Event(), threading.Event()
    original_publish = DriverInterfaces.publish_command_status
    node_type = LinkerbotHandNode

    def build(namespace=""):
        builder = DeviceBuilder()
        node = node_type(
            device_factory=builder,
            namespace=namespace,
            parameter_overrides=[Parameter("shutdown_timeout_s", value=0.05)],
        )
        nodes.append(node)
        builders.append(builder)
        return node

    def hold(self):
        entered.set()
        assert release.wait(5.0)
        original_publish(self)

    def spin(executor, logger):
        if mode == "single":
            assert nodes[0].trigger_configure() == TransitionCallbackReturn.SUCCESS
            assert nodes[0].trigger_activate() == TransitionCallbackReturn.SUCCESS
        assert entered.wait(1.0)

    module = entry
    if mode == "multi":
        module = multi_device
        container_type = multi_device.MultiHandContainerNode

        def container():
            owner = container_type(
                parameter_overrides=[
                    Parameter("device_namespaces", value=["/left", "/right"]),
                    Parameter("autostart", value=True),
                ]
            )
            containers.append(owner)
            return owner

        monkeypatch.setattr(module, "MultiHandContainerNode", container)
        create_nodes = module.create_hand_nodes
        monkeypatch.setattr(
            module,
            "create_hand_nodes",
            lambda cfg: create_nodes(cfg, node_factory=build),
        )
    else:
        monkeypatch.setattr(entry, "LinkerbotHandNode", build)
    monkeypatch.setattr(DriverInterfaces, "publish_command_status", hold)
    monkeypatch.setattr(module, "spin_until_shutdown", spin)
    try:
        with pytest.raises(RuntimeError, match="cleanup incomplete"):
            module.main(args=[])
        assert rclpy.ok()
        assert all(node._interfaces is not None for node in nodes)
        assert all(builder.latest_runtime.close_count == 0 for builder in builders)
        assert all(not node._driver_destroyed for node in nodes)
    finally:
        release.set()
        for node in nodes:
            node.destroy_node()
        for container in containers:
            container.destroy_node()
        rclpy.try_shutdown()


def test_activation_rollback_timeout_keeps_sdk_and_blocks_reuse(rig, monkeypatch):
    node, builder = rig
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    interfaces = node._interfaces
    entered, release = threading.Event(), threading.Event()
    activate = interfaces.activate
    interfaces._status_worker._callback = lambda: (
        entered.set(),
        release.wait(3.0),
    )

    def fail_activate(capabilities):
        activate(capabilities)
        assert entered.wait(1.0)
        raise RuntimeError("activation failed after starting workers")

    monkeypatch.setattr(interfaces, "activate", fail_activate)
    try:
        assert node.trigger_activate() == TransitionCallbackReturn.FAILURE
        assert builder.latest_runtime.close_count == 0
        assert node._interfaces is interfaces and node._cleanup_incomplete
        assert node.trigger_activate() == TransitionCallbackReturn.FAILURE
        assert not node.set_parameters_atomically(
            [Parameter("publish_rate_hz", value=50.0)]
        ).successful
        release.set()
        assert node.trigger_cleanup() == TransitionCallbackReturn.SUCCESS
        assert builder.latest_runtime.close_count == 1
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    finally:
        release.set()


def test_callback_gate_timeout_retains_sdk_until_callback_leaves(rig):
    node, builder = rig
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    interfaces = node._interfaces
    entered, release = threading.Event(), threading.Event()

    def callback():
        with interfaces._gate.admit() as admitted:
            assert admitted
            entered.set()
            assert release.wait(3.0)
            # The real node handle must remain usable throughout the callback.
            assert node.get_name() == "linkerbot_hand"

    thread = threading.Thread(target=callback)
    thread.start()
    try:
        assert entered.wait(1.0)
        with pytest.raises(RuntimeError, match="cleanup incomplete"):
            node.destroy_node()
        assert node._interfaces is interfaces
        assert builder.latest_runtime.close_count == 0
        release.set()
        thread.join(2.0)
        assert not thread.is_alive()
        node.destroy_node()
        assert builder.latest_runtime.close_count == 1
    finally:
        release.set()
        thread.join(2.0)
