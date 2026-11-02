"""无硬件时的串口回环。

dry-run 不打开任何串口，只把即将写出的完整帧按十六进制打印到日志，
这样接上 ESP32 之前也能核对协议、序号和 CRC。
作者：敕仞
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

LOGGER = logging.getLogger(__name__)


class LoopbackLink:
    def __init__(self) -> None:
        self.sent_count = 0
        self.last_frame_hex: str | None = None

    def send(self, frame: bytes) -> None:
        self.send_many([frame])

    def send_many(self, frames: Sequence[bytes]) -> None:
        if not frames:
            return
        first = self.sent_count + 1
        self.sent_count += len(frames)
        self.last_frame_hex = frames[-1].hex(" ").upper()
        # 一个控制周期有三帧；合成一条日志，避免 6 行/秒把其它日志挤掉。
        frame_text = "\n".join(
            f"  {frame.hex(' ').upper()}" for frame in frames
        )
        LOGGER.info(
            "[串口 dry-run] TX #%d-%d\n%s",
            first,
            self.sent_count,
            frame_text,
        )

    def read_available(self) -> bytes:
        return b""

    def close(self) -> None:
        return
