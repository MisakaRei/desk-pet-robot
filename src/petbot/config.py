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
    ui = _parse_ui(_as_section(raw, "ui"))

    return AppConfig(camera=camera, detector=detector, ui=ui)


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
