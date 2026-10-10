"""Discovery factories, persisted bindings and real ROS lifecycle integration."""

import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand import (
    DeviceInfo,
    HandSide,
    SampleMeta,
    TransportKind,
    ValidationError,
    get_declared_capabilities,
)
from linkerbot_hand.discovery import (
    AmbiguousHandError,
    DiscoveryAddress,
    DiscoveryCandidate,
    DiscoveryChannel,
    DiscoveryConfig,
    DiscoveryFailure,
    DiscoveryIdentity,
    DiscoveryProblem,
    DiscoveryReport,
    DiscoveryStatus,
    IncompleteIdentityError,
    NoHandFoundError,
    TransportSpec,
)
from linkerbot_hand_ros.discovery_deployment import (
    Deployment,
    deployment_from_selection,
    load_deployment,
    output_path,
    save_deployment,
    select_hands,
)
from linkerbot_hand_ros.multi_device import (
    HandLifecycleGroup,
    MultiDeviceConfiguration,
    MultiHandContainerNode,
    create_discovered_nodes,
    destroy_hand_nodes,
    prepare_discovery_startup,
)
from linkerbot_hand_ros.node import LinkerbotHandNode
from linkerbot_hand_ros.qos import COMMAND_QOS, STATE_QOS
from linkerbot_transport.testing import FakeTransport
from rclpy.executors import MultiThreadedExecutor
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.node import Node
from rclpy.parameter import Parameter

from linkerbot_hand_msgs.msg import HandJointCommand, HandJointState


def test_discovered_nodes_isolate_global_identity_rules_and_keep_ros_settings():
    selected = select_hands(
        DiscoveryConfig(),
        scan=lambda _: _report(_candidate(), _candidate("O6", HandSide.RIGHT, "can1")),
        emit=lambda _: None,
    )
    selected = tuple(
        replace(
            hand,
            binding=replace(
                hand.binding,
                parameters={
                    **hand.binding.parameters,
                    "command_rate_hz": 80.0 + i * 10,
                },
            ),
        )
        for i, hand in enumerate(selected)
    )
    rclpy.init(
        args=[
            "--ros-args",
            "-r",
            "__ns:=/robot",
            "-r",
            "__node:=outer_name",
            "-p",
            "use_sim_time:=true",
            "-r",
            "/l6l/linkerbot_hand/command/angles:=/left_command_override",
        ]
    )
    nodes = ()
    group = None
    observer = None
    executor = None
    try:
        nodes = create_discovered_nodes(
            MultiDeviceConfiguration(("/l6l", "/o6r"), False), selected
        )
        assert [node.get_fully_qualified_name() for node in nodes] == [
            "/l6l/linkerbot_hand",
            "/o6r/linkerbot_hand",
        ]
        assert all(node.get_parameter("use_sim_time").value for node in nodes)
        builders = [DeviceBuilder(), DeviceBuilder()]
        for node, builder in zip(nodes, builders):
            node._device_factory = builder
        group = HandLifecycleGroup(nodes)
        group.start()
        assert [
            builder.calls[0].device_config.command_rate_hz for builder in builders
        ] == [80.0, 90.0]
        observer = Node("identity_remap_probe", use_global_arguments=False)
        executor = MultiThreadedExecutor(num_threads=9)
        for node in (*nodes, observer):
            executor.add_node(node)
        publisher = observer.create_publisher(
            HandJointCommand, "/left_command_override", COMMAND_QOS
        )
        deadline = time.monotonic() + 5
        while publisher.get_subscription_count() != 1 and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.01)
        assert publisher.get_subscription_count() == 1
        assert observer.count_subscribers("/o6r/linkerbot_hand/command/angles") == 1
        assert (
            len(observer.get_service_names_and_types_by_node("linkerbot_hand", "/l6l"))
            > 0
        )
        assert (
            len(observer.get_service_names_and_types_by_node("linkerbot_hand", "/o6r"))
            > 0
        )
        publisher.publish(
            HandJointCommand(
                client_id=1,
                user_sequence=1,
                representation=HandJointCommand.REPRESENTATION_RAW,
                values=[10.0] * 6,
            )
        )
        deadline = time.monotonic() + 5
        while (
            not builders[0].latest_runtime.submissions and time.monotonic() < deadline
        ):
            executor.spin_once(timeout_sec=0.01)
        assert builders[0].latest_runtime.submissions
        assert not builders[1].latest_runtime.submissions
    finally:
        if group is not None:
            group.stop()
        if executor is not None:
            for node in (*nodes, observer):
                executor.remove_node(node)
            executor.shutdown(timeout_sec=5)
        destroy_hand_nodes(nodes)
        if observer is not None:
            observer.destroy_node()
        rclpy.try_shutdown()


