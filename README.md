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

第一阶段功能已全部接通：摄像头、人和猫的 YOLO 检测、跟踪与状态机、表情窗口、串口 dry-run 和调试控制台。准备权重后也可以直接运行：

```powershell
python -m petbot.main
```

程序会自动探测摄像头，打开原生 `PetBot - Vision Debug` 窗口、240 × 280 的 `PetBot - Face` 表情窗口和浏览器调试台。摄像头正常时，页面会显示带检测框、方位角和粗估距离的画面，眼睛会追视目标并按随机间隔眨眼。关闭任一原生窗口或按 Esc 会停止整个程序。

没有可用摄像头时，程序会在命令行和页面同时显示“未找到可用摄像头”及尝试过的索引，并继续运行表情待机预览和串口 dry-run，方便在没有硬件时检查界面与协议；点击“停止服务”或按 Ctrl+C 退出，不会静默失败。

权重不进入仓库：把 `yolo11n.pt` 放进 `models/` 即可，默认路径是 `models/yolo11n.pt`，也可以在 `config/default.yaml` 的 `detector.model_path` 中修改。

## 调试控制台

调用 `python -m petbot.main` 后访问 `http://127.0.0.1:8765/`，页面包含：

- 视觉调试：通过 MJPEG 显示摄像头画面和检测框；
- 状态机与目标：显示 IDLE / WATCH / APPROACH / BACKOFF 和当前目标信息；
- 表情窗口：240 × 280 的 pygame 画面通过独立 MJPEG 实时预览；
- 空间仿真：以机器人为中心显示目标方位角、粗估距离和雷达扫描，未接入实时目标时可用“演示轨迹”查看交互效果；
- 实时日志：把 Python logging 同步到浏览器，支持清屏；
- 串口通信：显示 dry-run / 实机、发送帧数和最近一帧十六进制。

页面使用 Python 标准库 `http.server` 和原生 HTML/CSS/JS 实现，不引入 Flask、FastAPI 或前端框架。页面和推流参数在 `config/default.yaml` 的 `ui.dashboard` 中配置。

## 跟踪与状态机

视觉链路依次经过 YOLO 检测、简单 IoU 跟踪和状态机：

- 方位角：目标框中心相对画面中心的水平偏移，结合水平视场角换算成角度，右侧为正；
- 粗估距离：`像素焦距 × 假设身高 ÷ 目标框高度`。像素焦距由水平视场角和画面宽度换算，没有深度相机，**这不是精确测距**，只用于行为决策；
- 跟踪：相邻帧按同类别目标的 IoU 关联，对方位角和距离做低通平滑，短时漏帧允许保留轨迹；
- 状态机：只以配置中的人作为互动目标，猫仍会检测和显示，但不驱动靠近/后退；
- 目标丢失后的三秒缓冲内先停下并保持注视，三秒后回到 IDLE；靠近/后退阈值为 `brain.approach_distance_m` 和 `brain.backoff_distance_m`。

调试台的“状态机”和“目标”面板会随视觉链路实时更新。没有摄像头时这些数据为空，页面仍保留错误提示、日志、表情待机预览、串口 dry-run 和带演示轨迹的空间仿真。

所有距离假设、视场角、平滑系数、速度限制、转向增益和三秒超时都在 `config/default.yaml` 中，不在代码里写死。

## 表情窗口

表情窗口用 pygame 绘制，尺寸和颜色由 `face` 配置控制：

- 输入目标方位角后，瞳孔在眼白范围内平滑追视；右侧为正；
- 随机间隔眨眼，间隔和闭眼时长从配置读取；
- 三种情绪：平静（calm）、好奇（curious）、开心（happy）。好奇会放大瞳孔并抬起眉毛，开心会压低上下眼睑形成眯眼笑；
- 情绪由状态机行为给出：IDLE/BACKOFF 为平静，WATCH 为好奇，APPROACH 为开心；
- 目标丢失后的三秒缓冲期内保持最后朝向，回到 IDLE 后眼睛平滑回中。

## 串口协议

串口帧格式：

```text
AA 55 | 版本(1) | 类型(1) | 序号(2, LE) | 载荷长度(2, LE) | 载荷 | CRC16(2, LE)
```

CRC 使用 CRC-16/CCITT-FALSE（初值 `0xFFFF`、多项式 `0x1021`），覆盖版本号到载荷末尾。载荷长度只统计载荷，不含帧头、固定字段和 CRC。

| 类型 | 名称 | 载荷 |
| --- | --- | --- |
| 0x01 | 底盘速度 | 线速度、角速度，两个 float32 小端 |
| 0x02 | 云台角度 | 水平、俯仰，两个 int16 小端，单位 0.01° |
| 0x03 | 表情指令 | 1 字节：0 平静、1 好奇、2 开心 |
| 0x10 | 状态回报 | 保留类型；协议层可原样拆帧，具体载荷待硬件定义 |

PC 端在每个控制周期发送 0x01、0x02、0x03 三帧，`serial.send_period_s` 默认 0.5 秒。`serial.dry_run: true` 时不打开任何端口，只把完整帧按十六进制写入日志；接实物后关闭 dry-run，程序会通过 pyserial 的 `list_ports` 按 `serial.vid_pid_candidates` 查找端口，不使用固定 COM 号。

协议往返、CRC、分块解析和异常重同步由 `tests/test_protocol.py` 覆盖：

```powershell
python -m pytest -q
```

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
- [x] 阶段 3：方位角、距离估算、跟踪与四状态机
- [x] 阶段 4：表情渲染与眼睛行为
- [x] 阶段 5：串口协议、dry-run 与单元测试

## 约定

- 注释使用中文，说明设计原因；作者署名：敕仞
- 跨平台：使用 `pathlib`，不拼接反斜杠，不调用 shell 命令
- 串口不使用固定 COM 号，通过 pyserial 的 `list_ports` 按 VID/PID 匹配
- 一次里程碑一次提交，提交信息格式为“阶段: 做了什么”
