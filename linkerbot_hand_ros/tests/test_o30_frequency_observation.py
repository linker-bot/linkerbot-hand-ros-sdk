"""Descriptor tactile frequency counts full messages, separately from FnS."""

import time
from copy import deepcopy
from dataclasses import replace

import pytest
import rclpy
from linkerbot_hand import SUPPORTED_MODELS, TelemetrySemantic
from linkerbot_hand_ros.benchmark import evaluate_measurements
from linkerbot_hand_ros.conversion import (
    capabilities_to_message,
    force_sample_to_messages,
)
from linkerbot_hand_ros.examples.frequency_benchmark import FrequencyBenchmarkNode
from linkerbot_hand_ros.qos import STATE_QOS
from rclpy.node import Node
from test_frequency_benchmark import _measurements, _state_events
from test_message_conversion import ROS_NOW_NS, _capabilities, _o30_force_sample

from linkerbot_hand_msgs.msg import HandNormalForceResultant, HandTactileSensorState


@pytest.mark.parametrize("model", SUPPORTED_MODELS)
def test_each_model_observes_its_declared_projection(model):
    rclpy.init()
    node = FrequencyBenchmarkNode("/driver")
    try:
        caps = capabilities_to_message(_capabilities(model))
        node.command_client._update_capabilities(caps)
        # A caller must not be able to mutate the client's capability cache.
        copied = node.command_client.telemetry_capability("force")
        copied.payload_projection = "damaged"
        assert (
            node.command_client.telemetry_capability("force").payload_projection
            != "damaged"
        )
        node.start_observing()
        topics = {
            subscription.topic_name for subscription in node._observation_subscriptions
        }
        if model == "O30":
            assert "/driver/state/tactile_sensors" in topics
            assert "/driver/state/normal_force_resultant" in topics
            assert "/driver/state/tactile" not in topics
        else:
            assert "/driver/state/tactile" in topics
            assert "/driver/state/tactile_sensors" not in topics
    finally:
        node.destroy_benchmark()
        node.destroy_node()
        rclpy.try_shutdown()


def test_descriptor_and_resultant_arrive_over_dds_as_separate_complete_events():
    rclpy.init()
    node = FrequencyBenchmarkNode("/driver")
    source = Node("force_source")
    try:
        caps = _capabilities("O30")
        node.command_client._update_capabilities(capabilities_to_message(caps))
        node.start_observing()
        messages = force_sample_to_messages(
            _o30_force_sample(),
            caps.telemetry_channel(TelemetrySemantic.FORCE),
            ros_now_ns=ROS_NOW_NS,
        )
        descriptor_pub = source.create_publisher(
            HandTactileSensorState, "/driver/state/tactile_sensors", STATE_QOS
        )
        resultant_pub = source.create_publisher(
            HandNormalForceResultant, "/driver/state/normal_force_resultant", STATE_QOS
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            descriptor_pub.publish(messages.tactile_sensors)
            resultant_pub.publish(messages.force_resultant)
            rclpy.spin_once(node, timeout_sec=0.01)
            channels = {event.channel for event in node.state_events}
            if {"tactile", "normal_force_resultant"} <= channels:
                break
        assert {event.channel for event in node.state_events} == {
            "tactile",
            "normal_force_resultant",
        }
        assert all(event.valid and not event.stale for event in node.state_events)
        damaged = deepcopy(messages.tactile_sensors)
        damaged.sensors[0].raw_bytes = [0]
        node._on_tactile_sensors(damaged)
        assert not node.state_events[-1].valid
        partial = deepcopy(messages.tactile_sensors)
        partial.sensors.pop()
        node._on_tactile_sensors(partial)
        assert not node.state_events[-1].valid
    finally:
        source.destroy_node()
        node.destroy_benchmark()
        node.destroy_node()
        rclpy.try_shutdown()


def test_resultant_publications_do_not_double_tactile_frequency():
    measurements = _measurements(tactile=True)
    extra = _state_events("normal_force_resultant", cache_updates=100, publications=200)
    result = evaluate_measurements(
        replace(measurements, state_events=(*measurements.state_events, *extra))
    )
    assert result.passed
    assert result.tactile_cache_update_hz == 30
    assert result.tactile_ros_publish_hz == 30
    assert result.normal_force_resultant_cache_update_hz == 10
    assert result.normal_force_resultant_ros_publish_hz == 20
