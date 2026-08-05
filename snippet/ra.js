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
    post(e, 1);
  }

  // Один ретрай через 2с при сетевой ошибке или 5xx (шлюз пережидает Kafka).
  function post(e, retries) {
    try {
      fetch(cfg.endpoint, {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + cfg.token },
        body: JSON.stringify(e),
      }).then(function (r) {
        if (r.status >= 500 && retries > 0) setTimeout(function () { post(e, retries - 1); }, 2000);
      }).catch(function () {
        if (retries > 0) setTimeout(function () { post(e, retries - 1); }, 2000);
      });
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

  // ── In-app виджет: баннеры кампаний (dunning и т.п.) внутри продукта ───────
  // Инбокс: GET {база}/public/saas/inbox (база выводится из endpoint события).
  // Показ/клик/закрытие уходят событиями inapp_shown/clicked/dismissed - по ним
  // сервер гасит баннер навсегда; localStorage прячет его мгновенно.
  var KD = "ra_inapp_hidden";

  function inboxBase() {
    if (w.inbox_base) return w.inbox_base;
    var m = cfg.endpoint.match(/^(https?:\/\/[^/]+)/);
    return m ? m[1] : "";
  }

  function hiddenIds() {
    try { return JSON.parse(localStorage.getItem(KD) || "[]"); } catch (_) { return []; }
  }

  function hideId(id) {
    var ids = hiddenIds();
    if (ids.indexOf(id) < 0) ids.push(id);
    localStorage.setItem(KD, JSON.stringify(ids.slice(-50)));
  }

  function renderBanner(msg) {
    if (document.getElementById("ra-inapp")) return;
    var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    var bar = document.createElement("div");
    bar.id = "ra-inapp";
    bar.setAttribute("role", "status");
    bar.style.cssText =
      "position:fixed;top:0;left:0;right:0;z-index:2147483000;display:flex;align-items:center;" +
      "gap:14px;padding:12px 18px;background:#101828;color:#fff;font:14px/1.45 system-ui,sans-serif;" +
      "box-shadow:0 6px 24px rgba(16,24,40,.28);" +
      (reduced ? "" : "transform:translateY(-100%);transition:transform .22s ease-out;");
    var text = document.createElement("div");
    text.style.cssText = "flex:1;min-width:0";
    if (msg.title) {
      var b = document.createElement("strong");
      b.textContent = msg.title;
      b.style.cssText = "display:block;font-weight:600";
      text.appendChild(b);
    }
    var p = document.createElement("span");
    p.textContent = msg.body;
    p.style.cssText = "opacity:.85";
    text.appendChild(p);
    bar.appendChild(text);
    if (msg.cta_url) {
      var a = document.createElement("a");
      a.href = msg.cta_url;
      a.textContent = msg.cta_label || "Open";
      a.style.cssText =
        "flex:none;background:#fff;color:#101828;border-radius:100px;padding:8px 16px;" +
        "font-weight:600;text-decoration:none";
      a.addEventListener("click", function () {
        send("inapp_clicked", { meta: JSON.stringify({ message_id: msg.message_id }) });
        hideId(msg.message_id);
      });
      bar.appendChild(a);
    }
    var x = document.createElement("button");
    x.type = "button";
    x.setAttribute("aria-label", "Dismiss");
    x.textContent = "×";
    x.style.cssText =
      "flex:none;background:none;border:0;color:#fff;opacity:.6;font-size:22px;" +
      "line-height:1;cursor:pointer;padding:4px";
    x.addEventListener("click", function () {
      send("inapp_dismissed", { meta: JSON.stringify({ message_id: msg.message_id }) });
      hideId(msg.message_id);
      bar.remove();
    });
    bar.appendChild(x);
    document.body.appendChild(bar);
    if (!reduced) requestAnimationFrame(function () {
      requestAnimationFrame(function () { bar.style.transform = "translateY(0)"; });
    });
    send("inapp_shown", { meta: JSON.stringify({ message_id: msg.message_id }) });
  }

  function checkInbox() {
    var uid = localStorage.getItem(K);
    var base = inboxBase();
    if (!uid || !base || !cfg.token || !cfg.tenant) return;
    fetch(base + "/public/saas/inbox?tenant=" + encodeURIComponent(cfg.tenant) +
          "&user=" + encodeURIComponent(uid), {
      headers: { Authorization: "Bearer " + cfg.token },
    }).then(function (r) { return r.json(); }).then(function (j) {
      var msgs = (j && j.data && j.data.messages) || [];
      var hidden = hiddenIds();
      for (var i = 0; i < msgs.length; i++) {
        if (hidden.indexOf(msgs[i].message_id) < 0) { renderBanner(msgs[i]); break; }
      }
    }).catch(function () {});
  }

  window.ra = {
    identify: function (userId, email) {
      var hadUser = !!localStorage.getItem(K);
      if (userId) localStorage.setItem(K, String(userId));
      var done = email
        ? sha256hex(email).then(function (h) { localStorage.setItem(KH, h); })
        : Promise.resolve();
      done.then(function () {
        if (!hadUser && userId) send("login");
        checkInbox();
      });
    },
    track: function (type, props) { send(type, props); },
  };

  sessionId();
  if (cfg.pages.test(location.pathname)) send("page_view");
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", checkInbox);
  } else {
    checkInbox();
  }
})();
