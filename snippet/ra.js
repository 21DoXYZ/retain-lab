/**
 * Revenue Autopilot site snippet (~1.5KB): события продукта → /ingest/saas/events.
 *
 * Подключение (одна строка на сайте тенанта):
 *   <script src="https://cdn.../ra.js" data-endpoint="https://ingest.../ingest/saas/events"
 *           data-token="TENANT_INGEST_TOKEN" data-tenant="hubcontent"></script>
 *
 * Затем из продукта:
 *   ra.identify(userId, email)          // после логина; email хэшируется локально (sha256)
 *   ra.track('generation_completed', {tokens_spent: 12})
 *
 * Автособытия: session_start (раз в 30 мин тишины), page_view для /pricing|/cancel.
 * В сеть уходит ТОЛЬКО sha256(email) — сырой email не покидает страницу.
 */
(function () {
  "use strict";
  var s = document.currentScript || {};
  var w = window.RA_CONFIG || {};   // альтернатива data-атрибутам (SPA/динамический конфиг)
  var cfg = {
    endpoint: (s.dataset && s.dataset.endpoint) || w.endpoint || "",
    token: (s.dataset && s.dataset.token) || w.token || "",
    tenant: (s.dataset && s.dataset.tenant) || w.tenant || "",
    pages: /\/(pricing|plans|cancel)/i,
  };
  var K = "ra_uid", KH = "ra_eh", KS = "ra_sess";

  function iso(d) { return d.toISOString().slice(0, 23).replace("T", " "); }

  function send(type, props) {
    if (!cfg.endpoint || !cfg.tenant) return;
    var e = {
      event_id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()),
      tenant_id: cfg.tenant,
      event_type: type,
      ts: iso(new Date()),
      source: "snippet",
      client_user_id: localStorage.getItem(K) || "",
      email_hash: localStorage.getItem(KH) || "",
      session_id: sessionId(),
      page: location.pathname,
    };
    if (props) for (var k in props) if (!(k in e)) e[k] = props[k];
    try {
      fetch(cfg.endpoint, {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + cfg.token },
        body: JSON.stringify(e),
      }).catch(function () {});
    } catch (_) {}
  }

  function sessionId() {
    var now = Date.now();
    var raw = (sessionStorage.getItem(KS) || "").split("|");
    if (raw.length === 2 && now - Number(raw[1]) < 30 * 60 * 1000) {
      sessionStorage.setItem(KS, raw[0] + "|" + now);
      return raw[0];
    }
    var sid = "s_" + now.toString(36) + Math.random().toString(36).slice(2, 8);
    sessionStorage.setItem(KS, sid + "|" + now);
    setTimeout(function () { send("session_start"); }, 0);
    return sid;
  }

  function sha256hex(text) {
    var data = new TextEncoder().encode(text.trim().toLowerCase());
    return crypto.subtle.digest("SHA-256", data).then(function (buf) {
      return Array.prototype.map.call(new Uint8Array(buf), function (b) {
        return b.toString(16).padStart(2, "0");
      }).join("");
    });
  }

  window.ra = {
    identify: function (userId, email) {
      var hadUser = !!localStorage.getItem(K);
      if (userId) localStorage.setItem(K, String(userId));
      var done = email
        ? sha256hex(email).then(function (h) { localStorage.setItem(KH, h); })
        : Promise.resolve();
      done.then(function () { if (!hadUser && userId) send("login"); });
    },
    track: function (type, props) { send(type, props); },
  };

  sessionId();
  if (cfg.pages.test(location.pathname)) send("page_view");
})();
