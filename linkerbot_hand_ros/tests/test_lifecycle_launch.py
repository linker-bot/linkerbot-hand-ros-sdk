"""Run the production launch events against a real driver with an in-memory SDK."""

import asyncio
import subprocess
import sys
import textwrap
from pathlib import Path
from uuid import uuid4

import pytest
import rclpy
from launch import LaunchDescription, LaunchService
from launch.actions import OpaqueFunction, RegisterEventHandler
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from lifecycle_msgs.msg import State, Transition
from lifecycle_msgs.srv import ChangeState, GetState
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from test_discovery_launch import _hand_launch

from linkerbot_hand_ros import discovery_launch


@pytest.mark.parametrize(
    "autostart,fail_initial_configure,drop_initial_state_response",
    [
        ("true", False, False),
        ("false", False, False),
        ("true", True, False),
        ("false", False, True),
    ],
)
def test_manual_launch_respects_autostart_and_stays_inactive_after_deactivation(
    autostart,
    fail_initial_configure,
    drop_initial_state_response,
):
    # Cross-process discovery needs fresh DDS participants on both sides.
    # Reusing the suite's process after many init/shutdown cycles can lose the
    # initial transition event even though the same check passes in isolation.
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            autostart,
            str(fail_initial_configure),
            str(drop_initial_state_response),
        ],
        capture_output=True,
        text=True,
        timeout=45.0,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _check_manual_launch(
    monkeypatch, autostart, fail_initial_configure, drop_initial_state_response
):
    # Replace only the executable; parameters, ROS launch events and the driver
    # lifecycle remain real. DeviceBuilder never opens a physical adapter.
    child = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(Path(__file__).parent)!r})
        import rclpy
        from rclpy.executors import ExternalShutdownException
        from linkerbot_hand_ros.executor import MultiThreadedExecutor
        from fakes_v1 import DeviceBuilder
        from linkerbot_hand_ros.node import (
            CALLBACK_GROUPS_PER_HAND, LinkerbotHandNode, spin_until_shutdown,
        )
        rclpy.init()
        builder = DeviceBuilder()
        fail_configure = {fail_initial_configure!r}
        def device_factory(configuration):
            global fail_configure
            if fail_configure:
                fail_configure = False
                raise RuntimeError("injected initial configuration failure")
            return builder(configuration)
        node = LinkerbotHandNode(device_factory=device_factory)
        if {drop_initial_state_response!r}:
            state_service = next(
                service for service in node.services
                if service.srv_name.endswith("/get_state")
            )
            send_response = state_service.send_response
            drop_response = True
            def send_state_response(response, header):
                global drop_response
                if drop_response:
                    drop_response = False
                    return
                send_response(response, header)
            state_service.send_response = send_state_response
        executor = MultiThreadedExecutor(num_threads=CALLBACK_GROUPS_PER_HAND)
        executor.add_node(node)
        try:
            spin_until_shutdown(executor, node.get_logger())
        except (KeyboardInterrupt, ExternalShutdownException):
            pass
        finally:
            executor.remove_node(node)
            executor.shutdown()
            node.destroy_node()
            rclpy.try_shutdown()
        """
    )

    def driver(**options):
        options.update(package=None, executable=sys.executable, arguments=["-c", child])
        return LifecycleNode(**options)

    monkeypatch.setattr(discovery_launch, "LifecycleNode", driver)
    # Use a new name on every run, including repeats of the same case. A graph
    # announcement retained by another participant must not make an old
    # driver's services appear ready before this driver's readers are matched.
    namespace = f"/launch_compat_{uuid4().hex}"
    context, actions = _hand_launch({"autostart": autostart, "namespace": namespace})
    configuration_results = []
    failure_observer = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=actions[-1],
            start_state="configuring",
            entities=[
                OpaqueFunction(
                    function=lambda context: configuration_results.append(
                        context.locals.event.goal_state
                    )
                )
            ],
            handle_once=True,
        )
    )

    async def exercise():
        launch = LaunchService()
        launch.context.launch_configurations.update(context.launch_configurations)
        launch.include_launch_description(
            LaunchDescription([failure_observer, *actions])
        )
        task = asyncio.create_task(launch.run_async())
        rclpy.init()
        caller = Node("lifecycle_launch_test_client")
        executor = SingleThreadedExecutor()
        executor.add_node(caller)
        prefix = f"{namespace}/linkerbot_hand"
        get_state = caller.create_client(GetState, f"{prefix}/get_state")
        change_state = caller.create_client(ChangeState, f"{prefix}/change_state")
        initial_state_requests = 0

        async def wait_until(predicate):
            deadline = asyncio.get_running_loop().time() + 10.0
            while not predicate():
                assert not task.done(), "driver launch exited before verification"
                assert asyncio.get_running_loop().time() < deadline, (
                    f"lifecycle timeout (configuration results: {configuration_results})"
                )
                executor.spin_once(timeout_sec=0.0)
                await asyncio.sleep(0.01)

        async def call(client, request, *, initial_discovery=False):
            nonlocal initial_state_requests
            await wait_until(client.service_is_ready)
            deadline = asyncio.get_running_loop().time() + 10.0
            while True:
                if initial_discovery:
                    initial_state_requests += 1
                future = client.call_async(request)
                attempt_deadline = (
                    min(deadline, asyncio.get_running_loop().time() + 1.0)
                    if initial_discovery
                    else deadline
                )
                while not future.done():
                    assert not task.done(), "driver launch exited before verification"
                    if asyncio.get_running_loop().time() >= attempt_deadline:
                        break
                    executor.spin_once(timeout_sec=0.0)
                    await asyncio.sleep(0.01)
                if future.done():
                    return future.result()
                client.remove_pending_request(future)
                future.cancel()
                assert (
                    initial_discovery and asyncio.get_running_loop().time() < deadline
                ), (
                    f"service timeout: {client.srv_name} "
                    f"(configuration results: {configuration_results})"
                )

        async def state(*, initial_discovery=False):
            return (
                await call(
                    get_state, GetState.Request(), initial_discovery=initial_discovery
                )
            ).current_state.id

        async def transition(identifier):
            response = await call(
                change_state,
                ChangeState.Request(transition=Transition(id=identifier)),
            )
            assert response.success

        try:
            # Readiness of the request endpoint can precede discovery of the
            # response reader. Retry only this initial idempotent query within
            # the existing deadline; lifecycle changes are never resent.
            initial_state = await state(initial_discovery=True)
            if drop_initial_state_response:
                assert initial_state_requests >= 2
            if fail_initial_configure:
                await wait_until(lambda: bool(configuration_results))
                assert configuration_results == ["unconfigured"]
                assert await state() == State.PRIMARY_STATE_UNCONFIGURED
                await transition(Transition.TRANSITION_CONFIGURE)
                # Allow launch to process the successful configure event. An
                # aborted autostart must not activate this manual retry.
                await asyncio.sleep(0.3)
                assert await state() == State.PRIMARY_STATE_INACTIVE
                await transition(Transition.TRANSITION_ACTIVATE)
                assert await state() == State.PRIMARY_STATE_ACTIVE
            elif autostart == "true":
                deadline = asyncio.get_running_loop().time() + 10.0
                observed_states = []
                while True:
                    observed_states.append(await state())
                    if observed_states[-1] == State.PRIMARY_STATE_ACTIVE:
                        break
                    assert asyncio.get_running_loop().time() < deadline, (
                        "autostart timeout "
                        f"(states: {observed_states[-10:]}, "
                        f"configuration results: {configuration_results})"
                    )
                    await asyncio.sleep(0.05)
            else:
                assert initial_state == State.PRIMARY_STATE_UNCONFIGURED
                await transition(Transition.TRANSITION_CONFIGURE)
                assert await state() == State.PRIMARY_STATE_INACTIVE
                await transition(Transition.TRANSITION_ACTIVATE)
                assert await state() == State.PRIMARY_STATE_ACTIVE

            await transition(Transition.TRANSITION_DEACTIVATE)
            await asyncio.sleep(0.3)
            assert await state() == State.PRIMARY_STATE_INACTIVE
            await transition(Transition.TRANSITION_CLEANUP)
            assert await state() == State.PRIMARY_STATE_UNCONFIGURED
            await transition(Transition.TRANSITION_CONFIGURE)
            await asyncio.sleep(0.3)
            assert await state() == State.PRIMARY_STATE_INACTIVE
            await transition(Transition.TRANSITION_CLEANUP)
        finally:
            shutdown = launch.shutdown()
            if shutdown is not None:
                await shutdown
            try:
                assert await asyncio.wait_for(task, timeout=10.0) == 0
            finally:
                executor.shutdown()
                caller.destroy_node()
                rclpy.try_shutdown()

    asyncio.run(exercise())


if __name__ == "__main__":
    with pytest.MonkeyPatch.context() as patch:
        _check_manual_launch(
            patch, sys.argv[1], sys.argv[2] == "True", sys.argv[3] == "True"
        )
