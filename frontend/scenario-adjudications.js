/* AdjudEditor — 场景级裁决列表编辑：选 adjudication 类型 + 参数表单。
   依赖 window.FormKit 与 window.ModelRegistry。读写 S.adjudications。 */
(function () {
  "use strict";
  var FK = window.FormKit;

  function render(S, refresh) {
    var s = FK.section("裁决模型 — 引擎级中立全局裁决（与实体平级调度）");
    S.adjudications = S.adjudications || [];
    var types = ModelRegistry.byKind("adjudication").map(function (m) { return m.model_type; });
    if (!types.length) types = ["adjud.proximity", "adjud.photo"];
    if (!S.adjudications.length) {
      var empty = FK.h("div", "muted"); empty.textContent = "未声明裁决（引擎将默认启用接近预警）。";
      s.appendChild(empty);
    }
    S.adjudications.forEach(function (adj, i) {
      var card = FK.h("div", "mount-card");
      var head = FK.h("div", "mount-head");
      head.appendChild(FK.field("裁决类型", FK.selectInput(adj.type, types, function (v) {
        adj.type = v; adj.params = {}; refresh();
      })));
      var rm = FK.h("button", "btn xs danger-btn", "×");
      rm.onclick = function () { S.adjudications.splice(i, 1); refresh(); };
      var ops = FK.h("div", "mount-ops"); ops.appendChild(rm); head.appendChild(ops);
      card.appendChild(head);
      adj.params = adj.params || {};
      card.appendChild(FK.paramForm(ModelRegistry.paramSchema(adj.type), adj.params,
        function (k, v) { adj.params[k] = v; }));
      s.appendChild(card);
    });
    var add = FK.h("button", "btn sm", "+ 添加裁决");
    add.onclick = function () {
      S.adjudications.push({ type: types[0], params: {} });
      refresh();
    };
    s.appendChild(add);
    return s;
  }

  window.AdjudEditor = { render: render };
})();
