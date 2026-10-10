"""Launch multiple Hand lifecycle drivers in one Python process."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare
from linkerbot_hand_ros.discovery_launch import build_multi_launch


def generate_launch_description() -> LaunchDescription:
    default_config = PathJoinSubstitution(
        [FindPackageShare("linkerbot_hand_ros"), "config", "multi_hand.yaml"]
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "config",
                default_value="",
                description="ROS parameter YAML or generated discovery deployment; empty uses packaged multi_hand.yaml",
            ),
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
            DeclareLaunchArgument(
                "output",
                default_value="",
                description="Discovery output YAML; empty uses ./hands.yaml, never overwritten",
            ),
            DeclareLaunchArgument(
                "autostart",
                default_value="",
                description="Optional true/false override; empty preserves configuration",
            ),
            OpaqueFunction(
                function=build_multi_launch, kwargs={"default_config": default_config}
            ),
        ]
    )
