"""Container failures and cancellation close only their owned fake devices."""

import threading

import pytest
import rclpy
from fakes_v1 import DeviceBuilder
from linkerbot_hand_ros.node import LinkerbotHandNode
from rclpy.parameter import Parameter

from linkerbot_hand_ros import multi_device


@pytest.mark.parametrize("failure", ["executor-constructor", "executor-spin", "cancel"])
def test_container_failure_and_cancel_destroy_all_owned_nodes(monkeypatch, failure):
    before = set(threading.enumerate())
    builders = {"/i06/left": DeviceBuilder(), "/i06/right": DeviceBuilder()}
    nodes = []
    original_container = multi_device.MultiHandContainerNode
    original_create = multi_device.create_hand_nodes

    def container():
        return original_container(
            parameter_overrides=[
                Parameter("device_namespaces", value=list(builders)),
                Parameter("autostart", value=True),
            ]
        )

    def create(config):
        result = original_create(
            config,
            node_factory=lambda namespace: LinkerbotHandNode(
                device_factory=builders[namespace], namespace=namespace
            ),
        )
        nodes.extend(result)
        return result

    monkeypatch.setattr(multi_device, "MultiHandContainerNode", container)
    monkeypatch.setattr(multi_device, "create_hand_nodes", create)

    if failure == "executor-constructor":

        def executor(**options):
            raise RuntimeError("executor constructor failed")

        monkeypatch.setattr(multi_device, "MultiThreadedExecutor", executor)
    else:

        def spin(executor, logger):
            assert all(node._active for node in nodes)
            if failure == "cancel":
                raise KeyboardInterrupt
            raise RuntimeError("executor spin failed")

        monkeypatch.setattr(multi_device, "spin_until_shutdown", spin)

    if failure == "cancel":
        multi_device.main(args=[])
    else:
        with pytest.raises(SystemExit) as caught:
            multi_device.main(args=[])
        assert caught.value.code == 1
    assert len(nodes) == 2
    assert all(node._driver_destroyed and node._device is None for node in nodes)
    assert not rclpy.ok()
    for builder in builders.values():
        if failure == "executor-constructor":
            assert not builder.calls
        else:
            assert (
                builder.latest_runtime.open_count
                == builder.latest_runtime.close_count
                == 1
            )
    assert not any(thread.is_alive() for thread in set(threading.enumerate()) - before)
