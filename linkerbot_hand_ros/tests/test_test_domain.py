"""Verify that an occupied test domain is rejected before driver tests run."""

import os
import subprocess
import sys
from pathlib import Path

import rclpy
from rclpy.context import Context
from rclpy.node import Node


def test_offline_tests_refuse_a_domain_with_another_node(tmp_path):
    # Keep the intentionally occupied domain in a fresh process. The main
    # suite repeatedly creates DDS contexts and can retain stale graph data.
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=20.0,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _check_occupied_domain(tmp_path):
    # Run a tiny second pytest process with the production test configuration.
    # This ordinary ROS node represents an unrelated application in its graph.
    tmp_path.joinpath("conftest.py").write_bytes(
        Path(__file__).with_name("conftest.py").read_bytes()
    )
    tmp_path.joinpath("test_probe.py").write_text(
        "def test_driver_would_run():\n    assert False, 'driver test started'\n"
    )
    context = Context()
    rclpy.init(args=[], context=context)
    node = Node("occupied_test_domain", context=context)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--maxfail=1", str(tmp_path)],
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            capture_output=True,
            text=True,
            timeout=15.0,
            cwd=tmp_path,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "is occupied" in result.stdout, result.stdout + result.stderr
        assert "occupied_test_domain" in result.stdout, result.stdout + result.stderr
        assert "driver test started" not in result.stdout, result.stdout + result.stderr
    finally:
        node.destroy_node()
        context.try_shutdown()


if __name__ == "__main__":
    _check_occupied_domain(Path(sys.argv[1]))
