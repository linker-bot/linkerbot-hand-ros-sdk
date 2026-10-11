"""ROS discovery ownership through the real SDK, pool and MiniCANFD ABI shim."""

import ctypes
import json
import queue
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
import rclpy
from linkerbot_hand import HandSide, ValidationError
from linkerbot_hand.api import _device_core
from linkerbot_hand.discovery import (
    DiscoveryConfig,
    MiniCANFDDiscoveryConfig,
    MiniCANFDDiscoverySource,
    TransportSpec,
)
from linkerbot_hand.protocols import ProtocolTransaction, ResponseProgress
from linkerbot_hand.runtime._transport_arbiter import TRANSPORT_POOL
from linkerbot_hand_ros.discovery_config import discovery_settings
from linkerbot_hand_ros.multi_device import (
    HandLifecycleGroup,
    MultiDeviceLifecycleError,
    MultiHandContainerNode,
    destroy_hand_nodes,
    prepare_discovery_startup,
)
from linkerbot_hand_ros.node import LinkerbotHandNode
from linkerbot_transport import CANRouteKey
from linkerbot_transport.canfd import CANFDMessage, CANFDTransport
from linkerbot_transport.canfd import ctypes_backend as native
from rclpy.lifecycle import TransitionCallbackReturn
from rclpy.parameter import Parameter
from test_discovery_startup import _candidate
from test_raw_reads import RawReadPeer


class NativeFunction:
    def __init__(self, result=0, hook=None):
        self.result = result
        self.hook = hook
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.hook(*args) if self.hook is not None else self.result


class MemoryLibrary:
    """Echo the exact ABI frame bytes; no native library or hardware is loaded."""

    def __init__(self, path, windows):
        self._name = str(path)
        self.windows = windows
        self.frames = {}
        self.CAN_ScanDevice = NativeFunction(2)
        self.CAN_OpenDevice = NativeFunction()
        self.CAN_CloseDevice = NativeFunction()
        self.CAN_ReadDevInfo = NativeFunction()
        self.CANFD_Init = NativeFunction()
        self.CANFD_Transmit = NativeFunction(hook=self.transmit)
        self.CANFD_Receive = NativeFunction(hook=self.receive)
        if windows:
            self.CAN_GetDevType = NativeFunction(1)
        else:
            self.LibCANbus_Init = NativeFunction()
            self.LibCANbus_Exit = NativeFunction()
            self.CAN_GetCHType = NativeFunction(1)

    def transmit(self, *args):
        channel, buffer, count = tuple(args[:-3]), args[-3], args[-2]
        mailbox = self.frames.setdefault(channel, queue.Queue())
        frames = ctypes.cast(buffer, ctypes.POINTER(native.CanFDMsg))
        for index in range(count):
            frame = frames[index]
            mailbox.put(ctypes.string_at(ctypes.addressof(frame), ctypes.sizeof(frame)))
        return count

    def receive(self, *args):
        channel, buffer = tuple(args[:-3]), args[-3]
        mailbox = self.frames.setdefault(channel, queue.Queue())
        try:
            data = mailbox.get(timeout=0.005)
        except queue.Empty:
            return 0
        frame = ctypes.cast(buffer, ctypes.POINTER(native.CanFDMsg))[0]
        ctypes.memmove(ctypes.addressof(frame), data, len(data))
        return 1


class FDProtocolPeer(RawReadPeer):
    """Reuse baseline/identity payloads with real CAN FD transport messages."""

    route_keys = (CANRouteKey(0x123, True),)

    def __init__(self):
        super().__init__()
        self.sequence = 0

    def transaction(self, message, result, *, ack=False, publications=()):
        self.sequence += 1
        frame = CANFDMessage(0x123, self.sequence.to_bytes(8, "little"))

        def consume(received):
            matched = isinstance(received, CANFDMessage) and received.data == frame.data
            return ResponseProgress(
                matched=matched,
                complete=matched,
                result=result if matched else None,
                acknowledged=ack and matched,
            )

        return ProtocolTransaction(
            key=message[:2],
            correlation_key=message[:2],
            request_messages=(frame,),
            response_timeout_s=0.5,
            estimated_duration_s=0.001,
            response_consumer=consume,
            response_acknowledges_command=ack,
        )


