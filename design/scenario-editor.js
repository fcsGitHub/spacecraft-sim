/* 场景生成页 — 结构树 + 表单编辑 + JSON/YAML 预览 + 实时校验 */
(function () {
  "use strict";
  var S = ScenarioStore.load();
  var sel = { type: "meta", i: 0 };
  var fmt = "json";
  var MU = 398600.4418; // km^3/s^2
  var PAYLOADS = ["光学成像", "合成孔径雷达", "电子侦察", "通信中继", "导航增强", "未知"];
  var PAYLOAD_STATES = ["待机", "开机", "关闭"];
  var EV_TYPES = ["机动", "载荷", "姿态", "系统"];

  /* ---------- 小工具 ---------- */
  function $(id) { return document.getElementById(id); }
  function h(tag, cls, html) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (html !== undefined) el.innerHTML = html;
    return el;
  }
  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function debounce(fn, ms) {
    var t;
    return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }

  /* ---------- 持久化 + 联动刷新 ---------- */
  var refreshLight = debounce(function () {
    ScenarioStore.save(S);
    renderPreview();
    renderValidation();
    renderTreeTexts();
    markSaved();
    var navName = document.getElementById("nav-scenario-name");
    if (navName) navName.textContent = S.meta.name || "未命名场景";
  }, 250);

  function markSaved() {
    var d = new Date();
    $("autosave-text").textContent = "已自动保存 " + d.toTimeString().slice(0, 8);
  }

  /* ---------- 结构树 ---------- */
  var validCache = { errors: [], warnings: [] };
  function errLocs() {
    var set = {};
    validCache.errors.forEach(function (e) { set[e.loc] = true; });
    return set;
  }

  function renderTree() {
    var body = $("tree-body");
    body.innerHTML = "";
    var locs = errLocs();

    function node(label, ic, selected, hasErr, extra, onclick, child) {
      var n = h("div", "tnode" + (selected ? " selected" : "") + (child ? " child" : ""));
      n.appendChild(h("span", "ic", ic));
      var lb = h("span", "lb", "");
      lb.textContent = label;
      n.appendChild(lb);
      if (hasErr) n.appendChild(h("span", "err-flag"));
      else if (extra) n.appendChild(h("span", "cnt", extra));
      n.onclick = onclick;
      return n;
    }

    body.appendChild(node("场景元信息", "◇", sel.type === "meta", locs["场景元信息"], "", function () { select({ type: "meta" }); }));
    body.appendChild(node("仿真参数", "◷", sel.type === "sim", locs["仿真参数"], "", function () { select({ type: "sim" }); }));

    var satHead = h("div", "tgroup-head");
    satHead.appendChild(node("卫星列表", "✦", false, locs["卫星列表"], String(S.satellites.length), function () {}));
    var addSat = h("div", "tadd", "+");
    addSat.title = "添加卫星";
    addSat.onclick = function () { addSatellite(); };
    satHead.appendChild(addSat);
    body.appendChild(satHead);

    S.satellites.forEach(function (st, i) {
      var label = st.name || st.id || "未命名";
      body.appendChild(node(label, String(i + 1).padStart(2, "0"),
        sel.type === "sat" && sel.i === i, locs[st.name || st.id],
        st.id, function () { select({ type: "sat", i: i }); }, true));
    });

    var gsHead = h("div", "tgroup-head");
    gsHead.appendChild(node("地面站", "▽", false, false, String(S.groundStations.length), function () {}));
    var addGs = h("div", "tadd", "+");
    addGs.title = "添加地面站";
    addGs.onclick = function () { addStation(); };
    gsHead.appendChild(addGs);
    body.appendChild(gsHead);

    S.groundStations.forEach(function (g, i) {
      body.appendChild(node(g.name || "未命名", String(i + 1).padStart(2, "0"),
        sel.type === "gs" && sel.i === i, locs[g.name || "地面站#" + (i + 1)],
        g.id, function () { select({ type: "gs", i: i }); }, true));
    });

    var evHasErr = validCache.errors.some(function (e) { return e.loc.indexOf("预设事件") === 0; });
    body.appendChild(node("预设事件", "⚑", sel.type === "events", evHasErr, String(S.events.length), function () { select({ type: "events" }); }));

    $("tree-stat").textContent = S.satellites.length + " 星 · " + S.groundStations.length + " 站 · " + S.events.length + " 事件";
  }
  function renderTreeTexts() { renderTree(); }

  function select(s) {
    sel = s;
    renderTree();
    renderForm();
  }

  /* ---------- 表单字段构造 ---------- */
  function field(label, inputEl, opts) {
    opts = opts || {};
    var f = h("div", "field" + (opts.span ? " span" + opts.span : ""));
    var lb = h("label");
    lb.textContent = label;
    f.appendChild(lb);
    f.appendChild(inputEl);
    if (opts.hint) {
      var hint = h("div", "hint");
      hint.textContent = opts.hint;
      f.appendChild(hint);
    }
    return f;
  }
  function textInput(value, onInput, opts) {
    opts = opts || {};
    var inp = h("input", "input" + (opts.mono ? " mono" : ""));
    inp.type = "text";
    inp.value = value == null ? "" : value;
    inp.setAttribute("value", inp.value);
    inp.oninput = function () { onInput(inp.value); inp.setAttribute("value", inp.value); refreshLight(); };
    return inp;
  }
  function numInput(value, onInput, opts) {
    opts = opts || {};
    var inp = h("input", "input mono");
    inp.type = "number";
    if (opts.step != null) inp.step = opts.step;
    inp.value = value == null ? "" : value;
    inp.setAttribute("value", inp.value);
    inp.oninput = function () { onInput(parseFloat(inp.value)); inp.setAttribute("value", inp.value); refreshLight(); };
    return inp;
  }
  function selectInput(value, options, onInput) {
    var sl = h("select", "select");
    options.forEach(function (o) {
      var op = h("option");
      op.value = o; op.textContent = o;
      if (o === value) { op.selected = true; op.setAttribute("selected", "selected"); }
      sl.appendChild(op);
    });
    sl.onchange = function () { onInput(sl.value); refreshLight(); };
    return sl;
  }
  function toggleInput(value, onInput) {
    var wrap = h("label", "switch");
    var inp = h("input");
    inp.type = "checkbox";
    inp.checked = !!value;
    inp.onchange = function () { onInput(inp.checked); refreshLight(); };
    wrap.appendChild(inp);
    wrap.appendChild(h("span", "track"));
    return wrap;
  }
  function section(title) {
    var s = h("div", "fsection");
    var t = h("h3");
    t.textContent = title;
    s.appendChild(t);
    return s;
  }
  function grid(parent) {
    var g = h("div", "fgrid");
    parent.appendChild(g);
    return g;
  }

  /* ---------- 表单渲染 ---------- */
  function renderForm() {
    var body = $("form-body");
    body.innerHTML = "";
    var title = $("form-title"), sub = $("form-sub");

    if (sel.type === "meta") {
      title.textContent = "场景元信息";
      sub.textContent = "meta";
      var s1 = section("基本信息");
      var g1 = grid(s1);
      g1.appendChild(field("场景名称", textInput(S.meta.name, function (v) { S.meta.name = v; }), { span: 2 }));
      g1.appendChild(field("版本号", textInput(S.meta.version, function (v) { S.meta.version = v; }, { mono: true }), { hint: "建议每次实验前递增，保证可追溯" }));
      g1.appendChild(field("作者", textInput(S.meta.author, function (v) { S.meta.author = v; })));
      g1.appendChild(field("创建日期", textInput(S.meta.created, function (v) { S.meta.created = v; }, { mono: true })));
      var desc = h("textarea", "input");
      desc.textContent = S.meta.description || "";
      desc.value = S.meta.description || "";
      desc.oninput = function () { S.meta.description = desc.value; refreshLight(); };
      g1.appendChild(field("场景描述", desc, { span: 3 }));
      body.appendChild(s1);
    }

    else if (sel.type === "sim") {
      title.textContent = "仿真参数";
      sub.textContent = "sim";
      var s2 = section("时间与步长");
      var g2 = grid(s2);
      g2.appendChild(field("起始历元 (UTC)", textInput(S.sim.epoch, function (v) { S.sim.epoch = v; }, { mono: true })));
      g2.appendChild(field("仿真时长 (s)", numInput(S.sim.duration, function (v) { S.sim.duration = v; })));
      g2.appendChild(field("仿真步长 (s)", numInput(S.sim.step, function (v) { S.sim.step = v; }, { step: 0.1 })));
      body.appendChild(s2);

      var s3 = section("实验可复现");
      var g3 = grid(s3);
      g3.appendChild(field("随机种子", numInput(S.sim.seed, function (v) { S.sim.seed = v; }), { hint: "固定种子可逐位复现实验，论文对比必填" }));
      var recWrap = h("div", "row");
      recWrap.style.height = "34px";
      recWrap.appendChild(toggleInput(S.sim.record, function (v) { S.sim.record = v; }));
      recWrap.appendChild(h("span", "muted", "记录全过程遥测与事件，供回放与指标评估"));
      g3.appendChild(field("数据记录", recWrap, { span: 2 }));
      body.appendChild(s3);
    }

    else if (sel.type === "sat") {
      var st = S.satellites[sel.i];
      if (!st) { select({ type: "meta" }); return; }
      title.textContent = st.name || st.id;
      sub.textContent = "satellites[" + sel.i + "]";

      var sb = section("基本信息");
      var gb = grid(sb);
      gb.appendChild(field("卫星编号", textInput(st.id, function (v) { st.id = v; }, { mono: true })));
      gb.appendChild(field("卫星名称", textInput(st.name, function (v) { st.name = v; })));
      gb.appendChild(field("编组", textInput(st.group, function (v) { st.group = v; })));
      gb.appendChild(field("整星质量 (kg)", numInput(st.mass, function (v) { st.mass = v; })));
      gb.appendChild(field("燃料余量 (%)", numInput(st.fuel, function (v) { st.fuel = v; })));
      body.appendChild(sb);

      var so = section("轨道六根数");
      var wrap = h("div", "orbit-preview-wrap");
      var go = h("div", "fgrid");
      go.style.flex = "1";
      function orb(label, key, step, hint) {
        go.appendChild(field(label, numInput(st.orbit[key], function (v) { st.orbit[key] = v; drawOrbit(st); }, { step: step }), { hint: hint }));
      }
      orb("半长轴 a (km)", "a", 1);
      orb("偏心率 e", "e", 0.001);
      orb("倾角 i (°)", "i", 0.1);
      orb("升交点赤经 Ω (°)", "raan", 1);
      orb("近地点幅角 ω (°)", "argp", 1);
      orb("初始平近点角 M₀ (°)", "M0", 1);
      var pv = h("div");
      var cv = h("canvas", "orbit-preview");
      cv.width = 360; cv.height = 360;
      cv.id = "orbit-canvas";
      pv.appendChild(cv);
      var ro = h("div", "orbit-readout");
      ro.id = "orbit-readout";
      pv.appendChild(ro);
      wrap.appendChild(go);
      wrap.appendChild(pv);
      so.appendChild(wrap);
      body.appendChild(so);

      var sp = section("载荷配置");
      var gp = grid(sp);
      gp.appendChild(field("载荷类型", selectInput(st.payload.type, PAYLOADS, function (v) { st.payload.type = v; })));
      gp.appendChild(field("初始状态", selectInput(st.payload.state, PAYLOAD_STATES, function (v) { st.payload.state = v; })));
      gp.appendChild(field("额定功率 (W)", numInput(st.payload.power, function (v) { st.payload.power = v; })));
      body.appendChild(sp);

      var act = h("div", "form-actions");
      var dup = h("button", "btn sm", "复制此卫星");
      dup.onclick = function () {
        var c = JSON.parse(JSON.stringify(st));
        c.id = nextSatId();
        c.name = st.name + "-副本";
        c.orbit.M0 = (c.orbit.M0 + 15) % 360;
        S.satellites.splice(sel.i + 1, 0, c);
        refreshLight();
        select({ type: "sat", i: sel.i + 1 });
        scToast("已复制卫星 " + c.id);
      };
      var del = h("button", "btn sm danger-btn", "删除此卫星");
      del.onclick = function () {
        S.satellites.splice(sel.i, 1);
        refreshLight();
        select({ type: "meta" });
        scToast("已删除卫星", "warn");
      };
      act.appendChild(dup);
      act.appendChild(del);
      body.appendChild(act);

      drawOrbit(st);
    }

    else if (sel.type === "gs") {
      var g = S.groundStations[sel.i];
      if (!g) { select({ type: "meta" }); return; }
      title.textContent = g.name || g.id;
      sub.textContent = "groundStations[" + sel.i + "]";
      var sg = section("站点信息");
      var gg = grid(sg);
      gg.appendChild(field("站点编号", textInput(g.id, function (v) { g.id = v; }, { mono: true })));
      gg.appendChild(field("站点名称", textInput(g.name, function (v) { g.name = v; })));
      gg.appendChild(field("纬度 (°)", numInput(g.lat, function (v) { g.lat = v; }, { step: 0.1 })));
      gg.appendChild(field("经度 (°)", numInput(g.lon, function (v) { g.lon = v; }, { step: 0.1 })));
      body.appendChild(sg);
      var act2 = h("div", "form-actions");
      var del2 = h("button", "btn sm danger-btn", "删除此地面站");
      del2.onclick = function () {
        S.groundStations.splice(sel.i, 1);
        refreshLight();
        select({ type: "meta" });
      };
      act2.appendChild(del2);
      body.appendChild(act2);
    }

    else if (sel.type === "events") {
      title.textContent = "预设事件";
      sub.textContent = "events[" + S.events.length + "]";
      var se = section("时序事件（仿真开始后按 t 自动触发）");
      var tbl = h("table", "dtable ev-table");
      tbl.innerHTML = "<thead><tr><th style='width:110px'>触发时刻 t (s)</th><th style='width:110px'>类型</th><th style='width:140px'>目标</th><th>动作描述</th><th style='width:36px'></th></tr></thead>";
      var tb = h("tbody");
      var satIds = S.satellites.map(function (s) { return s.id; });
      S.events.forEach(function (ev, i) {
        var tr = h("tr");
        var td1 = h("td");
        td1.appendChild(numInput(ev.t, function (v) { ev.t = v; }));
        var td2 = h("td");
        td2.appendChild(selectInput(ev.type, EV_TYPES, function (v) { ev.type = v; }));
        var td3 = h("td");
        td3.appendChild(selectInput(ev.target, satIds, function (v) { ev.target = v; }));
        var td4 = h("td");
        td4.appendChild(textInput(ev.action, function (v) { ev.action = v; }));
        var td5 = h("td");
        var del3 = h("span", "ev-del", "×");
        del3.title = "删除事件";
        del3.onclick = function () { S.events.splice(i, 1); refreshLight(); renderForm(); };
        td5.appendChild(del3);
        tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3); tr.appendChild(td4); tr.appendChild(td5);
        tb.appendChild(tr);
      });
      tbl.appendChild(tb);
      se.appendChild(tbl);
      var addEv = h("button", "btn sm", "+ 添加事件");
      addEv.style.marginTop = "12px";
      addEv.onclick = function () {
        S.events.push({ t: 0, type: "载荷", target: satIds[0] || "", action: "" });
        refreshLight();
        renderForm();
      };
      se.appendChild(addEv);
      body.appendChild(se);
    }
  }

  /* ---------- 轨道小窗预览 ---------- */
  function drawOrbit(st) {
    var cv = $("orbit-canvas");
    if (!cv) return;
    var ctx = cv.getContext("2d");
    var W = cv.width, Hh = cv.height, cx = W / 2, cy = Hh / 2;
    ctx.clearRect(0, 0, W, Hh);
    var a = st.orbit.a || 7000, e = Math.min(Math.max(st.orbit.e || 0, 0), 0.95);
    var apo = a * (1 + e);
    var scale = (W / 2 - 22) / apo;
    var Re = ScenarioStore.EARTH_R * scale;
    // 地球
    ctx.beginPath();
    ctx.arc(cx, cy, Re, 0, Math.PI * 2);
    ctx.fillStyle = "oklch(0.36 0.06 250)";
    ctx.fill();
    ctx.strokeStyle = "oklch(0.5 0.06 250)";
    ctx.lineWidth = 1;
    ctx.stroke();
    // 椭圆（焦点在地心）
    var b = a * Math.sqrt(1 - e * e);
    var off = a * e * scale;
    ctx.beginPath();
    ctx.ellipse(cx - off, cy, a * scale, b * scale, 0, 0, Math.PI * 2);
    ctx.strokeStyle = "oklch(0.72 0.13 245)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    // 近/远地点
    ctx.fillStyle = "oklch(0.78 0.11 75)";
    ctx.beginPath();
    ctx.arc(cx + (a * (1 - e)) * scale, cy, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "oklch(0.7 0.1 190)";
    ctx.beginPath();
    ctx.arc(cx - apo * scale, cy, 3, 0, Math.PI * 2);
    ctx.fill();

    var T = 2 * Math.PI * Math.sqrt(Math.pow(a, 3) / MU);
    var ro = $("orbit-readout");
    if (ro) {
      ro.innerHTML =
        "近地点高度 <b>" + Math.round(a * (1 - e) - ScenarioStore.EARTH_R) + " km</b><br>" +
        "远地点高度 <b>" + Math.round(apo - ScenarioStore.EARTH_R) + " km</b><br>" +
        "轨道周期 <b>" + (T / 60).toFixed(1) + " min</b>";
    }
  }

  /* ---------- 代码预览 ---------- */
  function highlightJSON(text) {
    return esc(text).replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|(-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|\b(true|false|null)\b/g,
      function (m, str, colon, num, kw) {
        if (str) return colon ? '<span class="k">' + str + "</span>" + colon : '<span class="s">' + str + "</span>";
        if (num) return '<span class="n">' + num + "</span>";
        if (kw) return '<span class="n">' + kw + "</span>";
        return m;
      });
  }
  function highlightYAML(text) {
    return esc(text).split("\n").map(function (line) {
      return line
        .replace(/^(\s*(?:- )?)([\w\u4e00-\u9fa5.\-]+):/, '$1<span class="k">$2</span><span class="p">:</span>')
        .replace(/: (-?\d+(?:\.\d+)?)(\s*)$/, ': <span class="n">$1</span>$2')
        .replace(/: (true|false)(\s*)$/, ': <span class="n">$1</span>$2');
    }).join("\n");
  }
  function renderPreview() {
    var pre = $("code-pre");
    if (fmt === "json") pre.innerHTML = highlightJSON(JSON.stringify(S, null, 2));
    else pre.innerHTML = highlightYAML(ScenarioStore.toYAML(S));
  }

  /* ---------- 校验 ---------- */
  function renderValidation() {
    validCache = ScenarioStore.validate(S);
    var body = $("valid-body");
    var chip = $("valid-chip");
    var ne = validCache.errors.length, nw = validCache.warnings.length;
    $("valid-sub").textContent = ne + " 错误 · " + nw + " 警告";
    if (ne === 0 && nw === 0) {
      chip.className = "badge ok";
      chip.textContent = "校验通过";
      body.innerHTML = '<div class="valid-pass"><span class="big">✓</span><span>场景结构与参数全部合规，可载入仿真</span></div>';
    } else {
      chip.className = ne > 0 ? "badge danger" : "badge warn";
      chip.textContent = ne > 0 ? ne + " 个错误" : nw + " 个警告";
      body.innerHTML = "";
      validCache.errors.forEach(function (e) {
        var it = h("div", "vitem");
        it.appendChild(h("span", "dot danger"));
        var loc = h("span", "loc"); loc.textContent = e.loc;
        var msg = h("span", "msg"); msg.textContent = e.msg;
        it.appendChild(loc); it.appendChild(msg);
        body.appendChild(it);
      });
      validCache.warnings.forEach(function (e) {
        var it = h("div", "vitem");
        it.appendChild(h("span", "dot warn"));
        var loc = h("span", "loc"); loc.textContent = e.loc;
        var msg = h("span", "msg"); msg.textContent = e.msg;
        it.appendChild(loc); it.appendChild(msg);
        body.appendChild(it);
      });
    }
    renderTree();
  }

  /* ---------- 新增实体 ---------- */
  function nextSatId() {
    var n = 1;
    while (S.satellites.some(function (s) { return s.id === "SAT-" + String(n).padStart(2, "0"); })) n++;
    return "SAT-" + String(n).padStart(2, "0");
  }
  function addSatellite() {
    var id = nextSatId();
    S.satellites.push({
      id: id, name: "新卫星-" + id.slice(-2), group: "观测星组",
      mass: 1000, fuel: 100,
      payload: { type: "光学成像", state: "待机", power: 320 },
      orbit: { a: 6878, e: 0.001, i: 97.5, raan: 0, argp: 90, M0: 0 }
    });
    refreshLight();
    select({ type: "sat", i: S.satellites.length - 1 });
    scToast("已添加卫星 " + id);
  }
  function addStation() {
    var n = S.groundStations.length + 1;
    S.groundStations.push({ id: "GS-" + String(n).padStart(2, "0"), name: "新地面站", lat: 0, lon: 0 });
    refreshLight();
    select({ type: "gs", i: S.groundStations.length - 1 });
  }

  /* ---------- 模板 ---------- */
  function tplRendezvous() {
    var s = ScenarioStore.defaultScenario();
    s.meta = { name: "双星交会对接-B", version: "1.0.0", author: "算法组", created: "2026-06-12", description: "追踪星对目标星的远程导引与近程接近场景，用于相对运动制导算法验证。" };
    s.sim.duration = 10800; s.sim.seed = 42;
    s.satellites = [
      { id: "CHS-01", name: "追踪星", group: "试验星组", mass: 2400, fuel: 95, payload: { type: "电子侦察", state: "开机", power: 380 }, orbit: { a: 6878, e: 0.0010, i: 51.6, raan: 80, argp: 30, M0: 0 } },
      { id: "TGT-01", name: "目标星", group: "非合作目标", mass: 8500, fuel: 50, payload: { type: "未知", state: "待机", power: 0 }, orbit: { a: 6893, e: 0.0012, i: 51.6, raan: 80, argp: 30, M0: 4 } }
    ];
    s.events = [
      { t: 1200, type: "机动", target: "CHS-01", action: "霍曼转移第一次点火 Δv=4.2 m/s" },
      { t: 4200, type: "机动", target: "CHS-01", action: "霍曼转移第二次点火 Δv=4.1 m/s" },
      { t: 7200, type: "姿态", target: "CHS-01", action: "转交会对接姿态" }
    ];
    return s;
  }
  function tplConstellation() {
    var s = ScenarioStore.defaultScenario();
    s.meta = { name: "区域观测星座-C", version: "1.0.0", author: "算法组", created: "2026-06-12", description: "12 星 Walker 3 面构型，用于区域覆盖与成像任务调度算法实验。" };
    s.sim.duration = 14400; s.sim.seed = 7;
    s.satellites = [];
    for (var p = 0; p < 3; p++) {
      for (var k = 0; k < 4; k++) {
        var n = p * 4 + k + 1;
        s.satellites.push({
          id: "WLK-" + String(n).padStart(2, "0"),
          name: "观测-" + String(n).padStart(2, "0"),
          group: "星座面" + (p + 1),
          mass: 860, fuel: 90,
          payload: { type: "光学成像", state: "待机", power: 300 },
          orbit: { a: 7178, e: 0.001, i: 55, raan: p * 120, argp: 0, M0: (k * 90 + p * 30) % 360 }
        });
      }
    }
    s.events = [
      { t: 600, type: "载荷", target: "WLK-01", action: "区域成像任务开始" },
      { t: 3600, type: "系统", target: "WLK-05", action: "模拟单星失效（调度重规划触发）" }
    ];
    return s;
  }

  /* ---------- 工具栏 ---------- */
  $("tb-new").onclick = function () {
    S = ScenarioStore.defaultScenario();
    S.meta.name = "未命名场景";
    S.meta.version = "0.1.0";
    S.meta.created = new Date().toISOString().slice(0, 10);
    S.satellites = S.satellites.slice(0, 1);
    S.events = [];
    ScenarioStore.save(S);
    select({ type: "meta" });
    renderAll();
    scToast("已新建空白场景");
  };

  var tplMenu = $("template-menu");
  $("tb-template").onclick = function (e) {
    e.stopPropagation();
    tplMenu.classList.toggle("open");
  };
  document.addEventListener("click", function () { tplMenu.classList.remove("open"); });
  tplMenu.querySelectorAll(".mi").forEach(function (mi) {
    mi.onclick = function () {
      var k = mi.getAttribute("data-tpl");
      S = k === "rendezvous" ? tplRendezvous() : k === "constellation" ? tplConstellation() : ScenarioStore.defaultScenario();
      ScenarioStore.save(S);
      select({ type: "meta" });
      renderAll();
      scToast("已载入模板：" + S.meta.name);
    };
  });

  $("tb-import").onclick = function () { $("import-file").click(); };
  $("import-file").onchange = function () {
    var f = this.files[0];
    if (!f) return;
    var r = new FileReader();
    r.onload = function () {
      try {
        var obj = JSON.parse(r.result);
        if (!obj.meta || !obj.satellites) throw new Error("结构不符");
        S = obj;
        ScenarioStore.save(S);
        select({ type: "meta" });
        renderAll();
        scToast("已导入场景：" + (S.meta.name || f.name));
      } catch (err) {
        scToast("导入失败：不是有效的场景 JSON", "danger");
      }
    };
    r.readAsText(f);
    this.value = "";
  };

  function download(name, text, mime) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: mime }));
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  }
  $("tb-export-json").onclick = function () {
    download((S.meta.name || "场景") + "_v" + (S.meta.version || "1") + ".json", JSON.stringify(S, null, 2), "application/json");
    scToast("已导出 JSON");
  };
  $("tb-export-yaml").onclick = function () {
    download((S.meta.name || "场景") + "_v" + (S.meta.version || "1") + ".yaml", ScenarioStore.toYAML(S), "text/yaml");
    scToast("已导出 YAML");
  };

  /* 预览选项卡 */
  document.querySelectorAll("#code-tabs .tab").forEach(function (t) {
    t.onclick = function () {
      document.querySelectorAll("#code-tabs .tab").forEach(function (x) { x.classList.remove("active"); });
      t.classList.add("active");
      fmt = t.getAttribute("data-fmt");
      renderPreview();
    };
  });
  $("copy-code").onclick = function () {
    var text = fmt === "json" ? JSON.stringify(S, null, 2) : ScenarioStore.toYAML(S);
    if (navigator.clipboard) navigator.clipboard.writeText(text);
    scToast("已复制 " + fmt.toUpperCase() + " 到剪贴板");
  };

  /* ---------- 启动 ---------- */
  function renderAll() {
    renderValidation();
    renderTree();
    renderForm();
    renderPreview();
    markSaved();
    var navName = document.getElementById("nav-scenario-name");
    if (navName) navName.textContent = S.meta.name || "未命名场景";
  }
  renderAll();
})();
