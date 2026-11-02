"""Ultralytics YOLO 检测封装。

检测层只负责把模型输出整理成统一的 Detection；方位角和距离属于跟踪层，
因此这里先留空，等阶段 3 由跟踪器补齐。
作者：敕仞
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Literal, Sequence, cast

import numpy as np

from petbot import PetBotError
from petbot.config import DetectorConfig

LOGGER = logging.getLogger(__name__)

Kind = Literal["person", "cat"]
BBox = tuple[int, int, int, int]


class DetectorError(PetBotError):
    """权重缺失、依赖缺失或推理失败。"""


@dataclass(frozen=True, slots=True)
class Detection:
    """一次检测结果。

    方位角和距离由跟踪器在下一阶段计算；检测阶段先保留字段为 None，
    这样契约从一开始固定，不会因后续加入跟踪而改变调用方结构。
    """

    kind: Kind
    bbox: BBox
    conf: float
    ts: float
    bearing_deg: float | None = None
    distance_m: float | None = None


class Detector:
    """把 YOLO 推理结果转换成与框架无关的 Detection 列表。"""

    def __init__(self, config: DetectorConfig) -> None:
        self._config = config
        self._target_by_id: dict[int, Kind] = {}
        for kind_name, class_id in config.target_classes.items():
            self._target_by_id[class_id] = cast(Kind, kind_name)

        if not config.model_path.is_file():
            raise DetectorError(
                f"未找到 YOLO 权重：{config.model_path}。"
                "请把权重放进 models/（该目录内容已被 .gitignore 排除），"
                "或修改 config/default.yaml 中的 detector.model_path。"
            )

        # 延迟导入：没有摄像头时入口能先给出清晰的摄像头错误，
        # 也避免测试 Detection 数据结构时加载整个 PyTorch。
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise DetectorError(
                "缺少 ultralytics 依赖，请在项目虚拟环境中执行 "
                "python -m pip install -e ."
            ) from exc

        try:
            self._model: Any = YOLO(str(config.model_path))
        except Exception as exc:
            raise DetectorError(
                f"加载 YOLO 权重失败：{config.model_path}（{exc}）"
            ) from exc

        LOGGER.info(
            "YOLO 模型已加载：%s（device=%s）",
            config.model_path.name,
            config.device,
        )

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """对一帧 BGR 图像做推理；同一帧内的检测共享同一个时间戳。"""
        # 使用单调时钟，系统时间被校准时也不会影响后续三秒超时判断。
        ts = time.monotonic()
        try:
            results = self._model.predict(
                source=frame,
                imgsz=self._config.image_size,
                conf=self._config.confidence_threshold,
                iou=self._config.iou_threshold,
                classes=sorted(self._target_by_id),
                device=self._config.device,
                verbose=False,
            )
        except Exception as exc:
            raise DetectorError(f"YOLO 推理失败：{exc}") from exc

        if not results:
            return []

        boxes = results[0].boxes
        if boxes is None:
            return []

        frame_height, frame_width = frame.shape[:2]
        detections: list[Detection] = []
        for box in boxes:
            class_id = int(box.cls.item())
            kind = self._target_by_id.get(class_id)
            if kind is None:
                continue

            bbox = _clamp_bbox(
                box.xyxy[0].tolist(),
                frame_width=frame_width,
                frame_height=frame_height,
            )
            if bbox is None:
                continue

            detections.append(
                Detection(
                    kind=kind,
                    bbox=bbox,
                    conf=float(box.conf.item()),
                    ts=ts,
                )
            )

        return detections


def _clamp_bbox(
    values: Sequence[float],
    *,
    frame_width: int,
    frame_height: int,
) -> BBox | None:
    """YOLO 的框可能越过画面边界，先裁到帧内再交给后续模块。"""
    x1, y1, x2, y2 = (int(round(value)) for value in values)
    x1 = max(0, min(x1, frame_width - 1))
    y1 = max(0, min(y1, frame_height - 1))
    x2 = max(0, min(x2, frame_width - 1))
    y2 = max(0, min(y2, frame_height - 1))

    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)
