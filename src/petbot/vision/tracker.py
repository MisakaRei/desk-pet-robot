"""轻量 IoU 跟踪、方位角和距离粗估。

训练/部署都拿不到真实景深，所以距离不是测量值，而是“像素焦距 × 假设身高
÷ 目标框高度”的估算。这里保留假设条件并全部从配置读取，行为层只把它
当作数量级参考，不能用于精确的避障或导航。
作者：敕仞
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Sequence

from petbot.config import TrackingConfig
from petbot.vision.detector import BBox, Detection, Kind


@dataclass(slots=True)
class _Track:
    kind: Kind
    bbox: BBox
    conf: float
    last_ts: float
    bearing_deg: float
    distance_m: float


class Tracker:
    """用 IoU 把相邻帧的检测连起来，并平滑方位角与距离。"""

    def __init__(self, config: TrackingConfig) -> None:
        self._config = config
        self._tracks: list[_Track] = []

    def update(
        self,
        detections: Sequence[Detection],
        *,
        frame_width: int,
        now: float | None = None,
    ) -> list[Detection]:
        timestamp = time.monotonic() if now is None else now
        focal_px = _focal_length_px(frame_width, self._config.horizontal_fov_deg)

        active = [
            track
            for track in self._tracks
            if timestamp - track.last_ts <= self._config.max_lost_s
        ]
        used: set[int] = set()
        output: list[Detection] = []

        for detection in detections:
            bearing_deg = _bearing_deg(
                detection.bbox,
                frame_width=frame_width,
                focal_px=focal_px,
            )
            distance_m = _distance_m(
                detection.bbox,
                focal_px=focal_px,
                assumed_height_m=self._config.assumed_height_m[detection.kind],
            )

            match_index = self._match(active, detection, used)
            if match_index is not None:
                used.add(match_index)
                track = active[match_index]
                alpha = self._config.smoothing_alpha
                track.bbox = detection.bbox
                track.conf = detection.conf
                track.last_ts = timestamp
                track.bearing_deg = _smooth(track.bearing_deg, bearing_deg, alpha)
                track.distance_m = _smooth(track.distance_m, distance_m, alpha)
            else:
                track = _Track(
                    kind=detection.kind,
                    bbox=detection.bbox,
                    conf=detection.conf,
                    last_ts=timestamp,
                    bearing_deg=bearing_deg,
                    distance_m=distance_m,
                )
                active.append(track)
                used.add(len(active) - 1)

            output.append(
                Detection(
                    kind=track.kind,
                    bbox=track.bbox,
                    conf=track.conf,
                    ts=detection.ts,
                    bearing_deg=track.bearing_deg,
                    distance_m=track.distance_m,
                )
            )

        self._tracks = [
            track
            for track in active
            if timestamp - track.last_ts <= self._config.max_lost_s
        ]
        return output

    def _match(
        self,
        tracks: Sequence[_Track],
        detection: Detection,
        used: set[int],
    ) -> int | None:
        best_index: int | None = None
        best_iou = self._config.match_iou_threshold

        for index, track in enumerate(tracks):
            if index in used or track.kind != detection.kind:
                continue
            overlap = _iou(track.bbox, detection.bbox)
            if overlap >= best_iou:
                best_iou = overlap
                best_index = index

        return best_index


def _focal_length_px(frame_width: int, horizontal_fov_deg: float) -> float:
    half_fov = math.radians(horizontal_fov_deg) / 2.0
    return (frame_width / 2.0) / math.tan(half_fov)


def _bearing_deg(bbox: BBox, *, frame_width: int, focal_px: float) -> float:
    center_x = (bbox[0] + bbox[2]) / 2.0
    offset_px = center_x - frame_width / 2.0
    return math.degrees(math.atan2(offset_px, focal_px))


def _distance_m(
    bbox: BBox,
    *,
    focal_px: float,
    assumed_height_m: float,
) -> float:
    box_height = max(1, bbox[3] - bbox[1])
    return focal_px * assumed_height_m / box_height


def _smooth(previous: float, current: float, alpha: float) -> float:
    # alpha 是新值的权重：越小越稳，越大越跟手。
    return previous * (1.0 - alpha) + current * alpha


def _iou(first: BBox, second: BBox) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    if right <= left or bottom <= top:
        return 0.0

    intersection = (right - left) * (bottom - top)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = first_area + second_area - intersection
    if union <= 0:
        return 0.0
    return intersection / union
