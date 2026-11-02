(() => {
  "use strict";

  const POLL_INTERVAL_MS = 500;
  const MAX_LOG_LINES = 600;
  const STATE_LABELS = {
    IDLE: "待机",
    WATCH: "注视目标",
    APPROACH: "靠近目标",
    BACKOFF: "后退避让",
  };

  const byId = (id) => document.getElementById(id);

  const ui = {
    connectionDot: byId("connectionDot"),
    connectionText: byId("connectionText"),
    modePill: byId("modePill"),
    uptime: byId("uptime"),
    fps: byId("fps"),
    stopButton: byId("stopButton"),
    cameraVital: byId("cameraVital"),
    cameraVitalSub: byId("cameraVitalSub"),
    cameraLed: byId("cameraLed"),
    detectorVital: byId("detectorVital"),
    detectorVitalSub: byId("detectorVitalSub"),
    detectorLed: byId("detectorLed"),
    stateVital: byId("stateVital"),
    stateVitalSub: byId("stateVitalSub"),
    serialVital: byId("serialVital"),
    serialVitalSub: byId("serialVitalSub"),
    serialLed: byId("serialLed"),
    visionStage: byId("visionStage"),
    visionStream: byId("visionStream"),
    visionSource: byId("visionSource"),
    visionBadge: byId("visionBadge"),
    detectionCount: byId("detectionCount"),
    cameraError: byId("cameraError"),
    resolutionValue: byId("resolutionValue"),
    cameraIndexValue: byId("cameraIndexValue"),
    modelValue: byId("modelValue"),
    deviceValue: byId("deviceValue"),
    stateName: byId("stateName"),
    stateLabel: byId("stateLabel"),
    stateOrb: byId("stateOrb"),
    stateChips: [...document.querySelectorAll(".state-chip")],
    behaviorNote: byId("behaviorNote"),
    targetKind: byId("targetKind"),
    targetConfidence: byId("targetConfidence"),
    targetBearing: byId("targetBearing"),
    targetDistance: byId("targetDistance"),
    demoToggle: byId("demoToggle"),
    demoBadge: byId("demoBadge"),
    simCanvas: byId("simCanvas"),
    logList: byId("logList"),
    logCount: byId("logCount"),
    clearLogs: byId("clearLogs"),
    serialMode: byId("serialMode"),
    serialSent: byId("serialSent"),
    serialLink: byId("serialLink"),
    lastFrame: byId("lastFrame"),
    versionText: byId("versionText"),
  };

  const sim = {
    context: ui.simCanvas.getContext("2d"),
    width: 0,
    height: 0,
    dpr: 1,
    demo: true,
    touched: false,
    liveTarget: null,
    heading: 0,
    lastTime: performance.now(),
  };

  const counters = {
    frames: 0,
    fpsTime: performance.now(),
    logged: 0,
  };

  let lastLogId = 0;
  let stateBusy = false;
  let logsBusy = false;
  let streamAttached = false;

  function setText(element, value) {
    if (element && element.textContent !== value) {
      element.textContent = value;
    }
  }

  function setTextById(id, value) {
    setText(byId(id), value);
  }

  function setLed(element, state) {
    if (!element) return;
    element.classList.remove("on", "warn", "error");
    if (state) element.classList.add(state);
  }

  function formatUptime(totalSeconds) {
    const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const rest = seconds % 60;
    if (hours > 0) {
      return [hours, minutes, rest].map((item) => String(item).padStart(2, "0")).join(":");
    }
    return [minutes, rest].map((item) => String(item).padStart(2, "0")).join(":");
  }

  function formatNumber(value, digits, suffix) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "—";
    }
    return Number(value).toFixed(digits) + (suffix || "");
  }

  function formatMode(mode) {
    switch (mode) {
      case "live":
        return ["LIVE", "pill-live"];
      case "no_camera":
        return ["NO CAMERA", "pill-error"];
      case "error":
        return ["ERROR", "pill-error"];
      case "stopping":
        return ["STOPPING", "pill-warn"];
      case "starting":
        return ["STARTING", "pill-warn"];
      default:
        return [String(mode || "UNKNOWN").toUpperCase(), "pill-muted"];
    }
  }

  function setOnline(online) {
    ui.connectionDot.classList.toggle("offline", !online);
    setText(ui.connectionText, online ? "调试台已连接" : "连接中断");
  }

  function applyMode(mode) {
    const [label, className] = formatMode(mode);
    ui.modePill.className = "pill " + className;
    setText(ui.modePill, label);
    document.body.dataset.mode = mode || "unknown";
  }

  function applyCamera(camera) {
    const connected = camera.state === "connected";
    const failed = camera.state === "error";
    const starting = camera.state === "starting";

    setText(ui.cameraVital, connected ? "已连接" : failed ? "不可用" : "探测中");
    setText(
      ui.cameraVitalSub,
      connected
        ? `索引 ${camera.index ?? "—"} · ${camera.width ?? "—"}×${camera.height ?? "—"}`
        : failed
          ? "未找到可用设备"
          : "等待自动探测",
    );
    setLed(ui.cameraLed, connected ? "on" : failed ? "error" : "warn");

    setText(
      ui.visionSource,
      connected
        ? `CAM ${camera.index ?? "—"} / ${camera.width ?? "—"}×${camera.height ?? "—"}`
        : "摄像头 —",
    );
    setText(ui.resolutionValue, connected ? `${camera.width} × ${camera.height}` : "—");
    setText(ui.cameraIndexValue, connected ? String(camera.index) : "—");
    setText(ui.visionBadge, connected ? "LIVE" : failed ? "NO CAMERA" : "WAITING");

    if (connected) {
      ui.visionStage.classList.add("live");
      if (!streamAttached) {
        ui.visionStream.src = "/stream.mjpg?t=" + Date.now();
        streamAttached = true;
      }
    } else {
      ui.visionStage.classList.remove("live");
      if (streamAttached) {
        ui.visionStream.removeAttribute("src");
        streamAttached = false;
      }
      setText(
        ui.cameraError,
        failed
          ? camera.error || "摄像头不可用。请检查连接后重启项目。"
          : starting
            ? "正在探测摄像头，请稍候…"
            : "摄像头未连接。",
      );
    }
  }

  function applyDetector(detector) {
    const ready = detector.state === "ready";
    const failed = detector.state === "error";
    const skipped = detector.state === "skipped";

    setText(
      ui.detectorVital,
      ready ? "YOLO 就绪" : failed ? "加载失败" : skipped ? "未启动" : "初始化中",
    );
    setText(
      ui.detectorVitalSub,
      ready
        ? `${detector.model || "模型"} · ${detector.device || "—"}`
        : failed
          ? "检查权重与依赖"
          : skipped
            ? "等待摄像头"
            : "等待模型加载",
    );
    setLed(ui.detectorLed, ready ? "on" : failed ? "error" : skipped ? "" : "warn");
    setText(ui.modelValue, detector.model || "—");
    setText(ui.deviceValue, detector.device || "—");
  }

  function applyBehavior(behavior, visionItems) {
    const state = behavior.available ? behavior.state || "IDLE" : "IDLE";
    const label = STATE_LABELS[state] || "未知状态";
    const target = pickTarget(behavior, visionItems);

    sim.liveTarget = target;

    setText(ui.stateName, state);
    setText(ui.stateLabel, label);
    setText(ui.stateVital, state);
    setText(ui.stateVitalSub, label);
    setText(ui.targetKind, target ? target.kind : "—");
    setText(ui.targetConfidence, target ? formatNumber(target.conf, 2) : "—");
    setText(ui.targetBearing, target ? formatNumber(target.bearing_deg, 1, "°") : "—");
    setText(ui.targetDistance, target ? formatNumber(target.distance_m, 2, " m") : "—");

    for (const chip of ui.stateChips) {
      chip.classList.toggle("active", chip.dataset.state === state);
    }
    ui.stateOrb.className = "state-orb " + state.toLowerCase();

    if (!behavior.available) {
      ui.behaviorNote.style.display = "";
      setText(ui.behaviorNote, "状态机在阶段 3 接入；当前仅展示视觉检测。");
    } else {
      ui.behaviorNote.style.display = "none";
    }

    if (!sim.touched) {
      ui.demoToggle.checked = !target;
      sim.demo = ui.demoToggle.checked;
    }
  }

  function pickTarget(behavior, visionItems) {
    if (behavior && behavior.target) {
      return behavior.target;
    }
    const items = Array.isArray(visionItems) ? visionItems : [];
    return (
      items.find(
        (item) =>
          item.bearing_deg !== null &&
          item.bearing_deg !== undefined &&
          item.distance_m !== null &&
          item.distance_m !== undefined,
      ) || null
    );
  }

  function applySerial(serial) {
    const available = Boolean(serial.available);
    setText(ui.serialVital, available ? (serial.dry_run ? "DRY-RUN" : "LIVE") : "待接入");
    setText(
      ui.serialVitalSub,
      available ? `已发送 ${serial.sent} 帧` : "dry-run · 阶段 5",
    );
    setLed(ui.serialLed, available ? (serial.dry_run ? "warn" : "on") : "");
    ui.serialMode.className = "pill " + (available ? (serial.dry_run ? "pill-warn" : "pill-live") : "pill-muted");
    setText(ui.serialMode, available ? (serial.dry_run ? "DRY-RUN" : "LIVE") : "PENDING");
    setText(ui.serialSent, String(serial.sent || 0));
    setText(ui.serialLink, available ? (serial.dry_run ? "回环打印" : "已连接") : "未接入");

    if (serial.last_hex) {
      setText(ui.lastFrame, serial.last_hex);
    } else {
      setText(ui.lastFrame, "尚无串口帧\n串口协议与 dry-run 在阶段 5 接入。");
    }
  }

  function applyVision(vision) {
    const frames = Number(vision.frames) || 0;
    const now = performance.now();
    const elapsed = (now - counters.fpsTime) / 1000;
    const delta = frames - counters.frames;

    if (elapsed >= 0.5) {
      const current = delta > 0 ? delta / elapsed : 0;
      const previous = Number(ui.fps.textContent) || 0;
      const smooth = previous * 0.35 + current * 0.65;
      setText(ui.fps, (delta > 0 ? smooth : 0).toFixed(1));
      counters.frames = frames;
      counters.fpsTime = now;
    }

    setText(ui.detectionCount, `${vision.detections || 0} 个目标`);
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("HTTP " + response.status);
    }
    return response.json();
  }

  async function refreshState() {
    if (stateBusy) return;
    stateBusy = true;
    try {
      const data = await fetchJson("/api/state");
      applyMode(data.app.mode);
      setText(ui.uptime, formatUptime(data.app.uptime_s));
      setText(ui.versionText, "v" + (data.app.version || "0.1.0"));
      applyCamera(data.camera || {});
      applyDetector(data.detector || {});
      applyBehavior(data.behavior || {}, data.vision ? data.vision.items : []);
      applySerial(data.serial || {});
      applyVision(data.vision || {});
      setOnline(true);
    } catch (error) {
      setOnline(false);
    } finally {
      stateBusy = false;
    }
  }

  function ensureLogPlaceholder() {
    const placeholder = ui.logList.querySelector(".log-empty");
    if (placeholder) placeholder.remove();
  }

  function appendLog(entry) {
    ensureLogPlaceholder();
    const nearBottom =
      ui.logList.scrollTop + ui.logList.clientHeight >= ui.logList.scrollHeight - 38;

    const line = document.createElement("div");
    line.className = "log-line " + String(entry.level || "INFO").toLowerCase();

    const time = document.createElement("span");
    time.className = "log-time";
    time.textContent = entry.time || "--:--:--";

    const level = document.createElement("span");
    level.className = "log-level " + String(entry.level || "INFO").toLowerCase();
    level.textContent = entry.level || "INFO";

    const message = document.createElement("span");
    message.className = "log-message";
    const source = document.createElement("span");
    source.className = "log-name";
    source.textContent = (entry.name || "petbot") + " · ";
    message.append(source, document.createTextNode(entry.message || ""));

    line.append(time, level, message);
    ui.logList.append(line);

    while (ui.logList.childElementCount > MAX_LOG_LINES) {
      ui.logList.firstElementChild.remove();
    }

    if (nearBottom) {
      ui.logList.scrollTop = ui.logList.scrollHeight;
    }
  }

  async function refreshLogs() {
    if (logsBusy) return;
    logsBusy = true;
    try {
      const data = await fetchJson("/api/logs?after=" + encodeURIComponent(lastLogId));
      if (Array.isArray(data.logs) && data.logs.length > 0) {
        for (const entry of data.logs) {
          appendLog(entry);
        }
        counters.logged += data.logs.length;
        setText(ui.logCount, `${counters.logged} 行`);
      }
      if (typeof data.next === "number") {
        lastLogId = Math.max(lastLogId, data.next);
      }
    } catch (error) {
      // 状态轮询负责显示连接状态，这里不重复刷错误，避免日志风暴。
    } finally {
      logsBusy = false;
    }
  }

  function resizeCanvas() {
    const rect = ui.simCanvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    if (width === sim.width && height === sim.height && dpr === sim.dpr) {
      return;
    }
    sim.width = width;
    sim.height = height;
    sim.dpr = dpr;
    ui.simCanvas.width = Math.round(width * dpr);
    ui.simCanvas.height = Math.round(height * dpr);
    sim.context.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function angleLerp(current, target, amount) {
    let delta = ((target - current + 540) % 360) - 180;
    return current + delta * amount;
  }

  function drawSimulation(now) {
    resizeCanvas();
    const ctx = sim.context;
    const width = sim.width;
    const height = sim.height;
    if (!width || !height) return;

    const dt = Math.min(0.05, (now - sim.lastTime) / 1000);
    sim.lastTime = now;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#071015";
    ctx.fillRect(0, 0, width, height);

    const cx = width / 2;
    const cy = height * 0.55;
    const range = Math.max(1.8, Math.min(width, height) * 0.006);
    const scale = Math.min(width, height) / 2 / range;

    ctx.save();
    ctx.translate(cx, cy);

    ctx.strokeStyle = "rgba(92, 130, 148, 0.16)";
    ctx.lineWidth = 1;
    for (let i = 1; i <= 3; i += 1) {
      ctx.beginPath();
      ctx.arc(0, 0, scale * i, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = "rgba(130, 158, 171, 0.4)";
      ctx.font = '9px "Cascadia Code", Consolas, monospace';
      ctx.fillText(i + "m", 3, -scale * i + 10);
    }

    ctx.beginPath();
    ctx.moveTo(-width, 0);
    ctx.lineTo(width, 0);
    ctx.moveTo(0, -height);
    ctx.lineTo(0, height);
    ctx.strokeStyle = "rgba(92, 130, 148, 0.1)";
    ctx.stroke();

    const liveTarget = sim.liveTarget;
    const useLive = Boolean(liveTarget) && !sim.demo;
    let target = null;
    if (useLive) {
      target = {
        kind: liveTarget.kind || "person",
        bearing: Number(liveTarget.bearing_deg) || 0,
        distance: Number(liveTarget.distance_m) || 0,
        conf: Number(liveTarget.conf) || 0,
      };
    } else if (sim.demo) {
      const t = now / 1000;
      target = {
        kind: "person",
        bearing: 38 * Math.sin(t * 0.38),
        distance: 1.55 + 0.72 * Math.sin(t * 0.54),
        conf: 0,
      };
    }

    const sweep = (now / 2400) % (Math.PI * 2);
    const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, scale * 3);
    gradient.addColorStop(0, "rgba(93, 225, 193, 0.07)");
    gradient.addColorStop(1, "rgba(93, 225, 193, 0)");
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.arc(0, 0, scale * 3, sweep - 0.15, sweep);
    ctx.closePath();
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(Math.sin(sweep) * scale * 3, -Math.cos(sweep) * scale * 3);
    ctx.strokeStyle = "rgba(93, 225, 193, 0.16)";
    ctx.stroke();

    const desiredHeading = target ? target.bearing : Math.sin(now / 4000) * 18;
    sim.heading = angleLerp(sim.heading, desiredHeading, Math.min(1, dt * 2.5));
    const headingRad = (sim.heading * Math.PI) / 180;

    ctx.fillStyle = "rgba(93, 225, 193, 0.035)";
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.arc(0, 0, scale * 2.1, headingRad - Math.PI * 0.16 - Math.PI / 2, headingRad + Math.PI * 0.16 - Math.PI / 2);
    ctx.closePath();
    ctx.fill();

    if (target) {
      const angle = (target.bearing * Math.PI) / 180;
      const tx = Math.sin(angle) * target.distance * scale;
      const ty = -Math.cos(angle) * target.distance * scale;
      const targetColor = target.kind === "cat" ? "#f4b860" : "#6fb7ff";

      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(tx, ty);
      ctx.strokeStyle = "rgba(111, 183, 255, 0.23)";
      ctx.setLineDash([4, 6]);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = targetColor;
      ctx.shadowColor = targetColor;
      ctx.shadowBlur = 13;
      ctx.beginPath();
      ctx.arc(tx, ty, 5.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.strokeStyle = targetColor + "88";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(tx, ty, 12, 0, Math.PI * 2);
      ctx.stroke();

      ctx.fillStyle = "#b8d5e6";
      ctx.font = '10px "Cascadia Code", Consolas, monospace';
      const label = target.kind + "  " + target.distance.toFixed(1) + "m";
      ctx.fillText(label, tx + 16, ty - 10);
      ctx.fillStyle = "rgba(143, 164, 180, 0.75)";
      ctx.font = '9px "Cascadia Code", Consolas, monospace';
      ctx.fillText(target.bearing.toFixed(0) + "°", tx + 16, ty + 3);
    }

    const robotX = Math.sin(headingRad) * 12;
    const robotY = -Math.cos(headingRad) * 12;
    ctx.fillStyle = "#122c32";
    ctx.strokeStyle = "#5de1c1";
    ctx.lineWidth = 1.5;
    ctx.shadowColor = "rgba(93, 225, 193, 0.55)";
    ctx.shadowBlur = 16;
    ctx.beginPath();
    ctx.arc(0, 0, 15, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.shadowBlur = 0;

    ctx.fillStyle = "#5de1c1";
    ctx.beginPath();
    ctx.arc(robotX, robotY, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = '9px "Cascadia Code", Consolas, monospace';
    ctx.fillStyle = "rgba(143, 164, 180, 0.8)";
    ctx.fillText("PET", 22, 3);

    ctx.restore();

    if (!target && !sim.demo) {
      ctx.fillStyle = "rgba(143, 164, 180, 0.52)";
      ctx.font = '11px "Segoe UI", "Microsoft YaHei UI", sans-serif';
      ctx.textAlign = "center";
      ctx.fillText("等待目标进入视野", width / 2, height - 20);
      ctx.textAlign = "start";
    }

    ui.demoBadge.style.display = sim.demo ? "inline-block" : "none";
    requestAnimationFrame(drawSimulation);
  }

  function bindEvents() {
    ui.demoToggle.addEventListener("change", () => {
      sim.touched = true;
      sim.demo = ui.demoToggle.checked;
      ui.demoBadge.style.display = sim.demo ? "inline-block" : "none";
    });

    ui.clearLogs.addEventListener("click", () => {
      ui.logList.replaceChildren();
      const empty = document.createElement("div");
      empty.className = "log-empty";
      empty.textContent = "视图已清空；新日志会继续出现在这里。";
      ui.logList.append(empty);
      counters.logged = 0;
      setText(ui.logCount, "0 行");
    });

    ui.stopButton.addEventListener("click", async () => {
      ui.stopButton.disabled = true;
      ui.stopButton.textContent = "停止中…";
      try {
        await fetch("/api/shutdown", { method: "POST" });
        setText(ui.connectionText, "服务正在停止");
      } catch (error) {
        ui.stopButton.disabled = false;
        ui.stopButton.textContent = "停止服务";
        setText(ui.connectionText, "停止请求失败，请使用 Ctrl+C");
      }
    });
  }

  bindEvents();

  const observer = new ResizeObserver(() => resizeCanvas());
  observer.observe(ui.simCanvas.parentElement);
  resizeCanvas();
  requestAnimationFrame(drawSimulation);

  refreshState();
  refreshLogs();
  setInterval(refreshState, POLL_INTERVAL_MS);
  setInterval(refreshLogs, POLL_INTERVAL_MS);
})();
