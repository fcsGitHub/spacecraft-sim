/* ModelRegistry — 拉取并缓存 /api/models，供编辑器动态生成模型下拉与参数表单。
   后端不可用时降级到内置兜底列表，保证离线可编辑。 */
(function () {
  "use strict";
  var FALLBACK = [
    { model_type: "prop.thruster", display_name: "推进", category: "propulsion", model_kind: "atomic", attribute_schema: {} },
    { model_type: "orbit.j2", display_name: "J2 轨道", category: "orbit", model_kind: "atomic", attribute_schema: {} },
    { model_type: "aocs.simple", display_name: "简化姿态", category: "attitude", model_kind: "atomic", attribute_schema: {} },
    { model_type: "payload.generic", display_name: "通用载荷", category: "payload", model_kind: "atomic", attribute_schema: {} },
    { model_type: "sensor.camera", display_name: "光学相机", category: "sensor", model_kind: "atomic",
      attribute_schema: {
        fov_deg: { type: "number", unit: "°", default: 5.0, desc: "视场全角" },
        max_range_km: { type: "number", unit: "km", default: 2000.0, desc: "最大作用距离" },
        sun_exclusion_deg: { type: "number", unit: "°", default: 30.0, desc: "防眩光最小日-视线夹角" },
        ifov_urad: { type: "number", unit: "µrad", default: 50.0, desc: "每像素瞬时视场" },
        gsd_threshold_m: { type: "number", unit: "m", default: 5.0, desc: "成像质量门限(GSD)" },
        point_mode: { type: "select", options: ["跟踪目标", "对地固定"], default: "跟踪目标", desc: "指向模式" } } },
    { model_type: "adjud.proximity", display_name: "接近预警裁决", category: "adjudication", model_kind: "adjudication",
      attribute_schema: { threshold_km: { type: "number", unit: "km", default: 100.0, desc: "预警门限距离" } } },
    { model_type: "adjud.photo", display_name: "空间拍照裁决", category: "adjudication", model_kind: "adjudication", attribute_schema: {} },
  ];

  var _all = null;

  function load() {
    return SCAPI.get("/api/models").then(function (list) {
      _all = Array.isArray(list) ? list : FALLBACK;
      return _all;
    }).catch(function () {
      _all = FALLBACK;
      return _all;
    });
  }
  function all() { return _all || FALLBACK; }
  function byKind(kind) { return all().filter(function (m) { return m.model_kind === kind; }); }
  function get(type) {
    var found = all().filter(function (m) { return m.model_type === type; });
    return found.length ? found[0] : null;
  }
  function paramSchema(type) { var m = get(type); return (m && m.attribute_schema) || {}; }
  function defaultsFor(type) {
    var s = paramSchema(type), out = {};
    Object.keys(s).forEach(function (k) { out[k] = s[k].default; });
    return out;
  }

  window.ModelRegistry = {
    load: load, all: all, byKind: byKind, get: get,
    paramSchema: paramSchema, defaultsFor: defaultsFor, FALLBACK: FALLBACK,
  };
})();
