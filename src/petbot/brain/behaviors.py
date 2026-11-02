"""把状态机状态翻译成底盘、云台和表情可消费的指令。

这一层不直接碰串口或窗口，只产出不可变的 BehaviorCommand，
后续阶段可以分别送给仿真底盘、ESP32 和表情渲染。
作者：敕仞
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from petbot.brain.state_machine import PetState
from petbot.config import BrainConfig
from petbot.vision.detector import Detection


@dataclass(frozen=True, slots=True)
class BehaviorCommand:
    state: PetState
    linear_mps: float
    angular_radps: float
    gimbal_yaw_deg: float
    gimbal_pitch_deg: float
    emotion: str
    target: Detection | None


def build_behavior(
    state: PetState,
    target: Detection | None,
    config: BrainConfig,
) -> BehaviorCommand:
    if state is PetState.IDLE or target is None or target.bearing_deg is None:
        return BehaviorCommand(
            state=state,
            linear_mps=0.0,
            angular_radps=0.0,
            gimbal_yaw_deg=0.0,
            gimbal_pitch_deg=0.0,
            emotion="calm",
            target=None,
        )

    bearing = float(target.bearing_deg)
    angular = _turn_toward(bearing, config)
    gimbal_yaw = max(-config.gimbal_limit_deg, min(config.gimbal_limit_deg, bearing))

    if state is PetState.APPROACH:
        return BehaviorCommand(
            state=state,
            linear_mps=config.approach_speed_mps,
            angular_radps=angular,
            gimbal_yaw_deg=gimbal_yaw,
            gimbal_pitch_deg=0.0,
            emotion="happy",
            target=target,
        )

    if state is PetState.BACKOFF:
        return BehaviorCommand(
            state=state,
            linear_mps=-config.backoff_speed_mps,
            angular_radps=angular,
            gimbal_yaw_deg=gimbal_yaw,
            gimbal_pitch_deg=0.0,
            emotion="calm",
            target=target,
        )

    return BehaviorCommand(
        state=PetState.WATCH,
        linear_mps=0.0,
        angular_radps=angular,
        gimbal_yaw_deg=gimbal_yaw,
        gimbal_pitch_deg=0.0,
        emotion="curious",
        target=target,
    )


def _turn_toward(bearing_deg: float, config: BrainConfig) -> float:
    if abs(bearing_deg) < config.turn_deadband_deg:
        return 0.0
    wanted = math.radians(bearing_deg) * config.turn_gain
    limit = config.max_turn_rate_rad_s
    return max(-limit, min(limit, wanted))
