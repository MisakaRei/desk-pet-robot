"""主控与 ESP32 之间的串口帧协议。

帧格式：
AA 55 | 版本(1) | 类型(1) | 序号(2,小端) | 载荷长度(2,小端) | 载荷 | CRC16(2,小端)

CRC 使用 CRC-16/CCITT-FALSE（初值 0xFFFF、多项式 0x1021），覆盖“版本号
到载荷末尾”。串口是字节流，解析器必须能跨 recv 边界拼帧，所以单独保留
一个带缓冲区的 FrameParser。
作者：敕仞
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

FRAME_HEADER = b"\xAA\x55"
PROTOCOL_VERSION = 1
_FIXED_BODY_SIZE = 6  # 版本 + 类型 + 序号(2) + 载荷长度(2)
_MIN_FRAME_SIZE = 2 + _FIXED_BODY_SIZE + 2
_MAX_PAYLOAD_SIZE = 0xFFFF


class ProtocolError(ValueError):
    """帧格式、CRC 或载荷长度不合法。"""


class MessageType(IntEnum):
    BASE_VELOCITY = 0x01
    GIMBAL_ANGLE = 0x02
    EMOTION = 0x03
    STATUS_REPORT = 0x10


class EmotionId(IntEnum):
    CALM = 0
    CURIOUS = 1
    HAPPY = 2


_EMOTION_TO_ID = {
    "calm": EmotionId.CALM,
    "curious": EmotionId.CURIOUS,
    "happy": EmotionId.HAPPY,
}
_ID_TO_EMOTION = {value: key for key, value in _EMOTION_TO_ID.items()}


@dataclass(frozen=True, slots=True)
class Frame:
    version: int
    msg_type: int
    seq: int
    payload: bytes


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE；不反射，初值 0xFFFF，结果不异或。"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def encode_frame(
    msg_type: int | MessageType,
    seq: int,
    payload: bytes = b"",
    *,
    version: int = PROTOCOL_VERSION,
) -> bytes:
    if not 0 <= version <= 0xFF:
        raise ProtocolError(f"版本号超出 1 字节范围：{version}")
    if not 0 <= int(msg_type) <= 0xFF:
        raise ProtocolError(f"消息类型超出 1 字节范围：{msg_type}")
    if not 0 <= seq <= 0xFFFF:
        raise ProtocolError(f"序号超出 2 字节范围：{seq}")
    if len(payload) > _MAX_PAYLOAD_SIZE:
        raise ProtocolError(f"载荷过长：{len(payload)} 字节")

    body = struct.pack("<BBHH", version, int(msg_type), seq, len(payload)) + payload
    return FRAME_HEADER + body + struct.pack("<H", crc16_ccitt(body))


def decode_frame(data: bytes) -> Frame:
    """解析恰好一帧；用于测试和单帧调试，不用于串口流。"""
    if len(data) < _MIN_FRAME_SIZE or not data.startswith(FRAME_HEADER):
        raise ProtocolError("数据缺少 AA 55 帧头或长度不足")

    payload_length = int.from_bytes(data[6:8], "little")
    total_length = _MIN_FRAME_SIZE + payload_length
    if len(data) != total_length:
        raise ProtocolError(
            f"帧长不匹配：长度字段推导为 {total_length}，实际 {len(data)}"
        )

    body = data[2 : 8 + payload_length]
    actual_crc = int.from_bytes(data[-2:], "little")
    if crc16_ccitt(body) != actual_crc:
        raise ProtocolError("CRC 校验失败")

    return Frame(
        version=data[2],
        msg_type=data[3],
        seq=int.from_bytes(data[4:6], "little"),
        payload=data[8 : 8 + payload_length],
    )


class FrameParser:
    """增量帧解析器，可处理任意切分的 TCP/串口字节流。"""

    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes) -> list[Frame]:
        self._buffer.extend(data)
        frames: list[Frame] = []

        while True:
            header_index = self._buffer.find(FRAME_HEADER)
            if header_index < 0:
                # 半截帧头可能在下一个数据块里，所以保留末尾的 0xAA。
                if self._buffer.endswith(b"\xAA"):
                    del self._buffer[:-1]
                else:
                    self._buffer.clear()
                break

            if header_index > 0:
                del self._buffer[:header_index]

            if len(self._buffer) < _MIN_FRAME_SIZE:
                break

            version = self._buffer[2]
            msg_type = self._buffer[3]
            seq = int.from_bytes(self._buffer[4:6], "little")
            payload_length = int.from_bytes(self._buffer[6:8], "little")
            total_length = _MIN_FRAME_SIZE + payload_length
            if len(self._buffer) < total_length:
                break

            body = bytes(self._buffer[2 : 8 + payload_length])
            expected_crc = crc16_ccitt(body)
            actual_crc = int.from_bytes(
                self._buffer[8 + payload_length : total_length], "little"
            )
            if actual_crc != expected_crc:
                # 丢掉开头的一个字节继续找下一个 AA 55，避免错误帧卡住解析。
                del self._buffer[0]
                continue

            frames.append(
                Frame(
                    version=version,
                    msg_type=msg_type,
                    seq=seq,
                    payload=bytes(self._buffer[8 : 8 + payload_length]),
                )
            )
            del self._buffer[:total_length]

        return frames


def encode_velocity(linear_mps: float, angular_radps: float) -> bytes:
    """0x01 底盘速度：两个 float32 小端。"""
    return struct.pack("<ff", float(linear_mps), float(angular_radps))


def decode_velocity(payload: bytes) -> tuple[float, float]:
    if len(payload) != 8:
        raise ProtocolError(f"底盘速度载荷应为 8 字节，实际 {len(payload)}")
    return struct.unpack("<ff", payload)


def encode_gimbal(yaw_deg: float, pitch_deg: float) -> bytes:
    """0x02 云台角度：两个 int16 小端，单位 0.01 度。"""
    yaw = _to_centidegrees(yaw_deg)
    pitch = _to_centidegrees(pitch_deg)
    return struct.pack("<hh", yaw, pitch)


def decode_gimbal(payload: bytes) -> tuple[float, float]:
    if len(payload) != 4:
        raise ProtocolError(f"云台角度载荷应为 4 字节，实际 {len(payload)}")
    yaw, pitch = struct.unpack("<hh", payload)
    return yaw / 100.0, pitch / 100.0


def encode_emotion(emotion: str) -> bytes:
    """0x03 表情：1 字节情绪编号。"""
    try:
        return bytes([int(_EMOTION_TO_ID[emotion])])
    except KeyError as exc:
        raise ProtocolError(f"未知情绪：{emotion!r}") from exc


def decode_emotion(payload: bytes) -> str:
    if len(payload) != 1:
        raise ProtocolError(f"表情载荷应为 1 字节，实际 {len(payload)}")
    try:
        return _ID_TO_EMOTION[EmotionId(payload[0])]
    except ValueError as exc:
        raise ProtocolError(f"未知情绪编号：{payload[0]}") from exc


def _to_centidegrees(degrees: float) -> int:
    value = int(round(float(degrees) * 100.0))
    if not -32768 <= value <= 32767:
        raise ProtocolError(f"角度超出 int16 的 0.01 度范围：{degrees}")
    return value
