"""Скан сайта клиента: читаем публичные страницы -> профиль продукта (LLM).

ЗАЧЕМ. Опросник спрашивал то, что написано на сайте клиента: что за продукт,
как называется единица ценности, какие планы и цены, есть ли триал. Теперь
владелец вводит адрес - система идёт, читает главную и страницу тарифов и
достаёт это сама. Ответы остаются редактируемыми: скан ПРЕДЗАПОЛНЯЕТ форму,
а не решает за клиента.

Что достаём (и куда идёт):
  product_name, product_desc -> тексты кампаний (голос продукта);
  value_unit                 -> «ваши видео/рендеры/экспорты» в письмах +
                                название бонус-оффера;
  monthly_units              -> лимит типового плана: burn_rate -> UPGRADE;
  avg_plan_price             -> экономика офферов (пока Stripe не подключён);
  trial_days                 -> продление триала как оффер;
  audience, aha_moment       -> активационные тексты (что делать первым).

БЕЗОПАСНОСТЬ (сервер ходит по ссылке от пользователя = SSRF-риск):
  • только http/https, никаких file/ftp/gopher;
  • хост резолвится и проверяется: приватные/локальные/link-local адреса
    запрещены (127.*, 10.*, 172.16-31.*, 192.168.*, 169.254.*, ::1, fc00::/7);
  • жёсткий таймаут, лимит размера ответа, максимум 2 редиректа (каждый
    редирект проверяется тем же фильтром).
Без ключа LLM возвращаем распознанные ссылки/текст? Нет - честно 'ai_not_configured'.
"""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

try:
    from ai_compose import _call_anthropic, _call_openai, resolve_provider
except ImportError:
    from stripe_sync.ai_compose import (_call_anthropic, _call_openai,
                                        resolve_provider)

_TIMEOUT = 12
_MAX_BYTES = 400_000
_MAX_TEXT = 12_000
UA = "RetivoBot/1.0 (+https://retivo.digital; site profile for onboarding)"

PRICING_HINTS = ("pricing", "plans", "price", "tarif", "тариф", "цены")

SYSTEM = """You extract a product profile from a SaaS website's own text.
Output ONLY valid JSON:
{"product_name": "...", "product_desc": "...", "value_unit": "...",
 "monthly_units": <number|null>, "avg_plan_price": <number|null>,
 "trial_days": <number|null>, "audience": "...", "aha_moment": "...",
 "pricing_model": "flat|per_seat|usage|unknown", "free_tier": <true|false|null>,
 "plans": [{"name": "...", "price_usd": <number|null>,
            "interval": "month|year|unknown", "units_included": <number|null>}]}

Rules:
- Use ONLY what the text actually says. If something is not stated, use null
  (numbers) or "" (strings). NEVER guess a price, a limit or a trial length.
- plans: EVERY paid tier the pricing page lists, in the order shown, with the
  price exactly as stated and the interval it is billed on. Include a free tier
  only with price_usd 0. Skip "contact us" tiers with no number. Max 6.
- units_included: the monthly allowance that tier states (10 videos, 2000
  credits, unlimited -> null). Same countable thing as value_unit.
- pricing_model: per_seat when the price is per user/seat/channel/member;
  usage when it scales with consumed credits/minutes/requests; flat otherwise.
- value_unit: the countable thing the product delivers, in the product's own
  wording, plural lowercase (videos, renders, exports, minutes, seats, posts).
  If the product does not meter anything countable, use "".
- monthly_units and avg_plan_price describe the TYPICAL PAID plan - the one a
  normal customer picks (not the free tier, not the enterprise one).
- trial_days: only if the site states a free trial length. A free plan is NOT
  a trial: in that case trial_days is null and free_tier is true.
- audience: who it is for, max 12 words. aha_moment: the first valuable action
  a new user takes, max 12 words, phrased as an action.
- No emoji, no em-dash, no marketing fluff in desc: one factual phrase."""


