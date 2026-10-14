"""Keep offline ROS tests separate from application discovery domains."""

import os
import time

import pytest


def pytest_configure(config):
    base_domain = os.environ.setdefault("ROS_DOMAIN_ID", "87")
    os.environ.setdefault("ROS_LOCALHOST_ONLY", "1")
    try:
        domain = int(base_domain)
        worker = getattr(config, "workerinput", {}).get("workerid")
        if worker is not None:
            domain += int(worker.removeprefix("gw"))
        if not 0 <= domain <= 232:
            raise ValueError
    except ValueError as error:
        raise pytest.UsageError(
            "ROS_DOMAIN_ID plus the pytest worker index must be between 0 and 232"
        ) from error
    os.environ["ROS_DOMAIN_ID"] = str(domain)


def pytest_report_header():
    return (
        f"ROS tests: ROS_DOMAIN_ID={os.environ['ROS_DOMAIN_ID']}, "
        f"ROS_LOCALHOST_ONLY={os.environ['ROS_LOCALHOST_ONLY']}"
    )


@pytest.fixture
def shutdown_ros_executor():
    """Drain a test's stopped multithreaded executor before destroying its guard."""

    def shutdown(executor):
        # Call only after the test has stopped spinning. These rigs have
        # synchronous callbacks, so joining the pool drains submitted work.
        for node in executor.get_nodes():
            executor.remove_node(node)
        assert executor.shutdown(timeout_sec=5.0), "ROS executor did not stop"

    return shutdown


@pytest.fixture(scope="session", autouse=True)
def check_ros_test_domain():
    """Refuse a domain already containing nodes from another test or application."""

    import rclpy
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node

    context = Context()
    rclpy.init(args=[], context=context)
    probe = None
    executor = SingleThreadedExecutor(context=context)
    try:
        probe = Node(
            f"linkerbot_test_probe_{os.getpid()}",
            context=context,
            use_global_arguments=False,
            enable_rosout=False,
            start_parameter_services=False,
        )
        executor.add_node(probe)
        own_name = (probe.get_name(), probe.get_namespace())
        # Discovery is asynchronous. Leave time for another announcement if
        # the probe missed an endpoint's initial announcement during startup.
        deadline = time.monotonic() + 5.0
        foreign = set()
        while time.monotonic() < deadline:
            # Gather the whole discovery window, including nodes announced
            # slightly later than an endpoint left by a preceding process.
            foreign.update(set(probe.get_node_names_and_namespaces()) - {own_name})
            executor.spin_once(timeout_sec=0.05)
        if foreign:
            pytest.fail(
                f"ROS test domain {os.environ['ROS_DOMAIN_ID']} is occupied: "
                f"{sorted(foreign)}. Select an unused ROS_DOMAIN_ID; "
                "offline tests must not share an application domain.",
                pytrace=False,
            )
    finally:
        executor.shutdown()
        if probe is not None:
            probe.destroy_node()
        context.try_shutdown()