def test_parent_namespace_is_saved_once_and_not_reapplied_on_file_load(
    tmp_path, monkeypatch
):
    import linkerbot_hand_ros.discovery_deployment as discovery

    monkeypatch.setattr(
        discovery,
        "discover_hands",
        lambda _: _report(_candidate(), _candidate("O6", HandSide.RIGHT, "can1")),
    )
    path = tmp_path / "scoped.yaml"
    for mode, prefix in (("multi", "/robot"), ("file", "/other")):
        rclpy.init(
            args=["--ros-args", "-r", f"__ns:={prefix}", "-r", "__node:=outer_name"]
        )
        container = MultiHandContainerNode(
            parameter_overrides=[
                Parameter("discovery_mode", value=mode),
                Parameter(
                    "discovery_output" if mode == "multi" else "deployment_config",
                    value=str(path),
                ),
                Parameter("autostart_override", value="false"),
            ]
        )
        nodes = ()
        try:
            configuration, selected = prepare_discovery_startup(container)
            assert configuration.device_namespaces == ("/robot/l6l", "/robot/o6r")
            assert (
                tuple(hand.namespace for hand in load_deployment(path).hands)
                == configuration.device_namespaces
            )
            nodes = create_discovered_nodes(configuration, selected)
            assert [node.get_fully_qualified_name() for node in nodes] == [
                "/robot/l6l/linkerbot_hand",
                "/robot/o6r/linkerbot_hand",
            ]
        finally:
            destroy_hand_nodes(nodes)
            container.destroy_node()
            rclpy.try_shutdown()


@pytest.mark.parametrize("namespace", ["/robot", "/robot/hand", "/absolute"])
def test_single_discovery_local_namespace_wins_over_parent_process_remap(namespace):
    selected = select_hands(
        DiscoveryConfig(),
        single_namespace=namespace,
        scan=lambda _: _report(_candidate()),
        emit=lambda _: None,
    )
    rclpy.init(args=["--ros-args", "-r", "__ns:=/robot", "-r", "__node:=outer_name"])
    nodes = ()
    try:
        nodes = create_discovered_nodes(
            MultiDeviceConfiguration((namespace,), False), selected
        )
        assert nodes[0].get_fully_qualified_name() == namespace + "/linkerbot_hand"
    finally:
        destroy_hand_nodes(nodes)
        rclpy.try_shutdown()


def _candidate(
    model="L6",
    side=HandSide.LEFT,
    channel="can0",
    *,
    provider="socketcan",
    factory=None,
):
    declared = get_declared_capabilities(model, side=None if model == "L30" else side)
    caps = replace(declared, identity=replace(declared.identity, verified=True))
    wire = caps.transport.kind
    info = DeviceInfo(
        model=model,
        serial_number=f"serial-{channel}",
        pcb_version=None,
        firmware_version=None,
        mechanical_version=None,
        product_code=None,
        sensor_variant=None,
        side=caps.side,
        raw_identity=None,
        meta=SampleMeta.unavailable(),
        reported_side=side,
    )
    discovered = DiscoveryChannel(
        provider,
        channel,
        wire,
        1_000_000,
        5_000_000 if wire is TransportKind.CAN_FD else None,
    )
    return DiscoveryCandidate(
        channel=discovered,
        wire_protocol=wire,
        address=DiscoveryAddress(
            "o30_hop_endpoint" if model == "O30" else "test_endpoint",
            0x17,
            0x417 if model == "O30" else 0x18,
            model in {"L30", "O20"},
            node_id=13 if model == "L30" else None,
        ),
        status=DiscoveryStatus.VERIFIED,
        identity=DiscoveryIdentity(
            model,
            caps.side,
            serial_number=info.serial_number,
            fingerprint=f"fingerprint-{channel}",
        ),
        transport=TransportSpec(
            provider,
            channel,
            wire,
            1_000_000,
            discovered.data_bitrate,
            factory or FakeTransport,
            (provider, channel),
        ),
        reported_side=side,
        capabilities=caps,
        device_info=info,
    )


