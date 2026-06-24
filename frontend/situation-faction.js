/* 阵营切换器 — 战争迷雾视角切换。全局显示真值，阵营显示己方+已感知。 */
(function () {
  "use strict";

  function distinctFactions(scn) {
    var set = {};
    (scn.satellites || []).forEach(function (s) {
      if (s.faction) set[s.faction] = true;
    });
    // 中立等同全局，不单列
    delete set["中立"];
    return Object.keys(set);
  }

  function build(opts) {
    var scn = opts.scenario();
    var anchor = document.getElementById("view-modes");
    if (!anchor) return null;
    var wrap = document.createElement("div");
    wrap.className = "faction-switch";
    wrap.id = "faction-switch";

    var current = "全局";
    var options = ["全局"].concat(distinctFactions(scn));

    function render() {
      wrap.innerHTML = "";
      options.forEach(function (f) {
        var b = document.createElement("button");
        b.className = "faction-btn" + (f === current ? " active" : "");
        b.textContent = f;
        b.onclick = function () {
          if (current === f) return;
          current = f;
          render();
          opts.onChange(f);
        };
        wrap.appendChild(b);
      });
    }
    render();
    anchor.parentNode.insertBefore(wrap, anchor.nextSibling);
    return {
      current: function () { return current; },
      rebuild: function () {
        scn = opts.scenario();
        options = ["全局"].concat(distinctFactions(scn));
        if (options.indexOf(current) < 0) current = "全局";
        render();
      }
    };
  }

  window.SitFaction = { build: build };
})();
