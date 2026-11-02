"""摄像头采集与索引自动探测。

不写死 COM 号或固定摄像头索引：先试配置里的首选索引，再逐个探测，
只有真正读到一帧才认定设备可用，避免 isOpened() 的假成功。
作者：敕仞
"""

from __future__ import annotations

import logging
import sys

import cv2
import numpy as np

from petbot import PetBotError
from petbot.config import CameraConfig

LOGGER = logging.getLogger(__name__)


class CameraError(PetBotError):
    """摄像头无法打开或读取。"""


class Camera:
    """已打开的摄像头；每帧返回 OpenCV 的 BGR ndarray。"""

    def __init__(
        self,
        capture: cv2.VideoCapture,
        index: int,
        width: int,
        height: int,
    ) -> None:
        self._capture: cv2.VideoCapture | None = capture
        self._index = index
        self._width = width
        self._height = height

    @classmethod
    def open(cls, config: CameraConfig) -> Camera:
        """按配置探测并打开第一个可用的摄像头。"""
        indices = _candidate_indices(config)

        for index in indices:
            LOGGER.debug("探测摄像头索引 %d", index)
            capture = _create_capture(index)
            if not capture.isOpened():
                capture.release()
                continue

            # 某些驱动会成功打开设备却无法出帧，所以探测阶段必须实际读一帧。
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
            capture.set(cv2.CAP_PROP_FPS, config.fps)
            ok, frame = capture.read()
            if not ok or frame is None:
                capture.release()
                continue

            height, width = frame.shape[:2]
            LOGGER.info(
                "摄像头已打开：索引 %d，实际画面 %dx%d",
                index,
                width,
                height,
            )
            return cls(capture, index, width, height)

        tried = "、".join(str(index) for index in indices)
        raise CameraError(
            f"未找到可用摄像头。已尝试索引 {tried}。"
            "请确认摄像头已连接且没有被其他程序占用，"
            "或检查 config/default.yaml 中的 camera.preferred_index 与 camera.probe_max_index。"
        )

    @property
    def index(self) -> int:
        return self._index

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def read(self) -> np.ndarray:
        """读取一帧；失败时直接抛出，避免上层拿到空画面继续运行。"""
        if self._capture is None:
            raise CameraError("摄像头已经释放，不能再读取画面。")

        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise CameraError(
                "摄像头读取画面失败。设备可能已断开，或被其他程序抢占；"
                "请重新连接摄像头后重启程序。"
            )
        return frame

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def __enter__(self) -> Camera:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def _candidate_indices(config: CameraConfig) -> list[int]:
    """首选索引优先，再按 0..probe_max_index 的顺序补齐。"""
    ordered: list[int] = []
    if config.preferred_index is not None:
        ordered.append(config.preferred_index)
    ordered.extend(range(config.probe_max_index + 1))

    seen: set[int] = set()
    result: list[int] = []
    for index in ordered:
        if index not in seen:
            seen.add(index)
            result.append(index)
    return result


def _create_capture(index: int) -> cv2.VideoCapture:
    # Windows 上 DirectShow 的启动延迟更低；Linux ARM 沿用 OpenCV 默认后端。
    if sys.platform == "win32":
        return cv2.VideoCapture(index, cv2.CAP_DSHOW)
    return cv2.VideoCapture(index)
