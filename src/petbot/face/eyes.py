"""眼睛的追视与眨眼状态。

把随时间变化的部分从绘制代码里拆出来，页面和原生窗口只需要消费
EyePose，不用各自维护一套随机眨眼计时器。
作者：敕仞
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from petbot.config import FaceConfig


@dataclass(frozen=True, slots=True)
class EyePose:
    look_x_px: float
    blink: float
    emotion: str


class EyesAnimator:
    def __init__(self, config: FaceConfig) -> None:
        self._config = config
        self._eye = config.eye
        self._random = random.Random()
        self._look_x_px = 0.0
        self._blink_started: float | None = None
        self._next_blink: float | None = None

    def update(
        self,
        now: float,
        bearing_deg: float | None,
        emotion: str,
    ) -> EyePose:
        target_ratio = 0.0
        if bearing_deg is not None:
            normalized = bearing_deg / self._eye.gaze_range_deg
            target_ratio = max(-1.0, min(1.0, normalized))
        target_px = target_ratio * self._eye.max_look_offset_px
        self._look_x_px += (
            target_px - self._look_x_px
        ) * self._eye.follow_smoothing

        self._advance_blink(now)
        return EyePose(
            look_x_px=self._look_x_px,
            blink=self._blink_value(now),
            emotion=emotion,
        )

    def _advance_blink(self, now: float) -> None:
        if self._next_blink is None:
            self._next_blink = now + self._random.uniform(
                self._eye.blink_min_interval_s,
                self._eye.blink_max_interval_s,
            )

        if self._blink_started is None and now >= self._next_blink:
            self._blink_started = now
            self._next_blink = None
            return

        if self._blink_started is not None:
            progress = (now - self._blink_started) / self._eye.blink_duration_s
            if progress >= 1.0:
                self._blink_started = None
                self._next_blink = now + self._random.uniform(
                    self._eye.blink_min_interval_s,
                    self._eye.blink_max_interval_s,
                )

    def _blink_value(self, now: float) -> float:
        if self._blink_started is None:
            return 0.0
        progress = (now - self._blink_started) / self._eye.blink_duration_s
        if progress <= 0.0 or progress >= 1.0:
            return 0.0
        # 正弦曲线让闭眼和睁眼都有一点缓动，不会像开关一样生硬。
        return math.sin(math.pi * progress)
