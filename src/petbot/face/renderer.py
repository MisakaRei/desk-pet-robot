"""240×280 的 pygame 表情窗口。

眼睛在内部 2 倍画布上绘制后再缩小，保证小窗口里的边缘仍然平滑；
窗口只负责表现，不读取摄像头，也不决定情绪，情绪由 behavior 层给出。
作者：敕仞
"""

from __future__ import annotations

import logging
import math
import os

# pygame 默认会在导入时打印版本横幅，调试台的日志已经足够，不需要额外噪声。
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np
import pygame

from petbot import PetBotError
from petbot.brain.behaviors import BehaviorCommand
from petbot.brain.state_machine import PetState
from petbot.config import FaceConfig
from petbot.face.eyes import EyePose, EyesAnimator

LOGGER = logging.getLogger(__name__)

_SUPERSAMPLE = 2
_EYE_CENTER_Y_RATIO = 0.46
_OUTLINE_WIDTH_PX = 2
_GLINT_RATIO = 0.27
_CURIOUS_PUPIL_SCALE = 1.18
_CALM_LID_TOP_RATIO = 0.08
_CURIOUS_LID_TOP_RATIO = 0.015
_HAPPY_EYE_HEIGHT_RATIO = 0.62
_BROW_OFFSET_PX = 13


class FaceError(PetBotError):
    """pygame 显示窗口无法创建或渲染。"""


class FaceWindow:
    def __init__(self, config: FaceConfig) -> None:
        self._config = config
        self._eyes = EyesAnimator(config)
        self._last_draw = -math.inf
        self._closed = False
        self._width = config.width
        self._height = config.height

        try:
            pygame.display.init()
            self._screen = pygame.display.set_mode((self._width, self._height))
            pygame.display.set_caption(config.title)
        except pygame.error as exc:
            pygame.display.quit()
            raise FaceError(f"无法创建表情窗口：{exc}") from exc

        self._canvas = pygame.Surface(
            (self._width * _SUPERSAMPLE, self._height * _SUPERSAMPLE)
        )

    def update(self, command: BehaviorCommand, now: float) -> bool:
        """处理事件并绘制一帧；返回 False 表示窗口被关闭。"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return False

        interval = 1.0 / self._config.fps
        if now - self._last_draw < interval:
            return True

        bearing: float | None = None
        if (
            command.state is not PetState.IDLE
            and command.target is not None
            and command.gimbal_yaw_deg is not None
        ):
            bearing = command.gimbal_yaw_deg

        pose = self._eyes.update(now, bearing, command.emotion)
        self._draw(pose)
        pygame.display.flip()
        self._last_draw = now
        return True

    def snapshot_bgr(self) -> np.ndarray:
        """把当前窗口内容转成 BGR，供调试台 MJPEG 预览。"""
        raw = pygame.image.tobytes(self._screen, "RGB")
        rgb = np.frombuffer(raw, dtype=np.uint8).reshape(
            (self._height, self._width, 3)
        )
        return np.ascontiguousarray(rgb[:, :, ::-1])

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        pygame.display.quit()

    def __enter__(self) -> FaceWindow:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _draw(self, pose: EyePose) -> None:
        config = self._config
        eye = config.eye
        canvas = self._canvas
        width = self._width * _SUPERSAMPLE
        height = self._height * _SUPERSAMPLE

        canvas.fill(config.background_rgb)
        center_x = width // 2
        eye_y = int(height * _EYE_CENTER_Y_RATIO)
        radius = eye.radius_px * _SUPERSAMPLE
        pupil_radius = eye.pupil_radius_px * _SUPERSAMPLE
        look = int(round(pose.look_x_px * _SUPERSAMPLE))
        half_spacing = eye.spacing_px * _SUPERSAMPLE // 2

        pupil_scale = (
            _CURIOUS_PUPIL_SCALE
            if pose.emotion == "curious"
            else 1.0
        )
        top_lid_ratio = (
            _CURIOUS_LID_TOP_RATIO
            if pose.emotion == "curious"
            else _CALM_LID_TOP_RATIO
        )

        happy = pose.emotion == "happy"
        half_height = (
            int(round(radius * _HAPPY_EYE_HEIGHT_RATIO))
            if happy
            else radius
        )

        for direction in (-1, 1):
            eye_x = center_x + direction * half_spacing
            if happy:
                # 开心时把眼睛压成横向椭圆，保留瞳孔追视，但形成明显的眯眼笑。
                eye_rect = (
                    eye_x - radius,
                    eye_y - half_height,
                    radius * 2,
                    half_height * 2,
                )
                pygame.draw.ellipse(canvas, config.eye_rgb, eye_rect)
                pygame.draw.ellipse(
                    canvas,
                    config.accent_rgb,
                    eye_rect,
                    max(1, _SUPERSAMPLE),
                )
            else:
                pygame.draw.circle(
                    canvas, config.eye_rgb, (eye_x, eye_y), radius
                )
                pygame.draw.circle(
                    canvas,
                    config.accent_rgb,
                    (eye_x, eye_y),
                    radius,
                    max(1, _SUPERSAMPLE),
                )

            pupil_x = eye_x + look
            pygame.draw.circle(
                canvas,
                config.pupil_rgb,
                (pupil_x, eye_y),
                int(round(pupil_radius * pupil_scale)),
            )
            glint_radius = max(2, int(round(pupil_radius * _GLINT_RATIO)))
            pygame.draw.circle(
                canvas,
                config.eye_rgb,
                (
                    pupil_x - glint_radius,
                    eye_y - glint_radius * 2,
                ),
                glint_radius,
            )

            top_cover_ratio = 0.0 if happy else top_lid_ratio
            top_cover = int(
                round(
                    (half_height * 2)
                    * min(1.0, top_cover_ratio + pose.blink)
                )
            )
            if top_cover > 0:
                pygame.draw.rect(
                    canvas,
                    config.background_rgb,
                    (
                        eye_x - radius,
                        eye_y - half_height,
                        radius * 2,
                        top_cover,
                    ),
                )

            if pose.blink > 0.72:
                pygame.draw.line(
                    canvas,
                    config.accent_rgb,
                    (eye_x - radius + 2, eye_y),
                    (eye_x + radius - 2, eye_y),
                    max(1, _SUPERSAMPLE),
                )

            if pose.emotion == "curious":
                brow_y = eye_y - radius - _BROW_OFFSET_PX * _SUPERSAMPLE
                lift = _SUPERSAMPLE * 3 if direction == 1 else 0
                pygame.draw.line(
                    canvas,
                    config.accent_rgb,
                    (eye_x - radius // 2, brow_y + lift),
                    (eye_x + radius // 2, brow_y - _SUPERSAMPLE * 5 + lift),
                    max(1, _SUPERSAMPLE * 2),
                )

        pygame.transform.smoothscale(
            canvas, (self._width, self._height), self._screen
        )
