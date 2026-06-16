/* 顶部导航 — 三页共享。<script src="shared/nav.js" data-page="scenario|situation|config"></script> */
(function () {
  var page = document.currentScript.getAttribute("data-page") || "";
  var scenarioName = "未加载场景";
  try {
    var raw = localStorage.getItem("scsim_scenario");
    if (raw) scenarioName = (JSON.parse(raw).meta || {}).name || scenarioName;
  } catch (e) {}

  var el = document.createElement("header");
  el.className = "topnav";
  el.innerHTML =
    '<div class="brand">' +
    '  <div class="brand-mark">SC</div>' +
    '  <div><div class="brand-name">空间飞行器仿真系统</div>' +
    '  <div class="brand-sub">SPACECRAFT SIM · 算法研究平台</div></div>' +
    "</div>" +
    "<nav>" +
    '  <a href="scenario.html" data-p="scenario"><span class="num">01</span>场景生成</a>' +
    '  <a href="situation.html" data-p="situation"><span class="num">02</span>仿真态势</a>' +
    '  <a href="config.html" data-p="config"><span class="num">03</span>外接配置</a>' +
    "</nav>" +
    '<div class="nav-right">' +
    '  <div class="scenario-chip">当前场景 <b id="nav-scenario-name"></b></div>' +
    '  <div class="sys-status" id="nav-sys-status"><span class="dot idle"></span>连接中…</div>' +
    "</div>";
  el.querySelector("#nav-scenario-name").textContent = scenarioName;
  var active = el.querySelector('[data-p="' + page + '"]');
  if (active) active.classList.add("active");
  document.body.prepend(el);

  /* 后端健康状态指示 */
  function setSysStatus(ok) {
    var box = document.getElementById("nav-sys-status");
    if (!box) return;
    box.innerHTML = ok
      ? '<span class="dot ok"></span>系统就绪'
      : '<span class="dot danger"></span>后端未连接';
  }
  function checkHealth() {
    fetch("/api/health").then(function (r) { setSysStatus(r.ok); })
      .catch(function () { setSysStatus(false); });
  }
  checkHealth();
  setInterval(checkHealth, 10000);

  /* 后端为权威：拉取当前场景名 */
  fetch("/api/scenario").then(function (r) { return r.json(); }).then(function (body) {
    var name = body && body.data && body.data.meta && body.data.meta.name;
    if (name) {
      var b = document.getElementById("nav-scenario-name");
      if (b) b.textContent = name;
    }
  }).catch(function () {});

  /* toast 工具，三页共用 */
  window.scToast = function (msg, kind) {
    var root = document.getElementById("toast-root");
    if (!root) {
      root = document.createElement("div");
      root.id = "toast-root";
      document.body.appendChild(root);
    }
    var t = document.createElement("div");
    t.className = "toast";
    t.innerHTML = '<span class="dot ' + (kind || "ok") + '"></span><span></span>';
    t.lastChild.textContent = msg;
    root.appendChild(t);
    setTimeout(function () {
      t.style.transition = "opacity 0.3s";
      t.style.opacity = "0";
      setTimeout(function () { t.remove(); }, 320);
    }, 2400);
  };
})();
