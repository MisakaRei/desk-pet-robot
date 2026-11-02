"""本地调试控制台。

用标准库自带的 HTTP 服务把视觉帧、行为状态和日志送到浏览器，避免为了
调试页面引入 Web 框架，也让同一套代码以后能在 Linux ARM 上直接运行。
服务默认只监听回环地址，不暴露到局域网。
作者：敕仞
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
import webbrowser
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence, cast
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from petbot import PetBotError, __version__
from petbot.config import DashboardConfig
from petbot.vision.detector import Detection

WEB_ROOT = Path(__file__).resolve().parent / "web"
LOGGER = logging.getLogger(__name__)
MJPEG_BOUNDARY = "petbotframe"
_STATIC_FILES = {
    "/static/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/static/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
}


class DashboardError(PetBotError):
    """调试控制台无法启动或停止。"""


class DashboardState:
    """线程安全的运行快照与日志环形缓冲区。

    HTTP 线程只读快照，采集/行为线程只写快照；两边不共享业务对象，
    以后继续接状态机和串口时只需要补充新的字段。
    """

    def __init__(self, log_history: int) -> None:
        self._lock = threading.Lock()
        self._started_monotonic = time.monotonic()
        self._logs: deque[dict[str, Any]] = deque(maxlen=log_history)
        self._next_log_id = 1
        self._frame: np.ndarray | None = None
        self._frame_seq = 0
        self._shutdown = threading.Event()
        self._status: dict[str, Any] = {
            "app": {
                "version": __version__,
                "mode": "starting",
                "started_at": time.time(),
                "uptime_s": 0.0,
            },
            "camera": {
                "state": "starting",
                "index": None,
                "width": None,
                "height": None,
                "error": None,
            },
            "detector": {
                "state": "starting",
                "model": None,
                "device": None,
                "error": None,
            },
            "vision": {"frames": 0, "detections": 0, "items": []},
            "behavior": {
                "available": False,
                "state": "IDLE",
                "since": None,
                "target": None,
            },
            "serial": {
                "available": False,
                "dry_run": True,
                "sent": 0,
                "last_hex": None,
            },
        }

    def set_app_mode(self, mode: str) -> None:
        with self._lock:
            self._status["app"]["mode"] = mode

    def set_camera(
        self,
        state: str,
        *,
        index: int | None = None,
        width: int | None = None,
        height: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._status["camera"] = {
                "state": state,
                "index": index,
                "width": width,
                "height": height,
                "error": error,
            }

    def set_detector(
        self,
        state: str,
        *,
        model: str | None = None,
        device: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._status["detector"] = {
                "state": state,
                "model": model,
                "device": device,
                "error": error,
            }

    def publish_frame(
        self,
        frame: np.ndarray,
        detections: Sequence[Detection],
    ) -> None:
        """保存已画框的画面和本帧检测结果，供页面轮询/取流。"""
        items = [
            {
                "kind": detection.kind,
                "bbox": list(detection.bbox),
                "conf": round(detection.conf, 3),
                "bearing_deg": (
                    None
                    if detection.bearing_deg is None
                    else round(detection.bearing_deg, 1)
                ),
                "distance_m": (
                    None
                    if detection.distance_m is None
                    else round(detection.distance_m, 2)
                ),
                "ts": detection.ts,
            }
            for detection in detections
        ]
        with self._lock:
            # 调用方传入的是 debug_window.render() 生成的新帧，不会再被原地修改。
            self._frame = frame
            self._frame_seq += 1
            self._status["vision"]["frames"] += 1
            self._status["vision"]["detections"] = len(items)
            self._status["vision"]["items"] = items

    def update_behavior(
        self,
        state: str,
        *,
        target: dict[str, Any] | None = None,
        available: bool = True,
    ) -> None:
        with self._lock:
            self._status["behavior"] = {
                "available": available,
                "state": state,
                "since": time.time(),
                "target": target,
            }

    def update_serial(
        self,
        *,
        available: bool,
        dry_run: bool,
        sent: int,
        last_hex: str | None,
    ) -> None:
        with self._lock:
            self._status["serial"] = {
                "available": available,
                "dry_run": dry_run,
                "sent": sent,
                "last_hex": last_hex,
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            status = copy.deepcopy(self._status)
            status["app"]["uptime_s"] = round(
                time.monotonic() - self._started_monotonic, 1
            )
        return status

    def add_log(
        self,
        *,
        level: str,
        name: str,
        message: str,
        created: float,
    ) -> None:
        with self._lock:
            self._logs.append(
                {
                    "id": self._next_log_id,
                    "level": level,
                    "name": name,
                    "message": message,
                    "time": time.strftime("%H:%M:%S", time.localtime(created)),
                }
            )
            self._next_log_id += 1

    def logs_after(self, after_id: int) -> dict[str, Any]:
        with self._lock:
            logs = [entry for entry in self._logs if entry["id"] > after_id]
            latest_id = self._logs[-1]["id"] if self._logs else 0
        return {"logs": logs, "next": latest_id}

    def latest_frame(self) -> tuple[int, np.ndarray | None]:
        with self._lock:
            return self._frame_seq, self._frame

    def request_shutdown(self) -> None:
        with self._lock:
            if self._status["app"]["mode"] != "stopping":
                self._status["app"]["mode"] = "stopping"
        self._shutdown.set()

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown.is_set()

    def wait_for_shutdown(self) -> None:
        self._shutdown.wait()


class DashboardLogHandler(logging.Handler):
    """把应用日志复制到页面；控制台日志仍由 basicConfig 负责。"""

    def __init__(self, state: DashboardState) -> None:
        super().__init__(level=logging.INFO)
        self._state = state

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + logging.Formatter().formatException(record.exc_info)
            self._state.add_log(
                level=record.levelname,
                name=record.name,
                message=message,
                created=record.created,
            )
        except Exception:
            self.handleError(record)


class Dashboard:
    """调试控制台服务器的生命周期。"""

    def __init__(self, config: DashboardConfig) -> None:
        self._config = config
        self.state = DashboardState(config.log_history)
        self._log_handler = DashboardLogHandler(self.state)
        self._httpd: _DashboardHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        display_host = (
            "127.0.0.1"
            if self._config.host in {"0.0.0.0", "::"}
            else self._config.host
        )
        return f"http://{display_host}:{self._config.port}/"

    def start(self) -> None:
        if self._httpd is not None:
            return

        try:
            self._httpd = _DashboardHTTPServer(
                (self._config.host, self._config.port),
                self.state,
                self._config,
            )
        except OSError as exc:
            raise DashboardError(
                f"无法启动调试控制台 {self._config.host}:{self._config.port}（{exc}）。"
                "请检查端口是否已被其他程序占用，或修改 config/default.yaml 中的 "
                "ui.dashboard.port。"
            ) from exc

        logging.getLogger().addHandler(self._log_handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="petbot-dashboard",
            daemon=True,
        )
        self._thread.start()
        LOGGER.info("调试控制台已启动：%s", self.url)
        LOGGER.info("浏览器关闭不会停止程序；请使用页面右上角的退出按钮或 Ctrl+C。")

        if self._config.auto_open_browser:
            threading.Thread(
                target=self._open_browser,
                name="petbot-open-browser",
                daemon=True,
            ).start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        self.state.request_shutdown()
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logging.getLogger().removeHandler(self._log_handler)
        LOGGER.info("调试控制台已停止。")

    def wait_for_shutdown(self) -> None:
        self.state.wait_for_shutdown()

    def _open_browser(self) -> None:
        try:
            webbrowser.open(self.url, new=2)
        except Exception as exc:
            LOGGER.warning("无法自动打开浏览器：%s（可手动访问 %s）", exc, self.url)


class _DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        state: DashboardState,
        config: DashboardConfig,
    ) -> None:
        self.state = state
        self.dashboard_config = config
        super().__init__(address, _DashboardRequestHandler)


class _DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "PetBotDashboard/0.1"

    @property
    def _state(self) -> DashboardState:
        return cast(_DashboardHTTPServer, self.server).state

    @property
    def _config(self) -> DashboardConfig:
        return cast(_DashboardHTTPServer, self.server).dashboard_config

    def log_message(self, format: str, *args: object) -> None:
        # 页面每 500ms 轮询一次，访问日志会淹没真正的应用日志，降到 DEBUG。
        LOGGER.debug("HTTP %s " + format, self.address_string(), *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if path in _STATIC_FILES:
            filename, content_type = _STATIC_FILES[path]
            self._serve_static(filename, content_type)
            return
        if path == "/api/state":
            self._send_json(self._state.snapshot())
            return
        if path == "/api/logs":
            after = _parse_after(parse_qs(parsed.query))
            self._send_json(self._state.logs_after(after))
            return
        if path == "/stream.mjpg":
            self._serve_mjpeg()
            return
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        self._send_text(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/shutdown":
            self._state.request_shutdown()
            self._send_json({"ok": True})
            return
        self._send_text(HTTPStatus.NOT_FOUND, "not found")

    def _serve_static(self, filename: str, content_type: str) -> None:
        path = WEB_ROOT / filename
        try:
            body = path.read_bytes()
        except OSError as exc:
            LOGGER.error("读取页面资源失败：%s（%s）", path, exc)
            self._send_text(HTTPStatus.INTERNAL_SERVER_ERROR, "dashboard asset missing")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: HTTPStatus, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_mjpeg(self) -> None:
        state = self._state
        config = self._config
        delay = 1.0 / config.stream_fps
        last_seq = -1
        placeholder_sent = False

        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        )
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        try:
            while not state.shutdown_requested:
                seq, frame = state.latest_frame()
                if frame is None:
                    if not placeholder_sent:
                        self._write_jpeg(_make_placeholder(config.max_stream_width), config)
                        placeholder_sent = True
                    time.sleep(delay)
                    continue

                if seq == last_seq:
                    time.sleep(delay)
                    continue

                last_seq = seq
                if frame.shape[1] > config.max_stream_width:
                    scale = config.max_stream_width / frame.shape[1]
                    frame = cv2.resize(
                        frame,
                        (config.max_stream_width, int(round(frame.shape[0] * scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                self._write_jpeg(frame, config)
                time.sleep(delay)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # 浏览器刷新或关闭页面会主动断开 MJPEG 长连接，这是正常现象。
            pass

    def _write_jpeg(self, frame: np.ndarray, config: DashboardConfig) -> None:
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), config.jpeg_quality],
        )
        if not ok:
            return
        payload = encoded.tobytes()
        self.wfile.write(f"--{MJPEG_BOUNDARY}\r\n".encode("ascii"))
        self.wfile.write(b"Content-Type: image/jpeg\r\n")
        self.wfile.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        self.wfile.write(payload)
        self.wfile.write(b"\r\n")
        self.wfile.flush()


def _parse_after(query: dict[str, list[str]]) -> int:
    values = query.get("after", ["0"])
    try:
        return max(0, int(values[0]))
    except (TypeError, ValueError):
        return 0


def _make_placeholder(width: int) -> np.ndarray:
    """MJPEG 在摄像头未就绪时也要有画面，避免浏览器显示破图。"""
    width = max(320, width)
    height = int(round(width * 9 / 16))
    frame = np.full((height, width, 3), (12, 18, 24), dtype=np.uint8)

    for x in range(0, width, width // 12):
        cv2.line(frame, (x, 0), (x, height), (24, 36, 48), 1)
    for y in range(0, height, height // 8):
        cv2.line(frame, (0, y), (width, y), (24, 36, 48), 1)

    title = "PETBOT VISION"
    subtitle = "WAITING FOR CAMERA"
    scale = max(0.8, width / 1200)
    thickness = max(2, int(width / 480))
    (tw, th), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    cv2.putText(
        frame,
        title,
        ((width - tw) // 2, height // 2 - th),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (96, 210, 190),
        thickness,
        cv2.LINE_AA,
    )
    (sw, _), _ = cv2.getTextSize(subtitle, cv2.FONT_HERSHEY_SIMPLEX, scale * 0.5, 1)
    cv2.putText(
        frame,
        subtitle,
        ((width - sw) // 2, height // 2 + th + 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale * 0.5,
        (130, 155, 170),
        1,
        cv2.LINE_AA,
    )
    return frame
