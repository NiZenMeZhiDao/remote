"""串口控制链路的紧凑协议定义。"""

from dataclasses import dataclass
import struct
from typing import Iterable, Sequence


HEADER = b"\x55\xaa"
VERSION = 2

FRAME_TYPE_CONTROL = 1
FRAME_TYPE_FEEDBACK = 2

MAX_AXES = 64
MAX_BUTTONS = 255
MAX_FEEDBACK_VALUES = 32

_FRAME_PREFIX_FORMAT = "<2sBBBB"
_FRAME_PREFIX_SIZE = struct.calcsize(_FRAME_PREFIX_FORMAT)
_CHECKSUM_SIZE = 1


class ProtocolError(ValueError):
    """协议相关异常。"""


@dataclass(frozen=True)
class ControlFrame:
    """Steam Deck 发往小电脑的控制帧。"""

    seq: int
    axes: list[float]
    buttons: list[int]


@dataclass(frozen=True)
class FeedbackFrame:
    """小电脑发往 Steam Deck 的反馈帧。"""

    seq: int
    status_flags: int
    values: list[float]


@dataclass(frozen=True)
class RawFrame:
    """统一的底层帧对象。"""

    frame_type: int
    seq: int
    payload: bytes


def checksum8(payload: bytes) -> int:
    """返回一个 8 位累加校验。"""
    return sum(payload) & 0xFF


def _build_frame(frame_type: int, seq: int, payload: bytes) -> bytes:
    if len(payload) > 255:
        raise ProtocolError(f"负载长度 {len(payload)} 超过 255 字节上限。")

    prefix = struct.pack(
        _FRAME_PREFIX_FORMAT,
        HEADER,
        VERSION,
        frame_type,
        seq & 0xFF,
        len(payload),
    )
    checksum = checksum8(prefix[len(HEADER) :] + payload)
    return prefix + payload + bytes([checksum])


def _float_to_int16(value: float) -> int:
    clamped = max(-1.0, min(1.0, float(value)))
    if clamped >= 0.0:
        return int(round(clamped * 32767.0))
    return int(round(clamped * 32768.0))


def _int16_to_float(value: int) -> float:
    if value >= 0:
        return float(value) / 32767.0 if value else 0.0
    return float(value) / 32768.0


def _buttons_to_bitmask(buttons: Sequence[int]) -> int:
    bitmask = 0
    for index, pressed in enumerate(buttons):
        if pressed:
            bitmask |= 1 << index
    return bitmask


def _button_bytes_length(button_count: int) -> int:
    return (button_count + 7) // 8


def pack_control_frame(axes: Sequence[float], buttons: Sequence[int], seq: int) -> bytes:
    """
    打包控制帧。

    控制负载布局:
    - axis_count: uint8
    - button_count: uint8
    - button_bitmask: bytes，长度为 ceil(button_count / 8)
    - axes: int16 * N

    这里使用 int16 而不是 float32，是为了在串口 100Hz 传输场景下降低带宽占用。
    """
    if len(axes) > MAX_AXES:
        raise ProtocolError(
            f"轴数量 {len(axes)} 超过协议上限 {MAX_AXES}，请按需扩展协议。"
        )
    if len(buttons) > MAX_BUTTONS:
        raise ProtocolError(
            f"按键数量 {len(buttons)} 超过协议上限 {MAX_BUTTONS}，请按需扩展协议。"
        )

    axis_values = [_float_to_int16(axis) for axis in axes]
    button_count = len(buttons)
    button_bytes = _buttons_to_bitmask(buttons).to_bytes(
        _button_bytes_length(button_count),
        byteorder="little",
        signed=False,
    )
    payload = struct.pack("<BB", len(axis_values), button_count) + button_bytes
    if axis_values:
        payload += struct.pack(f"<{len(axis_values)}h", *axis_values)
    return _build_frame(FRAME_TYPE_CONTROL, seq, payload)


def unpack_control_payload(seq: int, payload: bytes) -> ControlFrame:
    if len(payload) < struct.calcsize("<BB"):
        raise ProtocolError("控制负载过短。")

    axis_count, button_count = struct.unpack("<BB", payload[:2])
    if axis_count > MAX_AXES:
        raise ProtocolError(f"轴数量 {axis_count} 超过协议上限 {MAX_AXES}。")
    if button_count > MAX_BUTTONS:
        raise ProtocolError(f"按键数量 {button_count} 超过协议上限 {MAX_BUTTONS}。")

    button_bytes_length = _button_bytes_length(button_count)
    expected_size = 2 + button_bytes_length + axis_count * 2
    if len(payload) != expected_size:
        raise ProtocolError(
            f"控制负载长度 {len(payload)} 与 axis_count={axis_count} 推导结果不一致。"
        )

    button_bitmask = int.from_bytes(
        payload[2 : 2 + button_bytes_length],
        byteorder="little",
        signed=False,
    )
    axes = []
    if axis_count:
        raw_axes = struct.unpack(f"<{axis_count}h", payload[2 + button_bytes_length :])
        axes = [_int16_to_float(value) for value in raw_axes]
    buttons = [(button_bitmask >> index) & 0x01 for index in range(button_count)]

    return ControlFrame(seq=seq, axes=axes, buttons=buttons)


