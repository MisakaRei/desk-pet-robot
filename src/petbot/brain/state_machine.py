"""四状态行为状态机。

状态只由“当前是否看到目标”和“目标距离”驱动，把时间、阈值和方向判断
留在这一层，表情、底盘和串口各自只消费结果。目标短暂丢失时会保留最后
一个目标，给连续动作留出三秒缓冲，而不是一帧没检到就慌乱回中。
作者：敕仞
"""

from __future__ import annotations

from enum import StrEnum
from typing import Sequence

from petbot.config import BrainConfig
from petbot.vision.detector import Detection


class PetState(StrEnum):
    IDLE = "IDLE"
    WATCH = "WATCH"
    APPROACH = "APPROACH"
    BACKOFF = "BACKOFF"


class StateMachine:
    def __init__(self, config: BrainConfig) -> None:
        self._config = config
        self._state = PetState.IDLE
        self._last_seen: float | None = None
        self._last_target: Detection | None = None

    @property
    def state(self) -> PetState:
        return self._state

    @property
    def last_target(self) -> Detection | None:
        """目标丢失缓冲期内仍返回最后看到的目标，方便眼睛保持朝向。"""
        return self._last_target

    def update(self, target: Detection | None, now: float) -> PetState:
        if target is None or target.distance_m is None:
            if self._last_seen is None:
                self._state = PetState.IDLE
            elif now - self._last_seen >= self._config.lost_timeout_s:
                self._state = PetState.IDLE
                self._last_seen = None
                self._last_target = None
            else:
                # 丢失目标时先停下并保持注视，等满三秒再回 IDLE；
                # 不能带着最后已知距离继续靠近，否则会追着空气走。
                self._state = PetState.WATCH
            return self._state

        self._last_seen = now
        self._last_target = target
        distance = float(target.distance_m)

        if self._state is PetState.IDLE:
            self._state = PetState.WATCH
        elif self._state is PetState.WATCH:
            if distance > self._config.approach_distance_m:
                self._state = PetState.APPROACH
            elif distance < self._config.backoff_distance_m:
                self._state = PetState.BACKOFF
        elif self._state is PetState.APPROACH:
            if distance < self._config.backoff_distance_m:
                self._state = PetState.BACKOFF
            elif distance <= self._config.approach_distance_m:
                self._state = PetState.WATCH
        elif self._state is PetState.BACKOFF:
            # 回到安全距离先停一下，不立刻反向追过去，避免在阈值附近来回抖。
            if distance >= self._config.backoff_distance_m:
                self._state = PetState.WATCH

        return self._state


def select_primary_target(
    detections: Sequence[Detection],
    kind: str,
) -> Detection | None:
    """多个同类目标时选最近的；距离缺失的目标不参与行为决策。"""
    candidates = [
        detection
        for detection in detections
        if detection.kind == kind and detection.distance_m is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda detection: float(detection.distance_m))
