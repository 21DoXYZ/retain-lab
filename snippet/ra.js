/**
 * Revenue Autopilot site snippet (~7KB gzip): события продукта → /ingest/saas/events.
 *
 * Подключение (одна строка на сайте тенанта):
 *   <script src="https://cdn.../ra.js" data-endpoint="https://ingest.../ingest/saas/events"
 *           data-token="TENANT_INGEST_TOKEN" data-tenant="hubcontent"></script>
 *
 * Затем из продукта:
 *   ra.identify(userId, email)          // после логина; email хэшируется локально (sha256)
 *   ra.track('generation_completed', {tokens_spent: 12})
 *
 * Подписка на телеграм-бота: поставьте в разметку ЛЮБОЙ элемент с атрибутом
 * data-ra-telegram - сниппет сам подставит ссылку с id юзера и спрячет элемент,
 * если канал не подключён:
 *   <a data-ra-telegram>Получать уведомления в Telegram</a>
 * Программно: ra.telegramLink() -> строка ссылки или "" (канал выключен).
 *
 * Автособытия: session_start (раз в 30 мин тишины; с контекстом: referrer,
 * UTM, устройство, экран, язык, таймзона, скорость загрузки, first-touch),
 * page_view (все страницы, вкл. SPA-переходы), page_leave (секунды на странице
 * + глубина скролла), heartbeat (раз в 2 мин, только если юзер реально активен
 * и вкладка видима - из него живёт last_seen и длительность сессий),
 * js_error (первые 5 за сессию - баги продукта предсказывают отток),
 * rage_click (3+ клика в одну точку за 0.7с - фрустрация). Разметка
 * data-ra-event="имя" на любом элементе шлёт событие клика без кода.
 * Приватность: НИКОГДА не собираем тексты, значения полей, заголовки страниц
 * и сырой email - в сеть уходит только sha256(email) и техконтекст.
 */
