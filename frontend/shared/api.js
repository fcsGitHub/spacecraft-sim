/* 后端 API 客户端 — REST + WebSocket（自动重连），三页共享。 */
(function () {
  "use strict";

  function request(method, path, body) {
    var opts = { method: method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (resp) {
      var isJson = (resp.headers.get("content-type") || "").indexOf("json") >= 0;
      return (isJson ? resp.json() : resp.text()).then(function (data) {
        if (!resp.ok) {
          var detail = data && data.detail !== undefined ? data.detail : data;
          var msg = typeof detail === "string" ? detail : JSON.stringify(detail);
          var err = new Error(msg || ("HTTP " + resp.status));
          err.status = resp.status;
          err.detail = detail;
          throw err;
        }
        return data;
      });
    });
  }

  /* WebSocket 态势通道：断线 2s 后自动重连 */
  function connectSituation(handlers) {
    var closed = false;
    var ws = null;
    var pingTimer = null;
    var faction = "";                       // 当前阵营（重连后重发）

    function sendFaction() {
      if (ws && ws.readyState === 1) {
        ws.send(JSON.stringify({ op: "set_faction", faction: faction }));
      }
    }

    function open() {
      if (closed) return;
      var proto = location.protocol === "https:" ? "wss://" : "ws://";
      ws = new WebSocket(proto + location.host + "/ws/situation");
      ws.onopen = function () {
        if (handlers.onOpen) handlers.onOpen();
        if (faction) sendFaction();          // 重连后恢复阵营视图
        pingTimer = setInterval(function () {
          if (ws && ws.readyState === 1) ws.send("ping");
        }, 15000);
      };
      ws.onmessage = function (e) {
        var msg;
        try { msg = JSON.parse(e.data); } catch (err) { return; }
        if (msg.type === "status" && handlers.onStatus) handlers.onStatus(msg.data);
        if (msg.type === "frame" && handlers.onFrame) handlers.onFrame(msg);
      };
      ws.onclose = function () {
        clearInterval(pingTimer);
        if (handlers.onClose) handlers.onClose();
        if (!closed) setTimeout(open, 2000);
      };
      ws.onerror = function () { try { ws.close(); } catch (e) {} };
    }
    open();
    return {
      close: function () { closed = true; clearInterval(pingTimer); if (ws) ws.close(); },
      setFaction: function (f) { faction = f || ""; sendFaction(); }
    };
  }

  window.SCAPI = {
    get: function (p) { return request("GET", p); },
    post: function (p, b) { return request("POST", p, b === undefined ? {} : b); },
    put: function (p, b) { return request("PUT", p, b); },
    del: function (p) { return request("DELETE", p); },
    connectSituation: connectSituation
  };
})();
