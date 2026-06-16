/* 外接配置页 — 外部系统接入配置 + 真实连接测试 + 配置版本管理（后端权威存储） */
(function () {
  "use strict";

  var C = null;          // 配置（后端拉取）
  var selCat = null;
  var PROTOCOLS = ["gRPC", "HTTP REST", "TCP", "UDP", "WebSocket", "ZeroMQ", "RESP", "InfluxDB HTTP", "本地文件"];
  var AUTHS = ["无", "Bearer Token", "Token", "密码", "mTLS 证书"];

  function $(id) { return document.getElementById(id); }
  function h(tag, cls, html) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (html !== undefined) el.innerHTML = html;
    return el;
  }

  function statusBadge(sys) {
    if (!sys.enabled) return '<span class="badge">未启用</span>';
    if (sys.status === "ok") return '<span class="badge ok"><span class="dot ok"></span>已连接</span>';
    if (sys.status === "warn") return '<span class="badge warn"><span class="dot warn"></span>延迟偏高</span>';
    if (sys.status === "danger") return '<span class="badge danger"><span class="dot danger"></span>连接失败</span>';
    return '<span class="badge">待检测</span>';
  }

  /* ---------- 后端同步 ---------- */
  var saveTimer = null;
  function pushConfig() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      SCAPI.put("/api/external/config", C).catch(function () {
        scToast("配置同步后端失败", "danger");
      });
    }, 400);
  }

  var dirty = false;
  function markDirty() {
    dirty = true;
    pushConfig();
    var chip = $("cfg-ver-chip");
    chip.className = "badge warn mono";
    chip.textContent = C.version + " + 未保存变更";
    renderHealth();
  }

  /* ---------- 左侧分类 ---------- */
  function catStatus(cat) {
    var enabled = cat.systems.filter(function (s) { return s.enabled; });
    if (enabled.some(function (s) { return s.status === "danger"; })) return "danger";
    if (enabled.some(function (s) { return s.status === "warn"; })) return "warn";
    if (enabled.length === 0) return "idle";
    return "ok";
  }
  function renderCats() {
    var body = $("cat-body");
    body.innerHTML = "";
    C.categories.forEach(function (cat) {
      var it = h("div", "cat-item" + (cat.id === selCat ? " selected" : ""));
      var en = cat.systems.filter(function (s) { return s.enabled; }).length;
      it.innerHTML = '<span class="dot ' + catStatus(cat) + '"></span>' +
        '<div style="flex:1;min-width:0;"><div class="name"></div><div class="sub">' + en + "/" + cat.systems.length + " 启用 · " + cat.sub + "</div></div>";
      it.querySelector(".name").textContent = cat.name;
      it.onclick = function () { selCat = cat.id; renderCats(); renderSystems(); };
      body.appendChild(it);
    });
  }

  /* ---------- 中部系统卡片 ---------- */
  function fieldBlock(label, el) {
    var f = h("div", "field");
    var lb = h("label");
    lb.textContent = label;
    f.appendChild(lb);
    f.appendChild(el);
    return f;
  }
  function mkSelect(value, options, onchange) {
    var sl = h("select", "select");
    options.forEach(function (o) {
      var op = h("option");
      op.value = o; op.textContent = o;
      if (o === value) { op.selected = true; op.setAttribute("selected", "selected"); }
      sl.appendChild(op);
    });
    sl.onchange = function () { onchange(sl.value); markDirty(); };
    return sl;
  }
  function mkInput(value, mono, onchange) {
    var inp = h("input", "input" + (mono ? " mono" : ""));
    inp.type = "text";
    inp.value = value == null ? "" : value;
    inp.setAttribute("value", inp.value);
    inp.oninput = function () { onchange(inp.value); inp.setAttribute("value", inp.value); markDirty(); };
    return inp;
  }

  function renderSystems() {
    var col = $("sys-col");
    col.innerHTML = "";
    var cat = C.categories.find(function (c) { return c.id === selCat; });
    if (!cat) return;
    cat.systems.forEach(function (sys) {
      var card = h("section", "panel sys-card" + (sys.enabled ? "" : " disabled"));
      card.id = "card-" + sys.id;

      var head = h("div", "panel-h");
      var left = h("div", "grow");
      var t = h("div", "row");
      var nm = h("span", "t"); nm.textContent = sys.name;
      t.appendChild(nm);
      var bd = h("span", "", statusBadge(sys));
      bd.className = "status-slot";
      t.appendChild(bd);
      left.appendChild(t);
      var ds = h("div", "desc"); ds.textContent = sys.desc;
      left.appendChild(ds);
      head.appendChild(left);
      var sw = h("label", "switch");
      sw.title = sys.enabled ? "停用此系统" : "启用此系统";
      var ck = h("input"); ck.type = "checkbox"; ck.checked = sys.enabled;
      ck.onchange = function () {
        sys.enabled = ck.checked;
        sys.status = "idle";
        sys.latency = null;
        markDirty();
        renderSystems(); renderCats();
        scToast(sys.name + (sys.enabled ? " 已启用，建议测试连接" : " 已停用"), sys.enabled ? "ok" : "warn");
      };
      sw.appendChild(ck);
      sw.appendChild(h("span", "track"));
      head.appendChild(sw);
      card.appendChild(head);

      var body = h("div", "panel-b");
      var g = h("div", "sys-grid");
      g.appendChild(fieldBlock("通信协议", mkSelect(sys.protocol, PROTOCOLS, function (v) { sys.protocol = v; })));
      g.appendChild(fieldBlock("服务地址", mkInput(sys.endpoint, true, function (v) { sys.endpoint = v; })));
      g.appendChild(fieldBlock("超时 (ms)", mkInput(sys.timeout, true, function (v) { sys.timeout = parseInt(v) || 0; })));
      g.appendChild(fieldBlock("鉴权方式", mkSelect(sys.auth, AUTHS, function (v) { sys.auth = v; })));
      if (sys.extra) {
        var ex;
        if (sys.extra.options) ex = mkSelect(sys.extra.value, sys.extra.options, function (v) { sys.extra.value = v; });
        else ex = mkInput(sys.extra.value, true, function (v) { sys.extra.value = v; });
        g.appendChild(fieldBlock(sys.extra.label, ex));
      }
      body.appendChild(g);
      card.appendChild(body);

      var foot = h("div", "sys-foot");
      var lat = h("span", "lat");
      lat.textContent = sys.latency != null ? "往返延迟 " + sys.latency + " ms" : "尚未检测";
      var lc = h("span", "", "");
      lc.textContent = "上次检测 " + (sys.lastCheck || "—");
      var sp = h("span", "grow");
      var test = h("button", "btn sm", "测试连接");
      test.onclick = function () { testSystem(sys, test); };
      foot.appendChild(lat);
      foot.appendChild(lc);
      foot.appendChild(sp);
      foot.appendChild(test);
      card.appendChild(foot);

      col.appendChild(card);
    });
  }

  /* ---------- 连接测试（后端真实探测） ---------- */
  function testSystem(sys, btn, silent) {
    if (!sys.enabled) return Promise.resolve();
    if (btn) { btn.disabled = true; btn.innerHTML = '检测中 <span class="testing"><i></i><i></i><i></i></span>'; }
    return SCAPI.post("/api/external/test/" + encodeURIComponent(sys.id)).then(function (res) {
      sys.status = res.status;
      sys.latency = res.latency;
      sys.lastCheck = res.lastCheck;
      if (btn) { btn.disabled = false; btn.textContent = "测试连接"; }
      renderSystems(); renderCats(); renderHealth();
      if (!silent) {
        var text = sys.status === "ok" ? "连接正常 " + sys.latency + " ms"
          : sys.status === "warn" ? "可达但延迟偏高 " + sys.latency + " ms"
          : "连接失败";
        scToast(sys.name + "：" + text, sys.status);
      }
    }).catch(function (e) {
      if (btn) { btn.disabled = false; btn.textContent = "测试连接"; }
      if (!silent) scToast(sys.name + "：测试请求失败 " + (e.message || ""), "danger");
    });
  }

  $("tb-test-all").onclick = function () {
    var all = [];
    C.categories.forEach(function (c) { c.systems.forEach(function (s) { if (s.enabled) all.push(s); }); });
    scToast("正在检测 " + all.length + " 个已启用系统…");
    SCAPI.post("/api/external/test-all").then(function (body) {
      var results = body.results || {};
      all.forEach(function (s) {
        var r = results[s.id];
        if (r) { s.status = r.status; s.latency = r.latency; s.lastCheck = r.lastCheck; }
      });
      renderSystems(); renderCats(); renderHealth();
      scToast("全部检测完成");
    }).catch(function () { scToast("检测请求失败", "danger"); });
  };

  /* ---------- 健康总览 ---------- */
  function renderHealth() {
    var list = $("health-list");
    list.innerHTML = "";
    var nOk = 0, nAll = 0;
    C.categories.forEach(function (cat) {
      cat.systems.forEach(function (sys) {
        if (!sys.enabled) return;
        nAll++;
        if (sys.status === "ok") nOk++;
        var row = h("div", "health-row");
        row.innerHTML = '<span class="dot ' + (sys.status || "idle") + '"></span><span class="nm"></span><span class="st"></span>';
        row.querySelector(".nm").textContent = sys.name;
        row.querySelector(".st").textContent = sys.latency != null ? sys.latency + " ms" : "—";
        list.appendChild(row);
      });
    });
    $("health-sub").textContent = nOk + "/" + nAll + " 正常";
  }

  /* ---------- 版本管理 ---------- */
  function renderVersions() {
    var list = $("ver-list");
    list.innerHTML = "";
    (C.snapshots || []).forEach(function (snap) {
      var it = h("div", "ver-item");
      var tag = h("span", "ver-tag"); tag.textContent = snap.tag;
      var info = h("div", "ver-info");
      var note = h("div", "ver-note"); note.textContent = snap.note;
      var time = h("div", "ver-time"); time.textContent = snap.time;
      info.appendChild(note); info.appendChild(time);
      it.appendChild(tag); it.appendChild(info);
      if (snap.current) {
        var cur = h("span", "badge accent", "当前");
        cur.style.alignSelf = "center";
        it.appendChild(cur);
      } else {
        var rb = h("button", "btn sm ghost", "回滚");
        rb.style.alignSelf = "center";
        rb.onclick = function () {
          SCAPI.post("/api/external/rollback", { tag: snap.tag }).then(function () {
            return SCAPI.get("/api/external/config");
          }).then(function (cfg) {
            C = cfg;
            dirty = false;
            var chip = $("cfg-ver-chip");
            chip.className = "badge mono";
            chip.textContent = snap.tag + " 当前生效";
            renderAll();
            scToast("已回滚至配置 " + snap.tag + "（" + snap.note + "）", "warn");
          }).catch(function (e) { scToast("回滚失败：" + (e.message || ""), "danger"); });
        };
        it.appendChild(rb);
      }
      list.appendChild(it);
    });
  }

  $("snap-save").onclick = function () {
    var note = $("snap-note").value.trim() || "未填写变更说明";
    SCAPI.put("/api/external/config", C).then(function () {
      return SCAPI.post("/api/external/snapshots", { note: note });
    }).then(function (snap) {
      return SCAPI.get("/api/external/config").then(function (cfg) {
        C = cfg;
        dirty = false;
        $("snap-note").value = "";
        var chip = $("cfg-ver-chip");
        chip.className = "badge mono";
        chip.textContent = snap.tag + " 当前生效";
        renderAll();
        scToast("已保存配置快照 " + snap.tag);
      });
    }).catch(function (e) { scToast("快照保存失败：" + (e.message || ""), "danger"); });
  };

  $("tb-export-cfg").onclick = function () {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(C, null, 2)], { type: "application/json" }));
    a.download = "外接配置_" + C.version + ".json";
    a.click();
    URL.revokeObjectURL(a.href);
    scToast("已导出配置 " + C.version);
  };

  /* ---------- 启动 ---------- */
  function renderAll() {
    renderCats();
    renderSystems();
    renderHealth();
    renderVersions();
  }

  SCAPI.get("/api/external/config").then(function (cfg) {
    C = cfg;
    selCat = C.categories.length ? C.categories[0].id : null;
    $("cfg-ver-chip").textContent = C.version + " 当前生效";
    renderAll();
  }).catch(function () {
    $("cfg-ver-chip").className = "badge danger mono";
    $("cfg-ver-chip").textContent = "后端未连接";
    scToast("无法加载外接配置：后端未连接", "danger");
  });
})();
