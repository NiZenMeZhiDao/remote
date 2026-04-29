"""运行在 Steam Deck 侧的串口桥接节点。"""

import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
from std_msgs.msg import Bool
from std_msgs.msg import Float32MultiArray
from std_msgs.msg import UInt16

from teleop_bridge.protocol import FeedbackFrame
from teleop_bridge.protocol import ProtocolError
from teleop_bridge.protocol import StreamParser
from teleop_bridge.protocol import decode_stream_frames
from teleop_bridge.protocol import pack_control_frame
from teleop_bridge.transport import SerialEndpoint


class BridgeTxNode(Node):
    """
    Steam Deck 端桥接节点。

    设计目标：
    - 从 `/joy` 缓存最新手柄值
    - 固定 100Hz 通过串口发送控制帧
    - 固定频率轮询串口，接收并发布机器人回传的反馈值
    """

    def __init__(self) -> None:
        super().__init__("bridge_tx_node")

        self.declare_parameter("serial_port", "/dev/ttyUSB0")
        self.declare_parameter("baudrate", 115200)
        self.declare_parameter("loop_hz", 100.0)
        self.declare_parameter("joy_topic", "/joy")
        self.declare_parameter("feedback_topic", "/teleop_feedback")
        self.declare_parameter("feedback_flags_topic", "/teleop_feedback_flags")
        self.declare_parameter("link_topic", "/teleop_link_connected")
        self.declare_parameter("feedback_timeout_sec", 0.5)
        self.declare_parameter("diagnostic_log_period_sec", 2.0)

        serial_port = self.get_parameter("serial_port").value
        baudrate = int(self.get_parameter("baudrate").value)
        loop_hz = float(self.get_parameter("loop_hz").value)
        joy_topic = self.get_parameter("joy_topic").value
        feedback_topic = self.get_parameter("feedback_topic").value
        feedback_flags_topic = self.get_parameter("feedback_flags_topic").value
        link_topic = self.get_parameter("link_topic").value
        self._feedback_timeout_sec = float(
            self.get_parameter("feedback_timeout_sec").value
        )
        self._diagnostic_log_period_sec = float(
            self.get_parameter("diagnostic_log_period_sec").value
        )

        if loop_hz <= 0.0:
            raise ValueError("loop_hz 必须大于 0。")

        self._serial = SerialEndpoint(serial_port, baudrate)
        self._parser = StreamParser()
        self._sequence = 0
        self._latest_axes: list[float] = []
        self._latest_buttons: list[int] = []
        self._has_joy = False
        self._last_feedback: FeedbackFrame | None = None
        self._last_feedback_time_ns: int | None = None
        self._last_serial_warn_ns = 0
        self._last_diagnostic_log_ns = 0
        self._joy_msg_count = 0
        self._control_tx_count = 0
        self._feedback_rx_count = 0
        self._logged_first_joy = False
        self._logged_first_control_tx = False
        self._logged_first_feedback_rx = False

        self._joy_subscription = self.create_subscription(
            Joy,
            joy_topic,
            self._joy_callback,
            10,
        )
        self._feedback_publisher = self.create_publisher(
            Float32MultiArray,
            feedback_topic,
            10,
        )
        self._feedback_flags_publisher = self.create_publisher(
            UInt16,
            feedback_flags_topic,
            10,
        )
        self._link_publisher = self.create_publisher(Bool, link_topic, 10)

        self._loop_timer = self.create_timer(1.0 / loop_hz, self._loop_once)

        self.get_logger().info(
            "bridge_tx_node 已启动，当前结构为“网口传桌面画面，串口传摇杆/反馈”。"
        )
        self.get_logger().info(
            f"Steam Deck 串口链路参数: port={serial_port}, baudrate={baudrate}, loop_hz={loop_hz:.1f}"
        )

    def _joy_callback(self, joy_msg: Joy) -> None:
        self._latest_axes = list(joy_msg.axes)
        self._latest_buttons = [int(button) for button in joy_msg.buttons]
        self._has_joy = True
        self._joy_msg_count += 1
        if not self._logged_first_joy:
            self.get_logger().info(
                f"已收到首个 /joy: axes={len(self._latest_axes)}, buttons={len(self._latest_buttons)}"
            )
            self._logged_first_joy = True

    def _loop_once(self) -> None:
        self._read_feedback_frames()
        self._send_control_frame()
        self._publish_feedback_state()
        self._log_diagnostics()

    def _read_feedback_frames(self) -> None:
        try:
            raw_bytes = self._serial.read_available()
        except (OSError, RuntimeError) as exc:
            self._log_serial_warn(f"Steam Deck 串口读取失败，但节点会继续运行: {exc}")
            return

        if not raw_bytes:
            return

        try:
            for frame in decode_stream_frames(raw_bytes, self._parser):
                if not isinstance(frame, FeedbackFrame):
                    continue
                self._last_feedback = frame
                self._last_feedback_time_ns = self.get_clock().now().nanoseconds
                self._feedback_rx_count += 1
                if not self._logged_first_feedback_rx:
                    self.get_logger().info(
                        f"已收到首个机器人反馈帧: seq={frame.seq}, values={len(frame.values)}, flags=0x{frame.status_flags:04x}"
                    )
                    self._logged_first_feedback_rx = True
        except ProtocolError as exc:
            self._log_serial_warn(f"Steam Deck 收到非法反馈帧，已丢弃: {exc}")

    def _send_control_frame(self) -> None:
        if not self._has_joy:
            return

        try:
            payload = pack_control_frame(
                axes=self._latest_axes,
                buttons=self._latest_buttons,
                seq=self._sequence,
            )
            self._serial.write(payload)
            self._sequence = (self._sequence + 1) & 0xFF
            self._control_tx_count += 1
            if not self._logged_first_control_tx:
                self.get_logger().info(
                    f"已发送首个控制帧: bytes={len(payload)}, axes={len(self._latest_axes)}, buttons={len(self._latest_buttons)}"
                )
                self._logged_first_control_tx = True
        except (OSError, RuntimeError) as exc:
            self._log_serial_warn(f"Steam Deck 串口发送失败，但节点会继续运行: {exc}")
        except ProtocolError as exc:
            self._log_serial_warn(f"Steam Deck 控制帧封包失败: {exc}")

    def _publish_feedback_state(self) -> None:
        link_msg = Bool()
        link_msg.data = self._is_feedback_alive()
        self._link_publisher.publish(link_msg)

        if self._last_feedback is None:
            return

        feedback_msg = Float32MultiArray()
        feedback_msg.data = list(self._last_feedback.values)
        self._feedback_publisher.publish(feedback_msg)

        flags_msg = UInt16()
        flags_msg.data = int(self._last_feedback.status_flags)
        self._feedback_flags_publisher.publish(flags_msg)

    def _is_feedback_alive(self) -> bool:
        if not self._serial.is_open:
            return False
        if self._last_feedback_time_ns is None:
            return False

        age_sec = (
            self.get_clock().now().nanoseconds - self._last_feedback_time_ns
        ) / 1e9
        return bool(age_sec <= self._feedback_timeout_sec and not math.isnan(age_sec))

    def _log_serial_warn(self, message: str, throttle_sec: float = 2.0) -> None:
        now_ns = self.get_clock().now().nanoseconds
        throttle_ns = int(throttle_sec * 1e9)
        if now_ns - self._last_serial_warn_ns >= throttle_ns:
            self.get_logger().warn(message)
            self._last_serial_warn_ns = now_ns

    def _log_diagnostics(self) -> None:
        if self._diagnostic_log_period_sec <= 0.0:
            return

        now_ns = self.get_clock().now().nanoseconds
        throttle_ns = int(self._diagnostic_log_period_sec * 1e9)
        if now_ns - self._last_diagnostic_log_ns < throttle_ns:
            return

        self.get_logger().info(
            "Deck链路诊断: "
            f"serial_open={self._serial.is_open}, "
            f"joy_msgs={self._joy_msg_count}, "
            f"control_tx={self._control_tx_count}, "
            f"feedback_rx={self._feedback_rx_count}, "
            f"link={self._is_feedback_alive()}"
        )
        self._last_diagnostic_log_ns = now_ns

    def destroy_node(self) -> bool:
        self._serial.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = BridgeTxNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("收到退出信号，bridge_tx_node 正在关闭。")
    finally:
        node.destroy_node()
        rclpy.shutdown()
