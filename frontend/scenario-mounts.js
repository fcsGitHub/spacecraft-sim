/* MountsEditor — 卫星组件链（仅 atomic 模型）+ 子卫星(children) 编辑。
   依赖 window.FormKit 与 window.ModelRegistry。 */
(function () {
  "use strict";
  var FK = window.FormKit;

  var DEFAULT_CHAIN = [
    { name: "thruster", model: "prop.thruster" },
    { name: "orbit", model: "orbit.j2" },
    { name: "attitude", model: "aocs.simple" },
    { name: "payload", model: "payload.generic" },
  ];

  function swap(arr, a, b) { var t = arr[a]; arr[a] = arr[b]; arr[b] = t; }

  /* 组件链分区：增/删/上下移/选 atomic 模型/改参数。直接读写 sat.components。 */
  function componentSection(sat, refresh) {
    var s = FK.section("组件链（逻辑链）— 按顺序推进，仅挂载原子模型");
    if (!sat.components) {
      var tip = FK.h("div", "muted");
      tip.textContent = "当前使用标准链（推进→轨道→姿态→载荷）。点击下方按钮显式化以编辑。";
      s.appendChild(tip);
      var materialize = FK.h("button", "btn sm", "显式化标准链");
      materialize.onclick = function () {
        sat.components = JSON.parse(JSON.stringify(DEFAULT_CHAIN));
        refresh();
      };
      s.appendChild(materialize);
      return s;
    }
    var atomicTypes = ModelRegistry.byKind("atomic").map(function (m) { return m.model_type; });
    sat.components.forEach(function (comp, i) {
      var card = FK.h("div", "mount-card");
      var head = FK.h("div", "mount-head");
      var nameInp = FK.textInput(comp.name, function (v) { comp.name = v; }, { mono: true });
      nameInp.style.maxWidth = "140px";
      head.appendChild(FK.field("组件名", nameInp));
      head.appendChild(FK.field("原子模型", FK.selectInput(comp.model, atomicTypes, function (v) {
        comp.model = v; comp.params = {}; refresh();
      })));
      var ops = FK.h("div", "mount-ops");
      var up = FK.h("button", "btn xs", "↑"); up.disabled = i === 0;
      up.onclick = function () { swap(sat.components, i, i - 1); refresh(); };
      var dn = FK.h("button", "btn xs", "↓"); dn.disabled = i === sat.components.length - 1;
      dn.onclick = function () { swap(sat.components, i, i + 1); refresh(); };
      var rm = FK.h("button", "btn xs danger-btn", "×");
      rm.onclick = function () { sat.components.splice(i, 1); refresh(); };
      ops.appendChild(up); ops.appendChild(dn); ops.appendChild(rm);
      head.appendChild(ops);
      card.appendChild(head);
      comp.params = comp.params || {};
      card.appendChild(FK.paramForm(ModelRegistry.paramSchema(comp.model), comp.params,
        function (k, v) { comp.params[k] = v; }));
      s.appendChild(card);
    });
    var add = FK.h("button", "btn sm", "+ 添加组件");
    add.onclick = function () {
      var t = atomicTypes[0] || "orbit.j2";
      sat.components.push({ name: "comp" + (sat.components.length + 1), model: t, params: {} });
      refresh();
    };
    s.appendChild(add);
    return s;
  }

  /* 子卫星分区：列出 children，增/删/进入编辑。hooks: {refresh, onSelectChild, onAddChild}。 */
  function childrenSection(sat, hooks) {
    var s = FK.section("子卫星 — 独立可显示实体，与本星以母子关联");
    sat.children = sat.children || [];
    if (!sat.children.length) {
      var empty = FK.h("div", "muted"); empty.textContent = "无子卫星。"; s.appendChild(empty);
    }
    sat.children.forEach(function (kid, i) {
      var row = FK.h("div", "child-row");
      var open = FK.h("button", "btn xs", (kid.name || kid.id) + " ↗");
      open.onclick = function () { hooks.onSelectChild(i); };
      var rm = FK.h("button", "btn xs danger-btn", "删除");
      rm.onclick = function () { sat.children.splice(i, 1); hooks.refresh(); };
      row.appendChild(open); row.appendChild(rm);
      s.appendChild(row);
    });
    var add = FK.h("button", "btn sm", "+ 添加子卫星");
    add.onclick = function () { hooks.onAddChild(); };
    s.appendChild(add);
    return s;
  }

  window.MountsEditor = { componentSection: componentSection, childrenSection: childrenSection };
})();