def normalize_url(raw: str) -> str:
    """'hubcontent.ai' -> 'https://hubcontent.ai'. '' если явно не веб-адрес."""
    u = str(raw or "").strip()
    if not u:
        return ""
    if "://" in u:
        # схема указана явно: пускаем только веб (ftp/file/gopher - отказ)
        if not re.match(r"^https?://", u, re.I):
            return ""
    else:
        u = "https://" + u
    parts = urllib.parse.urlsplit(u)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))


def host_is_public(host: str) -> bool:
    """Резолвим и запрещаем внутренние адреса (SSRF-защита)."""
    if not host or host.lower() in ("localhost",):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def fetch(url: str, redirects: int = 2) -> str:
    """HTML страницы либо '' при любой проблеме. Каждый редирект перепроверяется."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not host_is_public(parts.hostname or ""):
        return ""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "text/html,*/*"})
    try:
        with opener.open(req, timeout=_TIMEOUT) as resp:
            ctype = str(resp.headers.get("Content-Type", ""))
            if "html" not in ctype and "text" not in ctype:
                return ""
            return resp.read(_MAX_BYTES).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308) and redirects > 0:
            loc = exc.headers.get("Location", "")
            nxt = urllib.parse.urljoin(url, loc)
            return fetch(nxt, redirects - 1) if nxt != url else ""
        return ""
    except Exception:  # noqa: BLE001
        return ""


def html_to_text(raw: str) -> str:
    """Грубая, но предсказуемая очистка: скрипты/стили прочь, теги в пробелы."""
    s = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", raw)
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def pricing_links(raw_html: str, base_url: str, limit: int = 2) -> list:
    """Ссылки, похожие на страницу тарифов - там живут цены и лимиты."""
    out, seen = [], set()
    for m in re.finditer(r'(?is)<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw_html):
        href, text = m.group(1), html_to_text(m.group(2)).lower()
        blob = (href + " " + text).lower()
        if not any(h in blob for h in PRICING_HINTS):
            continue
        full = urllib.parse.urljoin(base_url, href)
        p = urllib.parse.urlsplit(full)
        if p.scheme not in ("http", "https"):
            continue
        if p.hostname != urllib.parse.urlsplit(base_url).hostname:
            continue     # только свой домен
        clean = urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, "", ""))
        if clean in seen or clean == base_url:
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= limit:
            break
    return out


# Фолбэк-ридер: часть сайтов отдаёт пустой HTML (рендерят JS) или закрыта
# бот-стеной - тогда своим запросом мы получаем ноль. r.jina.ai рендерит
# страницу и возвращает чистый текст, ключ не нужен. Наружу уходит ТОЛЬКО
# публичный адрес сайта клиента. Выключается: SITE_SCAN_FALLBACK=0.
READER_URL = "https://r.jina.ai/"
MIN_USEFUL_TEXT = 500


def fallback_reader(url: str) -> str:
    import os as _os
    if _os.environ.get("SITE_SCAN_FALLBACK", "1") in ("0", "false", "False"):
        return ""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not host_is_public(parts.hostname or ""):
        return ""
    req = urllib.request.Request(READER_URL + url,
                                 headers={"User-Agent": UA, "Accept": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT * 2) as resp:
            return resp.read(_MAX_BYTES).decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""


# Куда класть тарифы принято у всех - пробуем напрямую, если ссылки с главной
# нет (её часто прячут в футер или рисуют скриптом).
PRICING_PATHS = ("/pricing", "/plans", "/pricing/plans", "/en/pricing", "/price")


def page_text(url: str) -> str:
    """Текст страницы своим запросом, а если пусто/мало - через ридер."""
    txt = html_to_text(fetch(url))
    if len(txt) >= MIN_USEFUL_TEXT:
        return txt
    via = fallback_reader(url)
    return via if len(via) > len(txt) else txt


def collect_text(url: str) -> tuple[str, list]:
    """Текст главной + страниц тарифов. ('', []) если сайт недоступен."""
    home_raw = fetch(url)
    home_txt = html_to_text(home_raw)
    used_reader = False
    if len(home_txt) < MIN_USEFUL_TEXT:
        via_reader = fallback_reader(url)
        if len(via_reader) >= MIN_USEFUL_TEXT:
            home_txt, used_reader = via_reader, True
    if not home_txt:
        return "", []

    pages = [("home", home_txt[:_MAX_TEXT])]
    visited = [url + (" (reader)" if used_reader else "")]

    # 1) ссылки «pricing/plans» с главной; 2) если их нет - типовые адреса.
    # Раньше сайт, рисующий главную скриптом, оставался вообще без цен: как
    # раз тех данных, ради которых клиента и просят дать адрес сайта.
    candidates = pricing_links(home_raw, url) if home_raw else []
    if not candidates:
        base = urllib.parse.urlsplit(url)
        root = urllib.parse.urlunsplit((base.scheme, base.netloc, "", "", ""))
        candidates = [root + path for path in PRICING_PATHS]
    for link in candidates:
        if len(visited) > 3:
            break
        txt = page_text(link)
        if len(txt) >= MIN_USEFUL_TEXT:
            pages.append(("pricing", txt[:_MAX_TEXT]))
            visited.append(link)
    blob = "\n\n".join(f"--- {name} ---\n{txt}" for name, txt in pages)
    return blob[: _MAX_TEXT * 2], visited


def parse_profile(text: str) -> dict:
    """JSON модели -> профиль с приведением типов. {} при кривом ответе."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        doc = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(doc, dict):
        return {}

    def _str(key, limit):
        v = str(doc.get(key) or "").replace("—", " - ").replace("–", "-").strip()
        return v[:limit]

    def _num(key, lo, hi):
        v = doc.get(key)
        if v in (None, "", "null"):
            return None
        try:
            n = float(v)
        except (TypeError, ValueError):
            return None
        return None if not (lo <= n <= hi) else (int(n) if float(n).is_integer() else n)

    model = _str("pricing_model", 20).lower()
    if model not in ("flat", "per_seat", "usage"):
        model = "unknown"
    free = doc.get("free_tier")
    profile = {
        "product_name": _str("product_name", 120),
        "product_desc": _str("product_desc", 200),
        "value_unit": _str("value_unit", 40).lower(),
        "monthly_units": _num("monthly_units", 1, 1_000_000),
        "avg_plan_price": _num("avg_plan_price", 1, 100_000),
        "trial_days": _num("trial_days", 1, 90),
        "audience": _str("audience", 120),
        "aha_moment": _str("aha_moment", 120),
        "pricing_model": model,
        "free_tier": bool(free) if isinstance(free, bool) else None,
        "plans": parse_plans(doc.get("plans")),
    }
    # Цена «типичного» тарифа - не мнение модели, а арифметика по линейке:
    # берём самый дешёвый ПЛАТНЫЙ, а при трёх и более - средний по счёту.
    typical = typical_plan(profile["plans"])
    if typical:
        profile["avg_plan_price"] = typical["price_usd"]
        if typical.get("units_included"):
            profile["monthly_units"] = typical["units_included"]
    return profile


