"""串口协议编解码测试。

协议是跨 MCU 的边界，CRC、端序和分块解析一旦写错，
在 PC 上看起来正常的逻辑到了板子上就会变成随机故障。
作者：敕仞
"""

from __future__ import annotations

import pytest

from petbot.comm.protocol import (
    FRAME_HEADER,
    EmotionId,
    FrameParser,
    MessageType,
    ProtocolError,
    crc16_ccitt,
    decode_emotion,
    decode_frame,
    decode_gimbal,
    decode_velocity,
    encode_emotion,
    encode_frame,
    encode_gimbal,
    encode_velocity,
)


def test_crc_ccitt_reference_vector() -> None:
    # CRC-16/CCITT-FALSE 的标准测试向量。
    assert crc16_ccitt(b"123456789") == 0x29B1


@pytest.mark.parametrize("message_type", list(MessageType))
def test_frame_roundtrip_for_every_message_type(message_type: MessageType) -> None:
    payload = bytes([0x01, 0x02, 0x03])
    encoded = encode_frame(message_type, seq=42, payload=payload)
    assert encoded.startswith(FRAME_HEADER)

    frame = decode_frame(encoded)
    assert frame.version == 1
    assert frame.msg_type == int(message_type)
    assert frame.seq == 42
    assert frame.payload == payload


def test_frame_parser_handles_split_and_batched_input() -> None:
    first = encode_frame(MessageType.BASE_VELOCITY, seq=1, payload=encode_velocity(0.1, 0.2))
    second = encode_frame(MessageType.EMOTION, seq=2, payload=encode_emotion("happy"))

    parser = FrameParser()
    assert parser.feed(first[:3]) == []
    assert parser.feed(first[3:] + second) == [
        decode_frame(first),
        decode_frame(second),
    ]
    assert parser.buffered_bytes == 0


def test_frame_parser_resynchronizes_after_bad_crc() -> None:
    broken = bytearray(encode_frame(MessageType.GIMBAL_ANGLE, seq=7, payload=encode_gimbal(1.0, 2.0)))
    broken[-1] ^= 0xFF
    good = encode_frame(MessageType.EMOTION, seq=8, payload=encode_emotion("calm"))

    parser = FrameParser()
    frames = parser.feed(bytes(broken) + good)
    assert [frame.seq for frame in frames] == [8]
    assert parser.buffered_bytes == 0


def test_velocity_payload_roundtrip() -> None:
    linear, angular = decode_velocity(encode_velocity(0.15, -0.8))
    assert linear == pytest.approx(0.15)
    assert angular == pytest.approx(-0.8)


def test_gimbal_payload_roundtrip() -> None:
    yaw, pitch = decode_gimbal(encode_gimbal(-12.34, 5.67))
    assert yaw == pytest.approx(-12.34)
    assert pitch == pytest.approx(5.67)


def test_emotion_payload_roundtrip() -> None:
    for name in ("calm", "curious", "happy"):
        assert decode_emotion(encode_emotion(name)) == name


def test_unknown_emotion_is_rejected() -> None:
    with pytest.raises(ProtocolError):
        encode_emotion("angry")


def test_sequence_wrap_boundaries() -> None:
    for seq in (0, 0xFFFF):
        assert decode_frame(
            encode_frame(MessageType.STATUS_REPORT, seq=seq)
        ).seq == seq


def test_decode_frame_rejects_trailing_bytes() -> None:
    encoded = encode_frame(MessageType.STATUS_REPORT, seq=3)
    with pytest.raises(ProtocolError):
        decode_frame(encoded + b"\x00")