def _report(*candidates, failures=()):
    return DiscoveryReport(
        tuple(c.channel for c in candidates), candidates, failures, 0.01
    )


def _partial(candidate):
    return replace(
        candidate,
        status=DiscoveryStatus.PARTIAL,
        identity=replace(candidate.identity, side=None),
        capabilities=None,
        device_info=None,
        problems=(DiscoveryProblem("missing_side", "side unavailable"),),
    )


@pytest.mark.parametrize("model", ["L6", "O6", "L20Lite", "L20", "O20", "L30", "O30"])
def test_verified_candidate_is_configured_via_real_sdk_factory_without_runtime_io(
    model,
):
    factory = Mock(side_effect=FakeTransport)
    candidate = _candidate(model, factory=factory)
    selected = select_hands(
        DiscoveryConfig(),
        single_namespace="",
        parameters={"command_rate_hz": 80, "angles_hz": 0},
        scan=lambda _: _report(candidate),
        emit=lambda _: None,
    )
    rclpy.init()
    nodes = create_discovered_nodes(MultiDeviceConfiguration(("/",), False), selected)
    try:
        node = nodes[0]
        assert node.get_fully_qualified_name() == "/linkerbot_hand"
        assert factory.call_count == 0
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        assert factory.call_count == 1
        assert node._configuration.transport is None
        assert node._configuration.device_config.command_rate_hz == 80.0
        assert node._device._runtime is None
        assert node._device._transport.sent == ()
        assert (
            node._device._runtime_factory.keywords["expected_fingerprint"]
            == candidate.identity.fingerprint
        )
        if model == "O30":
            assert node._device._config.o30_request_id == 0x17
        if model == "L30":
            assert node.get_parameter("side").value == ""
            assert node._device._protocol_backend._node_id == 13
        assert not node.set_parameters_atomically(
            [Parameter("model", value="O6" if model != "O6" else "L6")]
        ).successful
        assert node.trigger_cleanup() == TransitionCallbackReturn.SUCCESS
        assert not node.set_parameters_atomically(
            [
                Parameter(
                    "transport_json", value='{"backend":"socketcan","channel":"can9"}'
                )
            ]
        ).successful
        assert node.set_parameters_atomically(
            [Parameter("angles_hz", value=10.0)]
        ).successful
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        assert factory.call_count == 2
    finally:
        destroy_hand_nodes(nodes)
        rclpy.try_shutdown()


def test_single_ambiguity_prints_candidates_and_copyable_scope_commands():
    messages = []
    factory = Mock(side_effect=FakeTransport)
    with pytest.raises(AmbiguousHandError):
        select_hands(
            DiscoveryConfig(),
            single_namespace="",
            scan=lambda _: _report(
                _candidate(factory=factory),
                _candidate("O6", HandSide.RIGHT, "can1", factory=factory),
            ),
            emit=messages.append,
        )
    assert any("can0: L6, left, socketcan" in m for m in messages)
    assert any("discover:=true channels:=can0" in m for m in messages)
    assert any("multi_hand.launch.py discover:=true" in m for m in messages)
    factory.assert_not_called()


@pytest.mark.parametrize(
    "candidates,error",
    [((), NoHandFoundError), ((_partial(_candidate()),), IncompleteIdentityError)],
)
def test_single_missing_or_partial_target_never_becomes_a_driver(candidates, error):
    with pytest.raises(error):
        select_hands(
            DiscoveryConfig(),
            single_namespace="",
            scan=lambda _: _report(*candidates),
            emit=lambda _: None,
        )