def parse_plans(raw) -> list:
    """Линейка тарифов из ответа модели: чистим, приводим к месяцу, сортируем."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:6]:
        if not isinstance(item, dict):
            continue
        try:
            price = float(item.get("price_usd"))
        except (TypeError, ValueError):
            continue
        if not 0 <= price <= 100_000:
            continue
        interval = str(item.get("interval") or "").lower()
        if interval == "year":          # в системе всё живёт в месяцах
            price = round(price / 12, 2)
        units = item.get("units_included")
        try:
            units = int(units) if units not in (None, "", "null") else None
        except (TypeError, ValueError):
            units = None
        out.append({"name": str(item.get("name") or "")[:60],
                    "price_usd": int(price) if float(price).is_integer() else price,
                    "units_included": units if (units and units > 0) else None})
    out.sort(key=lambda p: p["price_usd"])
    # дубли по цене (одно и то же в месячном/годовом виде) схлопываем
    dedup, seen = [], set()
    for p in out:
        if p["price_usd"] in seen:
            continue
        seen.add(p["price_usd"])
        dedup.append(p)
    return dedup


def typical_plan(plans: list) -> dict:
    """Тариф, который берёт обычный клиент: самый дешёвый платный, а если
    платных три и больше - средний по счёту (края - это фри и энтерпрайз)."""
    paid = [p for p in plans if p["price_usd"] > 0]
    if not paid:
        return {}
    return paid[len(paid) // 2] if len(paid) >= 3 else paid[0]


def analyse(url_raw: str) -> tuple[dict, dict, list, str]:
    """(факты, разбор, страницы, note). Два прохода по одному тексту сайта.

    Первый - извлечение фактов (что написано). Второй - разбор: за что платят,
    когда наступает активация, почему уходят и какой рычаг удержания уместен.
    Без второго прохода в анкету попадала маркетинговая фраза с лендинга.
    """
    try:                                    # борд импортирует пакетом, джобы - плоско
        from client_brief import SYSTEM as BRIEF_SYSTEM, parse_brief
    except ImportError:
        from stripe_sync.client_brief import SYSTEM as BRIEF_SYSTEM, parse_brief

    try:
        from archetypes import read as read_economy
    except ImportError:
        from stripe_sync.archetypes import read as read_economy

    url = normalize_url(url_raw)
    if not url:
        return {}, {}, [], "invalid_url"
    blob, visited = collect_text(url)
    if not blob:
        return {}, {}, [], "site_unreachable"
    # ТИП ЭКОНОМИКИ СЧИТАЕТСЯ ВСЕГДА. Он детерминированный и не требует
    # модели, поэтому даже сайт, с которого ничего не извлеклось, перестаёт
    # быть пустым экраном: видно, где у бизнеса лежит маржа и что спросить.
    economy = read_economy(blob, None, None)
    provider, api_key = resolve_provider()
    if not provider:
        return {}, {"economy": economy}, visited, "ai_not_configured"
    call = _call_anthropic if provider == "anthropic" else _call_openai

    try:
        facts = parse_profile(call(
            api_key, SYSTEM,
            f"Website text of {url}:\n{blob}\n\nExtract the profile now."))
    except Exception as exc:  # noqa: BLE001
        return {}, {}, visited, f"ai_{type(exc).__name__}"

    brief = {}
    try:
        brief = parse_brief(call(
            api_key, BRIEF_SYSTEM,
            f"Website text of {url}:\n{blob}\n\n"
            f"Facts already extracted: {json.dumps(facts, ensure_ascii=False)}\n\n"
            f"Work out the retention picture now."))
    except Exception as exc:  # noqa: BLE001 - разбор не обязателен, факты важнее
        print(f"[scan] разбор не удался: {type(exc).__name__}", flush=True)

    # Ответ модели сверяется с признаками сайта: совпали - уверенность выше,
    # разошлись - в карточке написано, кто из них взят и почему.
    brief["economy"] = read_economy(blob, facts, brief)
    return facts, brief, visited, ("" if facts else "ai_empty")


def scan(url_raw: str) -> tuple[dict, list, str]:
    """(профиль, просмотренные страницы, note). Профиль пуст при любой беде."""
    url = normalize_url(url_raw)
    if not url:
        return {}, [], "invalid_url"
    blob, visited = collect_text(url)
    if not blob:
        return {}, [], "site_unreachable"
    provider, api_key = resolve_provider()
    if not provider:
        return {}, visited, "ai_not_configured"
    call = _call_anthropic if provider == "anthropic" else _call_openai
    try:
        out = call(api_key, SYSTEM,
                   f"Website text of {url}:\n{blob}\n\nExtract the profile now.")
    except urllib.error.HTTPError as exc:
        return {}, visited, f"ai_http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return {}, visited, f"ai_{type(exc).__name__}"
    profile = parse_profile(out)
    return profile, visited, ("" if profile else "ai_empty")


# ── Брендинг с сайта: цвет CTA, не самый частый хекс ─────────────────────────
# Урок hubcontent.ai: по чистой частоте побеждает мусор (зелёные галочки где-то
# в глубине разметки), а бренд у них - чёрная кнопка на кремовом. Поэтому вес
# у КОНТЕКСТА: переменные --primary/--brand и кнопочные селекторы бьют голую
# частоту, почти-белое отбрасывается (это фон, не бренд), а чёрный - легальный
# бренд, никакой «ищем яркое» эвристики.

import re as _re

_HEX = _re.compile(r"#[0-9a-fA-F]{6}\b")
_VAR_CTX = _re.compile(
    r"--(?:primary|brand|accent|cta|button)[\w-]*\s*:\s*(#[0-9a-fA-F]{6})", _re.I)
_BTN_CTX = _re.compile(
    r"(?:btn|button|cta|primary|accent|brand|sign[_-]?up)[^{};]{0,120}?"
    r"(#[0-9a-fA-F]{6})", _re.I)
_THEME = _re.compile(
    r'name=["\']theme-color["\'][^>]*content=["\'](#[0-9a-fA-F]{6})', _re.I)


def _luma(hex6: str) -> float:
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def brand_color_from_html(raw_html: str, css_texts: list | None = None) -> str:
    """Цвет бренда из разметки/стилей сайта; '' - не определился уверенно."""
    blobs = [raw_html or ""] + list(css_texts or [])
    ctx_w: dict[str, float] = {}
    freq_w: dict[str, float] = {}

    def usable(color: str) -> bool:
        # цвет пойдёт на кнопку с белым текстом: светлое не годится ни как
        # бренд-акцент, ни по контрасту (светло-серые - вторичные кнопки)
        return _luma(color) <= 0.75

    def add_ctx(color: str, w: float) -> None:
        c = color.lower()
        if usable(c):
            ctx_w[c] = ctx_w.get(c, 0.0) + w

    def add_freq(color: str) -> None:
        c = color.lower()
        if usable(c):
            freq_w[c] = freq_w.get(c, 0.0) + 1.0

    for blob in blobs:
        m = _THEME.search(blob)
        if m:
            add_ctx(m.group(1), 18.0)
        for m in _VAR_CTX.finditer(blob):
            add_ctx(m.group(1), 24.0)
        for m in _BTN_CTX.finditer(blob):
            add_ctx(m.group(1), 12.0)
        for m in _HEX.finditer(blob):
            add_freq(m.group(0))

    # Частота капится: гора зелёных галочек в разметке не должна перекричать
    # один честный --primary. Контекст - главный голос.
    weights = {c: min(w, 15.0) for c, w in freq_w.items()}
    for c, w in ctx_w.items():
        weights[c] = weights.get(c, 0.0) + w

    if not weights:
        return ""

    # КЛАСТЕРИЗАЦИЯ. Бренд почти никогда не один хекс: у hubcontent.ai чёрный
    # размазан по #0a0a0a/#141414/#1f1f1f/... - поодиночке ни один не набирал
    # уверенного отрыва, и скан молчал. Похожие цвета голосуют вместе,
    # представитель кластера - самый весомый его член.
    def _rgb(c):
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))

    def _close(a, b, limit=90):
        return sum(abs(x - y) for x, y in zip(_rgb(a), _rgb(b))) <= limit

    clusters: list[dict] = []
    for color, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        for cl in clusters:
            if _close(color, cl["rep"]):
                cl["weight"] += w
                break
        else:
            clusters.append({"rep": color, "weight": w})

    clusters.sort(key=lambda cl: -cl["weight"])
    best = clusters[0]
    # уверенность: кластер-лидер должен заметно отрываться, иначе честнее
    # промолчать (владелец увидит дефолт и поставит цвет сам)
    if len(clusters) > 1 and best["weight"] < clusters[1]["weight"] * 1.3:
        return ""
    return best["rep"]


def brand_color_from_url(url: str) -> str:
    """Цвет бренда прямо с сайта: страница + до трёх её стилевых файлов."""
    from urllib.parse import urljoin
    base = normalize_url(url)
    raw = fetch(base)
    if not raw:
        return ""
    css = []
    for href in _re.findall(
            r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)',
            raw, _re.I)[:3]:
        css.append(fetch(urljoin(base, href)))
    return brand_color_from_html(raw, [c for c in css if c])