def pack_feedback_frame(status_flags: int, values: Sequence[float], seq: int) -> bytes:
    """
    打包反馈帧。

    反馈负载布局:
    - status_flags: uint16
    - value_count: uint8
    - values: float32 * N
    """
    if len(values) > MAX_FEEDBACK_VALUES:
        raise ProtocolError(
            f"反馈值数量 {len(values)} 超过协议上限 {MAX_FEEDBACK_VALUES}。"
        )

    payload = struct.pack(
        f"<HB{len(values)}f",
        int(status_flags) & 0xFFFF,
        len(values),
        *values,
    )
    return _build_frame(FRAME_TYPE_FEEDBACK, seq, payload)


def unpack_feedback_payload(seq: int, payload: bytes) -> FeedbackFrame:
    if len(payload) < struct.calcsize("<HB"):
        raise ProtocolError("反馈负载过短。")

    status_flags, value_count = struct.unpack("<HB", payload[:3])
    if value_count > MAX_FEEDBACK_VALUES:
        raise ProtocolError(
            f"反馈值数量 {value_count} 超过协议上限 {MAX_FEEDBACK_VALUES}。"
        )

    expected_size = 3 + value_count * 4
    if len(payload) != expected_size:
        raise ProtocolError(
            f"反馈负载长度 {len(payload)} 与 value_count={value_count} 推导结果不一致。"
        )

    values = []
    if value_count:
        values = list(struct.unpack(f"<{value_count}f", payload[3:]))

    return FeedbackFrame(seq=seq, status_flags=status_flags, values=values)


def decode_raw_frame(frame: RawFrame) -> ControlFrame | FeedbackFrame:
    if frame.frame_type == FRAME_TYPE_CONTROL:
        return unpack_control_payload(frame.seq, frame.payload)
    if frame.frame_type == FRAME_TYPE_FEEDBACK:
        return unpack_feedback_payload(frame.seq, frame.payload)
    raise ProtocolError(f"未知帧类型 {frame.frame_type}。")


class StreamParser:
    """
    串口流式解析器。

    串口不同于 UDP，没有天然的报文边界，因此这里使用内部缓冲区做切帧。
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[RawFrame]:
        if data:
            self._buffer.extend(data)

        frames: list[RawFrame] = []
        while True:
            if len(self._buffer) < _FRAME_PREFIX_SIZE + _CHECKSUM_SIZE:
                return frames

            header_index = self._find_header()
            if header_index < 0:
                if self._buffer and self._buffer[-1] == HEADER[0]:
                    self._buffer[:] = self._buffer[-1:]
                else:
                    self._buffer.clear()
                return frames
            if header_index > 0:
                del self._buffer[:header_index]

            if len(self._buffer) < _FRAME_PREFIX_SIZE + _CHECKSUM_SIZE:
                return frames

            _, version, frame_type, seq, payload_length = struct.unpack(
                _FRAME_PREFIX_FORMAT,
                self._buffer[:_FRAME_PREFIX_SIZE],
            )

            frame_length = _FRAME_PREFIX_SIZE + payload_length + _CHECKSUM_SIZE
            if len(self._buffer) < frame_length:
                return frames

            frame_bytes = bytes(self._buffer[:frame_length])
            del self._buffer[:frame_length]

            if version != VERSION:
                continue

            expected_checksum = checksum8(frame_bytes[len(HEADER) : -1])
            if frame_bytes[-1] != expected_checksum:
                continue

            payload = frame_bytes[_FRAME_PREFIX_SIZE:-1]
            frames.append(RawFrame(frame_type=frame_type, seq=seq, payload=payload))

    def _find_header(self) -> int:
        buffer_bytes = bytes(self._buffer)
        return buffer_bytes.find(HEADER)


def decode_stream_frames(data: bytes, parser: StreamParser) -> Iterable[ControlFrame | FeedbackFrame]:
    """辅助函数：把串口字节流直接解析为高层帧。"""
    for raw_frame in parser.feed(data):
        yield decode_raw_frame(raw_frame)
