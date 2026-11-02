"""程序入口：组装配置、视觉链路、状态机和 Web 调试控制台。

第一阶段把采集/检测、跟踪、状态决策、浏览器可视化与生命周期放在同一个
进程里。表情窗口和串口会在后续里程碑接入，入口继续复用这里的启动和清理顺序。
作者：敕仞
"""

from __future__ import annotations

import logging
import time

from petbot import PetBotError
from petbot.brain.behaviors import build_behavior
from petbot.brain.state_machine import StateMachine, select_primary_target
from petbot.config import AppConfig, DEFAULT_CONFIG_PATH, load_config
from petbot.ui.dashboard import Dashboard
from petbot.ui.debug_window import DebugWindow
from petbot.vision.camera import Camera, CameraError
from petbot.vision.detector import Detector, DetectorError
from petbot.vision.tracker import Tracker

LOGGER = logging.getLogger("petbot.main")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = load_config()
    except PetBotError as exc:
        LOGGER.error("%s", exc)
        return 1

    LOGGER.info("配置文件：%s", DEFAULT_CONFIG_PATH)

    dashboard: Dashboard | None = None
    try:
        if config.ui.dashboard.enabled:
            dashboard = Dashboard(config.ui.dashboard)
            try:
                dashboard.start()
            except PetBotError:
                # 控制台没起来时不能进入“保持页面运行”的等待逻辑。
                dashboard = None
                raise

        return _run(config, dashboard)
    except PetBotError as exc:
        LOGGER.error("%s", exc)
        if (
            dashboard is not None
            and config.ui.dashboard.keep_alive_on_error
        ):
            dashboard.state.set_app_mode(
                "no_camera" if isinstance(exc, CameraError) else "error"
            )
            LOGGER.info(
                "调试控制台保持运行，请在页面查看错误和日志；"
                "点击右上角“停止服务”或按 Ctrl+C 退出。"
            )
            try:
                dashboard.wait_for_shutdown()
            except KeyboardInterrupt:
                LOGGER.info("收到中断，退出。")
            return 1
        return 1
    except KeyboardInterrupt:
        LOGGER.info("收到中断，退出。")
        return 0
    finally:
        if dashboard is not None:
            dashboard.stop()


def _run(config: AppConfig, dashboard: Dashboard | None) -> int:
    state = dashboard.state if dashboard is not None else None

    try:
        camera = Camera.open(config.camera)
    except CameraError as exc:
        if state is not None:
            state.set_camera("error", error=str(exc))
            state.set_detector(
                "skipped",
                model=config.detector.model_path.name,
                device=config.detector.device,
                error="摄像头不可用，检测器未启动。",
            )
        raise

    if state is not None:
        state.set_camera(
            "connected",
            index=camera.index,
            width=camera.width,
            height=camera.height,
        )

    try:
        try:
            detector = Detector(config.detector)
        except DetectorError as exc:
            if state is not None:
                state.set_detector(
                    "error",
                    model=config.detector.model_path.name,
                    device=config.detector.device,
                    error=str(exc),
                )
            raise

        if state is not None:
            state.set_detector(
                "ready",
                model=config.detector.model_path.name,
                device=config.detector.device,
            )
            state.set_app_mode("live")

        tracker = Tracker(config.tracking)
        state_machine = StateMachine(config.brain)

        with DebugWindow(config.ui.debug_window) as window:
            LOGGER.info("视觉链路已启动；关闭调试窗口或按 Esc 退出。")
            while True:
                if state is not None and state.shutdown_requested:
                    LOGGER.info("收到调试控制台的停止请求，退出。")
                    break

                frame = camera.read()
                raw_detections = detector.detect(frame)
                tracked = tracker.update(
                    raw_detections,
                    frame_width=frame.shape[1],
                )

                now = time.monotonic()
                target = select_primary_target(
                    tracked, config.brain.target_kind
                )
                previous_state = state_machine.state
                current_state = state_machine.update(target, now)
                if current_state is not previous_state:
                    LOGGER.info(
                        "行为状态切换：%s → %s",
                        previous_state.value,
                        current_state.value,
                    )

                behavior = build_behavior(
                    current_state,
                    state_machine.last_target,
                    config.brain,
                )
                rendered = window.render(frame, tracked)

                if state is not None:
                    state.publish_frame(rendered, tracked)
                    state.update_behavior(
                        current_state.value,
                        target=behavior.target,
                        available=True,
                    )

                if not window.show_rendered(rendered):
                    LOGGER.info("调试窗口已关闭或按下 Esc，退出。")
                    break
    finally:
        camera.release()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
