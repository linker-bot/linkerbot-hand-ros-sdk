"""Installed YAML examples parse and their deployments load in new processes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from linkerbot_hand.discovery import (
    DiscoveryConfig,
    DiscoveryEnumeration,
    discover_hands,
)
from linkerbot_hand.discovery import sources as sdk_sources
from linkerbot_hand_ros.discovery_config import (
    discovery_settings,
    load_yaml,
    parse_discovery_config,
)
from linkerbot_hand_ros.discovery_deployment import (
    deployment_from_selection,
    load_deployment,
    save_deployment,
    select_hands,
)
from test_discovery_startup import _candidate, _report

CONFIG_ROOT = Path(__file__).parents[1] / "config"
EXAMPLES = sorted(CONFIG_ROOT.glob("discovery-*.yaml")) + sorted(
    CONFIG_ROOT.glob("deployment-*.yaml")
)


@pytest.fixture
def sdk_enumeration_without_hardware(monkeypatch):
    calls = []

    def enumerator(backend):
        def enumerate_channels(self, config):
            calls.append(backend)
            return DiscoveryEnumeration()

        return enumerate_channels

    for backend, source in (
        ("socketcan", sdk_sources.SocketCANDiscoverySource),
        ("pcan", sdk_sources.PCANDiscoverySource),
        ("slcan", sdk_sources.SLCANDiscoverySource),
        ("minicanfd", sdk_sources.MiniCANFDDiscoverySource),
    ):
        # Keep the SDK's real platform selection and engine; stub only device I/O.
        monkeypatch.setattr(
            source, "enumerate_channels", enumerator(backend), raising=False
        )
    return calls


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.name)
def test_each_example_reaches_its_supported_sdk_platform_source(
    path, monkeypatch, sdk_enumeration_without_hardware
):
    system = "Windows" if "windows" in path.stem or "pcan" in path.stem else "Linux"
    config = (
        load_deployment(path).discovery
        if path.name.startswith("deployment-")
        else parse_discovery_config(load_yaml(path), base_dir=path.parent)
    )
    monkeypatch.setattr(sdk_sources.platform, "system", lambda: system)
    report = discover_hands(config)
    assert sdk_enumeration_without_hardware == list(config.backends)
    assert not any(failure.code == "source" for failure in report.failures)
    assert not report.channels and not report.candidates


@pytest.mark.parametrize(
    "system,expected",
    [
        ("Linux", {"socketcan", "minicanfd"}),
        ("Windows", {"pcan", "minicanfd", "slcan"}),
    ],
)
def test_sdk_default_platform_sources_match_supported_scope(
    system, expected, monkeypatch, sdk_enumeration_without_hardware
):
    monkeypatch.setattr(sdk_sources.platform, "system", lambda: system)
    report = discover_hands(DiscoveryConfig())
    assert set(sdk_enumeration_without_hardware) == expected
    assert not report.failures


@pytest.mark.parametrize(
    "system,backend",
    [("Linux", "slcan"), ("Linux", "pcan"), ("Windows", "socketcan")],
)
def test_cross_platform_backend_does_not_enable_an_unsupported_sdk_source(
    system, backend, monkeypatch, sdk_enumeration_without_hardware
):
    monkeypatch.setattr(sdk_sources.platform, "system", lambda: system)
    report = discover_hands(DiscoveryConfig(backends=(backend,)))
    assert not sdk_enumeration_without_hardware
    assert any(
        failure.backend == backend and "unavailable on this platform" in failure.message
        for failure in report.failures
    )


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.name)
def test_example_settings_or_deployment_are_reusable_in_a_new_process(path, tmp_path):
    if path.name.startswith("deployment-"):
        deployment = load_deployment(path)
        generated = tmp_path / path.name
        save_deployment(generated, deployment)
    else:
        config = parse_discovery_config(load_yaml(path), base_dir=path.parent)
        backend = config.backends[0]
        model = "L6" if backend == "socketcan" or "classic" in path.name else "L30"
        candidate = _candidate(model, channel=config.channels[0], provider=backend)
        selected = select_hands(
            config, scan=lambda _: _report(candidate), emit=lambda _: None
        )
        deployment = deployment_from_selection(config, selected, False)
        generated = tmp_path / "hands.yaml"
        save_deployment(generated, deployment)
    script = """
import json, sys
from dataclasses import replace
import rclpy
from linkerbot_hand import HandSide
from linkerbot_hand.discovery import DiscoveryAddress
from linkerbot_hand_ros.discovery_config import discovery_settings
from linkerbot_hand_ros.discovery_deployment import load_deployment, select_hands
from linkerbot_hand_ros.multi_device import MultiDeviceConfiguration, create_discovered_nodes, destroy_hand_nodes
from rclpy.lifecycle import TransitionCallbackReturn
from test_discovery_startup import _candidate, _report
deployment = load_deployment(sys.argv[1])
candidates = []
for binding in deployment.hands:
    match = binding.match
    side = HandSide(match.get("reported_side", "left") if match["side"] == "not_applicable" else match["side"])
    candidate = _candidate(match["model"], side, match["channel"], provider=match["backend"])
    candidates.append(replace(candidate, address=DiscoveryAddress(**match["address"])))
selected = select_hands(deployment.discovery, deployment=deployment, scan=lambda _: _report(*candidates), emit=lambda _: None)
rclpy.init()
nodes = ()
try:
    nodes = create_discovered_nodes(MultiDeviceConfiguration(tuple(h.binding.namespace for h in selected), False), selected)
    assert all(node.trigger_configure() == TransitionCallbackReturn.SUCCESS for node in nodes)
    assert all(not node._active for node in nodes)
    print(json.dumps({"settings": discovery_settings(deployment.discovery), "roles": [h.binding.namespace for h in selected]}))
finally:
    destroy_hand_nodes(nodes)
    rclpy.try_shutdown()
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = (
        str(Path(__file__).parent) + os.pathsep + environment.get("PYTHONPATH", "")
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(generated)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output["settings"] == discovery_settings(deployment.discovery)
    assert output["roles"] == [hand.namespace for hand in deployment.hands]


def test_platform_examples_preserve_native_ports_timing_layout_and_termination():
    def config(name):
        return parse_discovery_config(
            load_yaml(CONFIG_ROOT / name), base_dir=CONFIG_ROOT
        )

    pcan = config("discovery-pcan-fd.yaml")
    assert pcan.pcan.fd_timing.nom_bitrate == pcan.pcan.bitrate == 1_000_000
    assert pcan.pcan.fd_timing.data_bitrate == pcan.pcan.data_bitrate == 5_000_000
    assert pcan.pcan.channels == ("PCAN_USBBUS1",)
    assert config("discovery-slcan-windows.yaml").slcan.channels == ("COM5",)
    linux = config("discovery-minicanfd-linux.yaml")
    windows = config("discovery-minicanfd-windows.yaml")
    assert dict(linux.minicanfd.linux_channels) == {0: (0,)}
    assert windows.minicanfd.linux_channels is None
    assert linux.minicanfd.config.config == windows.minicanfd.config.config == 0x06
    assert Path(linux.minicanfd.library_path) == CONFIG_ROOT / "vendor/libcanbus.so"
