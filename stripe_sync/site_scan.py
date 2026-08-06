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
 "trial_days": <number|null>, "audience": "...", "aha_moment": "..."}

Rules:
- Use ONLY what the text actually says. If something is not stated, use null
  (numbers) or "" (strings). NEVER guess a price, a limit or a trial length.
- value_unit: the countable thing the product delivers, in the product's own
  wording, plural lowercase (videos, renders, exports, minutes, seats, posts).
- monthly_units: the monthly allowance of a typical PAID plan (not the free
  tier, not the top enterprise one) if the page states it.
- avg_plan_price: the monthly USD price of that same typical paid plan. If
  prices are yearly only, divide by 12. If a currency other than USD is shown,
  still return the number as stated.
- trial_days: only if the site states a free trial length.
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


def collect_text(url: str) -> tuple[str, list]:
    """Текст главной + страниц тарифов. ('', []) если сайт недоступен.
    Если свой запрос дал пусто/мало - пробуем фолбэк-ридер."""
    home = fetch(url)
    if len(html_to_text(home)) < MIN_USEFUL_TEXT:
        via_reader = fallback_reader(url)
        if len(via_reader) >= MIN_USEFUL_TEXT:
            return via_reader[: _MAX_TEXT * 2], [url + " (reader)"]
    if not home:
        return "", []
    pages = [("home", html_to_text(home)[:_MAX_TEXT])]
    visited = [url]
    for link in pricing_links(home, url):
        raw = fetch(link)
        if raw:
            pages.append(("pricing", html_to_text(raw)[:_MAX_TEXT]))
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

    return {
        "product_name": _str("product_name", 120),
        "product_desc": _str("product_desc", 200),
        "value_unit": _str("value_unit", 40).lower(),
        "monthly_units": _num("monthly_units", 1, 1_000_000),
        "avg_plan_price": _num("avg_plan_price", 1, 100_000),
        "trial_days": _num("trial_days", 1, 90),
        "audience": _str("audience", 120),
        "aha_moment": _str("aha_moment", 120),
    }


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
