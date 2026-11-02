"""程序入口：组装配置、摄像头、检测与调试窗口。

第一阶段这一步只负责视觉链路；状态机、表情窗口和串口会在后续里程碑
依次接入，入口继续复用这里的启动与清理顺序。
作者：敕仞
"""

from __future__ import annotations

import logging

from petbot import PetBotError
from petbot.config import DEFAULT_CONFIG_PATH, load_config
from petbot.ui.debug_window import DebugWindow
from petbot.vision.camera import Camera
from petbot.vision.detector import Detector

LOGGER = logging.getLogger("petbot.main")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = load_config()
        LOGGER.info("配置文件：%s", DEFAULT_CONFIG_PATH)

        # 先开摄像头再加载模型：没有摄像头时可以立刻得到明确提示，
        # 不必等待 PyTorch 初始化后才失败。
        with Camera.open(config.camera) as camera:
            detector = Detector(config.detector)
            with DebugWindow(config.ui.debug_window) as window:
                LOGGER.info("视觉链路已启动；关闭调试窗口或按 Esc 退出。")
                while True:
                    frame = camera.read()
                    detections = detector.detect(frame)
                    if not window.show(frame, detections):
                        LOGGER.info("调试窗口已关闭或按下 Esc，退出。")
                        break
    except PetBotError as exc:
        LOGGER.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        LOGGER.info("收到中断，退出。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
