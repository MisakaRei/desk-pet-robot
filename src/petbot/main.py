"""程序入口：组装配置、视觉链路、状态机、表情窗口和调试控制台。

第一阶段把采集/检测、跟踪、状态决策、表情表现、串口指令与浏览器可视化
放在同一个进程里；所有硬件交互都从配置和协议层进入，方便之后拆到三块板。
作者：敕仞
"""

from __future__ import annotations

import logging
import time

from petbot import PetBotError
from petbot.brain.behaviors import BehaviorCommand, build_behavior
from petbot.brain.state_machine import (
    PetState,
    StateMachine,
    select_primary_target,
)
from petbot.comm.protocol import (
    MessageType,
    encode_emotion,
    encode_frame,
    encode_gimbal,
    encode_velocity,
)
from petbot.comm.serial_link import PacketLink, create_link
from petbot.config import AppConfig, DEFAULT_CONFIG_PATH, load_config
from petbot.face.renderer import FaceError, FaceWindow
from petbot.ui.dashboard import Dashboard, DashboardState
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
                _run_idle_face_preview(config, dashboard)
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

    link: PacketLink | None = None
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
        link = _open_link(config, state)
        serial_sequence = 0
        last_serial_send = 0.0

        with DebugWindow(config.ui.debug_window) as window, FaceWindow(
            config.face
        ) as face:
            LOGGER.info("视觉链路与表情窗口已启动；关闭任一窗口或按 Esc 退出。")
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
                if (
                    link is not None
                    and now - last_serial_send >= config.serial.send_period_s
                ):
                    serial_sequence = _send_behavior_frames(
                        link, behavior, serial_sequence
                    )
                    last_serial_send = now
                    if state is not None:
                        state.update_serial(
                            available=True,
                            dry_run=config.serial.dry_run,
                            sent=link.sent_count,
                            last_hex=link.last_frame_hex,
                        )

                rendered = window.render(frame, tracked)

                if not face.update(behavior, now):
                    LOGGER.info("表情窗口已关闭或按下 Esc，退出。")
                    break

                if state is not None:
                    state.publish_frame(rendered, tracked)
                    state.publish_face(face.snapshot_bgr())
                    state.update_behavior(
                        current_state.value,
                        target=behavior.target,
                        emotion=behavior.emotion,
                        available=True,
                    )

                if not window.show_rendered(rendered):
                    LOGGER.info("调试窗口已关闭或按下 Esc，退出。")
                    break
    finally:
        if link is not None:
            link.close()
        camera.release()

    return 0


def _run_idle_face_preview(config: AppConfig, dashboard: Dashboard) -> None:
    """摄像头不可用时仍让页面能看到表情窗口，而不是停在黑屏。

    这只是待机表情预览：不会产生目标、不会驱动底盘。关闭表情窗口、
    点击页面“停止服务”或 Ctrl+C 都可以结束。
    """
    idle = build_behavior(PetState.IDLE, None, config.brain)
    try:
        face = FaceWindow(config.face)
    except FaceError as exc:
        LOGGER.warning("%s；仅保留调试控制台。", exc)
        dashboard.wait_for_shutdown()
        return

    LOGGER.info("视觉链路未就绪，启动表情待机预览。")
    state = dashboard.state
    link = _open_link(config, state)
    serial_sequence = 0
    last_serial_send = 0.0
    interval = 1.0 / config.face.fps
    try:
        while not state.shutdown_requested:
            started = time.monotonic()
            if not face.update(idle, started):
                LOGGER.info("表情窗口已关闭，退出。")
                break
            state.publish_face(face.snapshot_bgr())

            if (
                link is not None
                and started - last_serial_send >= config.serial.send_period_s
            ):
                serial_sequence = _send_behavior_frames(
                    link, idle, serial_sequence
                )
                last_serial_send = started
                state.update_serial(
                    available=True,
                    dry_run=config.serial.dry_run,
                    sent=link.sent_count,
                    last_hex=link.last_frame_hex,
                )

            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval - elapsed))
    finally:
        if link is not None:
            link.close()
        face.close()


def _open_link(config: AppConfig, state: DashboardState | None) -> PacketLink | None:
    try:
        link = create_link(config.serial)
    except PetBotError as exc:
        LOGGER.error("串口初始化失败，继续运行但不发送链路帧：%s", exc)
        return None

    if state is not None:
        state.update_serial(
            available=True,
            dry_run=config.serial.dry_run,
            sent=link.sent_count,
            last_hex=link.last_frame_hex,
        )
    return link


def _send_behavior_frames(
    link: PacketLink,
    behavior: BehaviorCommand,
    sequence: int,
) -> int:
    """一次控制周期发送底盘、云台、表情三帧；返回下一个序号。"""
    frames = (
        (
            MessageType.BASE_VELOCITY,
            encode_velocity(behavior.linear_mps, behavior.angular_radps),
        ),
        (
            MessageType.GIMBAL_ANGLE,
            encode_gimbal(
                behavior.gimbal_yaw_deg,
                behavior.gimbal_pitch_deg,
            ),
        ),
        (
            MessageType.EMOTION,
            encode_emotion(behavior.emotion),
        ),
    )
    encoded = [
        encode_frame(message_type, (sequence + index) & 0xFFFF, payload)
        for index, (message_type, payload) in enumerate(frames)
    ]
    link.send_many(encoded)
    return (sequence + len(frames)) & 0xFFFF


if __name__ == "__main__":
    raise SystemExit(main())
