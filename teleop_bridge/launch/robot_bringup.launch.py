from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import ExecuteProcess
from launch.actions import OpaqueFunction
from launch.conditions import IfCondition
from launch_ros.actions import Node
from launch.substitutions import LaunchConfiguration


def _is_true(text: str) -> bool:
    return text.strip().lower() in ("1", "true", "yes", "on")


def _create_video_sender(context):
    if not _is_true(LaunchConfiguration("enable_video_stream").perform(context)):
        return []

    target_ip = LaunchConfiguration("video_target_ip").perform(context)
    port = LaunchConfiguration("video_port").perform(context)
    width = LaunchConfiguration("video_width").perform(context)
    height = LaunchConfiguration("video_height").perform(context)
    fps = LaunchConfiguration("video_fps").perform(context)
    bitrate = LaunchConfiguration("video_bitrate_kbps").perform(context)

    return [
        ExecuteProcess(
            cmd=[
                "gst-launch-1.0",
                "-e",
                "ximagesrc",
                "use-damage=0",
                "show-pointer=true",
                "!",
                "videoconvert",
                "!",
                "videoscale",
                "!",
                "videorate",
                "!",
                f"video/x-raw,width={width},height={height},framerate={fps}/1",
                "!",
                "x264enc",
                "tune=zerolatency",
                "speed-preset=ultrafast",
                f"bitrate={bitrate}",
                "key-int-max=30",
                "!",
                "rtph264pay",
                "pt=96",
                "config-interval=1",
                "!",
                "udpsink",
                f"host={target_ip}",
                f"port={port}",
                "sync=false",
                "async=false",
            ],
            output="screen",
        )
    ]


def generate_launch_description() -> LaunchDescription:
    serial_port_arg = DeclareLaunchArgument(
        "serial_port",
        default_value="/dev/ttyUSB0",
        description="机器人小电脑控制链路所使用的串口设备。",
    )
    baudrate_arg = DeclareLaunchArgument(
        "baudrate",
        default_value="115200",
        description="串口波特率，默认按无线透传模块的 115200 配置。",
    )
    loop_hz_arg = DeclareLaunchArgument(
        "loop_hz",
        default_value="100.0",
        description="控制链路主循环频率。",
    )
    enable_control_link_arg = DeclareLaunchArgument(
        "enable_control_link",
        default_value="true",
        description="是否启动串口控制桥。单独测试网口视频透传时可设为 false。",
    )
    frame_id_arg = DeclareLaunchArgument(
        "frame_id",
        default_value="remote_joy",
        description="发布到 /joy_remote 时使用的 frame_id。",
    )
    joy_output_topic_arg = DeclareLaunchArgument(
        "joy_output_topic",
        default_value="/joy_remote",
        description="机器人端发布还原摇杆值的 topic。",
    )
    feedback_input_topic_arg = DeclareLaunchArgument(
        "feedback_input_topic",
        default_value="/teleop_feedback_in",
        description="机器人本地反馈值输入 topic，类型为 Float32MultiArray。",
    )
    feedback_flags_input_topic_arg = DeclareLaunchArgument(
        "feedback_flags_input_topic",
        default_value="/teleop_feedback_flags_in",
        description="机器人本地反馈标志位输入 topic，类型为 UInt16。",
    )
    link_topic_arg = DeclareLaunchArgument(
        "link_topic",
        default_value="/teleop_link_connected",
        description="控制链路在线状态 topic。",
    )
    stale_timeout_arg = DeclareLaunchArgument(
        "stale_timeout_sec",
        default_value="0.2",
        description="超过该时长未收到控制帧时认为链路断开。",
    )
    publish_neutral_arg = DeclareLaunchArgument(
        "publish_neutral_on_disconnect",
        default_value="true",
        description="链路断开时是否继续以 100Hz 发布全零 Joy。",
    )
    enable_video_stream_arg = DeclareLaunchArgument(
        "enable_video_stream",
        default_value="false",
        description="是否在机器人端同时启动桌面发送。",
    )
    video_target_ip_arg = DeclareLaunchArgument(
        "video_target_ip",
        default_value="192.168.1.10",
        description="Steam Deck 端视频接收 IP。",
    )
    video_port_arg = DeclareLaunchArgument(
        "video_port",
        default_value="5600",
        description="网口视频流发送端口。",
    )
    video_width_arg = DeclareLaunchArgument(
        "video_width",
        default_value="1280",
        description="桌面推流宽度。",
    )
    video_height_arg = DeclareLaunchArgument(
        "video_height",
        default_value="720",
        description="桌面推流高度。",
    )
    video_fps_arg = DeclareLaunchArgument(
        "video_fps",
        default_value="30",
        description="桌面推流帧率。",
    )
    video_bitrate_arg = DeclareLaunchArgument(
        "video_bitrate_kbps",
        default_value="4000",
        description="H.264 推流码率，单位 kbps。",
    )

    bridge_rx_node = Node(
        package="teleop_bridge",
        executable="bridge_rx_node",
        name="bridge_rx_node",
        condition=IfCondition(LaunchConfiguration("enable_control_link")),
        output="screen",
        parameters=[
            {
                "serial_port": LaunchConfiguration("serial_port"),
                "baudrate": LaunchConfiguration("baudrate"),
                "loop_hz": LaunchConfiguration("loop_hz"),
                "frame_id": LaunchConfiguration("frame_id"),
                "joy_output_topic": LaunchConfiguration("joy_output_topic"),
                "feedback_input_topic": LaunchConfiguration("feedback_input_topic"),
                "feedback_flags_input_topic": LaunchConfiguration(
                    "feedback_flags_input_topic"
                ),
                "link_topic": LaunchConfiguration("link_topic"),
                "stale_timeout_sec": LaunchConfiguration("stale_timeout_sec"),
                "publish_neutral_on_disconnect": LaunchConfiguration(
                    "publish_neutral_on_disconnect"
                ),
            }
        ],
    )

    return LaunchDescription(
        [
            serial_port_arg,
            baudrate_arg,
            loop_hz_arg,
            enable_control_link_arg,
            frame_id_arg,
            joy_output_topic_arg,
            feedback_input_topic_arg,
            feedback_flags_input_topic_arg,
            link_topic_arg,
            stale_timeout_arg,
            publish_neutral_arg,
            enable_video_stream_arg,
            video_target_ip_arg,
            video_port_arg,
            video_width_arg,
            video_height_arg,
            video_fps_arg,
            video_bitrate_arg,
            bridge_rx_node,
            OpaqueFunction(function=_create_video_sender),
        ]
    )