def test_multi_skips_partial_but_reports_it_and_rejects_channel_conflicts():
    messages = []
    candidate = _candidate()
    selected = select_hands(
        DiscoveryConfig(),
        scan=lambda _: _report(candidate, _partial(_candidate(channel="can1"))),
        emit=messages.append,
    )
    assert len(selected) == 1
    assert any("partial" in m and "missing_side" in m for m in messages)
    other = replace(candidate, address=replace(candidate.address, request_id=0x19))
    with pytest.raises(ValidationError, match="physical channel"):
        select_hands(
            DiscoveryConfig(),
            scan=lambda _: _report(candidate, other),
            emit=lambda _: None,
        )


@pytest.mark.parametrize("fails", [1, 2])
def test_probe_cleanup_precedes_selection_and_unreleased_resources_block_startup(fails):
    cleanup = Mock(side_effect=[RuntimeError("busy")] * fails + [None])
    report = _report(
        _candidate(),
        failures=(
            DiscoveryFailure(
                "close",
                "transport_error",
                "probe close failed",
                "RuntimeError",
                cleanup=cleanup,
            ),
        ),
    )
    if fails == 2:
        with pytest.raises(ValidationError, match="cleanup incomplete"):
            select_hands(DiscoveryConfig(), scan=lambda _: report, emit=lambda _: None)
    else:
        assert (
            len(
                select_hands(
                    DiscoveryConfig(), scan=lambda _: report, emit=lambda _: None
                )
            )
            == 1
        )
    assert cleanup.call_count == 2


def _save_one(tmp_path, candidate=None, *, autostart=False):
    candidate = candidate or _candidate()
    config = DiscoveryConfig()
    selected = select_hands(
        config, scan=lambda _: _report(candidate), emit=lambda _: None
    )
    path = output_path(str(tmp_path / "hands.yaml"))
    save_deployment(path, deployment_from_selection(config, selected, autostart))
    return path


def test_saved_roles_survive_alias_numbering_and_ignore_new_devices(tmp_path):
    original = _candidate()
    path = _save_one(tmp_path, original)
    deployment = load_deployment(path)
    assert deployment.discovery.channels == ("can0",)
    assert deployment.discovery.backends == ("socketcan",)
    assert not deployment.autostart
    new = _candidate(channel="can1")
    selected = select_hands(
        deployment.discovery,
        deployment=deployment,
        scan=lambda _: _report(new, original),
        emit=lambda _: None,
    )
    assert [s.binding.namespace for s in selected] == ["/l6l"]
    assert selected[0].candidate is original
    replaced = replace(
        original, identity=replace(original.identity, serial_number="other")
    )
    with pytest.raises(ValidationError, match="matched 0"):
        select_hands(
            deployment.discovery,
            deployment=deployment,
            scan=lambda _: _report(replaced),
            emit=lambda _: None,
        )


def test_output_race_does_not_overwrite_file_or_leave_temporaries(tmp_path):
    path = output_path(str(tmp_path / "hands.yaml"))
    path.write_text("user data")
    with pytest.raises(FileExistsError):
        save_deployment(path, Deployment(DiscoveryConfig(), (), True))
    assert path.read_text() == "user data"
    assert list(tmp_path.iterdir()) == [path]
    with pytest.raises(ValidationError, match="already exists"):
        output_path(str(path))


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", "other"),
        ("version", True),
        ("version", 2),
        ("autostart", "false"),
        ("hands", []),
        ("unknown", 1),
    ],
)
def test_deployment_schema_validation(tmp_path, field, value):
    import yaml

    path = _save_one(tmp_path)
    document = yaml.safe_load(path.read_text())
    document[field] = value
    path.write_text(yaml.safe_dump(document))
    with pytest.raises((ValidationError, ValueError)):
        load_deployment(path)


def test_existing_output_is_rejected_before_any_scan(tmp_path, monkeypatch):
    import linkerbot_hand_ros.discovery_deployment as module

    scan = Mock(side_effect=AssertionError("scan must not run"))
    monkeypatch.setattr(module, "discover_hands", scan)
    path = tmp_path / "hands.yaml"
    path.write_text("user data")
    rclpy.init()
    container = MultiHandContainerNode(
        parameter_overrides=[
            Parameter("discovery_mode", value="multi"),
            Parameter("discovery_output", value=str(path)),
        ]
    )
    try:
        with pytest.raises(ValidationError, match="already exists"):
            prepare_discovery_startup(container)
    finally:
        container.destroy_node()
        rclpy.try_shutdown()
    scan.assert_not_called()