(function () {
  "use strict";
  var s = document.currentScript || {};
  var w = window.RA_CONFIG || {};   // альтернатива data-атрибутам (SPA/динамический конфиг)
  var cfg = {
    endpoint: (s.dataset && s.dataset.endpoint) || w.endpoint || "",
    token: (s.dataset && s.dataset.token) || w.token || "",
    tenant: (s.dataset && s.dataset.tenant) || w.tenant || "",
    // страницы, которые важны сами по себе (их помечаем отдельным типом)
    pages: /\/(pricing|plans|cancel)/i,
  };
  var K = "ra_uid", KH = "ra_eh", KS = "ra_sess";
  var debug = (s.dataset && s.dataset.debug === "1") || !!w.debug;

  function warn(msg) { if (debug && window.console) console.warn("[ra] " + msg); }

  // ХРАНИЛИЩЕ МОЖЕТ БРОСАТЬ. Приватный режим Safari, запрет сторонних данных,
  // корпоративные политики, iframe без прав - localStorage.getItem кидает
  // исключение. Раньше оно вылетало из ra.track() прямо в код клиента, а на
  // старте роняло весь сниппет: window.ra не создавался и вызов ra.identify
  // валил приложение клиента. Наш код НЕ ИМЕЕТ ПРАВА ломать чужой продукт.
  var mem = {};

  function store(kind) {
    try { return kind === "s" ? window.sessionStorage : window.localStorage; }
    catch (_) { return null; }
  }

  function get(key, kind) {
    var st = store(kind);
    if (st) { try { return st.getItem(key); } catch (_) {} }
    return Object.prototype.hasOwnProperty.call(mem, key) ? mem[key] : null;
  }

  function set(key, value, kind) {
    mem[key] = value;                       // память - всегда, переживёт запрет
    var st = store(kind);
    if (st) { try { st.setItem(key, value); } catch (_) {} }
  }

  function iso(d) { return d.toISOString().slice(0, 23).replace("T", " "); }

  // ── Максимум контекста, ноль PII: техпараметры среды и источника визита ──
  var KF = "ra_ft";                      // first-touch: как человек ПРИШЁЛ впервые

  function utmOf(search) {
    var out = {};
    var keys = ["utm_source", "utm_medium", "utm_campaign", "utm_term",
                "utm_content", "gclid", "fbclid", "ref"];
    try {
      var q = new URLSearchParams(search || location.search);
      for (var i = 0; i < keys.length; i++) {
        var v = q.get(keys[i]);
        if (v) out[keys[i]] = String(v).slice(0, 120);
      }
    } catch (_) {}
    return out;
  }

  function deviceCtx() {
    var d = {};
    try {
      d.lang = navigator.language || "";
      d.tz = (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone || "";
      d.sw = screen.width; d.sh = screen.height;
      d.vw = innerWidth; d.vh = innerHeight;
      d.dpr = Math.round((window.devicePixelRatio || 1) * 100) / 100;
      d.mobile = /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent) ? 1 : 0;
      d.platform = (navigator.userAgentData && navigator.userAgentData.platform)
        || navigator.platform || "";
      var c = navigator.connection;
      if (c && c.effectiveType) d.net = c.effectiveType;
    } catch (_) {}
    return d;
  }

  function loadMs() {
    try {
      var nav = performance.getEntriesByType("navigation")[0];
      if (nav && nav.domContentLoadedEventEnd) return Math.round(nav.domContentLoadedEventEnd);
    } catch (_) {}
    return 0;
  }

  function firstTouch() {
    var raw = get(KF);
    if (raw) { try { return JSON.parse(raw); } catch (_) {} }
    var ft = { ts: Date.now(), ref: (document.referrer || "").slice(0, 200),
               page: location.pathname };
    var utm = utmOf();
    for (var k in utm) if (Object.prototype.hasOwnProperty.call(utm, k)) ft[k] = utm[k];
    set(KF, JSON.stringify(ft));
    return ft;
  }

  function sessionCtx() {
    var m = deviceCtx();
    m.ref = (document.referrer || "").slice(0, 200);
    var utm = utmOf();
    for (var k in utm) if (Object.prototype.hasOwnProperty.call(utm, k)) m[k] = utm[k];
    m.load_ms = loadMs();
    m.first = firstTouch();
    return m;
  }

  function metaProps(obj) {
    try { return { meta: JSON.stringify(obj) }; } catch (_) { return {}; }
  }

  function uuid() {
    try { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (_) {}
    return "e_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  function send(type, props) {
    if (!cfg.endpoint || !cfg.tenant) {
      warn("не задан data-endpoint или data-tenant - событие " + type + " никуда не ушло");
      return;
    }
    var e = {
      event_id: uuid(),
      tenant_id: cfg.tenant,
      event_type: type,
      ts: iso(new Date()),
      source: "snippet",
      client_user_id: get(K) || "",
      email_hash: get(KH) || "",
      session_id: sessionId(),
      page: location.pathname,
    };
    if (props) {
      for (var k in props) {
        // только свои поля: у объекта из чужого кода бывает грязный прототип
        if (Object.prototype.hasOwnProperty.call(props, k) && !(k in e)) e[k] = props[k];
      }
    }
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
    var raw = (get(KS, "s") || "").split("|");
    if (raw.length === 2 && now - Number(raw[1]) < 30 * 60 * 1000) {
      set(KS, raw[0] + "|" + now, "s");
      return raw[0];
    }
    var sid = "s_" + now.toString(36) + Math.random().toString(36).slice(2, 8);
    set(KS, sid + "|" + now, "s");
    setTimeout(function () { send("session_start", metaProps(sessionCtx())); }, 0);
    return sid;
  }

  // Хеш адреса считается ТОЛЬКО в защищённом контексте: на http-странице
  // crypto.subtle отсутствует и обращение к нему бросало исключение прямо в
  // ra.identify(). Теперь на http событие уходит без хеша (склейка сработает
  // по client_user_id), а в отладке об этом честно предупреждаем.
  function sha256hex(text) {
    var subtle = (window.crypto && crypto.subtle) || null;
    if (!subtle || typeof TextEncoder === "undefined") {
      warn("страница не в защищённом контексте (нужен https) - email не хешируется");
      return Promise.resolve("");
    }
    try {
      var data = new TextEncoder().encode(String(text).trim().toLowerCase());
      return subtle.digest("SHA-256", data).then(function (buf) {
        return Array.prototype.map.call(new Uint8Array(buf), function (b) {
          return b.toString(16).padStart(2, "0");
        }).join("");
      }).catch(function () { return ""; });
    } catch (_) {
      return Promise.resolve("");
    }
  }

  // ── In-app виджет: баннеры кампаний (dunning и т.п.) внутри продукта ───────
  // Инбокс: GET {база}/public/saas/inbox (база выводится из endpoint события).
  // Показ/клик/закрытие уходят событиями inapp_shown/clicked/dismissed - по ним
  // сервер гасит баннер навсегда; localStorage прячет его мгновенно.
  var KD = "ra_inapp_hidden";
  var shownThisSession = {};

  // Кнопка баннера не имеет права исполнять код на сайте клиента и вести в
  // сырой плейсхолдер. Сервер уже чистит - это второй рубеж для старых данных.
  function safeUrl(u) {
    u = String(u || "");
    if (!u || u.indexOf("{{") >= 0) return "";
    var low = u.toLowerCase();
    if (low.indexOf("https://") === 0 || low.indexOf("http://") === 0 || u.charAt(0) === "/") return u;
    return "";
  }

  function inboxBase() {
    if (w.inbox_base) return w.inbox_base;
    var m = cfg.endpoint.match(/^(https?:\/\/[^/]+)/);
    return m ? m[1] : "";
  }

  function hiddenIds() {
    try { return JSON.parse(get(KD) || "[]"); } catch (_) { return []; }
  }

  function hideId(id) {
    var ids = hiddenIds();
    if (ids.indexOf(id) < 0) ids.push(id);
    set(KD, JSON.stringify(ids.slice(-50)));
  }

  function renderBanner(msg) {
    if (document.getElementById("ra-inapp")) return;
    if (!document.body) {                    // сниппет позвали до <body>
      document.addEventListener("DOMContentLoaded", function () { renderBanner(msg); });
      return;
    }
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
    var cta = safeUrl(msg.cta_url);
    if (cta) {
      var a = document.createElement("a");
      a.href = cta;
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
    function dismiss() {
      send("inapp_dismissed", { meta: JSON.stringify({ message_id: msg.message_id }) });
      hideId(msg.message_id);
      document.removeEventListener("keydown", onKey);
      bar.remove();
    }
    // Escape закрывает баннер с клавиатуры - тот же контракт, что у крестика
    function onKey(ev) { if (ev.key === "Escape") dismiss(); }
    x.addEventListener("click", dismiss);
    document.addEventListener("keydown", onKey);
    bar.appendChild(x);
    document.body.appendChild(bar);
    if (!reduced) requestAnimationFrame(function () {
      requestAnimationFrame(function () { bar.style.transform = "translateY(0)"; });
    });
    // показ считаем раз в сессию, а не на каждой странице: иначе у активного
    // юзера метрика показов раздувается в десятки раз
    if (!shownThisSession[msg.message_id]) {
      shownThisSession[msg.message_id] = 1;
      send("inapp_shown", { meta: JSON.stringify({ message_id: msg.message_id }) });
    }
  }

  // ── Подписка на телеграм-бота тенанта ──────────────────────────────────
  // Сервер отдаёт ГОТОВУЮ подписанную ссылку (tg_link): голый id в ссылке
  // позволял бы увести чужие уведомления. tgBot - фолбэк для случая, когда
  // сервер старее сниппета.
  var tgBot = "";
  var tgLink = "";
  var waLink = "";

  function telegramLink() {
    if (tgLink) return tgLink;
    var uid = get(K);
    return (tgBot && uid) ? "https://t.me/" + tgBot + "?start=" + encodeURIComponent(uid) : "";
  }

  function applyConnect(selector, href, evName) {
    var els = document.querySelectorAll(selector);
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (!href) { el.style.display = "none"; continue; }
      el.style.display = "";
      if (el.tagName === "A") {
        el.setAttribute("href", href);
        el.setAttribute("target", "_blank");
        el.setAttribute("rel", "noopener");
      }
      if (!el.dataset.raBound) {
        el.dataset.raBound = "1";
        (function (h, name) {
          el.addEventListener("click", function () {
            send(name);
            if (this.tagName !== "A") window.open(h, "_blank", "noopener");
          });
        })(href, evName);
      }
    }
  }

  function applyTelegram() {
    applyConnect("[data-ra-whatsapp]", waLink, "whatsapp_connect_clicked");
    var els = document.querySelectorAll("[data-ra-telegram]");
    var href = telegramLink();
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      // канал не подключён или юзер не опознан - кнопке подписки неоткуда взять
      // привязку, показывать её бессмысленно
      if (!href) { el.style.display = "none"; continue; }
      el.style.display = "";
      if (el.tagName === "A") {
        el.setAttribute("href", href);
        el.setAttribute("target", "_blank");
        el.setAttribute("rel", "noopener");
      }
      if (!el.dataset.raTgBound) {
        el.dataset.raTgBound = "1";
        el.addEventListener("click", function () {
          send("telegram_connect_clicked");
          if (this.tagName !== "A") window.open(telegramLink(), "_blank", "noopener");
        });
      }
    }
  }

  function checkInbox() {
    var uid = get(K);
    var base = inboxBase();
    if (!uid || !base || !cfg.token || !cfg.tenant) { applyTelegram(); return; }
    fetch(base + "/public/saas/inbox?tenant=" + encodeURIComponent(cfg.tenant) +
          "&user=" + encodeURIComponent(uid), {
      headers: { Authorization: "Bearer " + cfg.token },
    }).then(function (r) { return r.json(); }).then(function (j) {
      tgBot = (j && j.data && j.data.tg_bot) || "";
      tgLink = (j && j.data && j.data.tg_link) || "";
      waLink = (j && j.data && j.data.wa_link) || "";
      applyTelegram();
      var msgs = (j && j.data && j.data.messages) || [];
      var hidden = hiddenIds();
      for (var i = 0; i < msgs.length; i++) {
        if (hidden.indexOf(msgs[i].message_id) < 0) { renderBanner(msgs[i]); break; }
      }
    }).catch(function () {});
  }

  window.ra = {
    identify: function (userId, email) {
      try {
        var hadUser = !!get(K);
        if (userId) set(K, String(userId));
        var done = email
          ? sha256hex(email).then(function (h) { if (h) set(KH, h); })
          : Promise.resolve();
        done.then(function () {
          if (!hadUser && userId) send("login");
          checkInbox();
        }).catch(function () {});
      } catch (err) { warn("identify: " + err); }
    },
    track: function (type, props) {
      try { send(type, props); } catch (err) { warn("track: " + err); }
    },
    telegramLink: function () {
      try { return telegramLink(); } catch (_) { return ""; }
    },
  };

  // ── Поведение: время на странице, активность, фрустрация, ошибки ─────────
  var pageEnter = Date.now();
  var maxScroll = 0;
  var lastActivity = Date.now();
  var leaveSent = false;

  function scrollPct() {
    try {
      var doc = document.documentElement;
      var total = doc.scrollHeight - innerHeight;
      if (total <= 0) return 100;
      return Math.min(100, Math.round((scrollY / total) * 100));
    } catch (_) { return 0; }
  }

  function noteActivity() {
    lastActivity = Date.now();
    var p = scrollPct();
    if (p > maxScroll) maxScroll = p;
  }

  ["scroll", "mousemove", "keydown", "touchstart", "click"].forEach(function (ev) {
    addEventListener(ev, noteActivity, { passive: true, capture: true });
  });

  // Сколько секунд человек РЕАЛЬНО провёл на странице - главный сигнал
  // вовлечённости. Шлём на уходе (закрытие, скрытие вкладки, SPA-переход).
  function sendLeave() {
    if (leaveSent) return;
    var secs = Math.round((Date.now() - pageEnter) / 1000);
    if (secs < 2) return;                  // мгновенный отскок не считаем уходом
    leaveSent = true;
    send("page_leave", metaProps({ seconds: secs, scroll_pct: maxScroll }));
  }

  function resetPage() {
    pageEnter = Date.now();
    maxScroll = scrollPct();
    leaveSent = false;
  }

  addEventListener("pagehide", sendLeave);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") sendLeave();
    else resetPage();                      // вернулся во вкладку - новый отсчёт
  });

  // Heartbeat раз в 2 минуты, только если вкладка видима и была активность:
  // из него живут last_seen и честная длительность сессий. Фоновая вкладка
  // молчит - «работал 8 часов» из открытой и забытой вкладки было бы враньём.
  setInterval(function () {
    try {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - lastActivity > 120000) return;
      send("heartbeat", metaProps({ scroll_pct: maxScroll }));
    } catch (_) {}
  }, 120000);

  // Ошибки JS продукта: баги -> фрустрация -> отток. Только техчасть
  // (сообщение+файл), максимум 5 за сессию, чтобы цикл ошибок не заспамил шину.
  var errBudget = 5;
  addEventListener("error", function (ev) {
    try {
      if (errBudget <= 0 || !ev || !ev.message) return;
      errBudget--;
      send("js_error", metaProps({
        message: String(ev.message).slice(0, 200),
        src: String(ev.filename || "").slice(0, 200),
        line: ev.lineno || 0,
      }));
    } catch (_) {}
  });
  addEventListener("unhandledrejection", function (ev) {
    try {
      if (errBudget <= 0) return;
      errBudget--;
      var r = ev && ev.reason;
      send("js_error", metaProps({
        message: String((r && r.message) || r || "unhandledrejection").slice(0, 200),
      }));
    } catch (_) {}
  });

  // Rage click: 3+ клика в одну точку за 0.7с - человек тычет в неработающий
  // элемент. Сигнал фрустрации, который не поймать ни одной метрикой сервера.
  var clicks = [];
  addEventListener("click", function (ev) {
    try {
      var now = Date.now();
      clicks.push({ t: now, x: ev.clientX, y: ev.clientY });
      clicks = clicks.filter(function (c) { return now - c.t < 700; });
      if (clicks.length >= 3) {
        var f = clicks[0];
        if (Math.abs(ev.clientX - f.x) < 30 && Math.abs(ev.clientY - f.y) < 30) {
          clicks = [];
          send("rage_click", metaProps({ x: ev.clientX, y: ev.clientY }));
        }
      }
      // разметка data-ra-event="имя" шлёт событие клика без кода на стороне клиента
      var el = ev.target && ev.target.closest && ev.target.closest("[data-ra-event]");
      if (el && el.dataset.raEvent) send(String(el.dataset.raEvent).slice(0, 60));
    } catch (_) {}
  }, { capture: true, passive: true });

  // Одностраничные приложения меняют адрес без перезагрузки: без этого хука
  // переход на страницу тарифов внутри SPA не давал события, и «смотрел цены»
  // как сигнал не работал вообще.
  function watchSpaRoutes() {
    var last = location.pathname;
    function onRoute() {
      if (location.pathname === last) return;
      sendLeave();                         // время на ПРЕДЫДУЩЕЙ странице
      resetPage();
      last = location.pathname;
      send("page_view");
      if (cfg.pages.test(last)) send("paywall_viewed");
    }
    ["pushState", "replaceState"].forEach(function (name) {
      var orig = history[name];
      if (typeof orig !== "function") return;
      history[name] = function () {
        var out = orig.apply(this, arguments);
        setTimeout(onRoute, 0);
        return out;
      };
    });
    window.addEventListener("popstate", onRoute);
  }

  try {
    sessionId();
    // Просмотр страницы шлём ВСЕГДА: иначе на сайте с трафиком мы видим одно
    // событие на сессию, и клиенту честно кажется, что ничего не работает.
    send("page_view");
    if (cfg.pages.test(location.pathname)) send("paywall_viewed");
    watchSpaRoutes();
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", checkInbox);
    } else {
      checkInbox();
    }
    // Долгоживущая SPA-вкладка без перезагрузок иначе никогда не увидит новый
    // баннер (несписание случается ПОСЛЕ загрузки страницы). Раз в 5 минут -
    // дёшево и укладывается в rate-limit инбокса.
    setInterval(function () {
      try { if (!document.getElementById("ra-inapp")) checkInbox(); } catch (_) {}
    }, 5 * 60 * 1000);
  } catch (err) {
    warn("init: " + err);      // сайт клиента продолжает работать в любом случае
  }
})();
