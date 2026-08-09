/**
 * Revenue Autopilot site snippet (~10KB gzip): события продукта → /ingest/saas/events.
 *
 * Подключение (одна строка на сайте тенанта):
 *   <script src="https://cdn.../ra.js" data-endpoint="https://ingest.../ingest/saas/events"
 *           data-token="TENANT_INGEST_TOKEN" data-tenant="hubcontent"></script>
 *
 * Затем из продукта:
 * ПРИВЯЗКА К ЮЗЕРУ (иначе события анонимны и не крепятся к человеку). Два пути:
 *   1) декларативно в теге - серверный шаблон подставит логин:
 *      data-user-id="{{user.id}}" data-user-email="{{user.email}}"
 *   2) из кода приложения ПОСЛЕ логина:
 *      ra.identify("user_12345", "user@example.com")
 *   email хэшируется локально (sha256), сырой адрес страницу не покидает.
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
 * Устройство/среда (session_start.meta + heartbeat): язык(и), таймзона, экран,
 * DPR, глубина цвета, платформа, модель/версия ОС/архитектура (Client Hints,
 * Chromium), память, ядра, тач/pointer, dark/reduced-motion/contrast,
 * ориентация, установленная PWA, HDR, сеть (тип/скорость/rtt/save-data).
 * Гео: страна/регион/город - на шлюзе из IP (+ таймзона как кросс-проверка VPN).
 * Web Vitals (page_leave/heartbeat): LCP, CLS, INP, load_ms.
 * Вовлечённость: download_click, outbound_click, copy_event(len), field_focus
 * (имя поля, НЕ значение), form_submit, media_play/complete, tab_switches.
 * Атрибуция: gclid/gbraid/wbraid/fbclid/msclkid/ttclid/li_fat_id + entry/exit.
 * RFM (кросс-сессия, localStorage): visits, days_known, days_since_last,
 * pricing_visits (повторные заходы на прайсинг - сильнейший buy-intent).
 * Ещё: GPU-строка (уровень устройства), батарея (Android), время суток/дня,
 * тип навигации, динамика скролла (reversals), dwell по секциям, колебание
 * до первого действия (ttfi), активное время, смена сети/offline.
 * iPhone/Safari: userAgentData/deviceMemory/battery/connection/GPU/CLS
 * там пусты - закрыто серверным разбором UA (ОС/браузер/тип на шлюзе) +
 * iOS-версия из UA, apple_pay/pay_api (платёжная готовность), dnt/cookies.
 * Приватность: НИКОГДА не собираем тексты, значения полей (в т.ч. пароли),
 * заголовки страниц и сырой email - только sha256(email), техконтекст и гео.
 */
