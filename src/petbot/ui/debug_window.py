"""叠加检测框的 OpenCV 调试窗口。

OpenCV 不会把点击窗口关闭按钮直接报告给 waitKey，因此每轮都要探测窗口
是否还存在；否则下一帧 imshow 会把已经关掉的窗口重新创建出来。
作者：敕仞
"""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from petbot.config import DebugWindowConfig
from petbot.vision.detector import Detection

ESC_KEY = 27


class DebugWindow:
    """负责画框和窗口生命周期，不关心摄像头或模型。"""

    def __init__(self, config: DebugWindowConfig) -> None:
        self._config = config
        self._open = True
        self._destroyed = False
        cv2.namedWindow(config.title, cv2.WINDOW_AUTOSIZE)

    def render(self, frame: np.ndarray, detections: Sequence[Detection]) -> np.ndarray:
        """返回叠加框后的新图，保留原始帧供后续表情或跟踪使用。"""
        canvas = frame.copy()
        for detection in detections:
            x1, y1, x2, y2 = detection.bbox
            color = self._color_for(detection.kind)
            cv2.rectangle(
                canvas,
                (x1, y1),
                (x2, y2),
                color,
                self._config.box_thickness,
            )

            label = f"{detection.kind} {detection.conf:.2f}"
            if detection.bearing_deg is not None:
                label += f" {detection.bearing_deg:+.0f}°"
            if detection.distance_m is not None:
                label += f" {detection.distance_m:.1f}m"
            (text_width, text_height), _baseline = cv2.getTextSize(
                label,
                cv2.FONT_HERSHEY_SIMPLEX,
                self._config.font_scale,
                self._config.font_thickness,
            )
            text_x = x1 + self._config.label_padding_px
            text_y = y1 + text_height + self._config.label_padding_px
            if text_x + text_width >= canvas.shape[1]:
                text_x = max(0, canvas.shape[1] - text_width)
            text_y = min(text_y, canvas.shape[0] - self._config.label_padding_px)
            cv2.putText(
                canvas,
                label,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                self._config.font_scale,
                self._config.text_color_bgr,
                self._config.font_thickness,
                cv2.LINE_AA,
            )
        return canvas

    def show(self, frame: np.ndarray, detections: Sequence[Detection]) -> bool:
        """渲染并显示一帧；返回 False 表示用户关闭了窗口或按了 Esc。"""
        return self.show_rendered(self.render(frame, detections))

    def show_rendered(self, frame: np.ndarray) -> bool:
        """显示已经画好框的帧；主入口也可以把它同步给浏览器调试台。"""
        if not self._window_visible():
            self._open = False
            return False

        cv2.imshow(self._config.title, frame)
        key = cv2.waitKey(self._config.wait_key_ms) & 0xFF
        if key == ESC_KEY:
            self._open = False
        elif not self._window_visible():
            self._open = False
        return self._open

    def close(self) -> None:
        # 按 Esc 时 _open 已经是 False，但窗口还在，所以清理不能依赖它。
        if self._destroyed:
            return
        self._open = False
        try:
            cv2.destroyWindow(self._config.title)
        except cv2.error:
            # 用户已经手动关闭窗口时再销毁一次会报错，这里属于正常清理路径。
            pass
        finally:
            self._destroyed = True

    def __enter__(self) -> DebugWindow:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _window_visible(self) -> bool:
        try:
            return cv2.getWindowProperty(
                self._config.title, cv2.WND_PROP_VISIBLE
            ) >= 1
        except cv2.error:
            return False

    def _color_for(self, kind: str) -> tuple[int, int, int]:
        if kind == "person":
            return self._config.person_color_bgr
        return self._config.cat_color_bgr
