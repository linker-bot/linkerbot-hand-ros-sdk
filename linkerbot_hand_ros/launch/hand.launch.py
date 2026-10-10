from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from linkerbot_hand_ros.discovery_launch import build_hand_launch, check_hand_mode

_ARGUMENTS = (
    ("model", "l6", str),
    ("side", "left", str),
    ("transport_json", '{"backend":"socketcan","channel":"can0"}', str),
    ("command_rate_hz", "250.0", float),
    ("discrete_queue_capacity", "16", int),
    ("mailbox_capacity", "256", int),
    ("route_queue_capacity", "256", int),
    ("identity_timeout_s", "0.2", float),
    ("transaction_timeout_s", "0.0", float),
    ("shutdown_timeout_s", "2.0", float),
    ("auto_reconnect", "false", bool),
    ("reconnect_initial_delay_s", "0.1", float),
    ("reconnect_max_delay_s", "2.0", float),
    ("recovery_max_attempts", "3", int),
    ("recovery_timeout_s", "5.0", float),
    ("recovery_retry_delay_s", "0.2", float),
    ("publish_rate_hz", "100.0", float),
    ("diagnostic_rate_hz", "1.0", float),
    ("angles_hz", "100.0", float),
    ("angle_feedback", "adaptive", str),
    ("speeds_hz", "0.0", float),
    ("force_hz", "0.0", float),
    ("force_fn_hz", "0.0", float),
    ("force_fns_hz", "0.0", float),
    ("force_ft_hz", "0.0", float),
    ("force_fts_hz", "0.0", float),
    ("force_fd_hz", "0.0", float),
    ("force_fds_hz", "0.0", float),
    ("force_px_hz", "0.0", float),
    ("temperature_hz", "0.0", float),
    ("current_hz", "0.0", float),
    ("faults_hz", "0.0", float),
    ("torques_hz", "0.0", float),
    ("voltage_hz", "0.0", float),
)


def generate_launch_description() -> LaunchDescription:
    arguments = [
        DeclareLaunchArgument(name, default_value=default)
        for name, default, _value_type in _ARGUMENTS
    ]
    arguments.extend(
        (
            DeclareLaunchArgument("namespace", default_value=""),
            DeclareLaunchArgument("autostart", default_value="true"),
        )
    )
    discovery_arguments = [
        DeclareLaunchArgument("discover", default_value="false"),
        DeclareLaunchArgument(
            "channels",
            default_value="",
            description="Comma-separated discovery report interfaces",
        ),
        DeclareLaunchArgument(
            "discovery_config",
            default_value="",
            description="Optional SDK discovery settings YAML",
        ),
    ]
    return LaunchDescription(
        [
            *discovery_arguments,
            OpaqueFunction(function=check_hand_mode),
            *arguments,
            OpaqueFunction(
                function=build_hand_launch, kwargs={"arguments": _ARGUMENTS}
            ),
        ]
    )