@pytest.fixture(params=["Linux", "Windows"])
def rig(request, monkeypatch, tmp_path):
    windows = request.param == "Windows"
    lib = MemoryLibrary(
        tmp_path / ("HCanbus.dll" if windows else "libcanbus.so"), windows
    )
    monkeypatch.setattr(native.platform, "system", lambda: request.param)
    monkeypatch.setattr(native, "_load_library", lambda path: lib)
    original_factory = _device_core._default_runtime_factory

    def runtime_factory(**options):
        options["protocol_backend"] = FDProtocolPeer()
        return original_factory(**options)

    monkeypatch.setattr(_device_core, "_default_runtime_factory", runtime_factory)
    before_threads = set(threading.enumerate())
    rclpy.init()
    nodes = []
    descriptors = []

    def node(index=0, fingerprint="raw-read-test"):
        def factory():
            descriptor = CANFDTransport(device_index=index, library_path=lib._name)
            descriptors.append(descriptor)
            return descriptor

        descriptor = factory()
        candidate = _candidate(
            "L30", HandSide.LEFT, f"minicanfd:{index}:0", provider="minicanfd"
        )
        candidate = replace(
            candidate,
            identity=replace(candidate.identity, fingerprint=fingerprint),
            transport=TransportSpec(
                "minicanfd",
                candidate.channel.name,
                candidate.wire_protocol,
                1_000_000,
                5_000_000,
                factory,
                descriptor.pool_key,
            ),
        )
        result = LinkerbotHandNode(
            discovery_candidate=candidate,
            namespace=f"/i06/hand{index}",
            parameter_overrides=[Parameter("angles_hz", value=0.0)],
        )
        nodes.append(result)
        return result

    config = DiscoveryConfig(
        backends=("minicanfd",),
        channels=("minicanfd:0:0",),
        minicanfd=MiniCANFDDiscoveryConfig(
            library_path=lib._name,
            linux_channels=None if windows else {0: (0,), 1: (0,)},
        ),
    )
    try:
        yield SimpleNamespace(
            lib=lib, node=node, config=config, path=tmp_path, nodes=nodes
        )
    finally:
        lib.CAN_CloseDevice.result = 0
        for item in reversed(nodes):
            item.destroy_node()
        # Repair only this fixture's mock idle pool entries after a failed
        # assertion; do not turn the regression's close retry into a success.
        for descriptor in descriptors:
            key = (type(descriptor), descriptor.pool_key)
            if key in TRANSPORT_POOL.active_keys():
                assert TRANSPORT_POOL.lease_count(key) == 0
                TRANSPORT_POOL.acquire(
                    key, lambda descriptor=descriptor: descriptor
                ).close()
        rclpy.try_shutdown()
        assert not any(
            thread.is_alive() for thread in set(threading.enumerate()) - before_threads
        )
        assert native._open_channel_counts.get(native._library_key(lib), 0) == 0


def assert_busy(rig):
    scans = len(rig.lib.CAN_ScanDevice.calls)
    result = MiniCANFDDiscoverySource().enumerate_channels(rig.config)
    assert not result.channels
    assert any(failure.code == "busy" for failure in result.failures)
    assert len(rig.lib.CAN_ScanDevice.calls) == scans


def test_active_and_inactive_hand_block_discovery_until_cleanup(rig):
    node = rig.node()
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert not rig.lib.CAN_OpenDevice.calls
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    assert node._device.get_health().connected
    assert_busy(rig)

    assert node.trigger_deactivate() == TransitionCallbackReturn.SUCCESS
    assert not node._interfaces.commands._subscriptions
    assert not rig.lib.CAN_CloseDevice.calls
    assert node._device.get_health().connected
    assert_busy(rig)

    output = rig.path / "hands.yaml"
    container = MultiHandContainerNode(
        parameter_overrides=[
            Parameter("discovery_mode", value="multi"),
            Parameter(
                "discovery_config_json",
                value=json.dumps(discovery_settings(rig.config)),
            ),
            Parameter("discovery_output", value=str(output)),
        ]
    )
    try:
        with pytest.raises(ValidationError, match="no verified hands"):
            prepare_discovery_startup(container)
        assert not output.exists()
    finally:
        container.destroy_node()

    assert node.trigger_cleanup() == TransitionCallbackReturn.SUCCESS
    result = MiniCANFDDiscoverySource().enumerate_channels(rig.config)
    assert result.channels and not result.failures


def test_pending_close_remains_busy_and_destroy_retries_the_same_device(rig):
    node = rig.node()
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    device = node._device
    assert node.trigger_deactivate() == TransitionCallbackReturn.SUCCESS
    rig.lib.CAN_CloseDevice.result = 1
    assert node.trigger_cleanup() == TransitionCallbackReturn.ERROR
    assert node._device is device and not node._active
    assert_busy(rig)
    rig.lib.CAN_CloseDevice.result = 0
    node.destroy_node()
    assert native._open_channel_counts.get(native._library_key(rig.lib), 0) == 0
    assert MiniCANFDDiscoverySource().enumerate_channels(rig.config).channels


def test_destroy_failure_is_reported_and_retains_device_for_cleanup_retry(rig):
    node = rig.node()
    assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
    assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
    device = node._device
    rig.lib.CAN_CloseDevice.result = 1
    errors = destroy_hand_nodes((node,))
    assert errors and "/i06/hand0/linkerbot_hand" in errors[0]
    assert node._device is device and not node._driver_destroyed
    assert not node._active
    assert_busy(rig)
    rig.lib.CAN_CloseDevice.result = 0
    assert destroy_hand_nodes((node,)) == ()
    assert node._driver_destroyed and node._device is None
    assert native._open_channel_counts.get(native._library_key(rig.lib), 0) == 0


def test_second_hand_identity_failure_rolls_back_all_real_leases(rig):
    first = rig.node(0)
    second = rig.node(1, fingerprint="wrong")
    group = HandLifecycleGroup((first, second))
    with pytest.raises(MultiDeviceLifecycleError, match="/i06/hand1.*activate"):
        group.start()
    assert not first._active and not second._active
    assert first._device is None and second._device is None
    assert native._open_channel_counts.get(native._library_key(rig.lib), 0) == 0
    assert group.stop() == ()


def test_repeated_discovered_configure_activation_cleanup_releases_each_runtime(rig):
    node = rig.node()
    devices = []
    for _ in range(3):
        assert node.trigger_configure() == TransitionCallbackReturn.SUCCESS
        devices.append(node._device)
        assert node.trigger_activate() == TransitionCallbackReturn.SUCCESS
        assert_busy(rig)
        assert node.trigger_deactivate() == TransitionCallbackReturn.SUCCESS
        assert node.trigger_cleanup() == TransitionCallbackReturn.SUCCESS
        assert native._open_channel_counts.get(native._library_key(rig.lib), 0) == 0
    assert len({id(device) for device in devices}) == 3
