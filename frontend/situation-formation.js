/* 构型分析（LVLH/RIC 相对运动视图）。
   以参考星 A 的本体坐标系（径向 R / 迹向 T / 法向 N）为原点，绘目标星 B 的
   已运行相对航迹（实线）与预推演相对航迹（虚线）。每个采样点用该时刻 A 的 r,v
   构建瞬时坐标系，得到经典相对运动轨迹。
   历史取自主控历史缓冲；预测取自后端预推演（实时）或回放游标后帧（回放）。 */
(function () {
  "use strict";
  var ctx = null;
  var refId = null, tgtId = null;
  var horizonS = 86400;
  var lastReplayPredT = null;
  var HIST_MAX_PTS = 1200;

  var HORIZONS = [
    { label: "1 小时", s: 3600 },
    { label: "6 小时", s: 21600 },
    { label: "12 小时", s: 43200 },
    { label: "1 天", s: 86400 },
    { label: "3 天", s: 259200 }
  ];

  function $(id) { return document.getElementById(id); }
  function h(tag, cls, html) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (html !== undefined) el.innerHTML = html;
    return el;
  }

  /* ---------- 向量与 LVLH ---------- */
  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function cross(a, b) {
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  }
  function norm(a) { var m = Math.sqrt(dot(a, a)) || 1; return [a[0] / m, a[1] / m, a[2] / m]; }
  function obj2arr(p) { return p ? [p.x, p.y, p.z] : null; }
  function factionOf(id) {
    var s = ctx.scenario().satellites.find(function (x) { return x.id === id; });
    return s ? s.faction : "";
  }

  /* 目标 rB 在参考星 (rA,vA) 的 RIC 系下的相对坐标（km）。 */
  function lvlh(rA, vA, rB) {
    var Rhat = norm(rA);
    var Nhat = norm(cross(rA, vA));
    var That = cross(Nhat, Rhat);
    var d = sub(rB, rA);
    return { R: dot(d, Rhat), T: dot(d, That), N: dot(d, Nhat) };
  }

  /* ---------- 数据采集 ---------- */
  function historyTrack() {
    var t = ctx.getTime();
    if (t <= 0) return [];
    var n = Math.min(HIST_MAX_PTS, Math.max(2, Math.round(t)));
    var pts = [];
    for (var k = 0; k <= n; k++) {
      var tk = (t * k) / n;
      var rA = obj2arr(ctx.samplePos(refId, tk));
      var vA = obj2arr(ctx.sampleVel(refId, tk));
      var rB = obj2arr(ctx.samplePos(tgtId, tk));
      if (!rA || !vA || !rB) continue;
      pts.push(lvlh(rA, vA, rB));
    }
    return pts;
  }

  function predictionTrack() {
    var pred = ctx.getPrediction();
    if (!pred || !pred.tracks || !pred.tracks[refId] || !pred.tracks[tgtId]) return [];
    var A = pred.tracks[refId], B = pred.tracks[tgtId];
    var pts = [];
    for (var k = 0; k < A.length && k < B.length; k++) {
      var rA = A[k].pos_km, vA = A[k].vel_kmps, rB = B[k].pos_km;
      if (!rA || rA.length < 3 || !vA || vA.length < 3 || !rB || rB.length < 3) continue;
      pts.push(lvlh(rA, vA, rB));
    }
    return pts;
  }

  function currentRel() {
    var rA = obj2arr(ctx.posOf(refId)), rB = obj2arr(ctx.posOf(tgtId));
    var sa = ctx.stateOf(refId), sb = ctx.stateOf(tgtId);
    if (!rA || !rB || !sa || !sb || !sa.vel_kmps || !sb.vel_kmps) return null;
    var vA = sa.vel_kmps, vB = sb.vel_kmps;
    var rel = sub(rB, rA), relV = sub(vB, vA);
    var dist = Math.sqrt(dot(rel, rel));
    var rate = dist < 1e-6 ? 0 : dot(rel, relV) / dist;
    var frame = lvlh(rA, vA, rB);
    // 星间通视：连线与地球最近点 > 地球半径
    var len2 = dot(rel, rel);
    var tt = len2 < 1e-9 ? 0 : Math.max(0, Math.min(1, -dot(rA, rel) / len2));
    var c = [rA[0] + rel[0] * tt, rA[1] + rel[1] * tt, rA[2] + rel[2] * tt];
    var vis = Math.sqrt(dot(c, c)) > SitScene.EARTH_R;
    return { dist: dist, rate: rate, R: frame.R, T: frame.T, N: frame.N, vis: vis };
  }

  /* ---------- 画布渲染 ---------- */
  function drawPlot(hist, pred, cur) {
    var cv = $("formation-canvas");
    if (!cv) return;
    var dpr = Math.min(window.devicePixelRatio, 2);
    var w = cv.clientWidth, hh = cv.clientHeight;
    if (!w || !hh) return;
    if (cv.width !== w * dpr) { cv.width = w * dpr; cv.height = hh * dpr; }
    var g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, hh);

    var all = hist.concat(pred);
    if (cur) all.push({ T: cur.T, R: cur.R });
    var mt = 0, mr = 0;
    all.forEach(function (p) { mt = Math.max(mt, Math.abs(p.T)); mr = Math.max(mr, Math.abs(p.R)); });
    var ext = Math.max(mt, mr, 0.5) * 1.15;  // 等比，保持构型形状不失真
    var pad = 26;
    var cx = w / 2, cy = hh / 2;
    var sc = Math.min(w - 2 * pad, hh - 2 * pad) / (2 * ext);
    function X(T) { return cx + T * sc; }
    function Y(R) { return cy - R * sc; }

    // 网格 + 轴
    g.strokeStyle = "oklch(0.30 0.015 255)";
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(pad, cy); g.lineTo(w - pad, cy);
    g.moveTo(cx, pad); g.lineTo(cx, hh - pad);
    g.stroke();
    g.fillStyle = "oklch(0.55 0.012 255)";
    g.font = "10px 'IBM Plex Mono'";
    g.fillText("+T 迹向", w - pad - 44, cy - 6);
    g.fillText("+R 径向", cx + 6, pad + 10);
    g.fillText("(km)", cx + 6, hh - pad - 4);

    function poly(pts, style, dash) {
      if (pts.length < 2) return;
      g.strokeStyle = style;
      g.lineWidth = 1.8;
      g.setLineDash(dash || []);
      g.beginPath();
      pts.forEach(function (p, i) {
        var x = X(p.T), y = Y(p.R);
        if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
      });
      g.stroke();
      g.setLineDash([]);
    }
    var tgtColor = SitScene.factionColor(factionOf(tgtId));
    poly(hist, tgtColor, []);
    poly(pred, tgtColor, [2, 5]);

    // 参考星 A（原点）
    var refColor = SitScene.factionColor(factionOf(refId));
    g.fillStyle = refColor;
    g.beginPath(); g.arc(cx, cy, 4.5, 0, Math.PI * 2); g.fill();
    g.strokeStyle = refColor; g.globalAlpha = 0.5;
    g.beginPath(); g.arc(cx, cy, 8, 0, Math.PI * 2); g.stroke();
    g.globalAlpha = 1;

    // 目标星 B 当前位置
    if (cur) {
      g.fillStyle = tgtColor;
      g.beginPath(); g.arc(X(cur.T), Y(cur.R), 4, 0, Math.PI * 2); g.fill();
    }
  }

  /* ---------- 面板 ---------- */
  function setReadout(cur) {
    var pred = ctx.getPrediction();
    function fmtKm(d) { return d == null ? "—" : (d >= 1000 ? (d / 1000).toFixed(2) + " Mm" : d.toFixed(2) + " km"); }
    $("fm-dist").textContent = cur ? fmtKm(cur.dist) : "—";
    $("fm-rate").textContent = cur ? (cur.rate > 0 ? "+" : "") + cur.rate.toFixed(3) + " km/s" : "—";
    $("fm-dr").textContent = cur ? cur.R.toFixed(2) + " km" : "—";
    $("fm-dt").textContent = cur ? cur.T.toFixed(2) + " km" : "—";
    $("fm-dn").textContent = cur ? cur.N.toFixed(2) + " km" : "—";
    $("fm-vis").textContent = cur ? (cur.vis ? "通视" : "遮挡") : "—";
    $("fm-vis-card").className = "geo-card" + (cur ? (cur.vis ? " vis-ok" : " vis-no") : "");
    var st = $("fm-status");
    if (pred && pred.loading) st.textContent = "预推演计算中…";
    else if (pred && pred.error) st.textContent = "预推演失败：" + pred.error;
    else if (pred && pred.times && pred.times.length) {
      var hrs = (pred.horizon / 3600).toFixed(pred.horizon % 3600 ? 1 : 0);
      var stepNote = pred.step_used > (pred.baseStep || 1) + 1e-6
        ? "（步长 " + pred.step_used.toFixed(1) + " s）" : "";
      st.textContent = "预推演 " + hrs + " h" + stepNote + " · " + pred.times.length + " 点";
    } else st.textContent = "尚未预推演 — 点「刷新预推演」生成";
  }

  function build() {
    var el = $("tab-formation");
    if (!el) return;
    el.innerHTML = "";
    var S = ctx.scenario();
    if (!S.satellites.length) return;
    if (!refId || !S.satellites.some(function (s) { return s.id === refId; })) refId = S.satellites[0].id;
    if (!tgtId || !S.satellites.some(function (s) { return s.id === tgtId; })) {
      tgtId = (S.satellites[1] || S.satellites[0]).id;
    }

    var row = h("div", "geo-pair-row");
    function mkSel(id, getVal, onSet) {
      var sl = h("select", "select");
      sl.id = id;
      S.satellites.forEach(function (s) {
        var op = h("option");
        op.value = s.id; op.textContent = s.name;
        if (s.id === getVal()) op.selected = true;
        sl.appendChild(op);
      });
      sl.onchange = function () { onSet(sl.value); update(); };
      return sl;
    }
    row.appendChild(h("span", "muted", "参考"));
    row.appendChild(mkSel("fm-ref", function () { return refId; }, function (v) { refId = v; }));
    row.appendChild(h("span", "muted", "⇄"));
    row.appendChild(mkSel("fm-tgt", function () { return tgtId; }, function (v) { tgtId = v; }));
    el.appendChild(row);

    el.appendChild(h("canvas", "fm-canvas")).id = "formation-canvas";

    el.appendChild(h("div", "geo-cards",
      "<div class='geo-card'><div class='v' id='fm-dist'>—</div><div class='k'>星间距离</div></div>" +
      "<div class='geo-card'><div class='v' id='fm-rate'>—</div><div class='k'>距离变化率</div></div>" +
      "<div class='geo-card' id='fm-vis-card'><div class='v' id='fm-vis'>—</div><div class='k'>星间通视</div></div>"));
    el.appendChild(h("div", "geo-cards",
      "<div class='geo-card'><div class='v' id='fm-dr'>—</div><div class='k'>ΔR 径向</div></div>" +
      "<div class='geo-card'><div class='v' id='fm-dt'>—</div><div class='k'>ΔT 迹向</div></div>" +
      "<div class='geo-card'><div class='v' id='fm-dn'>—</div><div class='k'>ΔN 法向</div></div>"));

    var ctrl = h("div", "fm-ctrl");
    var hl = h("span", "muted", "预推演时长");
    var hsel = h("select", "select");
    HORIZONS.forEach(function (o) {
      var op = h("option"); op.value = o.s; op.textContent = o.label;
      if (o.s === horizonS) op.selected = true;
      hsel.appendChild(op);
    });
    hsel.onchange = function () { horizonS = parseFloat(hsel.value); ctx.refreshPrediction(horizonS); };
    var btn = h("button", "btn sm", "刷新预推演");
    btn.onclick = function () { ctx.refreshPrediction(horizonS); };
    ctrl.appendChild(hl); ctrl.appendChild(hsel); ctrl.appendChild(btn);
    el.appendChild(ctrl);

    var legend = h("div", "fm-legend mono");
    legend.innerHTML = "<span><i class='lg solid'></i>已运行轨迹</span><span><i class='lg dash'></i>预推演轨迹</span>";
    el.appendChild(legend);
    el.appendChild(h("div", "fm-status muted", "")).id = "fm-status";
  }

  function update() {
    if (!$("tab-formation") || !refId || !tgtId) return;
    if (ctx.getMode() === "replay") {
      // 回放模式：游标移动较多时按游标后帧刷新预测
      var t = ctx.getTime();
      if (lastReplayPredT === null || Math.abs(t - lastReplayPredT) > Math.max(horizonS / 200, 5)) {
        lastReplayPredT = t;
        ctx.refreshPrediction(horizonS);
      }
    } else {
      // 实时模式：首次展示构型分析时自动预推一次（装载完成后）
      var pred = ctx.getPrediction();
      if (!pred.requested && !pred.loading) ctx.refreshPrediction(horizonS);
    }
    var cur = currentRel();
    drawPlot(historyTrack(), predictionTrack(), cur);
    setReadout(cur);
  }

  window.SitFormation = {
    init: function (c) { ctx = c; },
    build: build,
    rebuild: function () { lastReplayPredT = null; build(); },
    update: update,
    horizon: function () { return horizonS; }
  };
})();
