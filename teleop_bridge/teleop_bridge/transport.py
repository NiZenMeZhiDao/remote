"""串口传输层抽象。"""

import time

try:
    import serial
    from serial import SerialException
except ImportError:  # pragma: no cover - 运行时依赖由 ROS 环境提供
    serial = None

    class SerialException(Exception):
        """pyserial 不可用时的占位异常类型。"""


class SerialEndpoint:
    """
    带自动重连能力的串口端点。

    控制链路固定跑在串口上，节点通过 100Hz 定时器驱动本类收发，
    即使串口暂时掉线，节点也不会直接崩溃，而是等待下次循环自动重连。
    """

    def __init__(
        self,
        port: str,
        baudrate: int,
        read_chunk_size: int = 1024,
        reopen_interval_sec: float = 1.0,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._read_chunk_size = read_chunk_size
        self._reopen_interval_sec = reopen_interval_sec
        self._serial = None
        self._last_open_attempt = 0.0

    @property
    def is_open(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def write(self, payload: bytes) -> int:
        self._ensure_open()
        if not self.is_open:
            raise OSError(f"串口 {self._port} 当前未连接或暂不可用。")

        try:
            return self._serial.write(payload)
        except SerialException as exc:
            self.close()
            raise OSError(f"串口写入失败: {exc}") from exc

    def read_available(self) -> bytes:
        self._ensure_open()
        if not self.is_open:
            raise OSError(f"串口 {self._port} 当前未连接或暂不可用。")

        try:
            waiting = int(self._serial.in_waiting)
            if waiting <= 0:
                return b""
            return self._serial.read(min(waiting, self._read_chunk_size))
        except SerialException as exc:
            self.close()
            raise OSError(f"串口读取失败: {exc}") from exc

    def close(self) -> None:
        if self._serial is None:
            return

        try:
            self._serial.close()
        finally:
            self._serial = None

    def _ensure_open(self) -> None:
        if serial is None:
            raise RuntimeError(
                "当前环境缺少 pyserial，请先安装 python3-serial 或 pip install pyserial。"
            )
        if self.is_open:
            return

        now = time.monotonic()
        if now - self._last_open_attempt < self._reopen_interval_sec:
            return

        self._last_open_attempt = now
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=0.0,
                write_timeout=0.0,
            )
        except SerialException:
            self._serial = None
