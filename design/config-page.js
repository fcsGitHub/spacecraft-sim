/* 外接配置页 — 外部系统接入配置 + 连接测试 + 配置版本管理 */
(function () {
  "use strict";
  var KEY = "scsim_extconfig";

  /* ---------- 默认配置 ---------- */
  function defaultConfig() {
    return {
      version: "v2.4",
      categories: [
        {
          id: "algo", name: "算法服务", sub: "研究算法以服务形式接入",
          systems: [
            {
              id: "algo-maneuver", name: "轨道机动规划服务", desc: "接收当前轨道根数与任务约束，返回机动序列（Δv 与点火时刻）",
              enabled: true, protocol: "gRPC", endpoint: "127.0.0.1:50051",
              timeout: 3000, auth: "无", status: "ok", latency: 12, lastCheck: "10:42:18",
              extra: { label: "算法版本路由", value: "maneuver-rl/v0.9.3" }
            },
            {
              id: "algo-sa", name: "态势感知算法服务", desc: "非合作目标意图识别与威胁评估，订阅全量遥测",
              enabled: true, protocol: "HTTP REST", endpoint: "http://10.0.3.21:8080/api/v1",
              timeout: 5000, auth: "Bearer Token", status: "ok", latency: 28, lastCheck: "10:42:18",
              extra: { label: "算法版本路由", value: "sa-transformer/v1.2.0" }
            },
            {
              id: "algo-sched", name: "任务调度算法服务", desc: "多星成像任务分配与重规划（星座场景使用）",
              enabled: false, protocol: "gRPC", endpoint: "127.0.0.1:50052",
              timeout: 3000, auth: "无", status: "idle", latency: null, lastCheck: "—",
              extra: { label: "算法版本路由", value: "sched-milp/v0.4.1" }
            }
          ]
        },
        {
          id: "engine", name: "仿真引擎", sub: "动力学推进与时间管理",
          systems: [
            {
              id: "eng-orbit", name: "轨道动力学引擎", desc: "高精度轨道递推内核，前端通过 TCP 帧协议同步状态",
              enabled: true, protocol: "TCP", endpoint: "127.0.0.1:9100",
              timeout: 2000, auth: "无", status: "ok", latency: 4, lastCheck: "10:42:18",
              extra: { label: "积分器", value: "RKF7(8)", options: ["RK4", "RKF7(8)", "DP8(53)"] }
            },
            {
              id: "eng-att", name: "姿态动力学引擎", desc: "刚体姿态递推与执行机构模型（可选，未接入时由内置简化模型代替）",
              enabled: false, protocol: "TCP", endpoint: "127.0.0.1:9101",
              timeout: 2000, auth: "无", status: "idle", latency: null, lastCheck: "—",
              extra: { label: "积分器", value: "RK4", options: ["RK4", "RKF7(8)"] }
            }
          ]
        },
        {
          id: "data", name: "数据接口", sub: "遥测落盘与实验记录",
          systems: [
            {
              id: "data-tsdb", name: "遥测时序数据库", desc: "全量遥测写入，回放与指标评估的数据来源",
              enabled: true, protocol: "InfluxDB HTTP", endpoint: "http://127.0.0.1:8086",
              timeout: 5000, auth: "Token", status: "ok", latency: 9, lastCheck: "10:42:18",
              extra: { label: "保留策略", value: "30 天" }
            },
            {
              id: "data-exp", name: "实验记录存储", desc: "场景快照、随机种子、配置版本、指令序列归档 —— 实验可复现的关键链路",
              enabled: true, protocol: "本地文件", endpoint: "./experiments/",
              timeout: 1000, auth: "无", status: "warn", latency: 156, lastCheck: "10:42:18",
              extra: { label: "归档格式", value: "JSON + Parquet" }
            }
          ]
        },
        {
          id: "bus", name: "消息总线", sub: "模块间异步消息分发",
          systems: [
            {
              id: "bus-zmq", name: "ZeroMQ 总线", desc: "PUB/SUB 模式分发遥测帧与事件；指令注入走 REQ/REP 通道",
              enabled: true, protocol: "ZeroMQ", endpoint: "tcp://127.0.0.1:5555",
              timeout: 1000, auth: "无", status: "ok", latency: 2, lastCheck: "10:42:18",
              extra: { label: "订阅主题", value: "telemetry.* / event.* / cmd.ack" }
            },
            {
              id: "bus-redis", name: "Redis 缓存", desc: "最新态势快照缓存，供多个前端实例共享读取",
              enabled: true, protocol: "RESP", endpoint: "127.0.0.1:6379",
              timeout: 1000, auth: "密码", status: "warn", latency: 89, lastCheck: "10:42:18",
              extra: { label: "键空间", value: "scsim:snapshot:*" }
            }
          ]
        },
        {
          id: "viz", name: "可视化服务", sub: "态势推送与外部显示",
          systems: [
            {
              id: "viz-ws", name: "态势推送 WebSocket", desc: "向本前端态势页推送实时状态帧",
              enabled: true, protocol: "WebSocket", endpoint: "ws://127.0.0.1:8765/situation",
              timeout: 2000, auth: "无", status: "ok", latency: 6, lastCheck: "10:42:18",
              extra: { label: "推送频率", value: "20 Hz" }
            },
            {
              id: "viz-wall", name: "大屏显示服务", desc: "对外演示大屏的镜像推流（演示场合启用）",
              enabled: false, protocol: "WebSocket", endpoint: "ws://10.0.3.50:8766/wall",
              timeout: 2000, auth: "无", status: "idle", latency: null, lastCheck: "—",
              extra: { label: "推流分辨率", value: "3840×1080" }
            }
          ]
        }
      ],
      snapshots: [
        { tag: "v2.4", note: "切换机动规划服务至 gRPC 直连", time: "2026-06-12 10:02", current: true },
        { tag: "v2.3", note: "新增态势感知算法服务（transformer v1.2）", time: "2026-06-11 16:40", current: false },
        { tag: "v2.2", note: "遥测库迁移至 InfluxDB，保留 30 天", time: "2026-06-09 09:15", current: false },
        { tag: "v2.1", note: "初始联调配置", time: "2026-06-05 14:22", current: false }
      ]
    };
  }

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    var d = defaultConfig();
    save(d);
    return d;
  }
  function save(c) { try { localStorage.setItem(KEY, JSON.stringify(c)); } catch (e) {} }

  var C = load();
  var selCat = C.categories[0].id;
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

  var dirty = false;
  function markDirty() {
    dirty = true;
    save(C);
    var chip = $("cfg-ver-chip");
    chip.className = "badge warn mono";
    chip.textContent = C.version + " + 未保存变更";
    renderHealth();
  }

  function renderSystems() {
    var col = $("sys-col");
    col.innerHTML = "";
    var cat = C.categories.find(function (c) { return c.id === selCat; });
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
        sys.status = sys.enabled ? "idle" : "idle";
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
      var to = mkInput(sys.timeout, true, function (v) { sys.timeout = parseInt(v) || 0; });
      g.appendChild(fieldBlock("超时 (ms)", to));
      g.appendChild(fieldBlock("鉴权方式", mkSelect(sys.auth, AUTHS, function (v) { sys.auth = v; })));
      if (sys.extra) {
        var ex;
        if (sys.extra.options) ex = mkSelect(sys.extra.value, sys.extra.options, function (v) { sys.extra.value = v; });
        else ex = mkInput(sys.extra.value, true, function (v) { sys.extra.value = v; });
        var fb = fieldBlock(sys.extra.label, ex);
        g.appendChild(fb);
      }
      body.appendChild(g);
      card.appendChild(body);

      var foot = h("div", "sys-foot");
      var lat = h("span", "lat");
      lat.textContent = sys.latency != null ? "往返延迟 " + sys.latency + " ms" : "尚未检测";
      var lc = h("span", "", "");
      lc.textContent = "上次检测 " + sys.lastCheck;
      var sp = h("span", "grow");
      var test = h("button", "btn sm", "测试连接");
      test.onclick = function () { testSystem(sys, card, test); };
      foot.appendChild(lat);
      foot.appendChild(lc);
      foot.appendChild(sp);
      foot.appendChild(test);
      card.appendChild(foot);

      col.appendChild(card);
    });
  }

  /* ---------- 连接测试（模拟） ---------- */
  function testSystem(sys, card, btn, silent) {
    if (!sys.enabled) return Promise.resolve();
    if (btn) { btn.disabled = true; btn.innerHTML = '检测中 <span class="testing"><i></i><i></i><i></i></span>'; }
    return new Promise(function (res) {
      setTimeout(function () {
        // 确定性的“伪随机”：基于 endpoint 长度，保证演示稳定
        var base = 2 + (sys.endpoint.length * 7) % 40;
        if (sys.id === "data-exp" || sys.id === "bus-redis") base += 80; // 保留两个警告示例
        sys.latency = base;
        sys.status = base > 60 ? "warn" : "ok";
        sys.lastCheck = new Date().toTimeString().slice(0, 8);
        save(C);
        if (btn) { btn.disabled = false; btn.textContent = "测试连接"; }
        renderSystems(); renderCats(); renderHealth();
        if (!silent) scToast(sys.name + "：" + (sys.status === "ok" ? "连接正常 " : "可达但延迟偏高 ") + sys.latency + " ms", sys.status);
        res();
      }, 700 + Math.random() * 600);
    });
  }

  $("tb-test-all").onclick = function () {
    var all = [];
    C.categories.forEach(function (c) { c.systems.forEach(function (s) { if (s.enabled) all.push(s); }); });
    scToast("正在检测 " + all.length + " 个已启用系统…");
    Promise.all(all.map(function (s) { return testSystem(s, null, null, true); })).then(function () {
      scToast("全部检测完成");
    });
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
        row.innerHTML = '<span class="dot ' + sys.status + '"></span><span class="nm"></span><span class="st"></span>';
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
    C.snapshots.forEach(function (snap, i) {
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
          C.snapshots.forEach(function (s) { s.current = false; });
          snap.current = true;
          C.version = snap.tag;
          dirty = false;
          save(C);
          var chip = $("cfg-ver-chip");
          chip.className = "badge mono";
          chip.textContent = snap.tag + " 当前生效";
          renderVersions();
          scToast("已回滚至配置 " + snap.tag + "（" + snap.note + "）", "warn");
        };
        it.appendChild(rb);
      }
      list.appendChild(it);
    });
  }

  $("snap-save").onclick = function () {
    var note = $("snap-note").value.trim() || "未填写变更说明";
    var nv = "v" + (parseFloat(C.version.slice(1)) + 0.1).toFixed(1);
    C.snapshots.forEach(function (s) { s.current = false; });
    C.snapshots.unshift({
      tag: nv, note: note,
      time: new Date().toISOString().slice(0, 16).replace("T", " "),
      current: true
    });
    C.version = nv;
    dirty = false;
    save(C);
    $("snap-note").value = "";
    var chip = $("cfg-ver-chip");
    chip.className = "badge mono";
    chip.textContent = nv + " 当前生效";
    renderVersions();
    scToast("已保存配置快照 " + nv);
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
  var chip = $("cfg-ver-chip");
  chip.textContent = C.version + " 当前生效";
  renderCats();
  renderSystems();
  renderHealth();
  renderVersions();
})();
