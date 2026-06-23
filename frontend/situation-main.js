/* 仿真态势页主控 — 后端引擎驱动：WS 态势流、运行控制、异步指令注入、回放分析 */
(function () {
  "use strict";

  /* ---------- 状态 ---------- */
  var S = ScenarioStore.load();
  var status = { state: "idle", t: 0, duration: S.sim.duration, step: S.sim.step, speed: 60 };
  var mode = "live";
  var selected = null;
  var displayT = 0;

  var lastFrame = null;        // {t, entities, recvAt}
  var liveStates = {};         // 最新实体状态（live）
  var histories = {};          // satId -> [{t, alt, spd, att, fuel, pos}]
  var presetEvents = [];       // 场景预设事件（静态标记）
  var liveEvents = [];         // 后端推送的运行事件（预警/机动完成/载荷等）
  var commands = [];           // 注入指令 [{tpl,target,params,t,label,fired}]

  var replay = {
    list: [], recId: null, frames: [], events: [],
    duration: 0, t: 0, playing: false, lastFedT: -1,
    histories: {}, states: {}
  };

  // 预推演缓存（构型分析与 ECI 叠加共用）。实时走后端接口，回放用游标后帧。
  var prediction = {
    horizon: 86400, baseStep: S.sim.step || 1, t0: 0, step_used: 0,
    times: [], tracks: {}, loading: false, error: null, requested: false
  };

  function $(id) { return document.getElementById(id); }

  /* ---------- 事件集合 ---------- */
  function rebuildPresetEvents() {
    presetEvents = (S.events || []).map(function (e) {
      return { t: e.t, type: e.type, target: e.target, text: e.target + " " + e.action };
    });
  }
  function commandEvents() {
    return commands.map(function (c) {
      return { t: c.t, type: "指令", target: c.target, text: c.target + " " + (c.label || c.tpl) };
    });
  }
  function currentEvents() {
    if (mode === "replay") return replay.events;
    return presetEvents.concat(commandEvents(), liveEvents);
  }

  /* ---------- 历史缓冲与采样 ---------- */
  function pushHistory(store, t, entities) {
    Object.keys(entities).forEach(function (id) {
      var st = entities[id];
      if (!st || st.alt_km == null) return;
      var arr = store[id] || (store[id] = []);
      if (arr.length && t <= arr[arr.length - 1].t + 1e-9) return;
      arr.push({
        t: t, alt: st.alt_km, spd: st.speed_kmps,
        att: st.att_dev_deg, fuel: st.fuel_pct, pos: st.pos_km, vel: st.vel_kmps
      });
      if (arr.length > 4000) arr.splice(0, arr.length - 4000);
    });
  }
  function lookup(arr, tk) {
    if (!arr || !arr.length || tk < arr[0].t - 1e-9) return null;
    var lo = 0, hi = arr.length - 1;
    while (lo < hi) {
      var mid = (lo + hi + 1) >> 1;
      if (arr[mid].t <= tk) lo = mid; else hi = mid - 1;
    }
    return arr[lo];
  }
  function sample(satId, field, tk) {
    var store = mode === "replay" ? replay.histories : histories;
    var rec = lookup(store[satId], tk);
    return rec ? rec[field] : null;
  }
  function samplePos(satId, tk) {
    var store = mode === "replay" ? replay.histories : histories;
    var rec = lookup(store[satId], tk);
    return rec && rec.pos ? { x: rec.pos[0], y: rec.pos[1], z: rec.pos[2] } : null;
  }
  function sampleVel(satId, tk) {
    var store = mode === "replay" ? replay.histories : histories;
    var rec = lookup(store[satId], tk);
    return rec && rec.vel ? { x: rec.vel[0], y: rec.vel[1], z: rec.vel[2] } : null;
  }
  function stateOf(id) {
    return (mode === "replay" ? replay.states : liveStates)[id] || null;
  }

  /* ---------- 预推演 ---------- */
  function predictionPosTracks() {
    var out = {};
    Object.keys(prediction.tracks).forEach(function (id) {
      out[id] = prediction.tracks[id].map(function (p) { return p.pos_km; });
    });
    return out;
  }
  function applyOverlay() { SitScene.setPredicted(predictionPosTracks()); }

  function buildReplayPrediction() {
    var t = replay.t, end = t + prediction.horizon;
    var startIdx = frameIndexAt(t);
    if (startIdx < 0) startIdx = 0;
    var tracks = {}, times = [];
    (S.satellites || []).forEach(function (s) { tracks[s.id] = []; });
    for (var k = startIdx; k < replay.frames.length; k++) {
      var f = replay.frames[k];
      if (f.t < t - 1e-9) continue;
      if (f.t > end + 1e-9) break;
      times.push(f.t);
      S.satellites.forEach(function (s) {
        var st = f.entities[s.id] || {};
        tracks[s.id].push({ pos_km: st.pos_km || [], vel_kmps: st.vel_kmps || [] });
      });
    }
    prediction.t0 = t; prediction.times = times; prediction.tracks = tracks;
    prediction.step_used = 0; prediction.loading = false; prediction.error = null;
    applyOverlay();
  }

  function refreshPrediction(horizon) {
    if (horizon != null) prediction.horizon = horizon;
    if (mode === "replay") { prediction.requested = true; buildReplayPrediction(); return; }
    if (status.state === "idle") { prediction.error = "场景未装载"; return; }
    prediction.requested = true;
    prediction.loading = true;
    prediction.baseStep = status.step || S.sim.step || 1;
    SCAPI.get("/api/simulation/predict?horizon=" + prediction.horizon).then(function (res) {
      prediction.t0 = res.t0;
      prediction.times = res.times || [];
      prediction.tracks = res.tracks || {};
      prediction.step_used = res.step_used_s;
      prediction.loading = false;
      prediction.error = null;
      applyOverlay();
      SitPanels.update();
    }).catch(function (e) {
      prediction.loading = false;
      prediction.error = (e && e.message) || "预推演失败";
      SitPanels.update();
    });
  }

  function clearPrediction() {
    prediction.times = []; prediction.tracks = {}; prediction.error = null;
    prediction.loading = false; prediction.requested = false;
    SitScene.setPredicted(null);
  }

  /* ---------- 三维场景 ---------- */
  SitScene.init({
    canvas: $("gl-canvas"),
    labelLayer: $("label-layer"),
    onSelect: function (id) { selectSat(id); }
  });
  SitScene.build(S);
  SitScene.setTime(0);

  /* ---------- 阵营视角（战争迷雾） ---------- */
  var viewFaction = "全局";
  var faction = SitFaction.build({
    scenario: function () { return S; },
    onChange: function (f) {
      viewFaction = f;
      if (mode === "replay") {
        if (replay.recId) loadReplay(replay.recId);   // 回放：按阵营重新拉取
      } else {
        sitConn.setFaction(f === "全局" ? "" : f);     // 实时：声明阵营
      }
    }
  });

  function selectSat(id) {
    selected = selected === id ? null : id;
    SitScene.setSelected(selected);
    SitPanels.renderEntities();
    if (selected) SitPanels.setTeleSat(selected);
  }

  /* ---------- 面板 ---------- */
  var thresholdTimer = null;
  SitPanels.init({
    scenario: function () { return S; },
    getTime: function () { return displayT; },
    getDuration: function () { return mode === "replay" ? (replay.duration || status.duration) : status.duration; },
    getSelected: function () { return selected; },
    getEvents: currentEvents,
    getCommands: function () {
      var t = displayT;
      return commands.map(function (c) { return Object.assign({}, c, { fired: c.t <= t }); });
    },
    sample: sample,
    samplePos: samplePos,
    sampleVel: sampleVel,
    stateOf: stateOf,
    posOf: function (id) { return SitScene.satPos(id); },
    getMode: function () { return mode; },
    getPrediction: function () { return prediction; },
    refreshPrediction: refreshPrediction,
    onSelect: selectSat,
    setAlertThreshold: function (km) {
      clearTimeout(thresholdTimer);
      thresholdTimer = setTimeout(function () {
        SCAPI.post("/api/simulation/alert-threshold", { km: km }).catch(function () {});
      }, 500);
    },
    onInjectCommand: function (req) {
      if (mode === "replay") { scToast("回放模式下不可注入指令，请切回实时仿真", "warn"); return; }
      if (status.state === "idle") { scToast("场景尚未装载", "warn"); return; }
      SCAPI.post("/api/simulation/command", {
        tpl: req.tpl, target: req.target, params: req.params,
        when: req.when, delay: req.delay
      }).then(function (resp) {
        var cmd = resp.command;
        commands.push(cmd);
        scToast((req.when === "now" ? "指令已下发并执行：" : "指令已预约 " + SitPanels.fmtT(cmd.t) + "：") + cmd.label);
        SitPanels.update();
      }).catch(function (e) {
        scToast("指令注入失败：" + (e.message || ""), "danger");
      });
    }
  });

  /* ---------- 运行控制 ---------- */
  function applyStatus(st) {
    var prev = status;
    status = st;
    var playing = st.state === "running";
    $("ctl-play").textContent = playing ? "❚❚ 暂停" : "▶ 开始";
    document.body.classList.toggle("paused", !playing);
    document.querySelectorAll(".spd").forEach(function (b) {
      b.classList.toggle("active", parseFloat(b.getAttribute("data-v")) === st.speed);
    });
    $("repro-chip").textContent = "seed " + (st.seed != null ? st.seed : S.sim.seed) +
      " · 场景 v" + (st.scenario_version || S.meta.version || "?");
    if (st.state === "finished" && prev.state === "running") {
      scToast("仿真到达结束时刻 " + SitPanels.fmtT(st.duration) + "，可切换回放分析");
    }
    // 暂停瞬间刷新预推演，使构型视图与 ECI 叠加对齐当前态势
    if (mode === "live" && prediction.requested && st.state === "paused" && prev.state === "running") {
      refreshPrediction();
    }
  }

  $("ctl-play").onclick = function () {
    if (mode === "replay") { toggleReplayPlay(); return; }
    if (status.state === "idle") { scToast("场景装载中，请稍候", "warn"); return; }
    var api = status.state === "running" ? "/api/simulation/pause" : "/api/simulation/start";
    SCAPI.post(api).then(applyStatus).catch(function (e) {
      scToast("操作失败：" + (e.message || ""), "danger");
    });
  };

  $("ctl-step").onclick = function () {
    if (mode === "replay") { advanceReplayTo(Math.min(replay.t + 10, replay.duration)); return; }
    SCAPI.post("/api/simulation/step", { dt: 10 }).then(applyStatus).catch(function (e) {
      scToast(e.status === 409 ? "运行中无法单步推进，请先暂停" : "单步失败：" + (e.message || ""), "warn");
    });
  };

  $("ctl-reset").onclick = function () {
    if (mode === "replay") { advanceReplayTo(0); return; }
    SCAPI.post("/api/simulation/reset").then(function (st) {
      applyStatus(st);
      histories = {};
      liveEvents = [];
      commands = [];
      SitScene.clearTrails();
      clearPrediction();
      displayT = 0;
      scToast("已复位至 T+0 · 相同种子与指令序列可完整复现本次实验");
      SitPanels.update();
    }).catch(function (e) { scToast("复位失败：" + (e.message || ""), "danger"); });
  };

  document.querySelectorAll(".spd").forEach(function (b) {
    b.onclick = function () {
      var v = parseFloat(b.getAttribute("data-v"));
      document.querySelectorAll(".spd").forEach(function (x) { x.classList.remove("active"); });
      b.classList.add("active");
      if (mode === "replay") { replay.speed = v; return; }
      SCAPI.post("/api/simulation/speed", { speed: v }).then(applyStatus).catch(function () {});
    };
  });

  /* ---------- 模式切换 ---------- */
  $("mode-live").onclick = function () { setMode("live"); };
  $("mode-replay").onclick = function () { setMode("replay"); };

  function setMode(m) {
    if (m === mode) return;
    mode = m;
    clearPrediction();
    $("mode-live").classList.toggle("active", m === "live");
    $("mode-replay").classList.toggle("active", m === "replay");
    $("view-hint").textContent = m === "replay"
      ? "回放模式：拖动时间线跳转 · 全过程确定性复现"
      : "拖拽旋转 · 滚轮缩放 · 点击卫星选中";
    var sel = $("replay-sel");
    if (sel) sel.style.display = m === "replay" ? "" : "none";
    if (m === "replay") {
      if (status.state === "running") SCAPI.post("/api/simulation/pause").then(applyStatus).catch(function () {});
      replay.playing = false;
      loadReplayList();
    } else {
      replay.playing = false;
      SitScene.clearTrails();
      if (lastFrame) {
        SitScene.setEntityFrame(lastFrame.t, lastFrame.entities);
        displayT = lastFrame.t;
      }
      SitPanels.update();
    }
  }

  /* ---------- 回放 ---------- */
  var replaySel = document.createElement("select");
  replaySel.className = "select";
  replaySel.id = "replay-sel";
  replaySel.style.cssText = "display:none;width:auto;max-width:260px;padding:3px 8px;font-size:11.5px;margin-left:10px;";
  var tlHead = document.querySelector(".tl-head .spacer");
  if (tlHead) tlHead.parentNode.insertBefore(replaySel, tlHead);
  replaySel.onchange = function () { loadReplay(replaySel.value); };

  function loadReplayList() {
    SCAPI.get("/api/replays").then(function (list) {
      replay.list = list;
      replaySel.innerHTML = "";
      if (!list.length) {
        scToast("暂无回放录制 — 完整运行一次仿真后自动生成", "warn");
        var op = document.createElement("option");
        op.textContent = "（无录制）";
        replaySel.appendChild(op);
        return;
      }
      list.forEach(function (item) {
        var op = document.createElement("option");
        op.value = item.run_id;
        op.textContent = item.run_id + " · " + item.scenario_name + " · " + Math.round(item.duration_recorded_s) + "s";
        replaySel.appendChild(op);
      });
      loadReplay(list[0].run_id);
    }).catch(function () { scToast("回放列表加载失败", "danger"); });
  }

  function loadReplay(recId) {
    if (!recId) return;
    var q = viewFaction && viewFaction !== "全局" ? "?faction=" + encodeURIComponent(viewFaction) : "";
    SCAPI.get("/api/replays/" + encodeURIComponent(recId) + q).then(function (rec) {
      replay.recId = recId;
      replay.frames = rec.frames || [];
      replay.duration = rec.duration_recorded_s || (replay.frames.length ? replay.frames[replay.frames.length - 1].t : 0);
      replay.events = (rec.events || []).map(function (e) {
        return { t: e.t, type: e.type || "系统", target: e.target, text: e.text };
      });
      replay.histories = {};
      replay.frames.forEach(function (f) { pushHistory(replay.histories, f.t, f.entities); });
      replay.lastFedT = -1;
      advanceReplayTo(0, true);
      scToast("已载入回放 " + recId + "（" + replay.frames.length + " 帧）");
    }).catch(function () { scToast("回放载入失败", "danger"); });
  }

  function frameIndexAt(t) {
    var fr = replay.frames;
    var lo = 0, hi = fr.length - 1;
    if (!fr.length || t < fr[0].t) return -1;
    while (lo < hi) {
      var mid = (lo + hi + 1) >> 1;
      if (fr[mid].t <= t) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  function advanceReplayTo(t, forceRebuild) {
    if (!replay.frames.length) return;
    t = Math.max(0, Math.min(t, replay.duration));
    var jumpBack = t < replay.lastFedT;
    var idx = frameIndexAt(t);
    if (forceRebuild || jumpBack) {
      SitScene.clearTrails();
      // 时间窗内逐帧喂入，重建轨迹
      var windowStart = t - 1200;
      for (var k = 0; k <= idx; k++) {
        var f = replay.frames[k];
        if (f.t >= windowStart) SitScene.setEntityFrame(f.t, f.entities);
      }
    } else {
      for (var k2 = frameIndexAt(replay.lastFedT) + 1; k2 <= idx; k2++) {
        SitScene.setEntityFrame(replay.frames[k2].t, replay.frames[k2].entities);
      }
    }
    if (idx >= 0) replay.states = replay.frames[idx].entities;
    replay.lastFedT = idx >= 0 ? replay.frames[idx].t : -1;
    replay.t = t;
    displayT = t;
    SitScene.setTime(t);
    SitPanels.update();
  }

  function toggleReplayPlay() {
    if (!replay.frames.length) { scToast("请先载入回放录制", "warn"); return; }
    if (replay.t >= replay.duration) replay.t = 0;
    replay.playing = !replay.playing;
    $("ctl-play").textContent = replay.playing ? "❚❚ 暂停" : "▶ 开始";
    document.body.classList.toggle("paused", !replay.playing);
  }

  /* ---------- 时间线拖拽 ---------- */
  var track = $("tl-track");
  function trackSeek(e) {
    var r = track.getBoundingClientRect();
    var pct = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    advanceReplayTo(pct * (replay.duration || status.duration));
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

  /* ---------- 视角模式 ---------- */
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

  /* ---------- WebSocket 接入 ---------- */
  function handleFrame(msg) {
    var data = msg.data;
    // 时间倒退 = 其他端复位/重载：清空运行态缓存
    if (lastFrame && data.t < lastFrame.t - 1e-6) {
      histories = {};
      liveEvents = [];
      SitScene.clearTrails();
      SCAPI.get("/api/simulation/commands").then(function (c) { commands = c; }).catch(function () {});
    }
    lastFrame = { t: data.t, entities: data.entities, recvAt: performance.now() };
    liveStates = data.entities;
    pushHistory(histories, data.t, data.entities);
    (msg.events || []).forEach(function (ev) {
      var src = ev.data && ev.data.source;
      if (src === "event" || src === "command") return; // 静态标记已有，避免重复
      liveEvents.push({ t: ev.t, type: ev.type || "系统", target: ev.target, text: ev.text });
      if (ev.type === "预警") scToast(ev.text, "danger");
    });
    if (liveEvents.length > 800) liveEvents.splice(0, liveEvents.length - 800);
    if (mode === "live") {
      SitScene.setEntityFrame(data.t, data.entities);
    }
  }

  var sitConn = SCAPI.connectSituation({
    onStatus: applyStatus,
    onFrame: handleFrame,
    onClose: function () {
      var box = document.getElementById("nav-sys-status");
      if (box) box.innerHTML = '<span class="dot danger"></span>态势链路断开';
    },
    onOpen: function () {
      var box = document.getElementById("nav-sys-status");
      if (box) box.innerHTML = '<span class="dot ok"></span>系统就绪';
    }
  });

  /* ---------- 时钟 ---------- */
  function updateClock() {
    $("clock-t").textContent = SitPanels.fmtT(displayT);
    var epochMs = Date.parse(S.sim.epoch) || Date.now();
    var d = new Date(epochMs + displayT * 1000);
    $("clock-utc").textContent = d.toISOString().slice(0, 19).replace("T", " ") + " UTC";
  }

  /* ---------- 主循环 ---------- */
  var lastReal = performance.now();
  var lastPanel = 0;
  function loop(now) {
    var dt = Math.min((now - lastReal) / 1000, 0.1);
    lastReal = now;
    if (mode === "live") {
      if (lastFrame) {
        var est = lastFrame.t;
        if (status.state === "running") {
          est += ((now - lastFrame.recvAt) / 1000) * status.speed;
        }
        displayT = Math.min(Math.max(est, 0), status.duration || est);
        SitScene.setTime(displayT);
      }
    } else if (replay.playing) {
      var nt = replay.t + dt * (replay.speed || status.speed || 60);
      if (nt >= replay.duration) {
        nt = replay.duration;
        replay.playing = false;
        $("ctl-play").textContent = "▶ 开始";
        document.body.classList.add("paused");
      }
      advanceReplayTo(nt);
    }
    SitScene.frame();
    updateClock();
    if (now - lastPanel > 200) {
      lastPanel = now;
      SitPanels.update();
    }
  }
  function rafLoop(now) {
    loop(now);
    requestAnimationFrame(rafLoop);
  }

  /* ---------- 启动 ---------- */
  rebuildPresetEvents();
  document.body.classList.add("paused");
  updateClock();
  SitPanels.update();
  SitScene.frame();
  requestAnimationFrame(rafLoop);
  // 隐藏标签页时 rAF 停止，用低频定时器兜底驱动
  setInterval(function () {
    if (document.hidden || document.visibilityState === "hidden") loop(performance.now());
  }, 250);

  function bootstrap() {
    ScenarioStore.pull().then(function (remote) {
      if (remote) {
        S = remote;
        rebuildPresetEvents();
        SitScene.build(S);
        SitPanels.rebuild();
        if (faction) faction.rebuild();
      }
      return SCAPI.get("/api/simulation/status");
    }).then(function (st) {
      var needLoad = st.state === "idle" ||
        st.scenario_name !== S.meta.name ||
        st.scenario_version !== (S.meta.version || "1.0.0");
      if (needLoad) {
        return SCAPI.post("/api/simulation/load").then(function (loaded) {
          applyStatus(loaded);
          scToast("场景已装载至仿真引擎：" + (loaded.scenario_name || ""));
        });
      }
      applyStatus(st);
      displayT = st.t || 0;
      return SCAPI.get("/api/simulation/commands").then(function (c) { commands = c; });
    }).catch(function (e) {
      var detail = e && e.detail;
      if (detail && detail.errors && detail.errors.length) {
        scToast("场景校验未通过：" + detail.errors[0].loc + " " + detail.errors[0].msg, "danger");
      } else {
        scToast("后端未连接，态势页不可用", "danger");
      }
    });
  }
  bootstrap();
})();
