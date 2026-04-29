"""运行在机器人小电脑侧的串口桥接节点。"""

import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
from std_msgs.msg import Bool
from std_msgs.msg import Float32MultiArray
from std_msgs.msg import UInt16

from teleop_bridge.protocol import ControlFrame
from teleop_bridge.protocol import ProtocolError
from teleop_bridge.protocol import StreamParser
from teleop_bridge.protocol import decode_stream_frames
from teleop_bridge.protocol import pack_feedback_frame
from teleop_bridge.transport import SerialEndpoint


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class BridgeRxNode(Node):
    """
    机器人端桥接节点。

    设计目标：
    - 固定 100Hz 读取串口控制帧
    - 固定 100Hz 发布 `/joy_remote`
    - 固定 100Hz 将本地反馈值回传给 Steam Deck
    """

    def __init__(self) -> None:
        super().__init__("bridge_rx_node")

        self.declare_parameter("serial_port", "/dev/ttyUSB0")
        self.declare_parameter("baudrate", 115200)
        self.declare_parameter("loop_hz", 100.0)
        self.declare_parameter("frame_id", "remote_joy")
        self.declare_parameter("joy_output_topic", "/joy_remote")
        self.declare_parameter("feedback_input_topic", "/teleop_feedback_in")
        self.declare_parameter("feedback_flags_input_topic", "/teleop_feedback_flags_in")
        self.declare_parameter("link_topic", "/teleop_link_connected")
        self.declare_parameter("stale_timeout_sec", 0.2)
        self.declare_parameter("publish_neutral_on_disconnect", True)
        self.declare_parameter("diagnostic_log_period_sec", 2.0)

        serial_port = self.get_parameter("serial_port").value
        baudrate = int(self.get_parameter("baudrate").value)
        loop_hz = float(self.get_parameter("loop_hz").value)
        self._frame_id = self.get_parameter("frame_id").value
        joy_output_topic = self.get_parameter("joy_output_topic").value
        feedback_input_topic = self.get_parameter("feedback_input_topic").value
        feedback_flags_input_topic = self.get_parameter(
            "feedback_flags_input_topic"
        ).value
        link_topic = self.get_parameter("link_topic").value
        self._stale_timeout_sec = float(self.get_parameter("stale_timeout_sec").value)
        self._publish_neutral_on_disconnect = _to_bool(
            self.get_parameter("publish_neutral_on_disconnect").value
        )
        self._diagnostic_log_period_sec = float(
            self.get_parameter("diagnostic_log_period_sec").value
        )

        if loop_hz <= 0.0:
            raise ValueError("loop_hz 必须大于 0。")

        self._serial = SerialEndpoint(serial_port, baudrate)
        self._parser = StreamParser()
        self._feedback_sequence = 0
        self._last_control: ControlFrame | None = None
        self._last_control_time_ns: int | None = None
        self._last_serial_warn_ns = 0
        self._last_diagnostic_log_ns = 0
        self._latest_feedback_values: list[float] = []
        self._latest_feedback_flags = 0
        self._control_rx_count = 0
        self._joy_publish_count = 0
        self._feedback_tx_count = 0
        self._logged_first_control_rx = False
        self._logged_first_joy_publish = False
        self._logged_first_feedback_tx = False

        self._feedback_subscription = self.create_subscription(
            Float32MultiArray,
            feedback_input_topic,
            self._feedback_values_callback,
            10,
        )
        self._feedback_flags_subscription = self.create_subscription(
            UInt16,
            feedback_flags_input_topic,
            self._feedback_flags_callback,
            10,
        )
        self._joy_publisher = self.create_publisher(Joy, joy_output_topic, 10)
        self._link_publisher = self.create_publisher(Bool, link_topic, 10)

        self._loop_timer = self.create_timer(1.0 / loop_hz, self._loop_once)

        self.get_logger().info(
            "bridge_rx_node 已启动，当前结构为“网口传桌面画面，串口传摇杆/反馈”。"
        )
        self.get_logger().info(
            f"机器人串口链路参数: port={serial_port}, baudrate={baudrate}, loop_hz={loop_hz:.1f}"
        )

    def _feedback_values_callback(self, msg: Float32MultiArray) -> None:
        self._latest_feedback_values = [float(value) for value in msg.data]

    def _feedback_flags_callback(self, msg: UInt16) -> None:
        self._latest_feedback_flags = int(msg.data) & 0xFFFF

    def _loop_once(self) -> None:
        self._read_control_frames()
        self._publish_joy_output()
        self._send_feedback_frame()
        self._publish_link_state()
        self._log_diagnostics()

    def _read_control_frames(self) -> None:
        try:
            raw_bytes = self._serial.read_available()
        except (OSError, RuntimeError) as exc:
            self._log_serial_warn(f"机器人端串口读取失败，但节点会继续运行: {exc}")
            return

        if not raw_bytes:
            return

        try:
            for frame in decode_stream_frames(raw_bytes, self._parser):
                if not isinstance(frame, ControlFrame):
                    continue
                self._last_control = frame
                self._last_control_time_ns = self.get_clock().now().nanoseconds
                self._control_rx_count += 1
                if not self._logged_first_control_rx:
                    self.get_logger().info(
                        f"已收到首个控制帧: seq={frame.seq}, axes={len(frame.axes)}, buttons={len(frame.buttons)}"
                    )
                    self._logged_first_control_rx = True
        except ProtocolError as exc:
            self._log_serial_warn(f"机器人端收到非法控制帧，已丢弃: {exc}")

    def _publish_joy_output(self) -> None:
        link_alive = self._is_control_alive()
        if self._last_control is None:
            return
        if not link_alive and not self._publish_neutral_on_disconnect:
            return

        joy_msg = Joy()
        joy_msg.header.stamp = self.get_clock().now().to_msg()
        joy_msg.header.frame_id = self._frame_id

        if link_alive:
            joy_msg.axes = list(self._last_control.axes)
            joy_msg.buttons = list(self._last_control.buttons)
        else:
            joy_msg.axes = [0.0] * len(self._last_control.axes)
            joy_msg.buttons = [0] * len(self._last_control.buttons)

        self._joy_publisher.publish(joy_msg)
        self._joy_publish_count += 1
        if not self._logged_first_joy_publish:
            self.get_logger().info(
                f"已发布首个 /joy_remote: axes={len(joy_msg.axes)}, buttons={len(joy_msg.buttons)}"
            )
            self._logged_first_joy_publish = True

    def _send_feedback_frame(self) -> None:
        try:
            payload = pack_feedback_frame(
                status_flags=self._latest_feedback_flags,
                values=self._latest_feedback_values,
                seq=self._feedback_sequence,
            )
            self._serial.write(payload)
            self._feedback_sequence = (self._feedback_sequence + 1) & 0xFF
            self._feedback_tx_count += 1
            if not self._logged_first_feedback_tx:
                self.get_logger().info(
                    f"已发送首个反馈帧: bytes={len(payload)}, values={len(self._latest_feedback_values)}, flags=0x{self._latest_feedback_flags:04x}"
                )
                self._logged_first_feedback_tx = True
        except (OSError, RuntimeError) as exc:
            self._log_serial_warn(f"机器人端串口发送失败，但节点会继续运行: {exc}")
        except ProtocolError as exc:
            self._log_serial_warn(f"机器人端反馈帧封包失败: {exc}")

    def _publish_link_state(self) -> None:
        msg = Bool()
        msg.data = self._is_control_alive()
        self._link_publisher.publish(msg)

    def _is_control_alive(self) -> bool:
        if not self._serial.is_open:
            return False
        if self._last_control_time_ns is None:
            return False

        age_sec = (
            self.get_clock().now().nanoseconds - self._last_control_time_ns
        ) / 1e9
        return bool(age_sec <= self._stale_timeout_sec and not math.isnan(age_sec))

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
            "机器人链路诊断: "
            f"serial_open={self._serial.is_open}, "
            f"control_rx={self._control_rx_count}, "
            f"joy_remote_pub={self._joy_publish_count}, "
            f"feedback_tx={self._feedback_tx_count}, "
            f"link={self._is_control_alive()}"
        )
        self._last_diagnostic_log_ns = now_ns

    def destroy_node(self) -> bool:
        self._serial.close()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = BridgeRxNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("收到退出信号，bridge_rx_node 正在关闭。")
    finally:
        node.destroy_node()
        rclpy.shutdown()
