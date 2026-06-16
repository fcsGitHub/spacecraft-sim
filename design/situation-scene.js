/* 三维态势场景 — Three.js 地球 + 轨道 + 卫星 + 标签 */
(function () {
  "use strict";
  var MU = 398600.4418;
  var EARTH_R = 6371;
  var SCALE = 1 / 100; // 1 单位 = 100 km
  var OMEGA_E = (2 * Math.PI) / 86164;

  var GROUP_COLORS = {
    "观测星组": "#5b8def",
    "通信中继组": "#3fb5ad",
    "试验星组": "#d9a13f",
    "非合作目标": "#d96459"
  };
  var FALLBACK_COLORS = ["#9b7fd4", "#6fae6f", "#c47fb0"];

  var renderer, scene, camera, controls, raycaster;
  var earthGroup, satGroup, orbitGroup, trailGroup, localGroup;
  var labelLayer, canvas, onSelectCb;
  var sats = [];       // {data, mesh, orbitLine, trailLine, trailBuf, color, labelEl}
  var stations = [];   // {data, mesh, labelEl}
  var selectedId = null;
  var viewMode = "global";
  var curT = 0;
  var tweaks = { labels: true, trailSec: 1200, orbitOpacity: 0.55 };
  var fallbackIdx = 0, groupColorCache = {};

  function groupColor(g) {
    if (GROUP_COLORS[g]) return GROUP_COLORS[g];
    if (!groupColorCache[g]) {
      groupColorCache[g] = FALLBACK_COLORS[fallbackIdx % FALLBACK_COLORS.length];
      fallbackIdx++;
    }
    return groupColorCache[g];
  }

  /* ---------- 轨道递推（开普勒） ---------- */
  function eciPos(o, t) {
    var a = o.a, e = o.e || 0;
    var n = Math.sqrt(MU / (a * a * a));
    var M = (o.M0 * Math.PI) / 180 + n * t;
    var E = M;
    for (var k = 0; k < 6; k++) E = E - (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
    var nu = 2 * Math.atan2(Math.sqrt(1 + e) * Math.sin(E / 2), Math.sqrt(1 - e) * Math.cos(E / 2));
    var r = a * (1 - e * Math.cos(E));
    var xp = r * Math.cos(nu), yp = r * Math.sin(nu);
    var cO = Math.cos((o.raan * Math.PI) / 180), sO = Math.sin((o.raan * Math.PI) / 180);
    var ci = Math.cos((o.i * Math.PI) / 180), si = Math.sin((o.i * Math.PI) / 180);
    var cw = Math.cos((o.argp * Math.PI) / 180), sw = Math.sin((o.argp * Math.PI) / 180);
    var x = (cO * cw - sO * sw * ci) * xp + (-cO * sw - sO * cw * ci) * yp;
    var y = (sO * cw + cO * sw * ci) * xp + (-sO * sw + cO * cw * ci) * yp;
    var z = si * sw * xp + si * cw * yp;
    return { x: x, y: y, z: z, r: r, nu: nu };
  }
  function toThree(p) { return new THREE.Vector3(p.x * SCALE, p.z * SCALE, -p.y * SCALE); }
  function speed(o, t) {
    var p = eciPos(o, t);
    return Math.sqrt(MU * (2 / p.r - 1 / o.a));
  }

  /* ---------- 初始化 ---------- */
  function init(opts) {
    canvas = opts.canvas;
    labelLayer = opts.labelLayer;
    onSelectCb = opts.onSelect || function () {};

    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: false, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    scene = new THREE.Scene();
    scene.background = new THREE.Color("#0d1117");

    camera = new THREE.PerspectiveCamera(45, 2, 0.5, 30000);
    camera.position.set(190, 110, 230);

    controls = new THREE.OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 75;
    controls.maxDistance = 2200;

    scene.add(new THREE.AmbientLight(0x8899bb, 0.55));
    var sun = new THREE.DirectionalLight(0xfff4e0, 0.9);
    sun.position.set(500, 180, 300);
    scene.add(sun);

    // 星空
    var starGeo = new THREE.BufferGeometry();
    var starPos = new Float32Array(1200 * 3);
    for (var i = 0; i < 1200; i++) {
      var th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
      var rr = 9000 + Math.random() * 9000;
      var v = new THREE.Vector3(rr * Math.sin(ph) * Math.cos(th), rr * Math.cos(ph), rr * Math.sin(ph) * Math.sin(th));
      starPos[i * 3] = v.x; starPos[i * 3 + 1] = v.y; starPos[i * 3 + 2] = v.z;
    }
    starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
    scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0x7788aa, size: 1.6, sizeAttenuation: false, transparent: true, opacity: 0.7 })));

    // 地球
    earthGroup = new THREE.Group();
    var earth = new THREE.Mesh(
      new THREE.SphereGeometry(EARTH_R * SCALE, 48, 36),
      new THREE.MeshPhongMaterial({ color: 0x16314f, emissive: 0x081320, specular: 0x16243a, shininess: 8 })
    );
    earthGroup.add(earth);
    var grid = new THREE.Mesh(
      new THREE.SphereGeometry(EARTH_R * SCALE * 1.001, 36, 24),
      new THREE.MeshBasicMaterial({ color: 0x3a6a9a, wireframe: true, transparent: true, opacity: 0.13 })
    );
    earthGroup.add(grid);
    var atmo = new THREE.Mesh(
      new THREE.SphereGeometry(EARTH_R * SCALE * 1.035, 48, 36),
      new THREE.MeshBasicMaterial({ color: 0x4a7fc0, transparent: true, opacity: 0.055, side: THREE.BackSide })
    );
    earthGroup.add(atmo);
    scene.add(earthGroup);

    orbitGroup = new THREE.Group(); scene.add(orbitGroup);
    trailGroup = new THREE.Group(); scene.add(trailGroup);
    satGroup = new THREE.Group(); scene.add(satGroup);
    localGroup = new THREE.Group(); scene.add(localGroup);

    raycaster = new THREE.Raycaster();
    raycaster.params.Points = { threshold: 3 };

    var downPos = null;
    canvas.addEventListener("pointerdown", function (e) { downPos = [e.clientX, e.clientY]; });
    canvas.addEventListener("pointerup", function (e) {
      if (!downPos) return;
      var dx = e.clientX - downPos[0], dy = e.clientY - downPos[1];
      downPos = null;
      if (dx * dx + dy * dy > 25) return; // 拖拽不算点击
      var rect = canvas.getBoundingClientRect();
      var m = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(m, camera);
      raycaster.params.Mesh = {};
      var meshes = sats.map(function (s) { return s.hit; });
      var hits = raycaster.intersectObjects(meshes);
      if (hits.length) onSelectCb(hits[0].object.userData.satId);
    });

    window.addEventListener("resize", resize);
    resize();
  }

  function resize() {
    var w = canvas.clientWidth || canvas.parentElement.clientWidth;
    var hh = canvas.clientHeight || canvas.parentElement.clientHeight;
    if (!w || !hh) return;
    renderer.setSize(w, hh, false);
    camera.aspect = w / hh;
    camera.updateProjectionMatrix();
  }

  /* ---------- 构建场景实体 ---------- */
  function clearGroup(g) { while (g.children.length) g.remove(g.children[0]); }

  function makeOrbitLine(orbit, color) {
    var pts = [];
    for (var k = 0; k <= 180; k++) {
      var M0save = orbit.M0;
      var o2 = { a: orbit.a, e: orbit.e, i: orbit.i, raan: orbit.raan, argp: orbit.argp, M0: (k / 180) * 360 };
      pts.push(toThree(eciPos(o2, 0)));
      orbit.M0 = M0save;
    }
    var geo = new THREE.BufferGeometry().setFromPoints(pts);
    return new THREE.Line(geo, new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: tweaks.orbitOpacity }));
  }

  function build(scenario) {
    clearGroup(orbitGroup); clearGroup(satGroup); clearGroup(trailGroup);
    labelLayer.innerHTML = "";
    sats = []; stations = [];

    scenario.satellites.forEach(function (sd) {
      var color = groupColor(sd.group);
      var mesh = new THREE.Mesh(
        new THREE.SphereGeometry(1.1, 12, 10),
        new THREE.MeshBasicMaterial({ color: color })
      );
      // 放大的不可见命中体，便于点击
      var hit = new THREE.Mesh(new THREE.SphereGeometry(4.5, 8, 6), new THREE.MeshBasicMaterial({ visible: false }));
      hit.userData.satId = sd.id;
      mesh.add(hit);
      var ring = new THREE.Mesh(
        new THREE.RingGeometry(2.4, 2.9, 32),
        new THREE.MeshBasicMaterial({ color: "#ffffff", side: THREE.DoubleSide, transparent: true, opacity: 0.9 })
      );
      ring.visible = false;
      mesh.add(ring);
      satGroup.add(mesh);

      var orbitLine = makeOrbitLine(sd.orbit, color);
      orbitGroup.add(orbitLine);

      var MAXTRAIL = 90;
      var tb = new Float32Array(MAXTRAIL * 3);
      var tgeo = new THREE.BufferGeometry();
      tgeo.setAttribute("position", new THREE.BufferAttribute(tb, 3));
      tgeo.setDrawRange(0, 0);
      var trail = new THREE.Line(tgeo, new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: 0.85 }));
      trailGroup.add(trail);

      var label = document.createElement("div");
      label.className = "sat-label";
      label.textContent = sd.name;
      labelLayer.appendChild(label);

      sats.push({ data: sd, mesh: mesh, hit: hit, ring: ring, orbitLine: orbitLine, trail: trail, trailBuf: tb, color: color, labelEl: label, maxTrail: MAXTRAIL });
    });

    (scenario.groundStations || []).forEach(function (gd) {
      var lat = (gd.lat * Math.PI) / 180, lon = (gd.lon * Math.PI) / 180;
      var R = EARTH_R * SCALE * 1.005;
      var pos = new THREE.Vector3(R * Math.cos(lat) * Math.cos(lon), R * Math.sin(lat), -R * Math.cos(lat) * Math.sin(lon));
      var m = new THREE.Mesh(new THREE.ConeGeometry(0.8, 2.2, 6), new THREE.MeshBasicMaterial({ color: "#3fb5ad" }));
      m.position.copy(pos);
      m.lookAt(pos.clone().multiplyScalar(2));
      earthGroup.add(m);
      var label = document.createElement("div");
      label.className = "sat-label gs";
      label.textContent = gd.name;
      labelLayer.appendChild(label);
      stations.push({ data: gd, mesh: m, labelEl: label });
    });
  }

  function applyOrbitChange(satId, newOrbit) {
    var s = sats.find(function (x) { return x.data.id === satId; });
    if (!s) return;
    s.data.orbit = newOrbit;
    orbitGroup.remove(s.orbitLine);
    s.orbitLine = makeOrbitLine(newOrbit, s.color);
    orbitGroup.add(s.orbitLine);
  }

  /* ---------- 每帧更新 ---------- */
  function setTime(t) {
    curT = t;
    earthGroup.rotation.y = OMEGA_E * t;
    sats.forEach(function (s) {
      var p = toThree(eciPos(s.data.orbit, t));
      s.mesh.position.copy(p);
      // 轨迹：从 t-trailSec 到 t 均匀采样（确定性，支持回放任意跳转）
      var n = s.maxTrail;
      var span = tweaks.trailSec;
      for (var k = 0; k < n; k++) {
        var tk = t - span + (span * k) / (n - 1);
        var pk = toThree(eciPos(s.data.orbit, Math.max(tk, 0)));
        s.trailBuf[k * 3] = pk.x; s.trailBuf[k * 3 + 1] = pk.y; s.trailBuf[k * 3 + 2] = pk.z;
      }
      s.trail.geometry.attributes.position.needsUpdate = true;
      s.trail.geometry.setDrawRange(0, n);
    });
  }

  function satPos(id, t) {
    var s = sats.find(function (x) { return x.data.id === id; });
    if (!s) return null;
    return eciPos(s.data.orbit, t == null ? curT : t);
  }

  /* ---------- 相机与局部视图 ---------- */
  var lastTarget = new THREE.Vector3();
  function updateCamera() {
    var selSat = sats.find(function (s) { return s.data.id === selectedId; });
    if (viewMode === "global" || !selSat) {
      controls.target.lerp(new THREE.Vector3(0, 0, 0), 0.08);
      controls.minDistance = 75;
    } else {
      var p = selSat.mesh.position;
      var delta = p.clone().sub(controls.target);
      controls.target.copy(p);
      camera.position.add(delta);
      controls.minDistance = viewMode === "local" ? 4 : 20;
      if (viewMode === "local") {
        var d = camera.position.distanceTo(p);
        if (d > 60) camera.position.copy(p.clone().add(camera.position.clone().sub(p).normalize().multiplyScalar(30)));
      }
    }
  }

  function updateLocalLines() {
    clearGroup(localGroup);
    if (viewMode !== "local" || !selectedId) return;
    var sel = sats.find(function (s) { return s.data.id === selectedId; });
    if (!sel) return;
    sats.forEach(function (s) {
      if (s === sel) return;
      var d = s.mesh.position.distanceTo(sel.mesh.position) * 100; // km
      if (d < 3000) {
        var geo = new THREE.BufferGeometry().setFromPoints([sel.mesh.position, s.mesh.position]);
        var ln = new THREE.Line(geo, new THREE.LineDashedMaterial({ color: "#8899bb", dashSize: 1.2, gapSize: 0.8, transparent: true, opacity: 0.7 }));
        ln.computeLineDistances();
        localGroup.add(ln);
        s.labelEl.dataset.dist = d.toFixed(0) + " km";
      } else delete s.labelEl.dataset.dist;
    });
  }

  /* ---------- 标签投影 ---------- */
  var pv = new THREE.Vector3();
  function updateLabels() {
    var rect = canvas.getBoundingClientRect();
    var camPos = camera.position;
    var Re = EARTH_R * SCALE;
    function place(el, worldPos, extra) {
      if (!tweaks.labels) { el.style.display = "none"; return; }
      pv.copy(worldPos).project(camera);
      if (pv.z > 1) { el.style.display = "none"; return; }
      // 地球遮挡判断
      var toObj = worldPos.clone().sub(camPos);
      var len = toObj.length();
      var dir = toObj.normalize();
      var tc = -camPos.dot(dir);
      if (tc > 0 && tc < len) {
        var closest = camPos.clone().add(dir.multiplyScalar(tc));
        if (closest.length() < Re * 0.99) { el.style.display = "none"; return; }
      }
      el.style.display = "block";
      el.style.left = ((pv.x + 1) / 2) * rect.width + "px";
      el.style.top = ((1 - pv.y) / 2) * rect.height + "px";
      el.textContent = extra || el.dataset.base || el.textContent;
    }
    sats.forEach(function (s) {
      s.labelEl.dataset.base = s.data.name;
      var txt = s.data.name + (s.labelEl.dataset.dist && viewMode === "local" && s.data.id !== selectedId ? " · " + s.labelEl.dataset.dist : "");
      s.labelEl.classList.toggle("sel", s.data.id === selectedId);
      place(s.labelEl, s.mesh.position, txt);
    });
    stations.forEach(function (g) {
      var wp = g.mesh.getWorldPosition(new THREE.Vector3());
      place(g.labelEl, wp);
    });
  }

  function frame() {
    updateCamera();
    controls.update();
    updateLocalLines();
    sats.forEach(function (s) {
      s.ring.visible = s.data.id === selectedId;
      if (s.ring.visible) s.ring.lookAt(camera.position);
      var d = camera.position.distanceTo(s.mesh.position);
      var sc = Math.max(0.6, d / 260);
      s.mesh.scale.setScalar(sc);
    });
    renderer.render(scene, camera);
    updateLabels();
  }

  window.SitScene = {
    init: init,
    build: build,
    setTime: setTime,
    frame: frame,
    resize: resize,
    satPos: satPos,
    eciPos: eciPos,
    speed: speed,
    applyOrbitChange: applyOrbitChange,
    groupColor: groupColor,
    setSelected: function (id) { selectedId = id; },
    setViewMode: function (m) { viewMode = m; },
    setTweaks: function (t) {
      Object.assign(tweaks, t);
      sats.forEach(function (s) { s.orbitLine.material.opacity = tweaks.orbitOpacity; });
    },
    EARTH_R: EARTH_R,
    MU: MU
  };
})();
