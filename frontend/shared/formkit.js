/* FormKit — 场景编辑器共享 UI 原语 + attribute_schema 驱动参数表单。buildless 全局。
   值变更后统一回调 FormKit.onChange（编辑器启动时设为 refreshLight）。 */
(function () {
  "use strict";
  function fire() { if (FK.onChange) FK.onChange(); }

  function h(tag, cls, html) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (html !== undefined) el.innerHTML = html;
    return el;
  }
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function field(label, inputEl, opts) {
    opts = opts || {};
    var f = h("div", "field" + (opts.span ? " span" + opts.span : ""));
    var lb = h("label"); lb.textContent = label; f.appendChild(lb);
    f.appendChild(inputEl);
    if (opts.hint) { var hint = h("div", "hint"); hint.textContent = opts.hint; f.appendChild(hint); }
    return f;
  }
  function textInput(value, onInput, opts) {
    opts = opts || {};
    var inp = h("input", "input" + (opts.mono ? " mono" : ""));
    inp.type = "text";
    inp.value = value == null ? "" : value;
    inp.setAttribute("value", inp.value);
    inp.oninput = function () { onInput(inp.value); inp.setAttribute("value", inp.value); fire(); };
    return inp;
  }
  function numInput(value, onInput, opts) {
    opts = opts || {};
    var inp = h("input", "input mono");
    inp.type = "number";
    if (opts.step != null) inp.step = opts.step;
    inp.value = value == null ? "" : value;
    inp.setAttribute("value", inp.value);
    inp.oninput = function () { onInput(parseFloat(inp.value)); inp.setAttribute("value", inp.value); fire(); };
    return inp;
  }
  function selectInput(value, options, onInput) {
    var sl = h("select", "select");
    options.forEach(function (o) {
      var op = h("option"); op.value = o; op.textContent = o;
      if (o === value) { op.selected = true; op.setAttribute("selected", "selected"); }
      sl.appendChild(op);
    });
    sl.onchange = function () { onInput(sl.value); fire(); };
    return sl;
  }
  function toggleInput(value, onInput) {
    var wrap = h("label", "switch");
    var inp = h("input"); inp.type = "checkbox"; inp.checked = !!value;
    inp.onchange = function () { onInput(inp.checked); fire(); };
    wrap.appendChild(inp); wrap.appendChild(h("span", "track"));
    return wrap;
  }
  function section(title) {
    var s = h("div", "fsection");
    var t = h("h3"); t.textContent = title; s.appendChild(t);
    return s;
  }
  function grid(parent) { var g = h("div", "fgrid"); if (parent) parent.appendChild(g); return g; }

  /* attribute_schema 驱动的参数表单。schema:{key:{type,unit,default,options,desc}}。
     values: 当前 params（缺省回退 default）。onChange(key,value) 每次编辑回调。 */
  function paramForm(schema, values, onChange) {
    var g = grid(null);
    values = values || {};
    Object.keys(schema || {}).forEach(function (key) {
      var spec = schema[key] || {};
      var cur = values[key] != null ? values[key] : spec.default;
      var label = (spec.desc || key) + (spec.unit ? " (" + spec.unit + ")" : "");
      var input;
      if (spec.type === "select") {
        input = selectInput(cur, spec.options || [], function (v) { onChange(key, v); });
      } else if (spec.type === "boolean") {
        input = toggleInput(cur, function (v) { onChange(key, v); });
      } else if (spec.type === "string") {
        input = textInput(cur, function (v) { onChange(key, v); });
      } else {
        input = numInput(cur, function (v) { onChange(key, v); });
      }
      g.appendChild(field(label, input, { hint: spec.type === "select" ? "" : ("默认 " + spec.default) }));
    });
    if (!Object.keys(schema || {}).length) {
      var none = h("div", "muted"); none.textContent = "该模型无可配置参数"; g.appendChild(none);
    }
    return g;
  }

  var FK = {
    onChange: null,
    h: h, esc: esc, field: field, textInput: textInput, numInput: numInput,
    selectInput: selectInput, toggleInput: toggleInput, section: section, grid: grid,
    paramForm: paramForm,
  };
  window.FormKit = FK;
})();
