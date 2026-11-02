"""读取并校验收拢后的运行配置。

YAML 只在这里接触一次，之后各模块拿到的是带类型的只读对象。
这样视觉、行为和通信代码里不会散落字典键和字符串转数值。
作者：敕仞
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from petbot import PetBotError

# 配置里的相对模型路径以仓库根目录为基准，而不是以启动时的当前目录为基准。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.yaml"

# Detection 只接受这两种标签，避免模型输出了没定义行为的类别。
SUPPORTED_KINDS = ("person", "cat")


class ConfigError(PetBotError):
    """配置文件缺失、格式错误或字段不合法。"""


@dataclass(frozen=True, slots=True)
class CameraConfig:
    preferred_index: int | None
    probe_max_index: int
    width: int
    height: int
    fps: int


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    model_path: Path
    image_size: int
    confidence_threshold: float
    iou_threshold: float
    device: str
    target_classes: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class TrackingConfig:
    match_iou_threshold: float
    max_lost_s: float
    smoothing_alpha: float
    horizontal_fov_deg: float
    assumed_height_m: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class BrainConfig:
    target_kind: str
    approach_distance_m: float
    backoff_distance_m: float
    lost_timeout_s: float
    approach_speed_mps: float
    backoff_speed_mps: float
    turn_gain: float
    max_turn_rate_rad_s: float
    turn_deadband_deg: float
    gimbal_limit_deg: float


@dataclass(frozen=True, slots=True)
class EyeConfig:
    spacing_px: int
    radius_px: int
    pupil_radius_px: int
    max_look_offset_px: int
    follow_smoothing: float
    blink_min_interval_s: float
    blink_max_interval_s: float
    blink_duration_s: float
    gaze_range_deg: float


@dataclass(frozen=True, slots=True)
class SerialPortId:
    vid: int
    pid: int


@dataclass(frozen=True, slots=True)
class SerialConfig:
    dry_run: bool
    baudrate: int
    write_timeout_s: float
    read_timeout_s: float
    send_period_s: float
    status_period_s: float
    vid_pid_candidates: tuple[SerialPortId, ...]


@dataclass(frozen=True, slots=True)
class FaceConfig:
    title: str
    width: int
    height: int
    fps: int
    background_rgb: tuple[int, int, int]
    eye_rgb: tuple[int, int, int]
    pupil_rgb: tuple[int, int, int]
    accent_rgb: tuple[int, int, int]
    eye: EyeConfig


@dataclass(frozen=True, slots=True)
class DebugWindowConfig:
    title: str
    wait_key_ms: int
    box_thickness: int
    font_scale: float
    font_thickness: int
    label_padding_px: int
    person_color_bgr: tuple[int, int, int]
    cat_color_bgr: tuple[int, int, int]
    text_color_bgr: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    enabled: bool
    host: str
    port: int
    auto_open_browser: bool
    keep_alive_on_error: bool
    stream_fps: int
    jpeg_quality: int
    max_stream_width: int
    log_history: int


@dataclass(frozen=True, slots=True)
class UiConfig:
    dashboard: DashboardConfig
    debug_window: DebugWindowConfig


@dataclass(frozen=True, slots=True)
class AppConfig:
    camera: CameraConfig
    detector: DetectorConfig
    tracking: TrackingConfig
    brain: BrainConfig
    face: FaceConfig
    serial: SerialConfig
    ui: UiConfig


def load_config(path: str | Path | None = None) -> AppConfig:
    """读取配置；传入路径用于测试或以后接入其他配置文件。"""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件：{config_path}") from exc

    try:
        raw_data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件不是合法 YAML：{config_path}（{exc}）") from exc

    raw = _as_mapping(raw_data, "根配置")

    camera = _parse_camera(_as_section(raw, "camera"))
    detector = _parse_detector(_as_section(raw, "detector"))
    tracking = _parse_tracking(_as_section(raw, "tracking"))
    brain = _parse_brain(_as_section(raw, "brain"))
    face = _parse_face(_as_section(raw, "face"))
    serial = _parse_serial(_as_section(raw, "serial"))
    ui = _parse_ui(_as_section(raw, "ui"))

    return AppConfig(
        camera=camera,
        detector=detector,
        tracking=tracking,
        brain=brain,
        face=face,
        serial=serial,
        ui=ui,
    )


def _parse_camera(section: Mapping[str, Any]) -> CameraConfig:
    preferred_raw = section.get("preferred_index")
    preferred_index = (
        None
        if preferred_raw is None
        else _as_int(preferred_raw, "camera.preferred_index", minimum=0)
    )

    return CameraConfig(
        preferred_index=preferred_index,
        probe_max_index=_as_int(
            _field(section, "camera", "probe_max_index"),
            "camera.probe_max_index",
            minimum=0,
        ),
        width=_as_int(_field(section, "camera", "width"), "camera.width", minimum=1),
        height=_as_int(_field(section, "camera", "height"), "camera.height", minimum=1),
        fps=_as_int(_field(section, "camera", "fps"), "camera.fps", minimum=1),
    )


def _parse_detector(section: Mapping[str, Any]) -> DetectorConfig:
    model_path = Path(
        _as_str(_field(section, "detector", "model_path"), "detector.model_path")
    )
    if not model_path.is_absolute():
        model_path = (PROJECT_ROOT / model_path).resolve()

    targets_raw = _as_mapping(
        _field(section, "detector", "target_classes"), "detector.target_classes"
    )
    targets: dict[str, int] = {}
    for kind, class_id in targets_raw.items():
        if kind not in SUPPORTED_KINDS:
            allowed = "、".join(SUPPORTED_KINDS)
            raise ConfigError(
                f"detector.target_classes 只支持 {allowed}，发现未知类别：{kind!r}"
            )
        targets[kind] = _as_int(
            class_id, f"detector.target_classes.{kind}", minimum=0
        )

    missing = set(SUPPORTED_KINDS) - set(targets)
    if missing:
        raise ConfigError(
            "detector.target_classes 缺少类别："
            + "、".join(sorted(missing))
        )

    return DetectorConfig(
        model_path=model_path,
        image_size=_as_int(
            _field(section, "detector", "image_size"),
            "detector.image_size",
            minimum=1,
        ),
        confidence_threshold=_as_float(
            _field(section, "detector", "confidence_threshold"),
            "detector.confidence_threshold",
            minimum=0.0,
            maximum=1.0,
        ),
        iou_threshold=_as_float(
            _field(section, "detector", "iou_threshold"),
            "detector.iou_threshold",
            minimum=0.0,
            maximum=1.0,
        ),
        device=_as_str(_field(section, "detector", "device"), "detector.device"),
        target_classes=MappingProxyType(targets),
    )


def _parse_tracking(section: Mapping[str, Any]) -> TrackingConfig:
    heights_raw = _as_mapping(
        _field(section, "tracking", "assumed_height_m"),
        "tracking.assumed_height_m",
    )
    heights: dict[str, float] = {}
    for kind, height in heights_raw.items():
        if kind not in SUPPORTED_KINDS:
            raise ConfigError(
                f"tracking.assumed_height_m 含未知类别：{kind!r}"
            )
        heights[kind] = _as_float(
            height,
            f"tracking.assumed_height_m.{kind}",
            minimum=0.05,
        )

    missing = set(SUPPORTED_KINDS) - set(heights)
    if missing:
        raise ConfigError(
            "tracking.assumed_height_m 缺少类别：" + "、".join(sorted(missing))
        )

    return TrackingConfig(
        match_iou_threshold=_as_float(
            _field(section, "tracking", "match_iou_threshold"),
            "tracking.match_iou_threshold",
            minimum=0.0,
            maximum=1.0,
        ),
        max_lost_s=_as_float(
            _field(section, "tracking", "max_lost_s"),
            "tracking.max_lost_s",
            minimum=0.0,
        ),
        smoothing_alpha=_as_float(
            _field(section, "tracking", "smoothing_alpha"),
            "tracking.smoothing_alpha",
            minimum=0.0,
            maximum=1.0,
        ),
        horizontal_fov_deg=_as_float(
            _field(section, "tracking", "horizontal_fov_deg"),
            "tracking.horizontal_fov_deg",
            minimum=1.0,
            maximum=179.0,
        ),
        assumed_height_m=MappingProxyType(heights),
    )


def _parse_brain(section: Mapping[str, Any]) -> BrainConfig:
    target_kind = _as_str(
        _field(section, "brain", "target_kind"), "brain.target_kind"
    )
    if target_kind not in SUPPORTED_KINDS:
        raise ConfigError(
            f"brain.target_kind 必须是 {'、'.join(SUPPORTED_KINDS)}，实际为 {target_kind!r}"
        )

    backoff = _as_float(
        _field(section, "brain", "backoff_distance_m"),
        "brain.backoff_distance_m",
        minimum=0.0,
    )
    approach = _as_float(
        _field(section, "brain", "approach_distance_m"),
        "brain.approach_distance_m",
        minimum=0.0,
    )
    if backoff >= approach:
        raise ConfigError(
            "brain.backoff_distance_m 必须小于 brain.approach_distance_m，"
            "否则状态机会在同一个距离上反复切换"
        )

    return BrainConfig(
        target_kind=target_kind,
        approach_distance_m=approach,
        backoff_distance_m=backoff,
        lost_timeout_s=_as_float(
            _field(section, "brain", "lost_timeout_s"),
            "brain.lost_timeout_s",
            minimum=0.1,
        ),
        approach_speed_mps=_as_float(
            _field(section, "brain", "approach_speed_mps"),
            "brain.approach_speed_mps",
            minimum=0.0,
        ),
        backoff_speed_mps=_as_float(
            _field(section, "brain", "backoff_speed_mps"),
            "brain.backoff_speed_mps",
            minimum=0.0,
        ),
        turn_gain=_as_float(
            _field(section, "brain", "turn_gain"),
            "brain.turn_gain",
            minimum=0.0,
        ),
        max_turn_rate_rad_s=_as_float(
            _field(section, "brain", "max_turn_rate_rad_s"),
            "brain.max_turn_rate_rad_s",
            minimum=0.1,
        ),
        turn_deadband_deg=_as_float(
            _field(section, "brain", "turn_deadband_deg"),
            "brain.turn_deadband_deg",
            minimum=0.0,
        ),
        gimbal_limit_deg=_as_float(
            _field(section, "brain", "gimbal_limit_deg"),
            "brain.gimbal_limit_deg",
            minimum=0.0,
            maximum=90.0,
        ),
    )


def _parse_face(section: Mapping[str, Any]) -> FaceConfig:
    eye_raw = _as_mapping(_field(section, "face", "eye"), "face.eye")
    blink_min = _as_float(
        _field(eye_raw, "face.eye", "blink_min_interval_s"),
        "face.eye.blink_min_interval_s",
        minimum=0.1,
    )
    blink_max = _as_float(
        _field(eye_raw, "face.eye", "blink_max_interval_s"),
        "face.eye.blink_max_interval_s",
        minimum=0.1,
    )
    if blink_min > blink_max:
        raise ConfigError(
            "face.eye.blink_min_interval_s 不能大于 blink_max_interval_s"
        )

    radius = _as_int(
        _field(eye_raw, "face.eye", "radius_px"),
        "face.eye.radius_px",
        minimum=1,
    )
    pupil_radius = _as_int(
        _field(eye_raw, "face.eye", "pupil_radius_px"),
        "face.eye.pupil_radius_px",
        minimum=1,
    )
    look_offset = _as_int(
        _field(eye_raw, "face.eye", "max_look_offset_px"),
        "face.eye.max_look_offset_px",
        minimum=0,
    )
    if pupil_radius + look_offset >= radius:
        raise ConfigError(
            "face.eye.pupil_radius_px + max_look_offset_px 必须小于 radius_px，"
            "否则追视时瞳孔会跑出眼白"
        )

    return FaceConfig(
        title=_as_str(_field(section, "face", "title"), "face.title"),
        width=_as_int(_field(section, "face", "width"), "face.width", minimum=80),
        height=_as_int(
            _field(section, "face", "height"), "face.height", minimum=80
        ),
        fps=_as_int(
            _field(section, "face", "fps"),
            "face.fps",
            minimum=1,
            maximum=120,
        ),
        background_rgb=_as_color(
            _field(section, "face", "background_rgb"), "face.background_rgb"
        ),
        eye_rgb=_as_color(_field(section, "face", "eye_rgb"), "face.eye_rgb"),
        pupil_rgb=_as_color(
            _field(section, "face", "pupil_rgb"), "face.pupil_rgb"
        ),
        accent_rgb=_as_color(
            _field(section, "face", "accent_rgb"), "face.accent_rgb"
        ),
        eye=EyeConfig(
            spacing_px=_as_int(
                _field(eye_raw, "face.eye", "spacing_px"),
                "face.eye.spacing_px",
                minimum=1,
            ),
            radius_px=radius,
            pupil_radius_px=pupil_radius,
            max_look_offset_px=look_offset,
            follow_smoothing=_as_float(
                _field(eye_raw, "face.eye", "follow_smoothing"),
                "face.eye.follow_smoothing",
                minimum=0.0,
                maximum=1.0,
            ),
            blink_min_interval_s=blink_min,
            blink_max_interval_s=blink_max,
            blink_duration_s=_as_float(
                _field(eye_raw, "face.eye", "blink_duration_s"),
                "face.eye.blink_duration_s",
                minimum=0.02,
            ),
            gaze_range_deg=_as_float(
                _field(eye_raw, "face.eye", "gaze_range_deg"),
                "face.eye.gaze_range_deg",
                minimum=1.0,
                maximum=90.0,
            ),
        ),
    )


def _parse_serial(section: Mapping[str, Any]) -> SerialConfig:
    candidates_raw = _field(section, "serial", "vid_pid_candidates")
    if not isinstance(candidates_raw, (list, tuple)) or not candidates_raw:
        raise ConfigError("serial.vid_pid_candidates 必须是非空数组")

    candidates: list[SerialPortId] = []
    for index, candidate in enumerate(candidates_raw):
        candidate_map = _as_mapping(
            candidate, f"serial.vid_pid_candidates[{index}]"
        )
        candidates.append(
            SerialPortId(
                vid=_as_int(
                    _field(
                        candidate_map,
                        f"serial.vid_pid_candidates[{index}]",
                        "vid",
                    ),
                    f"serial.vid_pid_candidates[{index}].vid",
                    minimum=0,
                    maximum=0xFFFF,
                ),
                pid=_as_int(
                    _field(
                        candidate_map,
                        f"serial.vid_pid_candidates[{index}]",
                        "pid",
                    ),
                    f"serial.vid_pid_candidates[{index}].pid",
                    minimum=0,
                    maximum=0xFFFF,
                ),
            )
        )

    return SerialConfig(
        dry_run=_as_bool(
            _field(section, "serial", "dry_run"), "serial.dry_run"
        ),
        baudrate=_as_int(
            _field(section, "serial", "baudrate"),
            "serial.baudrate",
            minimum=1,
        ),
        write_timeout_s=_as_float(
            _field(section, "serial", "write_timeout_s"),
            "serial.write_timeout_s",
            minimum=0.0,
        ),
        read_timeout_s=_as_float(
            _field(section, "serial", "read_timeout_s"),
            "serial.read_timeout_s",
            minimum=0.0,
        ),
        send_period_s=_as_float(
            _field(section, "serial", "send_period_s"),
            "serial.send_period_s",
            minimum=0.02,
        ),
        status_period_s=_as_float(
            _field(section, "serial", "status_period_s"),
            "serial.status_period_s",
            minimum=0.05,
        ),
        vid_pid_candidates=tuple(candidates),
    )


def _parse_ui(section: Mapping[str, Any]) -> UiConfig:
    dashboard_raw = _as_mapping(
        _field(section, "ui", "dashboard"), "ui.dashboard"
    )
    dashboard = DashboardConfig(
        enabled=_as_bool(
            _field(dashboard_raw, "ui.dashboard", "enabled"),
            "ui.dashboard.enabled",
        ),
        host=_as_str(
            _field(dashboard_raw, "ui.dashboard", "host"),
            "ui.dashboard.host",
        ),
        port=_as_int(
            _field(dashboard_raw, "ui.dashboard", "port"),
            "ui.dashboard.port",
            minimum=1,
            maximum=65535,
        ),
        auto_open_browser=_as_bool(
            _field(dashboard_raw, "ui.dashboard", "auto_open_browser"),
            "ui.dashboard.auto_open_browser",
        ),
        keep_alive_on_error=_as_bool(
            _field(dashboard_raw, "ui.dashboard", "keep_alive_on_error"),
            "ui.dashboard.keep_alive_on_error",
        ),
        stream_fps=_as_int(
            _field(dashboard_raw, "ui.dashboard", "stream_fps"),
            "ui.dashboard.stream_fps",
            minimum=1,
            maximum=60,
        ),
        jpeg_quality=_as_int(
            _field(dashboard_raw, "ui.dashboard", "jpeg_quality"),
            "ui.dashboard.jpeg_quality",
            minimum=1,
            maximum=100,
        ),
        max_stream_width=_as_int(
            _field(dashboard_raw, "ui.dashboard", "max_stream_width"),
            "ui.dashboard.max_stream_width",
            minimum=320,
            maximum=3840,
        ),
        log_history=_as_int(
            _field(dashboard_raw, "ui.dashboard", "log_history"),
            "ui.dashboard.log_history",
            minimum=20,
            maximum=5000,
        ),
    )

    debug = _as_mapping(_field(section, "ui", "debug_window"), "ui.debug_window")
    return UiConfig(
        dashboard=dashboard,
        debug_window=DebugWindowConfig(
            title=_as_str(
                _field(debug, "ui.debug_window", "title"),
                "ui.debug_window.title",
            ),
            wait_key_ms=_as_int(
                _field(debug, "ui.debug_window", "wait_key_ms"),
                "ui.debug_window.wait_key_ms",
                minimum=0,
            ),
            box_thickness=_as_int(
                _field(debug, "ui.debug_window", "box_thickness"),
                "ui.debug_window.box_thickness",
                minimum=1,
            ),
            font_scale=_as_float(
                _field(debug, "ui.debug_window", "font_scale"),
                "ui.debug_window.font_scale",
                minimum=0.1,
            ),
            font_thickness=_as_int(
                _field(debug, "ui.debug_window", "font_thickness"),
                "ui.debug_window.font_thickness",
                minimum=1,
            ),
            label_padding_px=_as_int(
                _field(debug, "ui.debug_window", "label_padding_px"),
                "ui.debug_window.label_padding_px",
                minimum=0,
            ),
            person_color_bgr=_as_color(
                _field(debug, "ui.debug_window", "person_color_bgr"),
                "ui.debug_window.person_color_bgr",
            ),
            cat_color_bgr=_as_color(
                _field(debug, "ui.debug_window", "cat_color_bgr"),
                "ui.debug_window.cat_color_bgr",
            ),
            text_color_bgr=_as_color(
                _field(debug, "ui.debug_window", "text_color_bgr"),
                "ui.debug_window.text_color_bgr",
            ),
        )
    )


def _as_section(root: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    if name not in root:
        raise ConfigError(f"缺少配置节：{name}")
    return _as_mapping(root[name], name)


def _field(section: Mapping[str, Any], section_name: str, key: str) -> Any:
    if key not in section:
        raise ConfigError(f"缺少配置项：{section_name}.{key}")
    return section[key]


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{name} 必须是 YAML 映射")
    return value


def _as_int(
    value: Any,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} 必须是整数，实际为 {value!r}")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} 不能小于 {minimum}，实际为 {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} 不能大于 {maximum}，实际为 {value}")
    return value


def _as_float(
    value: Any,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} 必须是数字，实际为 {value!r}")
    result = float(value)
    if minimum is not None and result < minimum:
        raise ConfigError(f"{name} 不能小于 {minimum}，实际为 {result}")
    if maximum is not None and result > maximum:
        raise ConfigError(f"{name} 不能大于 {maximum}，实际为 {result}")
    return result


def _as_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} 必须是非空字符串，实际为 {value!r}")
    return value.strip()


def _as_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} 必须是 true 或 false，实际为 {value!r}")
    return value


def _as_color(value: Any, name: str) -> tuple[int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ConfigError(f"{name} 必须是长度为 3 的颜色数组，实际为 {value!r}")
    channels = [_as_int(channel, name, minimum=0) for channel in value]
    if any(channel > 255 for channel in channels):
        raise ConfigError(f"{name} 的每个通道必须在 0 到 255 之间")
    return (channels[0], channels[1], channels[2])
