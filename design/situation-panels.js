/* 态势页面板 — 实体列表 / 遥测曲线 / 几何分析 / 指令注入 / 事件时间线 */
(function () {
  "use strict";
  var ctx = null; // init 时注入的回调集合
  var teleSatId = null;
  var geoA = null, geoB = null;
  var alertDist = 100;
  var cmdTpl = "轨道机动", cmdTarget = null, cmdWhen = "now", cmdDelay = 600;
  var cmdParams = {};

  var EV_COLORS = { "机动": "oklch(0.68 0.14 75)", "载荷": "oklch(0.62 0.13 190)", "指令": "oklch(0.58 0.14 245)", "预警": "oklch(0.55 0.17 28)", "姿态": "oklch(0.62 0.13 190)", "系统": "oklch(0.6 0.01 260)" };

  var TEMPLATES = {
    "轨道机动": [
      { k: "dv", label: "Δv (m/s)", type: "number", def: 2.0 },
      { k: "dir", label: "方向", type: "select", options: ["切向", "法向", "径向"], def: "切向" }
    ],
    "载荷控制": [
      { k: "act", label: "动作", type: "select", options: ["开机", "关机", "单次成像", "持续侦收"], def: "开机" }
    ],
    "姿态调整": [
      { k: "att", label: "目标姿态", type: "select", options: ["对地定向", "对日定向", "惯性指向", "目标跟瞄"], def: "对地定向" }
    ],
    "编队保持": [
      { k: "ref", label: "参考星", type: "satselect", def: null },
      { k: "dist", label: "保持距离 (km)", type: "number", def: 50 }
    ]
  };

  function $(id) { return document.getElementById(id); }
  function h(tag, cls, html) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (html !== undefined) el.innerHTML = html;
    return el;
  }
  function fmtT(t) {
    t = Math.max(0, Math.round(t));
    var hh = String(Math.floor(t / 3600)).padStart(2, "0");
    var mm = String(Math.floor((t % 3600) / 60)).padStart(2, "0");
    var ss = String(t % 60).padStart(2, "0");
    return "T+" + hh + ":" + mm + ":" + ss;
  }

  /* ---------- 确定性伪随机（按种子+时间） ---------- */
  function noise(seed, t, f) {
    return Math.sin(t * f + seed * 0.7) * 0.6 + Math.sin(t * f * 2.7 + seed * 1.3) * 0.3 + Math.sin(t * f * 7.1 + seed * 2.9) * 0.1;
  }

  /* ---------- 遥测计算（全部确定性，可回放） ---------- */
  function altitude(sat, t) {
    var p = SitScene.eciPos(sat.orbit, t);
    return p.r - SitScene.EARTH_R;
  }
  function attitude(sat, t, seed) {
    return noise(seed + sat.id.length * 13, t, 0.004) * 1.8;
  }
  function fuel(sat, t) {
    var f = sat.fuel;
    ctx.getBurns(sat.id).forEach(function (b) {
      if (b.t <= t) f -= b.dv * 0.45;
    });
    return Math.max(0, f - t * 0.00004 * (sat.payload.state === "开机" ? 3 : 1));
  }

  /* ---------- 实体列表 ---------- */
  function renderEntities() {
    var body = $("ent-body");
    body.innerHTML = "";
    var S = ctx.scenario();
    var t = ctx.getTime();
    var sel = ctx.getSelected();
    var groups = {};
    S.satellites.forEach(function (s) {
      (groups[s.group] = groups[s.group] || []).push(s);
    });
    Object.keys(groups).forEach(function (g) {
      body.appendChild(h("div", "ent-group-h", "")).textContent = g.toUpperCase() + " · " + groups[g].length;
      groups[g].forEach(function (s) {
        var it = h("div", "ent-item" + (sel === s.id ? " selected" : ""));
        it.innerHTML = '<span class="sw"></span><span class="nm"></span><span class="alt mono"></span>';
        it.querySelector(".sw").style.background = SitScene.groupColor(s.group);
        it.querySelector(".nm").innerHTML = "<div></div><div class='pl'></div>";
        it.querySelector(".nm div").textContent = s.name;
        it.querySelector(".pl").textContent = s.id + " · " + s.payload.type;
        it.querySelector(".alt").textContent = Math.round(altitude(s, t)) + " km";
        it.dataset.alt = "1";
        it.dataset.sat = s.id;
        it.onclick = function () { ctx.onSelect(s.id); };
        body.appendChild(it);
      });
    });
    var gsArr = S.groundStations || [];
    if (gsArr.length) {
      body.appendChild(h("div", "ent-group-h", "")).textContent = "地面站 · " + gsArr.length;
      gsArr.forEach(function (g) {
        var it = h("div", "ent-item");
        it.innerHTML = '<span class="sw" style="background:#3fb5ad;border-radius:50%"></span><span class="nm"></span><span class="alt mono"></span>';
        it.querySelector(".nm").textContent = g.name;
        it.querySelector(".alt").textContent = g.lat.toFixed(1) + "°," + g.lon.toFixed(1) + "°";
        body.appendChild(it);
      });
    }
    $("ent-count").textContent = S.satellites.length + " 星 · " + gsArr.length + " 站";
  }
  function refreshEntityAlts() {
    var t = ctx.getTime();
    var S = ctx.scenario();
    document.querySelectorAll(".ent-item[data-sat]").forEach(function (it) {
      var s = S.satellites.find(function (x) { return x.id === it.dataset.sat; });
      if (s) it.querySelector(".alt").textContent = Math.round(altitude(s, t)) + " km";
    });
  }

  /* ---------- 选中信息卡 ---------- */
  function updateSelCard() {
    var card = $("sel-card");
    var sel = ctx.getSelected();
    var S = ctx.scenario();
    var s = S.satellites.find(function (x) { return x.id === sel; });
    if (!s) { card.style.display = "none"; return; }
    var t = ctx.getTime();
    card.style.display = "block";
    var v = SitScene.speed(s.orbit, t);
    card.innerHTML =
      "<h4></h4><div class='gid'></div>" +
      "<div class='kv'>" +
      "<span>轨道高度</span><b>" + Math.round(altitude(s, t)) + " km</b>" +
      "<span>飞行速度</span><b>" + v.toFixed(2) + " km/s</b>" +
      "<span>倾角 / 偏心率</span><b>" + s.orbit.i.toFixed(1) + "° / " + s.orbit.e.toFixed(4) + "</b>" +
      "<span>载荷</span><b>" + s.payload.type + " · " + s.payload.state + "</b>" +
      "<span>燃料余量</span><b>" + fuel(s, t).toFixed(1) + " %</b>" +
      "</div>";
    card.querySelector("h4").textContent = s.name;
    card.querySelector(".gid").textContent = s.id + " · " + s.group;
  }

  /* ---------- 图表 ---------- */
  function drawChart(cv, fn, t, opts) {
    var dpr = Math.min(window.devicePixelRatio, 2);
    var w = cv.clientWidth, hh = cv.clientHeight;
    if (cv.width !== w * dpr) { cv.width = w * dpr; cv.height = hh * dpr; }
    var g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, hh);
    var N = 90, span = opts.span || 900;
    var vals = [];
    for (var k = 0; k < N; k++) {
      var tk = t - span + (span * k) / (N - 1);
      vals.push(tk < 0 ? null : fn(tk));
    }
    var nums = vals.filter(function (v) { return v != null; });
    if (!nums.length) return null;
    var mn = Math.min.apply(null, nums), mx = Math.max.apply(null, nums);
    if (mx - mn < 1e-6) { mn -= 1; mx += 1; }
    var pad = (mx - mn) * 0.15;
    mn -= pad; mx += pad;
    // 网格
    g.strokeStyle = "oklch(0.30 0.015 255)";
    g.lineWidth = 1;
    g.beginPath();
    for (var gy = 1; gy < 3; gy++) { g.moveTo(0, (hh * gy) / 3); g.lineTo(w, (hh * gy) / 3); }
    for (var gx = 1; gx < 6; gx++) { g.moveTo((w * gx) / 6, 0); g.lineTo((w * gx) / 6, hh); }
    g.stroke();
    // 曲线
    g.strokeStyle = opts.color;
    g.lineWidth = 1.6;
    g.beginPath();
    var started = false;
    vals.forEach(function (v, k) {
      if (v == null) return;
      var x = (k / (N - 1)) * w;
      var y = hh - ((v - mn) / (mx - mn)) * hh;
      if (!started) { g.moveTo(x, y); started = true; } else g.lineTo(x, y);
    });
    g.stroke();
    // 当前值点
    var last = nums[nums.length - 1];
    g.fillStyle = opts.color;
    g.beginPath();
    g.arc(w - 2, hh - ((last - mn) / (mx - mn)) * hh, 2.6, 0, Math.PI * 2);
    g.fill();
    // 量程标注
    g.fillStyle = "oklch(0.55 0.012 255)";
    g.font = "9px 'IBM Plex Mono'";
    g.fillText(mx.toFixed(opts.dp), 4, 10);
    g.fillText(mn.toFixed(opts.dp), 4, hh - 4);
    return last;
  }

  function buildTelemetryTab() {
    var el = $("tab-telemetry");
    el.innerHTML = "";
    var row = h("div", "tele-sel-row");
    var sl = h("select", "select");
    sl.id = "tele-sat-sel";
    ctx.scenario().satellites.forEach(function (s) {
      var op = h("option");
      op.value = s.id; op.textContent = s.name + " (" + s.id + ")";
      sl.appendChild(op);
    });
    sl.onchange = function () { teleSatId = sl.value; };
    row.appendChild(sl);
    var hint = h("span", "muted", "");
    hint.style.fontSize = "11px";
    hint.textContent = "近 15 min";
    row.appendChild(hint);
    el.appendChild(row);
    [
      { id: "ch-alt", title: "轨道高度", unit: "km" },
      { id: "ch-spd", title: "飞行速度", unit: "km/s" },
      { id: "ch-att", title: "姿态偏差", unit: "°" },
      { id: "ch-fuel", title: "燃料余量", unit: "%" }
    ].forEach(function (c) {
      var b = h("div", "chart-block");
      b.innerHTML = "<div class='ch-head'><span class='ch-title'>" + c.title + "</span><span class='ch-val' id='" + c.id + "-v'>—</span></div><canvas class='chart-canvas' id='" + c.id + "'></canvas>";
      el.appendChild(b);
    });
  }

  function updateTelemetry() {
    var S = ctx.scenario();
    var s = S.satellites.find(function (x) { return x.id === teleSatId; }) || S.satellites[0];
    if (!s) return;
    var t = ctx.getTime();
    var seed = S.sim.seed % 1000;
    var v1 = drawChart($("ch-alt"), function (tk) { return altitude(s, tk); }, t, { color: "#5b8def", dp: 0 });
    var v2 = drawChart($("ch-spd"), function (tk) { return SitScene.speed(s.orbit, tk); }, t, { color: "#3fb5ad", dp: 2 });
    var v3 = drawChart($("ch-att"), function (tk) { return attitude(s, tk, seed); }, t, { color: "#d9a13f", dp: 2 });
    var v4 = drawChart($("ch-fuel"), function (tk) { return fuel(s, tk); }, t, { color: "#9b7fd4", dp: 1 });
    if (v1 != null) $("ch-alt-v").textContent = Math.round(v1) + " km";
    if (v2 != null) $("ch-spd-v").textContent = v2.toFixed(2) + " km/s";
    if (v3 != null) $("ch-att-v").textContent = v3.toFixed(2) + " °";
    if (v4 != null) $("ch-fuel-v").textContent = v4.toFixed(1) + " %";
  }

  /* ---------- 几何分析 ---------- */
  function dist3(a, b) {
    var dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }
  function visible(pa, pb) {
    // 连线与地球求交：最近点距地心 > 地球半径 即通视
    var d = { x: pb.x - pa.x, y: pb.y - pa.y, z: pb.z - pa.z };
    var len2 = d.x * d.x + d.y * d.y + d.z * d.z;
    var tt = -(pa.x * d.x + pa.y * d.y + pa.z * d.z) / len2;
    tt = Math.max(0, Math.min(1, tt));
    var c = { x: pa.x + d.x * tt, y: pa.y + d.y * tt, z: pa.z + d.z * tt };
    return Math.sqrt(c.x * c.x + c.y * c.y + c.z * c.z) > SitScene.EARTH_R;
  }

  function buildGeometryTab() {
    var el = $("tab-geometry");
    el.innerHTML = "";
    var S = ctx.scenario();
    var row = h("div", "geo-pair-row");
    function mkSel(id, defIdx) {
      var sl = h("select", "select");
      sl.id = id;
      S.satellites.forEach(function (s, i) {
        var op = h("option");
        op.value = s.id; op.textContent = s.name;
        if (i === defIdx) op.selected = true;
        sl.appendChild(op);
      });
      return sl;
    }
    var sa = mkSel("geo-a", 0), sb = mkSel("geo-b", Math.min(5, S.satellites.length - 1));
    geoA = sa.value; geoB = sb.value;
    sa.onchange = function () { geoA = sa.value; };
    sb.onchange = function () { geoB = sb.value; };
    row.appendChild(sa);
    row.appendChild(h("span", "muted", "⇄"));
    row.appendChild(sb);
    el.appendChild(row);
    el.appendChild(h("div", "geo-cards",
      "<div class='geo-card'><div class='v' id='geo-dist'>—</div><div class='k'>星间距离</div></div>" +
      "<div class='geo-card'><div class='v' id='geo-rv'>—</div><div class='k'>距离变化率</div></div>" +
      "<div class='geo-card' id='geo-vis-card'><div class='v' id='geo-vis'>—</div><div class='k'>星间通视</div></div>"));
    el.appendChild(h("canvas", "chart-canvas", "")).id = "geo-chart";
    var lbl = h("div", "muted", "");
    lbl.style.cssText = "font-size:10.5px;margin-top:4px;";
    lbl.textContent = "星间距离历史（近 30 min）";
    el.appendChild(lbl);

    var sh = h("div", "sec-h", "");
    sh.textContent = "接近预警";
    el.appendChild(sh);
    var thRow = h("div", "row");
    thRow.style.marginBottom = "6px";
    var thLbl = h("span", "muted", "");
    thLbl.style.fontSize = "11.5px";
    thLbl.textContent = "预警门限";
    var th = h("input", "input mono");
    th.type = "number"; th.value = alertDist;
    th.setAttribute("value", alertDist);
    th.style.width = "90px";
    th.oninput = function () { alertDist = parseFloat(th.value) || 100; };
    thRow.appendChild(thLbl);
    thRow.appendChild(th);
    thRow.appendChild(h("span", "muted", "km"));
    el.appendChild(thRow);
    el.appendChild(h("div", "", "")).id = "geo-alerts";

    var sh2 = h("div", "sec-h", "");
    sh2.textContent = "地面站可见性（对选中卫星）";
    el.appendChild(sh2);
    el.appendChild(h("div", "", "")).id = "geo-gs";
  }

  function updateGeometry() {
    var S = ctx.scenario();
    var t = ctx.getTime();
    var a = S.satellites.find(function (x) { return x.id === geoA; });
    var b = S.satellites.find(function (x) { return x.id === geoB; });
    if (!a || !b) return;
    var pa = SitScene.eciPos(a.orbit, t), pb = SitScene.eciPos(b.orbit, t);
    var d = dist3(pa, pb);
    var d2 = dist3(SitScene.eciPos(a.orbit, t + 10), SitScene.eciPos(b.orbit, t + 10));
    $("geo-dist").textContent = d >= 1000 ? (d / 1000).toFixed(1) + " Mm" : d.toFixed(1) + " km";
    var rate = (d2 - d) / 10;
    $("geo-rv").textContent = (rate > 0 ? "+" : "") + rate.toFixed(2) + " km/s";
    var vis = visible(pa, pb);
    $("geo-vis").textContent = vis ? "通视" : "遮挡";
    $("geo-vis-card").className = "geo-card " + (vis ? "vis-ok" : "vis-no");
    drawChart($("geo-chart"), function (tk) {
      return dist3(SitScene.eciPos(a.orbit, tk), SitScene.eciPos(b.orbit, tk));
    }, t, { color: "#5b8def", dp: 0, span: 1800 });

    // 接近预警
    var alerts = [];
    for (var i = 0; i < S.satellites.length; i++) {
      for (var j = i + 1; j < S.satellites.length; j++) {
        var pi = SitScene.eciPos(S.satellites[i].orbit, t);
        var pj = SitScene.eciPos(S.satellites[j].orbit, t);
        var dd = dist3(pi, pj);
        if (dd < alertDist) alerts.push({ a: S.satellites[i], b: S.satellites[j], d: dd });
      }
    }
    alerts.sort(function (x, y) { return x.d - y.d; });
    var box = $("geo-alerts");
    if (!alerts.length) box.innerHTML = "<div class='geo-empty'>当前无小于门限的接近对</div>";
    else {
      box.innerHTML = "";
      alerts.slice(0, 5).forEach(function (al) {
        var r = h("div", "alert-row");
        r.innerHTML = "<span class='dot danger'></span><span class='pair'></span><span class='d'></span>";
        r.querySelector(".pair").textContent = al.a.id + " ↔ " + al.b.id;
        r.querySelector(".d").textContent = al.d.toFixed(1) + " km";
        box.appendChild(r);
      });
    }
    ctx.reportAlerts(alerts);

    // 地面站可见性
    var selId = ctx.getSelected() || (S.satellites[0] && S.satellites[0].id);
    var sel = S.satellites.find(function (x) { return x.id === selId; });
    var gsBox = $("geo-gs");
    gsBox.innerHTML = "";
    if (sel) {
      var theta = ((2 * Math.PI) / 86164) * t;
      var ps = SitScene.eciPos(sel.orbit, t);
      (S.groundStations || []).forEach(function (g) {
        var lat = (g.lat * Math.PI) / 180, lon = (g.lon * Math.PI) / 180 + theta;
        var R = SitScene.EARTH_R;
        var pg = { x: R * Math.cos(lat) * Math.cos(lon), y: R * Math.cos(lat) * Math.sin(lon), z: R * Math.sin(lat) };
        var dx = ps.x - pg.x, dy = ps.y - pg.y, dz = ps.z - pg.z;
        var rng = Math.sqrt(dx * dx + dy * dy + dz * dz);
        var elev = Math.asin((pg.x * dx + pg.y * dy + pg.z * dz) / (R * rng)) * 180 / Math.PI;
        var ok = elev > 5;
        var r = h("div", "alert-row");
        r.innerHTML = "<span class='dot " + (ok ? "ok" : "idle") + "'></span><span class='pair'></span><span class='d'></span>";
        r.querySelector(".pair").textContent = g.name + " → " + sel.name;
        r.querySelector(".d").textContent = ok ? "仰角 " + elev.toFixed(0) + "°" : "不可见";
        gsBox.appendChild(r);
      });
    }
  }

  /* ---------- 指令注入 ---------- */
  function buildCommandTab() {
    var el = $("tab-command");
    el.innerHTML = "";
    var S = ctx.scenario();
    cmdTarget = S.satellites[0] && S.satellites[0].id;

    var form = h("div", "cmd-form");
    var fr1 = h("div", "frow");
    var tplSel = h("select", "select");
    Object.keys(TEMPLATES).forEach(function (k) {
      var op = h("option"); op.value = k; op.textContent = k;
      tplSel.appendChild(op);
    });
    tplSel.onchange = function () { cmdTpl = tplSel.value; renderParams(); };
    var tgtSel = h("select", "select");
    S.satellites.forEach(function (s) {
      var op = h("option"); op.value = s.id; op.textContent = s.name + " (" + s.id + ")";
      tgtSel.appendChild(op);
    });
    tgtSel.onchange = function () { cmdTarget = tgtSel.value; };
    var f1 = h("div", "field"); f1.innerHTML = "<label>指令模板</label>"; f1.appendChild(tplSel);
    var f2 = h("div", "field"); f2.innerHTML = "<label>目标卫星</label>"; f2.appendChild(tgtSel);
    fr1.appendChild(f1); fr1.appendChild(f2);
    form.appendChild(fr1);

    var pbox = h("div", "frow");
    pbox.id = "cmd-params";
    form.appendChild(pbox);

    var whenField = h("div", "field");
    whenField.innerHTML = "<label>执行时机</label>";
    var when = h("div", "cmd-when");
    var bNow = h("button", "active", "立即执行");
    var bLater = h("button", "", "定时执行");
    bNow.onclick = function () { cmdWhen = "now"; bNow.className = "active"; bLater.className = ""; delayRow.style.display = "none"; };
    bLater.onclick = function () { cmdWhen = "later"; bLater.className = "active"; bNow.className = ""; delayRow.style.display = "flex"; };
    when.appendChild(bNow); when.appendChild(bLater);
    whenField.appendChild(when);
    var delayRow = h("div", "row");
    delayRow.style.cssText = "display:none;margin-top:7px;";
    var dl = h("input", "input mono");
    dl.type = "number"; dl.value = cmdDelay;
    dl.setAttribute("value", cmdDelay);
    dl.oninput = function () { cmdDelay = parseFloat(dl.value) || 0; };
    delayRow.appendChild(h("span", "muted", "当前时刻 +"));
    delayRow.appendChild(dl);
    delayRow.appendChild(h("span", "muted", "秒后执行"));
    whenField.appendChild(delayRow);
    form.appendChild(whenField);

    var send = h("button", "btn primary", "下发指令");
    send.onclick = function () {
      ctx.onInjectCommand({
        tpl: cmdTpl, target: cmdTarget,
        params: JSON.parse(JSON.stringify(cmdParams)),
        when: cmdWhen, delay: cmdDelay
      });
    };
    form.appendChild(send);
    el.appendChild(form);

    var sh = h("div", "sec-h", "");
    sh.textContent = "指令队列";
    el.appendChild(sh);
    el.appendChild(h("div", "", "")).id = "cmd-queue";

    function renderParams() {
      pbox.innerHTML = "";
      cmdParams = {};
      TEMPLATES[cmdTpl].forEach(function (p) {
        var f = h("div", "field");
        var lb = h("label"); lb.textContent = p.label;
        f.appendChild(lb);
        var inp;
        if (p.type === "number") {
          inp = h("input", "input mono");
          inp.type = "number"; inp.value = p.def;
          inp.setAttribute("value", p.def);
          cmdParams[p.k] = p.def;
          inp.oninput = function () { cmdParams[p.k] = parseFloat(inp.value); };
        } else {
          inp = h("select", "select");
          var opts = p.type === "satselect" ? S.satellites.map(function (s) { return s.id; }) : p.options;
          opts.forEach(function (o) {
            var op = h("option"); op.value = o; op.textContent = o;
            inp.appendChild(op);
          });
          cmdParams[p.k] = opts[0];
          inp.onchange = function () { cmdParams[p.k] = inp.value; };
        }
        f.appendChild(inp);
        pbox.appendChild(f);
      });
    }
    renderParams();
  }

  function describeCmd(c) {
    if (c.tpl === "轨道机动") return "轨道机动 Δv=" + c.params.dv + " m/s " + c.params.dir;
    if (c.tpl === "载荷控制") return "载荷" + c.params.act;
    if (c.tpl === "姿态调整") return "姿态调整 → " + c.params.att;
    if (c.tpl === "编队保持") return "编队保持 ref=" + c.params.ref + " " + c.params.dist + "km";
    return c.tpl;
  }

  function updateCommandQueue() {
    var box = $("cmd-queue");
    if (!box) return;
    var cmds = ctx.getCommands();
    var t = ctx.getTime();
    box.innerHTML = "";
    if (!cmds.length) { box.innerHTML = "<div class='geo-empty'>尚未注入指令</div>"; return; }
    cmds.slice().reverse().forEach(function (c) {
      var fired = c.t <= t;
      var r = h("div", "cmd-queue-item");
      r.innerHTML = "<span class='t'></span><span class='what'><div></div><div class='tgt'></div></span><span class='badge " + (fired ? "ok" : "accent") + "'>" + (fired ? "已执行" : "待执行") + "</span>";
      r.querySelector(".t").textContent = fmtT(c.t);
      r.querySelector(".what div").textContent = describeCmd(c);
      r.querySelector(".tgt").textContent = c.target;
      box.appendChild(r);
    });
  }

  /* ---------- 时间线 ---------- */
  function renderTimelineMarks() {
    var S = ctx.scenario();
    var dur = S.sim.duration;
    var marks = $("tl-marks");
    marks.innerHTML = "";
    var t = ctx.getTime();
    ctx.getEvents().forEach(function (ev) {
      var m = h("div", "tl-mark" + (ev.t <= t ? " fired" : ""));
      m.style.left = Math.min(99.5, (ev.t / dur) * 100) + "%";
      m.style.background = EV_COLORS[ev.type] || EV_COLORS["系统"];
      m.style.color = m.style.background;
      m.title = fmtT(ev.t) + " " + ev.text;
      marks.appendChild(m);
    });
    $("tl-range").textContent = "T+0 — " + fmtT(dur);
  }

  function updateTimeline() {
    var S = ctx.scenario();
    var dur = S.sim.duration;
    var t = ctx.getTime();
    var pct = Math.min(100, (t / dur) * 100);
    $("tl-progress").style.width = pct + "%";
    $("tl-cursor").style.left = pct + "%";
    // 日志：最近 4 条已发生事件
    var evs = ctx.getEvents().filter(function (e) { return e.t <= t; });
    evs.sort(function (a, b) { return a.t - b.t; });
    var log = $("tl-log");
    log.innerHTML = "";
    if (!evs.length) {
      log.innerHTML = "<span class='muted' style='font-size:11.5px'>暂无事件 — 事件将随仿真推进按时间线触发</span>";
    } else {
      evs.slice(-4).forEach(function (ev) {
        var s = h("span", "ev");
        s.innerHTML = "<i></i><span class='tm'></span><span></span>";
        s.querySelector("i").style.background = EV_COLORS[ev.type] || EV_COLORS["系统"];
        s.querySelector(".tm").textContent = fmtT(ev.t);
        s.lastChild.textContent = ev.text;
        log.appendChild(s);
      });
    }
    renderTimelineMarks();
  }

  /* ---------- 选项卡 ---------- */
  var activeTab = "telemetry";
  function initTabs() {
    document.querySelectorAll("#right-tabs .tab").forEach(function (tab) {
      tab.onclick = function () {
        document.querySelectorAll("#right-tabs .tab").forEach(function (x) { x.classList.remove("active"); });
        tab.classList.add("active");
        activeTab = tab.getAttribute("data-t");
        ["telemetry", "geometry", "command"].forEach(function (k) {
          $("tab-" + k).style.display = k === activeTab ? "block" : "none";
        });
      };
    });
  }

  window.SitPanels = {
    init: function (c) {
      ctx = c;
      teleSatId = c.scenario().satellites[0] && c.scenario().satellites[0].id;
      initTabs();
      buildTelemetryTab();
      buildGeometryTab();
      buildCommandTab();
      renderEntities();
      renderTimelineMarks();
    },
    renderEntities: renderEntities,
    setTeleSat: function (id) {
      teleSatId = id;
      var sl = $("tele-sat-sel");
      if (sl) sl.value = id;
    },
    update: function () {
      refreshEntityAlts();
      updateSelCard();
      if (activeTab === "telemetry") updateTelemetry();
      if (activeTab === "geometry") updateGeometry();
      if (activeTab === "command") updateCommandQueue();
      updateTimeline();
    },
    fmtT: fmtT,
    describeCmd: describeCmd
  };
})();
