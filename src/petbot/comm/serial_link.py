"""pyserial 发送与按 VID/PID 自动查找端口。

不写死 COM 号：启动时用 pyserial 的 list_ports 查找配置中的 VID/PID。
dry-run 模式由 loopback.py 接管，不会碰真实串口。
作者：敕仞
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

from serial import Serial, SerialException
from serial.tools import list_ports

from petbot import PetBotError
from petbot.comm.loopback import LoopbackLink
from petbot.config import SerialConfig, SerialPortId

LOGGER = logging.getLogger(__name__)


class SerialLinkError(PetBotError):
    """找不到匹配端口、打开失败或读写失败。"""


class PacketLink(Protocol):
    sent_count: int
    last_frame_hex: str | None

    def send(self, frame: bytes) -> None: ...

    def send_many(self, frames: Sequence[bytes]) -> None: ...

    def read_available(self) -> bytes: ...

    def close(self) -> None: ...


def create_link(config: SerialConfig) -> PacketLink:
    if config.dry_run:
        LOGGER.info("串口处于 dry-run 模式，帧只打印，不打开硬件。")
        return LoopbackLink()
    return SerialLink(config)


class SerialLink:
    def __init__(self, config: SerialConfig) -> None:
        port = _find_port(config.vid_pid_candidates)
        try:
            self._serial = Serial(
                port=port.device,
                baudrate=config.baudrate,
                timeout=config.read_timeout_s,
                write_timeout=config.write_timeout_s,
            )
        except SerialException as exc:
            raise SerialLinkError(
                f"打开串口 {port.device} 失败：{exc}"
            ) from exc

        self.sent_count = 0
        self.last_frame_hex: str | None = None
        self._port_name = port.device
        LOGGER.info(
            "串口已连接：%s（%s，VID:PID=%04X:%04X）",
            port.device,
            port.description or "unknown",
            port.vid or 0,
            port.pid or 0,
        )

    def send(self, frame: bytes) -> None:
        self.send_many([frame])

    def send_many(self, frames: Sequence[bytes]) -> None:
        if not frames:
            return
        try:
            self._serial.write(b"".join(frames))
            self._serial.flush()
        except SerialException as exc:
            raise SerialLinkError(
                f"串口 {self._port_name} 写入失败：{exc}"
            ) from exc

        self.sent_count += len(frames)
        self.last_frame_hex = frames[-1].hex(" ").upper()

    def read_available(self) -> bytes:
        try:
            waiting = self._serial.in_waiting
            if waiting <= 0:
                return b""
            return self._serial.read(waiting)
        except SerialException as exc:
            raise SerialLinkError(
                f"串口 {self._port_name} 读取失败：{exc}"
            ) from exc

    def close(self) -> None:
        if getattr(self, "_serial", None) is not None:
            self._serial.close()
            self._serial = None


def _find_port(candidates: tuple[SerialPortId, ...]):
    ports = list(list_ports.comports())
    for candidate in candidates:
        for port in ports:
            if port.vid == candidate.vid and port.pid == candidate.pid:
                return port

    wanted = "、".join(
        f"{candidate.vid:04X}:{candidate.pid:04X}"
        for candidate in candidates
    )
    found = "、".join(
        f"{port.device}({port.vid or 0:04X}:{port.pid or 0:04X})"
        for port in ports
    ) or "未发现任何串口"
    raise SerialLinkError(
        f"未找到匹配 VID/PID 的串口。期望：{wanted}；当前：{found}。"
        "请检查 USB 连接或 config/default.yaml 中的 serial.vid_pid_candidates。"
    )
