# 桌面宠物机器人

这是一个先跑通软件、再逐步落到三块板子上的桌面宠物机器人项目。第一阶段在 Windows 11 上使用普通摄像头和窗口，验证“看见目标 → 判断方位与距离 → 状态机决策 → 眼睛表情 → 串口指令”的完整链路；代码保持跨平台，后续可直接迁移到 Linux ARM。项目还提供一个本地浏览器调试台，用来同时观察视觉画面、空间仿真、状态和日志。

作者：敕仞

## 最终形态

| 板卡 | 职责 |
| --- | --- |
| Linux 单板机（树莓派 5 / 香橙派 5） | 摄像头采集、YOLO 检测、跟踪、状态机与串口编排 |
| ESP32-C6 触摸屏板 | 240 × 280 表情显示与语音交互 |
| ESP32-S3 | 底盘电机与云台控制 |

当前第一阶段不需要这些板卡，全部逻辑在 PC 上运行。

## 第一阶段目标

- 摄像头采集，自动探测可用摄像头
- YOLO 检测人和猫，绘制检测框并计算目标方位角
- 按目标框高度和假设身高粗估距离
- 四状态机：IDLE、WATCH、APPROACH、BACKOFF
- 240 × 280 表情窗口：眼睛追视、随机眨眼、平静 / 好奇 / 开心三种情绪
- 串口帧编解码；dry-run 模式只在控制台打印十六进制帧
- 协议编解码往返测试

## 目标结构

以下为目标结构，随里程碑逐步补齐：

```text
desk-pet-robot/
├── README.md
├── .gitignore
├── pyproject.toml
├── start.bat                 # Windows 一键启动器
├── config/
│   └── default.yaml          # 所有阈值、模型路径、摄像头与串口参数
├── models/                   # 模型权重，不进仓库
├── src/petbot/
│   ├── __init__.py
│   ├── main.py               # 入口，组装各模块并管理生命周期
│   ├── config.py             # YAML → 带类型的配置对象
│   ├── vision/
│   │   ├── camera.py         # 采集，自动探测摄像头索引
│   │   ├── detector.py       # YOLO 封装，输出 Detection 列表
│   │   └── tracker.py        # 简单跟踪、方位角与距离粗估
│   ├── brain/
│   │   ├── state_machine.py  # 四状态状态机
│   │   └── behaviors.py      # 各状态的具体行为
│   ├── face/
│   │   ├── renderer.py       # 240 × 280 画面渲染
│   │   └── eyes.py           # 眨眼、追视与情绪
│   ├── comm/
│   │   ├── protocol.py       # 串口帧编解码与 CRC
│   │   ├── serial_link.py    # pyserial 收发与 VID/PID 查找
│   │   └── loopback.py       # 无硬件时的 dry-run 输出
│   └── ui/
│       ├── dashboard.py      # 本地 HTTP 调试台、运行快照与日志
│       ├── debug_window.py   # 叠加检测框的原生调试窗口
│       └── web/              # 调试控制台页面（HTML/CSS/JS）
│           ├── index.html
│           ├── dashboard.css
│           └── dashboard.js
├── tools/
│   └── sim_base.py           # 第二阶段：二维差速底盘仿真
└── tests/
    └── test_protocol.py
```

## 开发环境

- Windows 11
- Python 3.11 或 3.12
- 建议使用项目内虚拟环境

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

迁移到 Linux ARM 时同样创建 venv，改用 `source .venv/bin/activate` 即可。项目中的路径使用 `pathlib` 处理，不依赖 Windows 路径分隔符。

## 双击启动（Windows）

直接双击项目根目录的 `start.bat`。脚本会：

- 检查 `.venv`，不存在时用 Python 3.12 创建并安装依赖；
- 启动 `python -m petbot.main`；
- 自动打开浏览器调试台：`http://127.0.0.1:8765/`；
- 保留命令行窗口用于日志和按 Ctrl+C 退出。

浏览器页面关闭不会结束程序；要停止项目，请点页面右上角“停止服务”，或在命令行窗口按 Ctrl+C。调试台只监听 `127.0.0.1`，不会暴露到局域网。

## 运行

阶段 2 已接通摄像头、人和猫的 YOLO 检测以及调试窗口。准备权重后也可以直接运行：

```powershell
python -m petbot.main
```

程序会自动探测摄像头，打开原生 `PetBot - Vision Debug` 窗口和浏览器调试台。摄像头正常时，两边都会显示带检测框的画面；关闭原生窗口或按 Esc 会停止整个程序。

没有可用摄像头时，程序会在命令行和页面同时显示“未找到可用摄像头”及尝试过的索引，并保持调试台运行，方便查看错误与日志；点击“停止服务”或按 Ctrl+C 退出，不会静默失败。

当前尚未接入表情窗口，阶段 4 会加入。

权重不进入仓库：把 `yolo11n.pt` 放进 `models/` 即可，默认路径是 `models/yolo11n.pt`，也可以在 `config/default.yaml` 的 `detector.model_path` 中修改。

## 调试控制台

调用 `python -m petbot.main` 后访问 `http://127.0.0.1:8765/`，页面包含：

- 视觉调试：通过 MJPEG 显示摄像头画面和检测框；
- 空间仿真：以机器人为中心显示目标方位角、粗估距离和雷达扫描，未接入实时目标时可用“演示轨迹”查看交互效果；
- 状态机与目标：显示 IDLE / WATCH / APPROACH / BACKOFF 和当前目标信息；
- 实时日志：把 Python logging 同步到浏览器，支持清屏；
- 串口通信：dry-run 帧数与十六进制内容，阶段 5 接入后填充。

页面使用 Python 标准库 `http.server` 和原生 HTML/CSS/JS 实现，不引入 Flask、FastAPI 或前端框架。页面和推流参数在 `config/default.yaml` 的 `ui.dashboard` 中配置。

## 配置

所有可调阈值、模型路径、摄像头索引、表情尺寸和串口参数集中在 `config/default.yaml`。源码中不写魔法数字，便于之后在 PC 和板卡上使用不同配置。

## 依赖

运行时只使用：

- opencv-python
- ultralytics
- numpy
- pyserial
- pygame
- pyyaml

测试依赖 `pytest`，通过 `.[test]` 安装，不引入 Web 框架。

## 里程碑

- [x] 阶段 1：仓库骨架、README、依赖与默认配置
- [x] 阶段 2：摄像头采集、YOLO 检测与调试窗口
- [x] 阶段 2 补充：可视化调试台、日志面板与一键启动
- [ ] 阶段 3：方位角、距离估算与状态机
- [ ] 阶段 4：表情渲染与眼睛行为
- [ ] 阶段 5：串口协议、dry-run 与单元测试

## 约定

- 注释使用中文，说明设计原因；作者署名：敕仞
- 跨平台：使用 `pathlib`，不拼接反斜杠，不调用 shell 命令
- 串口不使用固定 COM 号，通过 pyserial 的 `list_ports` 按 VID/PID 匹配
- 一次里程碑一次提交，提交信息格式为“阶段: 做了什么”