def test_required_write_failure_never_constructs_a_device(tmp_path, monkeypatch):
    import linkerbot_hand_ros.discovery_deployment as discovery
    import linkerbot_hand_ros.multi_device as multi

    factory = Mock(side_effect=FakeTransport)
    monkeypatch.setattr(
        discovery, "discover_hands", lambda _: _report(_candidate(factory=factory))
    )
    monkeypatch.setattr(
        multi, "save_deployment", Mock(side_effect=OSError("disk full"))
    )
    rclpy.init()
    container = MultiHandContainerNode(
        parameter_overrides=[
            Parameter("discovery_mode", value="multi"),
            Parameter("discovery_output", value=str(tmp_path / "hands.yaml")),
        ]
    )
    try:
        with pytest.raises(OSError, match="disk full"):
            prepare_discovery_startup(container)
        factory.assert_not_called()
        assert not list(tmp_path.iterdir())
        assert not container.set_parameters_atomically(
            [Parameter("discovery_mode", value="single")]
        ).successful
    finally:
        container.destroy_node()
        rclpy.try_shutdown()


def test_partial_endpoint_on_selected_channel_blocks_multi_startup():
    candidate = _candidate()
    partial = _partial(
        replace(candidate, address=replace(candidate.address, request_id=0x19))
    )
    with pytest.raises(ValidationError, match="physical channel"):
        select_hands(
            DiscoveryConfig(),
            scan=lambda _: _report(candidate, partial),
            emit=lambda _: None,
        )


def test_discovery_identity_override_is_rejected_before_factory_io():
    factory = Mock(side_effect=FakeTransport)
    rclpy.init()
    node = LinkerbotHandNode(
        discovery_candidate=_candidate("O6", factory=factory),
        parameter_overrides=[Parameter("model", value="L6")],
    )
    try:
        assert node.trigger_configure() == TransitionCallbackReturn.FAILURE
        factory.assert_not_called()
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


@pytest.mark.parametrize("mutation", ["namespace", "channel", "parameters", "match"])
def test_invalid_bindings_are_rejected_without_scanning(tmp_path, mutation):
    import yaml

    path = _save_one(tmp_path)
    document = yaml.safe_load(path.read_text())
    if mutation == "namespace":
        second = dict(document["hands"][0])
        second["match"] = {**second["match"], "channel": "can1"}
        document["hands"].append(second)
    elif mutation == "channel":
        second = {**document["hands"][0], "namespace": "/other"}
        document["hands"].append(second)
    elif mutation == "parameters":
        document["hands"][0]["parameters"]["model"] = "O6"
    else:
        document["hands"][0]["match"]["address"]["request_id"] = -1
    path.write_text(yaml.safe_dump(document))
    with pytest.raises((ValidationError, ValueError)):
        load_deployment(path)


def test_multi_saves_before_node_construction_and_file_mode_preserves_autostart(
    tmp_path, monkeypatch
):
    import linkerbot_hand_ros.discovery_deployment as module

    factory = Mock(side_effect=FakeTransport)
    candidates = (
        _candidate(factory=factory),
        _candidate("O6", HandSide.RIGHT, "can1", factory=factory),
    )
    monkeypatch.setattr(
        module, "discover_hands", lambda _: _report(*reversed(candidates))
    )
    path = tmp_path / "hands.yaml"
    rclpy.init()
    container = MultiHandContainerNode(
        parameter_overrides=[
            Parameter("discovery_mode", value="multi"),
            Parameter("discovery_output", value=str(path)),
            Parameter("autostart_override", value="false"),
        ]
    )
    nodes = ()
    try:
        config, selected = prepare_discovery_startup(container)
        assert path.exists()
        assert config.device_namespaces == ("/l6l", "/o6r")
        assert not config.autostart
        factory.assert_not_called()
        nodes = create_discovered_nodes(config, selected)
        factory.assert_not_called()
    finally:
        destroy_hand_nodes(nodes)
        container.destroy_node()
        rclpy.try_shutdown()
    rclpy.init()
    container = MultiHandContainerNode(
        parameter_overrides=[
            Parameter("discovery_mode", value="file"),
            Parameter("deployment_config", value=str(path)),
        ]
    )
    try:
        loaded_config, loaded_selected = prepare_discovery_startup(container)
        assert loaded_config == config
        assert [s.binding.match for s in loaded_selected] == [
            s.binding.match for s in selected
        ]
    finally:
        container.destroy_node()
        rclpy.try_shutdown()