(function () {
  "use strict";
  if (window.ra) return;   // повторная вставка тега не должна дублировать
                           // слушатели, hearbeat-интервалы и обёртку pushState
  var s = document.currentScript || {};
  var w = window.RA_CONFIG || {};   // альтернатива data-атрибутам (SPA/динамический конфиг)
  var cfg = {
    endpoint: (s.dataset && s.dataset.endpoint) || w.endpoint || "",
    token: (s.dataset && s.dataset.token) || w.token || "",
    tenant: (s.dataset && s.dataset.tenant) || w.tenant || "",
    // Декларативная привязка: залогиненного юзера можно отдать прямо в теге
    // (серверный шаблон подставит) - тогда ra.identify() руками звать не надо.
    //   data-user-id="{{user.id}}" data-user-email="{{user.email}}"
    // или window.RA_CONFIG = { user_id, user_email }.
    userId: (s.dataset && s.dataset.userId) || w.user_id || "",
    userEmail: (s.dataset && s.dataset.userEmail) || w.user_email || "",
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
                "utm_content", "gclid", "gbraid", "wbraid", "fbclid",
                "msclkid", "ttclid", "li_fat_id", "ref"];
    try {
      var q = new URLSearchParams(search || location.search);
      for (var i = 0; i < keys.length; i++) {
        var v = q.get(keys[i]);
        if (v) out[keys[i]] = String(v).slice(0, 120);
      }
    } catch (_) {}
    return out;
  }

  function mq(q) { try { return matchMedia(q).matches ? 1 : 0; } catch (_) { return 0; } }

  // Модель/бренд/версия ОС - высокоэнтропийные Client Hints (async, Chromium).
  // Резолвим один раз при старте, кладём в модульную переменную - следующие
  // события несут её в meta. Первое session_start может уйти без модели -
  // heartbeat/page_leave её уже добавят.
  var hicues = {};
  var envx = {};                       // GPU/батарея - резолвятся при старте
  (function () {
    try {
      var ua = navigator.userAgentData;
      if (ua && ua.getHighEntropyValues) {
        ua.getHighEntropyValues(["model", "platformVersion", "architecture",
                                 "bitness", "fullVersionList"]).then(function (h) {
          hicues = {
            model: h.model || "", os_ver: h.platformVersion || "",
            arch: h.architecture || "", bits: h.bitness || "",
            brands: (h.fullVersionList || []).map(function (b) {
              return b.brand + " " + b.version; }).join(", ").slice(0, 200),
          };
        }).catch(function () {});
      }
    } catch (_) {}
    // GPU-строка: лучший прокси уровня устройства (кошелька) на Android.
    // Провал создания WebGL-контекста = самый дешёвый девайс, это тоже сигнал.
    try {
      var cv = document.createElement("canvas");
      var gl = cv.getContext("webgl") || cv.getContext("experimental-webgl");
      if (gl) {
        var dbg = gl.getExtension("WEBGL_debug_renderer_info");
        if (dbg) envx.gpu = String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || "").slice(0, 80);
      } else { envx.gpu = "none"; }
    } catch (_) {}
    // Батарея: на Chrome-Android промпта НЕТ. Низкий заряд без зарядки =
    // скорая смерть сессии (не считать обрыв за намерение уйти); зарядка+wifi
    // = «лежачее» окно, лучшее для апселла.
    try {
      if (navigator.getBattery) {
        navigator.getBattery().then(function (b) {
          envx.batt = Math.round(b.level * 100);
          envx.charging = b.charging ? 1 : 0;
        }).catch(function () {});
      }
    } catch (_) {}
  })();

  // ── RFM: кросс-сессионные счётчики. Давность+частота - самые проверенные
  // предикторы оттока в мире, а стоят 15 строк. localStorage per-browser -
  // это НИЖНЯЯ оценка возвратов, не идентификатор.
  var KV = "ra_visits", KL = "ra_last", KFS = "ra_first", KPV = "ra_pricing";
  var PRICING_RE = /\/(pricing|plans|billing|upgrade|tarif|price)/i;

  function rfm() {
    var out = {};
    try {
      var now = Date.now();
      var visits = parseInt(get(KV) || "0", 10) + 1;
      set(KV, String(visits));
      out.visits = visits;
      var first = parseInt(get(KFS) || "0", 10);
      if (!first) { set(KFS, String(now)); first = now; }
      out.days_known = Math.floor((now - first) / 86400000);
      var last = parseInt(get(KL) || "0", 10);
      if (last) out.days_since_last = Math.floor((now - last) / 86400000);
      set(KL, String(now));
      // повторные заходы на прайсинг между сессиями - сильнейший buy-intent
      if (PRICING_RE.test(location.pathname)) {
        var pv = parseInt(get(KPV) || "0", 10) + 1;
        set(KPV, String(pv));
        out.pricing_visits = pv;
      } else {
        var pvp = parseInt(get(KPV) || "0", 10);
        if (pvp) out.pricing_visits = pvp;
      }
    } catch (_) {}
    return out;
  }

  function deviceCtx() {
    var d = {};
    try {
      d.lang = navigator.language || "";
      d.langs = (navigator.languages || []).slice(0, 4).join(",");
      d.tz = (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone || "";
      d.sw = screen.width; d.sh = screen.height;
      d.vw = innerWidth; d.vh = innerHeight;
      d.dpr = Math.round((window.devicePixelRatio || 1) * 100) / 100;
      d.depth = screen.colorDepth || 0;
      d.mobile = /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent) ? 1 : 0;
      d.platform = (navigator.userAgentData && navigator.userAgentData.platform)
        || navigator.platform || "";
      // железо (в ЮВА собираем): память, ядра, тач
      if (navigator.deviceMemory) d.ram = navigator.deviceMemory;
      if (navigator.hardwareConcurrency) d.cores = navigator.hardwareConcurrency;
      d.touch = navigator.maxTouchPoints || 0;
      d.pointer = mq("(pointer: coarse)") ? "coarse"
        : (mq("(pointer: fine)") ? "fine" : "");
      // модель/версия ОС/архитектура - если high-entropy уже отрезолвился
      for (var hk in hicues) {
        if (Object.prototype.hasOwnProperty.call(hicues, hk) && hicues[hk])
          d[hk] = hicues[hk];
      }
      // среда/предпочтения: сегменты и UX-соответствие
      d.dark = mq("(prefers-color-scheme: dark)");
      d.reduce_motion = mq("(prefers-reduced-motion: reduce)");
      d.contrast = mq("(prefers-contrast: more)");
      d.orient = mq("(orientation: portrait)") ? "portrait" : "landscape";
      d.standalone = mq("(display-mode: standalone)");   // установленная PWA
      d.hdr = mq("(dynamic-range: high)");
      // сеть: тип, скорость, режим экономии
      var c = navigator.connection;
      if (c) {
        if (c.effectiveType) d.net = c.effectiveType;
        if (c.downlink) d.downlink = c.downlink;
        if (c.rtt) d.rtt = c.rtt;
        if (c.saveData) d.save_data = 1;
      }
      // бот-фильтр для чистоты данных (не фича юзера)
      if (navigator.webdriver) d.bot = 1;
      // iOS: userAgentData в WebKit нет вовсе - версию ОС парсим из UA,
      // тип устройства определяем явно (модель Apple не отдаёт никак).
      var uas = navigator.userAgent || "";
      d.ios = /iPhone|iPad|iPod/.test(uas) ? 1 : 0;
      if (d.ios || d.platform === "MacIntel") {
        var mo = uas.match(/OS (\d+[_\d]*) like Mac/);
        if (mo && !d.os_ver) d.os_ver = mo[1].replace(/_/g, ".");
        d.ipad = (/iPad/.test(uas)
                  || (d.platform === "MacIntel" && navigator.maxTouchPoints > 1)) ? 1 : 0;
      }
      // Платёжная готовность: карта в Apple/Google Pay = транзакционный юзер +
      // уровень устройства. canMakePayments не требует промпта. Работает там,
      // где батарея/сеть/память на iPhone молчат.
      try {
        if (window.ApplePaySession && ApplePaySession.canMakePayments
            && ApplePaySession.canMakePayments()) d.apple_pay = 1;
      } catch (_) {}
      if (window.PaymentRequest) d.pay_api = 1;
      // сегменты: приватность и стоимость трафика
      d.dnt = (navigator.doNotTrack === "1" || window.doNotTrack === "1") ? 1 : 0;
      d.cookies = navigator.cookieEnabled ? 1 : 0;
      d.reduced_data = mq("(prefers-reduced-data: reduce)");
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
    // GPU/батарея (если уже отрезолвились), RFM, локальное время суток
    for (var ek in envx)
      if (Object.prototype.hasOwnProperty.call(envx, ek)) m[ek] = envx[ek];
    var r = rfm();
    for (var rk in r)
      if (Object.prototype.hasOwnProperty.call(r, rk)) m[rk] = r[rk];
    try {
      var d = new Date();
      m.local_hour = d.getHours();
      m.dow = d.getDay();
      var nav = performance.getEntriesByType("navigation")[0];
      if (nav && nav.type) m.nav_type = nav.type;   // navigate|reload|back_forward
    } catch (_) {}
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
    // Таймзона в meta КАЖДОГО события: сервер выводит из неё страну (гео), а
    // не только из session_start - иначе country был бы лишь на первом событии.
    try {
      var _tz = (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone || "";
      if (_tz) e.meta = JSON.stringify({ tz: _tz });
    } catch (_) {}
    if (props) {
      // Поля-колонки (tokens_spent и пр.) кладём как есть; ВСЁ остальное - в
      // meta-JSON: шина отбрасывает неизвестные колонки молча, и кастомные
      // свойства ra.track(...) раньше просто исчезали.
      var COLS = { amount: 1, currency: 1, plan_id: 1, subscription_id: 1,
                   invoice_id: 1, charge_id: 1, status: 1, tokens_spent: 1,
                   tokens_balance: 1, meta: 1 };
      var extra = null;
      for (var k in props) {
        // только свои поля: у объекта из чужого кода бывает грязный прототип
        if (!Object.prototype.hasOwnProperty.call(props, k) || (k in e)) continue;
        if (k === "meta") {
          // meta СЛИВАЕМ, не перезаписываем: в конверте уже лежит {tz},
          // событие со своей meta (rage/page_leave) не должно её потерять
          var cur = {};
          if (e.meta) { try { cur = JSON.parse(e.meta) || {}; } catch (_) {} }
          var add = props.meta;
          if (typeof add === "string") { try { add = JSON.parse(add); } catch (_) { add = {}; } }
          for (var mk in add) {
            if (Object.prototype.hasOwnProperty.call(add, mk)) cur[mk] = add[mk];
          }
          try { e.meta = JSON.stringify(cur); } catch (_) {}
        } else if (COLS[k]) { e[k] = props[k]; }
        else { (extra = extra || {})[k] = props[k]; }
      }
      if (extra) {
        var base = {};
        if (e.meta) { try { base = JSON.parse(e.meta) || {}; } catch (_) {} }
        for (var k2 in extra) {
          if (Object.prototype.hasOwnProperty.call(extra, k2)) base[k2] = extra[k2];
        }
        try { e.meta = JSON.stringify(base); } catch (_) {}
      }
    }
    post(e, 1);
  }

  // ── Очередь недоставленного ───────────────────────────────────────────
  // Мобильная сеть рвётся, вкладки закрываются: событие, не ушедшее после
  // ретраев, ложится в localStorage (кап 50) и уезжает при следующей
  // загрузке страницы одним батчем. Лучше поздно, чем никогда: дедуп по
  // event_id на приёме делает повторы безопасными.
  var KQ = "ra_q";

  function qload() {
    try { return JSON.parse(get(KQ) || "[]") || []; } catch (_) { return []; }
  }

  function qsave(items) {
    try { set(KQ, JSON.stringify(items.slice(-50))); } catch (_) {}
  }

  function enqueue(e) {
    var q = qload();
    q.push(e);
    qsave(q);
  }

  function flushQueue() {
    var q = qload();
    if (!q.length || !cfg.endpoint || !cfg.token) return;
    fetch(cfg.endpoint, {
      method: "POST", keepalive: true,
      headers: { "Content-Type": "application/json",
                 Authorization: "Bearer " + cfg.token },
      body: JSON.stringify(q),
    }).then(function (r) {
      if (r.ok) qsave([]);           // доехало - очередь чиста
      else if (r.status < 500 && r.status !== 429) qsave([]);  // яд не копим
    }).catch(function () {});         // сеть всё ещё лежит - попробуем позже
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
        if (r.status >= 500 || r.status === 429) {
          if (retries > 0)
            setTimeout(function () { post(e, retries - 1); }, 2000 + Math.random() * 1000);
          else enqueue(e);
        }
      }).catch(function () {
        if (retries > 0)
          setTimeout(function () { post(e, retries - 1); }, 2000 + Math.random() * 1000);
        else enqueue(e);
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

  // Колебание перед первым действием: долгая пауза до первого осмысленного
  // взаимодействия - чистейший предвестник отказа и рычаг для A/B копии.
  var firstInteractAt = 0;
  function noteInteract() {
    if (!firstInteractAt) firstInteractAt = Date.now();
  }

  // Динамика скролла поверх уже собираемого потока: развороты и рывки =
  // «не могу найти» = растерянность; ровный медленный скролл = чтение.
  var scrollReversals = 0, lastScrollY = 0, lastScrollDir = 0, activeMs = 0;
  var lastTick = Date.now();

  function scrollPct() {
    try {
      var doc = document.documentElement;
      var total = doc.scrollHeight - innerHeight;
      if (total <= 0) return 100;
      return Math.min(100, Math.round((scrollY / total) * 100));
    } catch (_) { return 0; }
  }

  function noteActivity() {
    var now = Date.now();
    // активное время: суммируем промежутки между действиями, если пауза < 30с
    // (свой idle-детектор без промпт-API); «оставил вкладку на диване» не в счёт
    if (now - lastActivity < 30000) activeMs += now - lastActivity;
    lastActivity = now;
    var p = scrollPct();
    if (p > maxScroll) maxScroll = p;
  }

  ["scroll", "mousemove", "keydown", "touchstart", "click"].forEach(function (ev) {
    addEventListener(ev, noteActivity, { passive: true, capture: true });
  });
  ["keydown", "touchstart", "click"].forEach(function (ev) {
    addEventListener(ev, noteInteract, { passive: true, capture: true });
  });
  addEventListener("scroll", function () {
    try {
      var y = scrollY, dir = y > lastScrollY ? 1 : (y < lastScrollY ? -1 : 0);
      if (dir && lastScrollDir && dir !== lastScrollDir) scrollReversals++;
      if (dir) lastScrollDir = dir;
      lastScrollY = y;
    } catch (_) {}
  }, { passive: true });

  // Dwell по секциям: ЧТО именно человека зацепило (цены/фичи/FAQ), а не
  // просто глубина скролла. Секции - [data-ra-section] или заголовки h2/h3.
  var sectionMs = {}, sectionSeen = {};
  (function () {
    try {
      if (!window.IntersectionObserver) return;
      var io = new IntersectionObserver(function (ents) {
        var now = Date.now();
        ents.forEach(function (e) {
          var el = e.target;
          var name = (el.getAttribute && (el.getAttribute("data-ra-section")
                      || (el.textContent || "").trim().slice(0, 40))) || "";
          if (!name) return;
          if (e.isIntersecting) { sectionSeen[name] = now; }
          else if (sectionSeen[name]) {
            sectionMs[name] = (sectionMs[name] || 0) + (now - sectionSeen[name]);
            delete sectionSeen[name];
          }
        });
      }, { threshold: 0.5 });
      var scan = function () {
        var els = document.querySelectorAll("[data-ra-section], h2, h3");
        for (var i = 0; i < els.length && i < 40; i++) io.observe(els[i]);
      };
      if (document.readyState === "loading")
        document.addEventListener("DOMContentLoaded", scan);
      else scan();
    } catch (_) {}
  })();

  function topSections() {
    var now = Date.now(), out = [];
    for (var k in sectionSeen)                   // ещё видимые - досчитать
      if (Object.prototype.hasOwnProperty.call(sectionSeen, k))
        sectionMs[k] = (sectionMs[k] || 0) + (now - sectionSeen[k]);
    for (var n in sectionMs)
      if (Object.prototype.hasOwnProperty.call(sectionMs, n))
        out.push([n, Math.round(sectionMs[n] / 1000)]);
    out.sort(function (a, b) { return b[1] - a[1]; });
    return out.slice(0, 5).filter(function (x) { return x[1] >= 1; });
  }

  // Смена сети (wifi<->cellular) и online/offline: обрыв середины сессии
  // предсказывает bounce и объясняет всплеск INP/LCP не по нашей вине.
  try {
    var conn = navigator.connection;
    if (conn && conn.addEventListener)
      conn.addEventListener("change", function () {
        send("network_change", metaProps({ net: conn.effectiveType || "",
          downlink: conn.downlink || 0, save_data: conn.saveData ? 1 : 0 }));
      });
  } catch (_) {}
  addEventListener("offline", function () { send("net_offline"); });

  // Сколько секунд человек РЕАЛЬНО провёл на странице - главный сигнал
  // вовлечённости. Шлём на уходе (закрытие, скрытие вкладки, SPA-переход).
  function sendLeave() {
    if (leaveSent) return;
    var secs = Math.round((Date.now() - pageEnter) / 1000);
    if (secs < 2) return;                  // мгновенный отскок не считаем уходом
    leaveSent = true;
    var props = metaProps(Object.assign(
      { seconds: secs, scroll_pct: maxScroll, entry: firstTouch().page,
        exit: location.pathname }, vitalsSnapshot()));
    // На уходе со страницы fetch часто обрывается браузером - beacon доживает.
    // Авторизацию beacon нести не умеет, поэтому токен уходит в query
    // (токен публичного класса, он и так в HTML страницы).
    if (navigator.sendBeacon && cfg.endpoint && cfg.tenant) {
      try {
        var e = { event_id: uuid(), tenant_id: cfg.tenant,
                  event_type: "page_leave", ts: iso(new Date()),
                  source: "snippet", client_user_id: get(K) || "",
                  email_hash: get(KH) || "", session_id: sessionId(),
                  page: location.pathname, meta: props.meta };
        var url = cfg.endpoint + (cfg.endpoint.indexOf("?") < 0 ? "?" : "&") +
                  "token=" + encodeURIComponent(cfg.token);
        if (navigator.sendBeacon(url, new Blob([JSON.stringify(e)],
                                               { type: "application/json" })))
          return;
      } catch (_) {}
    }
    send("page_leave", props);
  }

  function resetPage() {
    pageEnter = Date.now();
    maxScroll = scrollPct();
    leaveSent = false;
    // попутевые счётчики - заново на каждой странице SPA
    firstInteractAt = 0; scrollReversals = 0; activeMs = 0;
    lastActivity = Date.now(); sectionMs = {}; sectionSeen = {};
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
      send("heartbeat", metaProps(Object.assign(
        { scroll_pct: maxScroll }, vitalsSnapshot())));
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

  // ── Вовлечённость: клики-действия, копирование, формы, медиа ──────────────
  // Всё СОБЫТИЯ ПОВЕДЕНИЯ на своих страницах, без содержимого. Главная
  // ценность для оттока живёт здесь, а не в железе.

  // Переключения вкладки: частый уход = раздвоенное внимание, слабое
  // вовлечение. Считаем за сессию, шлём в page_leave/heartbeat через счётчик.
  var tabSwitches = 0;
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") tabSwitches++;
  });

  // Клики по ссылкам: скачивания (адаптация фич), исходящие (куда уходят -
  // в доки или к конкуренту). Только href, без текста и содержимого.
  var FILE_RE = /\.(pdf|csv|xlsx?|docx?|zip|png|jpe?g|mp4|mp3|pptx?)($|\?)/i;
  addEventListener("click", function (ev) {
    try {
      var a = ev.target && ev.target.closest && ev.target.closest("a[href]");
      if (!a) return;
      var href = a.getAttribute("href") || "";
      if (a.hasAttribute("download") || FILE_RE.test(href)) {
        send("download_click", metaProps({ href: href.slice(0, 200) }));
        return;
      }
      var host = "";
      try { host = new URL(a.href, location.href).host; } catch (_) {}
      if (host && host !== location.host)
        send("outbound_click", metaProps({ host: host }));
    } catch (_) {}
  }, { capture: true, passive: true });

  // Копирование - извлечение ценности (цены, API-ключи, тексты). Только ФАКТ
  // и длина, НИКОГДА содержимое.
  var copyCount = 0;
  addEventListener("copy", function () {
    try {
      copyCount++;
      var len = 0;
      try { len = String((getSelection() || "")).length; } catch (_) {}
      if (copyCount <= 10) send("copy_event", metaProps({ len: len }));
    } catch (_) {}
  });

  // Формы: заброшенность. Имя/id поля, порядок и время фокуса - НИКОГДА
  // значения. Юзер тронул поле и ушёл, не отправив - премиальный сигнал
  // воронки (регистрация, чекаут, онбординг).
  var formTouched = {};
  addEventListener("focusin", function (ev) {
    try {
      var el = ev.target;
      if (!el || !/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (el.type === "password") return;       // к паролям не подходим вовсе
      var form = el.form && (el.form.getAttribute("name") || el.form.id) || "";
      var key = form + ":" + (el.getAttribute("name") || el.id || el.type);
      if (!formTouched[key]) {
        formTouched[key] = 1;
        send("field_focus", metaProps({ field: key.slice(0, 80) }));
      }
    } catch (_) {}
  }, { capture: true });
  addEventListener("submit", function (ev) {
    try {
      var f = ev.target;
      send("form_submit", metaProps({
        form: (f && (f.getAttribute("name") || f.id) || "").slice(0, 80) }));
    } catch (_) {}
  }, { capture: true });

  // Медиа: досмотр онбординг-видео сильно предсказывает активацию.
  addEventListener("play", function (ev) {
    try {
      if (/^(VIDEO|AUDIO)$/.test(ev.target.tagName))
        send("media_play", metaProps({ src: (ev.target.currentSrc || "").slice(-80) }));
    } catch (_) {}
  }, { capture: true });
  addEventListener("ended", function (ev) {
    try {
      if (/^(VIDEO|AUDIO)$/.test(ev.target.tagName)) send("media_complete");
    } catch (_) {}
  }, { capture: true });

  // ── Web Vitals: медленно/дёргано/тормозит = тихий драйвер оттока ──────────
  // Это ИСХОД (что человек реально пережил), а не косвенный железный прокси -
  // объясняет «почему» лучше, чем deviceMemory. INP заменил FID в 2024+.
  function observeVital(type, cb, opts) {
    try {
      var po = new PerformanceObserver(function (list) {
        list.getEntries().forEach(cb);
      });
      po.observe(Object.assign({ type: type, buffered: true }, opts || {}));
      return po;
    } catch (_) { return null; }
  }
  var vitals = { lcp: 0, cls: 0, inp: 0 };
  observeVital("largest-contentful-paint", function (e) {
    vitals.lcp = Math.round(e.startTime);
  });
  observeVital("layout-shift", function (e) {
    if (!e.hadRecentInput) vitals.cls += e.value;
  });
  observeVital("event", function (e) {
    if (e.duration > vitals.inp) vitals.inp = Math.round(e.duration);
  }, { durationThreshold: 40 });
  // Web Vitals финализируются к уходу - их несёт page_leave (см. sendLeave).
  function vitalsSnapshot() {
    return { lcp: vitals.lcp, cls: Math.round(vitals.cls * 1000) / 1000,
             inp: vitals.inp, load_ms: loadMs(), tab_switches: tabSwitches,
             active_sec: Math.round(activeMs / 1000),
             scroll_reversals: scrollReversals,
             ttfi_ms: firstInteractAt ? firstInteractAt - pageEnter : 0,
             sections: topSections() };
  }

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
    flushQueue();                     // недоставленное с прошлого визита
    // Юзер передан в теге/конфиге - привязываем сразу, без ручного ra.identify.
    if (cfg.userId) { try { window.ra.identify(cfg.userId, cfg.userEmail); } catch (_) {} }
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
