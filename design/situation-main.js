/* 仿真态势页主控 — 状态机、仿真循环、指令注入、回放 */
(function () {
  "use strict";
  var S = ScenarioStore.load();
  var DUR = S.sim.duration;
  var epochMs = Date.parse(S.sim.epoch) || Date.now();

  /* ---------- 状态 ---------- */
  var simT = parseFloat(localStorage.getItem("scsim_simT")) || 0;
  simT = Math.min(Math.max(simT, 0), DUR);
  var playing = false;
  var speedMul = 60;
  var mode = "live";
  var selected = null;
  var commands = [];
  try { commands = JSON.parse(localStorage.getItem("scsim_cmds")) || []; } catch (e) {}
  // 仅保留属于当前场景的指令
  commands = commands.filter(function (c) {
    return S.satellites.some(function (s) { return s.id === c.target; });
  });

  var pristineOrbits = {};
  var pristinePayload = {};
  S.satellites.forEach(function (s) {
    pristineOrbits[s.id] = JSON.parse(JSON.stringify(s.orbit));
    pristinePayload[s.id] = s.payload.state;
  });

  /* ---------- 事件 ---------- */
  var events = (S.events || []).map(function (e) {
    return { t: e.t, type: e.type, target: e.target, text: e.target + " " + e.action };
  });
  commands.forEach(function (c) {
    events.push({ t: c.t, type: "指令", target: c.target, text: c.target + " " + SitPanels.describeCmd(c) });
  });
  var alertSeen = {};

  function $(id) { return document.getElementById(id); }

  /* ---------- 机动与载荷效果（确定性重建，支持任意时间跳转） ---------- */
  function burnsFor(satId) {
    var out = [];
    (S.events || []).forEach(function (e) {
      if (e.type === "机动" && e.target === satId) {
        var m = /Δv\s*=?\s*([\d.]+)/.exec(e.action);
        out.push({ t: e.t, dv: m ? parseFloat(m[1]) : 1.5, dir: /法向/.test(e.action) ? "法向" : "切向", src: "event" });
      }
    });
    commands.forEach(function (c) {
      if (c.tpl === "轨道机动" && c.target === satId) out.push({ t: c.t, dv: c.params.dv || 0, dir: c.params.dir, src: "cmd" });
    });
    out.sort(function (a, b) { return a.t - b.t; });
    return out;
  }

  var lastEffectKey = "";
  function rebuildEffects(t) {
    var key = "";
    S.satellites.forEach(function (sat) {
      var o = JSON.parse(JSON.stringify(pristineOrbits[sat.id]));
      burnsFor(sat.id).forEach(function (b) {
        if (b.t > t) return;
        key += sat.id + b.t + ";";
        if (b.dir === "切向") o.a += b.dv * 2.2;
        else if (b.dir === "法向") o.i = (o.i + b.dv * 0.06) % 180;
        else o.e = Math.min(0.95, Math.max(0, o.e + b.dv * 0.0004));
      });
      // 载荷状态：取 t 之前最后一次载荷指令
      var st = pristinePayload[sat.id];
      commands.forEach(function (c) {
        if (c.tpl === "载荷控制" && c.target === sat.id && c.t <= t) {
          key += sat.id + "p" + c.t + ";";
          st = c.params.act === "关机" ? "关闭" : "开机";
        }
      });
      sat.payload.state = st;
      if (JSON.stringify(sat.orbit) !== JSON.stringify(o)) {
        sat.orbit = o;
        SitScene.applyOrbitChange(sat.id, o);
      }
    });
    lastEffectKey = key;
  }
  function maybeRebuild(t) {
    var key = "";
    S.satellites.forEach(function (sat) {
      burnsFor(sat.id).forEach(function (b) { if (b.t <= t) key += sat.id + b.t + ";"; });
      commands.forEach(function (c) { if (c.tpl === "载荷控制" && c.target === sat.id && c.t <= t) key += sat.id + "p" + c.t + ";"; });
    });
    if (key !== lastEffectKey) rebuildEffects(t);
  }

  /* ---------- 接近预警检测 ---------- */
  window.SitAlertThreshold = 100;
  function detectAlerts(t) {
    var th = window.SitAlertThreshold || 100;
    for (var i = 0; i < S.satellites.length; i++) {
      for (var j = i + 1; j < S.satellites.length; j++) {
        var a = S.satellites[i], b = S.satellites[j];
        var pa = SitScene.eciPos(a.orbit, t), pb = SitScene.eciPos(b.orbit, t);
        var dx = pa.x - pb.x, dy = pa.y - pb.y, dz = pa.z - pb.z;
        var d = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (d < th) {
          var k = a.id + "|" + b.id;
          if (!alertSeen[k]) {
            alertSeen[k] = true;
            events.push({ t: Math.round(t), type: "预警", target: a.id, text: a.id + " ↔ " + b.id + " 接近 " + d.toFixed(0) + " km" });
            scToast("接近预警：" + a.id + " ↔ " + b.id + " 距离 " + d.toFixed(0) + " km", "danger");
          }
        }
      }
    }
  }

  /* ---------- 三维场景 ---------- */
  SitScene.init({
    canvas: $("gl-canvas"),
    labelLayer: $("label-layer"),
    onSelect: function (id) { selectSat(id); }
  });
  SitScene.build(S);
  SitScene.setTime(simT);

  function selectSat(id) {
    selected = selected === id ? null : id;
    SitScene.setSelected(selected);
    SitPanels.renderEntities();
    if (selected) SitPanels.setTeleSat(selected);
  }

  /* ---------- 面板 ---------- */
  SitPanels.init({
    scenario: function () { return S; },
    getTime: function () { return simT; },
    getSelected: function () { return selected; },
    getEvents: function () { return events; },
    getCommands: function () { return commands; },
    getBurns: burnsFor,
    onSelect: selectSat,
    reportAlerts: function () {},
    onInjectCommand: function (req) {
      var t = req.when === "now" ? Math.round(simT) : Math.round(simT + req.delay);
      if (t > DUR) { scToast("执行时刻超出仿真时长", "danger"); return; }
      var cmd = { tpl: req.tpl, target: req.target, params: req.params, t: t };
      commands.push(cmd);
      localStorage.setItem("scsim_cmds", JSON.stringify(commands));
      events.push({ t: t, type: "指令", target: req.target, text: req.target + " " + SitPanels.describeCmd(cmd) });
      scToast((req.when === "now" ? "指令已下发并执行：" : "指令已预约 " + SitPanels.fmtT(t) + "：") + SitPanels.describeCmd(cmd));
      maybeRebuild(simT);
      SitPanels.update();
    }
  });

  /* ---------- 运行控制 ---------- */
  function setPlaying(p) {
    playing = p;
    $("ctl-play").textContent = playing ? "❚❚ 暂停" : "▶ 开始";
    document.body.classList.toggle("paused", !playing);
  }
  $("ctl-play").onclick = function () {
    if (simT >= DUR) simT = 0;
    setPlaying(!playing);
  };
  $("ctl-step").onclick = function () { seek(simT + 10); };
  $("ctl-reset").onclick = function () {
    seek(0);
    setPlaying(false);
    alertSeen = {};
    // 移除运行期产生的预警事件，预设事件与指令保留 —— 同种子同指令序列可逐位复现
    events = events.filter(function (e) { return e.type !== "预警"; });
    scToast("已复位至 T+0 · 相同种子与指令序列可完整复现本次实验");
    SitPanels.update();
  };
  document.querySelectorAll(".spd").forEach(function (b) {
    b.onclick = function () {
      document.querySelectorAll(".spd").forEach(function (x) { x.classList.remove("active"); });
      b.classList.add("active");
      speedMul = parseFloat(b.getAttribute("data-v"));
    };
  });

  /* 模式切换 */
  $("mode-live").onclick = function () { setMode("live"); };
  $("mode-replay").onclick = function () { setMode("replay"); };
  function setMode(m) {
    mode = m;
    $("mode-live").classList.toggle("active", m === "live");
    $("mode-replay").classList.toggle("active", m === "replay");
    $("view-hint").textContent = m === "replay"
      ? "回放模式：拖动时间线跳转 · 全过程确定性复现"
      : "拖拽旋转 · 滚轮缩放 · 点击卫星选中";
    if (m === "replay") setPlaying(false);
  }

  /* 时间线拖拽 */
  var track = $("tl-track");
  function trackSeek(e) {
    var r = track.getBoundingClientRect();
    var pct = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    seek(pct * DUR);
  }
  var dragging = false;
  track.addEventListener("pointerdown", function (e) {
    if (mode !== "replay") {
      scToast("切换到「回放分析」模式后可拖动时间线", "warn");
      return;
    }
    dragging = true;
    track.setPointerCapture(e.pointerId);
    trackSeek(e);
  });
  track.addEventListener("pointermove", function (e) { if (dragging) trackSeek(e); });
  track.addEventListener("pointerup", function () { dragging = false; });

  function seek(t) {
    simT = Math.min(Math.max(t, 0), DUR);
    maybeRebuild(simT);
    SitScene.setTime(simT);
    SitPanels.update();
    persistT();
  }

  /* 视角模式 */
  document.querySelectorAll(".vm").forEach(function (b) {
    b.onclick = function () {
      document.querySelectorAll(".vm").forEach(function (x) { x.classList.remove("active"); });
      b.classList.add("active");
      var m = b.getAttribute("data-m");
      if (m !== "global" && !selected) {
        scToast("请先点击选中一颗卫星", "warn");
        selected = S.satellites[0].id;
        SitScene.setSelected(selected);
        SitPanels.renderEntities();
      }
      SitScene.setViewMode(m);
    };
  });

  /* ---------- 时钟 ---------- */
  function updateClock() {
    $("clock-t").textContent = SitPanels.fmtT(simT);
    var d = new Date(epochMs + simT * 1000);
    $("clock-utc").textContent = d.toISOString().slice(0, 19).replace("T", " ") + " UTC";
  }
  $("repro-chip").textContent = "seed " + S.sim.seed + " · 场景 v" + (S.meta.version || "?");

  var persistTimer = 0;
  function persistT() {
    localStorage.setItem("scsim_simT", String(simT));
  }

  /* ---------- 主循环 ---------- */
  var lastReal = performance.now();
  var lastPanel = 0, lastAlert = 0;
  function loop(now) {
    var dt = Math.min((now - lastReal) / 1000, 0.1);
    lastReal = now;
    if (playing && mode === "live") {
      simT += dt * speedMul;
      if (simT >= DUR) {
        simT = DUR;
        setPlaying(false);
        scToast("仿真到达结束时刻 " + SitPanels.fmtT(DUR) + "，可切换回放分析");
      }
      maybeRebuild(simT);
      SitScene.setTime(simT);
    }
    SitScene.frame();
    updateClock();
    if (now - lastPanel > 200) {
      lastPanel = now;
      SitPanels.update();
    }
    if (playing && now - lastAlert > 500) {
      lastAlert = now;
      detectAlerts(simT);
    }
    if (now - persistTimer > 1000) {
      persistTimer = now;
      persistT();
    }
  }
  function rafLoop(now) {
    loop(now);
    requestAnimationFrame(rafLoop);
  }
  maybeRebuild(simT);
  SitScene.setTime(simT);
  setPlaying(false);
  updateClock();
  SitPanels.update();
  SitScene.frame(); // 同步渲染首帧，保证隐藏环境/截图下也有画面
  requestAnimationFrame(rafLoop);
  // rAF 在隐藏标签页中不触发，用低频定时器兜底驱动
  setInterval(function () {
    if (document.hidden || document.visibilityState === "hidden") loop(performance.now());
  }, 250);

  /* ---------- 供 Tweaks 调用 ---------- */
  window.SitMain = {
    setAccent: function (hex) {
      document.documentElement.style.setProperty("--accent", hex);
      document.documentElement.style.setProperty("--accent-strong", hex);
      document.documentElement.style.setProperty("--accent-soft", hex + "22");
    },
    setTweaks: function (t) { SitScene.setTweaks(t); }
  };
})();