def test_new_process_can_load_generated_yaml_and_configure_selected_sdk_device(
    tmp_path,
):
    path = _save_one(tmp_path)
    script = """
import rclpy, sys
from test_discovery_startup import _candidate, _report
from linkerbot_hand_ros.discovery_deployment import load_deployment, select_hands
from linkerbot_hand_ros.multi_device import MultiDeviceConfiguration, create_discovered_nodes, destroy_hand_nodes
from rclpy.lifecycle import TransitionCallbackReturn
deployment = load_deployment(sys.argv[1])
selected = select_hands(deployment.discovery, deployment=deployment, scan=lambda _: _report(_candidate(channel="can1"), _candidate()), emit=lambda _: None)
rclpy.init()
nodes = create_discovered_nodes(MultiDeviceConfiguration(tuple(s.binding.namespace for s in selected), False), selected)
try:
    assert len(nodes) == 1
    assert nodes[0].get_fully_qualified_name() == "/l6l/linkerbot_hand"
    assert nodes[0].trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert nodes[0]._device._runtime is None
finally:
    destroy_hand_nodes(nodes)
    rclpy.try_shutdown()
"""
    env = dict(
        os.environ,
        PYTHONPATH=str(Path(__file__).parent)
        + os.pathsep
        + os.environ.get("PYTHONPATH", ""),
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mismatch", [False, True])
def test_candidate_factory_real_sdk_runtime_identity_and_dds_state(
    monkeypatch, mismatch
):
    from linkerbot_hand.api import _device_core
    from test_raw_reads import RawReadPeer

    peer = RawReadPeer()
    candidate = _candidate("O6", factory=lambda: peer)
    candidate = replace(
        candidate,
        identity=replace(
            candidate.identity, fingerprint="wrong" if mismatch else "raw-read-test"
        ),
    )
    actual_factory = _device_core._default_runtime_factory

    def protocol_peer_factory(**options):
        options["protocol_backend"] = peer
        return actual_factory(**options)

    monkeypatch.setattr(_device_core, "_default_runtime_factory", protocol_peer_factory)
    rclpy.init()
    driver = LinkerbotHandNode(
        discovery_candidate=candidate,
        parameter_overrides=[Parameter("angles_hz", value=0.0)],
    )
    consumer = Node("discovery_state_consumer")
    executor = MultiThreadedExecutor(num_threads=5)
    executor.add_node(driver)
    executor.add_node(consumer)
    received = []
    consumer.create_subscription(
        HandJointState, "/linkerbot_hand/state/angles", received.append, STATE_QOS
    )
    configured = False
    try:
        configured = driver.trigger_configure() == TransitionCallbackReturn.SUCCESS
        assert configured
        assert peer.sent == ()
        result = driver.trigger_activate()
        if mismatch:
            assert result == TransitionCallbackReturn.FAILURE
            assert not driver._active
            assert not driver._device.get_health().connected
            assert not driver._device.get_snapshot().angles.meta.valid
            assert all(message[0] == "identity" for message in peer.sent)
            assert driver.trigger_activate() == TransitionCallbackReturn.FAILURE
        else:
            assert result == TransitionCallbackReturn.SUCCESS
            deadline = time.monotonic() + 5
            while not received and time.monotonic() < deadline:
                executor.spin_once(timeout_sec=0.01)
            assert received
            assert list(received[-1].raw) == [11] * 6
            assert driver._device.get_capabilities().identity.verified
    finally:
        if driver._active:
            driver.trigger_deactivate()
        if configured:
            driver.trigger_cleanup()
        executor.remove_node(driver)
        executor.remove_node(consumer)
        executor.shutdown(timeout_sec=5)
        driver.destroy_node()
        consumer.destroy_node()
        rclpy.try_shutdown()
