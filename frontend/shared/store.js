/* 场景数据存储 — 三页共享。后端为权威存储，localStorage 作离线缓存与首屏加速。 */
(function () {
  var KEY = "scsim_scenario";

  /* ---------- 默认演示场景（与后端 defaults.py 同构，离线兜底用） ---------- */
  function defaultScenario() {
    return {
      meta: {
        name: "多星协同观测-A",
        version: "1.2.0",
        author: "算法组",
        created: "2026-06-10",
        description: "三星对地观测编组 + 中轨中继 + 机动试验星与两个非合作目标的态势感知场景，用于轨道机动与任务规划算法验证。"
      },
      sim: {
        epoch: "2026-06-12T04:00:00Z",
        duration: 7200,
        step: 1,
        seed: 20260612,
        record: true
      },
      satellites: [
        sat("SAT-01", "侦察-01", "观测星组", "红方", "光学成像", 6878, 0.0011, 97.5, 60, 90, 0, 86, 1240),
        sat("SAT-02", "侦察-02", "观测星组", "红方", "光学成像", 6878, 0.0011, 97.5, 60, 90, 40, 82, 1240),
        sat("SAT-03", "侦察-03", "观测星组", "红方", "合成孔径雷达", 6928, 0.0015, 97.8, 100, 90, 0, 78, 1560),
        sat("SAT-04", "中继-01", "通信中继组", "红方", "通信中继", 12760, 0.0008, 28.5, 30, 0, 0, 93, 2100),
        sat("SAT-05", "中继-02", "通信中继组", "红方", "通信中继", 12760, 0.0008, 28.5, 150, 0, 120, 91, 2100),
        sat("SAT-06", "机动试验星", "试验星组", "红方", "电子侦察", 7178, 0.0210, 45.0, 200, 30, 0, 64, 980),
        sat("TGT-01", "目标-01", "非合作目标", "蓝方", "未知", 7078, 0.0030, 53.0, 210, 60, 25, 50, 800),
        sat("TGT-02", "目标-02", "非合作目标", "蓝方", "未知", 7278, 0.0150, 63.4, 250, 270, 80, 50, 800)
      ],
      groundStations: [
        { id: "GS-01", name: "北京站", lat: 40.1, lon: 116.3 },
        { id: "GS-02", name: "喀什站", lat: 39.5, lon: 76.0 },
        { id: "GS-03", name: "三亚站", lat: 18.3, lon: 109.5 }
      ],
      events: [
        { t: 600, type: "载荷", target: "SAT-01", action: "光学载荷开机" },
        { t: 900, type: "载荷", target: "SAT-03", action: "SAR 条带成像" },
        { t: 1800, type: "机动", target: "SAT-06", action: "轨道机动 Δv=2.0 m/s 切向" },
        { t: 3600, type: "机动", target: "SAT-06", action: "轨道机动 Δv=1.2 m/s 法向" },
        { t: 5400, type: "载荷", target: "SAT-02", action: "光学载荷关机" }
      ]
    };
  }

  function sat(id, name, group, faction, payload, a, e, i, raan, argp, M0, fuel, mass) {
    return {
      id: id, name: name, group: group, faction: faction,
      mass: mass, fuel: fuel,
      payload: { type: payload, state: "待机", power: payload === "通信中继" ? 450 : 320 },
      orbit: { a: a, e: e, i: i, raan: raan, argp: argp, M0: M0 }
    };
  }

  /* ---------- 本地缓存读写 ---------- */
  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    var d = defaultScenario();
    save(d);
    return d;
  }
  function save(s) {
    try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {}
  }

  /* ---------- 后端同步 ---------- */
  function pull() {
    return SCAPI.get("/api/scenario").then(function (body) {
      if (body && body.data) {
        save(body.data);
        return body.data;
      }
      return null;
    });
  }

  var pushTimer = null;
  var pushCallbacks = [];
  function push(s, onDone) {
    if (onDone) pushCallbacks.push(onDone);
    clearTimeout(pushTimer);
    pushTimer = setTimeout(function () {
      var cbs = pushCallbacks;
      pushCallbacks = [];
      SCAPI.put("/api/scenario", s).then(function (resp) {
        cbs.forEach(function (cb) { cb(null, resp); });
      }).catch(function (err) {
        cbs.forEach(function (cb) { cb(err, null); });
      });
    }, 400);
  }

  /* ---------- YAML 序列化（本地预览用；导出走后端） ---------- */
  function yamlScalar(v) {
    if (typeof v === "string") {
      if (/^[一-龥A-Za-z0-9_\-. :+Δ]*$/.test(v) && !/^[\s\-?:]|[:#]\s|\s$/.test(v) && v !== "") return v;
      return JSON.stringify(v);
    }
    return String(v);
  }
  function toYAML(obj, indent) {
    indent = indent || 0;
    var pad = "  ".repeat(indent);
    var out = [];
    if (Array.isArray(obj)) {
      if (obj.length === 0) return pad + "[]";
      obj.forEach(function (item) {
        if (item !== null && typeof item === "object") {
          var inner = toYAML(item, indent + 1).split("\n");
          out.push(pad + "- " + inner[0].trim());
          for (var k = 1; k < inner.length; k++) out.push(inner[k]);
        } else {
          out.push(pad + "- " + yamlScalar(item));
        }
      });
    } else if (obj !== null && typeof obj === "object") {
      Object.keys(obj).forEach(function (key) {
        var v = obj[key];
        if (v !== null && typeof v === "object") {
          if (Array.isArray(v) && v.length === 0) { out.push(pad + key + ": []"); return; }
          out.push(pad + key + ":");
          out.push(toYAML(v, indent + 1));
        } else {
          out.push(pad + key + ": " + yamlScalar(v));
        }
      });
    } else {
      return pad + yamlScalar(obj);
    }
    return out.join("\n");
  }

  /* ---------- 校验（与后端 simcore/scenario.py 同规则，用于即时反馈） ---------- */
  var EARTH_R = 6371;
  var FACTIONS = ["红方", "蓝方", "中立"];   // 阵营预设值（红蓝对抗）；其它取值仅警告
  function validate(s) {
    var errs = [], warns = [];
    function err(loc, msg) { errs.push({ loc: loc, msg: msg }); }
    function warn(loc, msg) { warns.push({ loc: loc, msg: msg }); }

    if (!s.meta || !s.meta.name) err("场景元信息", "场景名称不能为空");
    if (!s.sim) { err("仿真参数", "缺少仿真参数段"); return { errors: errs, warnings: warns }; }
    if (!(s.sim.duration > 0)) err("仿真参数", "仿真时长必须大于 0");
    if (!(s.sim.step > 0)) err("仿真参数", "仿真步长必须大于 0");
    if (s.sim.step > 60) warn("仿真参数", "步长大于 60s，机动与预警事件可能漏检");
    if (!Number.isInteger(Number(s.sim.seed))) err("仿真参数", "随机种子必须为整数（实验可复现的关键）");

    var ids = {};
    (s.satellites || []).forEach(function (st, idx) {
      var loc = st.name || st.id || "卫星#" + (idx + 1);
      if (!st.id) err(loc, "缺少卫星编号 id");
      else if (ids[st.id]) err(loc, "卫星编号重复：" + st.id);
      ids[st.id] = true;
      if (!st.name) err(loc, "卫星名称不能为空");
      var o = st.orbit || {};
      if (!(o.a > EARTH_R + 100)) err(loc, "半长轴 a=" + o.a + " km 过小（须大于 " + (EARTH_R + 100) + " km）");
      if (!(o.e >= 0 && o.e < 1)) err(loc, "偏心率 e 须在 [0,1) 区间");
      else if (o.a * (1 - o.e) < EARTH_R + 100) err(loc, "近地点高度低于 100 km，轨道将再入");
      if (!(o.i >= 0 && o.i <= 180)) err(loc, "轨道倾角 i 须在 [0°,180°]");
      ["raan", "argp", "M0"].forEach(function (k) {
        if (!(o[k] >= 0 && o[k] < 360)) err(loc, k + " 须在 [0°,360°)");
      });
      if (!(st.fuel >= 0 && st.fuel <= 100)) err(loc, "燃料余量须在 0–100%");
      else if (st.fuel < 20) warn(loc, "燃料余量低于 20%，机动类算法实验可能受限");
      if (!(st.mass > 0)) err(loc, "整星质量须大于 0");
      if (st.faction && FACTIONS.indexOf(st.faction) < 0)
        warn(loc, "阵营 " + st.faction + " 非预设值（红方/蓝方/中立），三维将按中立色显示");
    });
    if ((s.satellites || []).length === 0) err("卫星列表", "场景至少需要 1 颗卫星");
    if ((s.satellites || []).length > 50) warn("卫星列表", "实体超过 50，三维渲染与分析刷新率可能下降");

    (s.groundStations || []).forEach(function (g, idx) {
      var loc = g.name || "地面站#" + (idx + 1);
      if (!(g.lat >= -90 && g.lat <= 90)) err(loc, "纬度须在 [-90°,90°]");
      if (!(g.lon >= -180 && g.lon <= 180)) err(loc, "经度须在 [-180°,180°]");
    });

    (s.events || []).forEach(function (ev, idx) {
      var loc = "预设事件#" + (idx + 1);
      if (!(ev.t >= 0 && ev.t <= s.sim.duration)) err(loc, "触发时刻 t=" + ev.t + "s 超出仿真时长范围");
      if (ev.target && !ids[ev.target]) err(loc, "目标 " + ev.target + " 不存在于卫星列表");
    });

    return { errors: errs, warnings: warns };
  }

  window.ScenarioStore = {
    load: load,
    save: save,
    pull: pull,
    push: push,
    reset: function () { var d = defaultScenario(); save(d); return d; },
    defaultScenario: defaultScenario,
    toYAML: function (s) { return toYAML(s, 0); },
    validate: validate,
    EARTH_R: EARTH_R
  };
})();
