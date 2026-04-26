from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import ExecuteProcess
from launch.actions import OpaqueFunction
from launch.conditions import IfCondition
from launch_ros.actions import Node
from launch.substitutions import LaunchConfiguration


def _is_true(text: str) -> bool:
    return text.strip().lower() in ("1", "true", "yes", "on")


def _create_video_receiver(context):
    if not _is_true(LaunchConfiguration("enable_video_stream").perform(context)):
        return []

    port = LaunchConfiguration("video_port").perform(context)
    sink = LaunchConfiguration("video_sink").perform(context)
    return [
        ExecuteProcess(
            cmd=[
                "gst-launch-1.0",
                "-e",
                "udpsrc",
                f"port={port}",
                "caps=application/x-rtp,media=video,encoding-name=H264,payload=96",
                "!",
                "rtpjitterbuffer",
                "latency=10",
                "drop-on-latency=true",
                "!",
                "rtph264depay",
                "!",
                "avdec_h264",
                "!",
                "videoconvert",
                "!",
                sink,
                "sync=false",
            ],
            output="screen",
        )
    ]


def generate_launch_description() -> LaunchDescription:
    serial_port_arg = DeclareLaunchArgument(
        "serial_port",
        default_value="/dev/ttyUSB0",
        description="Steam Deck 与小电脑控制链路所使用的串口设备。",
    )
    baudrate_arg = DeclareLaunchArgument(
        "baudrate",
        default_value="460800",
        description="串口波特率，100Hz 下建议至少使用 460800。",
    )
    loop_hz_arg = DeclareLaunchArgument(
        "loop_hz",
        default_value="100.0",
        description="控制链路主循环频率。",
    )
    device_id_arg = DeclareLaunchArgument(
        "device_id",
        default_value="0",
        description="joy_node 使用的手柄设备编号。",
    )
    deadzone_arg = DeclareLaunchArgument(
        "deadzone",
        default_value="0.05",
        description="摇杆死区配置。",
    )
    autorepeat_rate_arg = DeclareLaunchArgument(
        "autorepeat_rate",
        default_value="100.0",
        description="joy_node 自动重复发布频率，建议与控制链路保持一致。",
    )
    enable_control_link_arg = DeclareLaunchArgument(
        "enable_control_link",
        default_value="true",
        description="是否启动 joy_node 与串口控制桥。单独测试网口视频透传时可设为 false。",
    )
    joy_topic_arg = DeclareLaunchArgument(
        "joy_topic",
        default_value="/joy",
        description="Steam Deck 本地摇杆话题。",
    )
    feedback_topic_arg = DeclareLaunchArgument(
        "feedback_topic",
        default_value="/teleop_feedback",
        description="Steam Deck 接收机器人反馈值后发布的 ROS 2 topic。",
    )
    feedback_flags_topic_arg = DeclareLaunchArgument(
        "feedback_flags_topic",
        default_value="/teleop_feedback_flags",
        description="Steam Deck 接收机器人反馈标志位后发布的 ROS 2 topic。",
    )
    link_topic_arg = DeclareLaunchArgument(
        "link_topic",
        default_value="/teleop_link_connected",
        description="控制链路在线状态 topic。",
    )
    enable_video_stream_arg = DeclareLaunchArgument(
        "enable_video_stream",
        default_value="false",
        description="是否在 Steam Deck 侧同时启动视频接收与显示。",
    )
    video_port_arg = DeclareLaunchArgument(
        "video_port",
        default_value="5600",
        description="网口视频流接收端口。",
    )
    video_sink_arg = DeclareLaunchArgument(
        "video_sink",
        default_value="autovideosink",
        description="GStreamer 视频显示 sink，Steam Deck 上可改成 glimagesink。",
    )

    joy_node = Node(
        package="joy",
        executable="joy_node",
        name="joy_node",
        condition=IfCondition(LaunchConfiguration("enable_control_link")),
        output="screen",
        parameters=[
            {
                "device_id": LaunchConfiguration("device_id"),
                "deadzone": LaunchConfiguration("deadzone"),
                "autorepeat_rate": LaunchConfiguration("autorepeat_rate"),
            }
        ],
    )

    bridge_tx_node = Node(
        package="teleop_bridge",
        executable="bridge_tx_node",
        name="bridge_tx_node",
        condition=IfCondition(LaunchConfiguration("enable_control_link")),
        output="screen",
        parameters=[
            {
                "serial_port": LaunchConfiguration("serial_port"),
                "baudrate": LaunchConfiguration("baudrate"),
                "loop_hz": LaunchConfiguration("loop_hz"),
                "joy_topic": LaunchConfiguration("joy_topic"),
                "feedback_topic": LaunchConfiguration("feedback_topic"),
                "feedback_flags_topic": LaunchConfiguration("feedback_flags_topic"),
                "link_topic": LaunchConfiguration("link_topic"),
            }
        ],
    )

    return LaunchDescription(
        [
            serial_port_arg,
            baudrate_arg,
            loop_hz_arg,
            device_id_arg,
            deadzone_arg,
            autorepeat_rate_arg,
            enable_control_link_arg,
            joy_topic_arg,
            feedback_topic_arg,
            feedback_flags_topic_arg,
            link_topic_arg,
            enable_video_stream_arg,
            video_port_arg,
            video_sink_arg,
            joy_node,
            bridge_tx_node,
            OpaqueFunction(function=_create_video_receiver),
        ]
    )
