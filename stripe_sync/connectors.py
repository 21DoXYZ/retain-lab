"""Источники базы юзеров: берём данные там, где они УЖЕ есть.

ПОЧЕМУ ТАК. Просить клиента дописать в продукт вызов ra.identify - значит
поставить весь проект в очередь его разработчиков. А база пользователей уже
лежит в готовом виде минимум в трёх местах, к каждому из которых есть ключ:

  • биллинг (Stripe) - все, кто хоть раз дошёл до оплаты; уже подключён;
  • провайдер авторизации (Supabase, Firebase, Auth0, Clerk) - ВСЕ, включая
    бесплатных: у каждого есть админский список юзеров;
  • собственный админский API продукта - если он есть, это просто URL + токен.

Здесь живут читатели этих источников. Каждый возвращает ОДИН И ТОТ ЖЕ формат -
список словарей вида {id, email, created_at, last_seen} - дальше их разбирает
users_import, и данные идут штатным конвейером.

Ничего, кроме чтения. Ключи хранятся в конфиге пространства клиента.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "RevenueAutopilot/1.0 (+https://retivo.digital)"
_TIMEOUT = 30
PAGE = 200
MAX_PAGES = 100          # 20 000 юзеров за один прогон - дальше следующий тик


def _get(url: str, headers: dict) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode() or "{}")


def _dig(doc, path: str):
    """'data.users' -> doc['data']['users']. Пустой путь - сам документ."""
    out = doc
    for part in [p for p in str(path or "").split(".") if p]:
        if isinstance(out, dict):
            out = out.get(part)
        else:
            return None
    return out


def supabase_users(base_url: str, service_key: str, pages: int = MAX_PAGES) -> list:
    """Все юзеры проекта Supabase (включая бесплатных и неподтверждённых)."""
    base = base_url.rstrip("/")
    out: list = []
    for page in range(1, pages + 1):
        url = f"{base}/auth/v1/admin/users?page={page}&per_page={PAGE}"
        doc = _get(url, {"apikey": service_key,
                         "Authorization": f"Bearer {service_key}"})
        users = doc.get("users") if isinstance(doc, dict) else doc
        if not users:
            break
        for u in users:
            out.append({
                "id": u.get("id") or "",
                "email": (u.get("email") or "").lower(),
                "created_at": u.get("created_at") or "",
                "last_seen": u.get("last_sign_in_at") or "",
            })
        if len(users) < PAGE:
            break
    return out


def clerk_users(secret_key: str, pages: int = MAX_PAGES) -> list:
    """Юзеры Clerk. Адрес берём первый подтверждённый."""
    out: list = []
    for page in range(pages):
        url = ("https://api.clerk.com/v1/users"
               f"?limit={PAGE}&offset={page * PAGE}")
        doc = _get(url, {"Authorization": f"Bearer {secret_key}"})
        users = doc if isinstance(doc, list) else (doc or {}).get("data") or []
        if not users:
            break
        for u in users:
            emails = u.get("email_addresses") or []
            email = (emails[0].get("email_address") if emails else "") or ""
            created = u.get("created_at")
            out.append({
                "id": u.get("id") or "",
                "email": email.lower(),
                "created_at": str(created or ""),
                "last_seen": str(u.get("last_sign_in_at") or ""),
            })
        if len(users) < PAGE:
            break
    return out


def json_endpoint_users(url: str, token: str, list_path: str = "",
                        id_field: str = "id", email_field: str = "email",
                        created_field: str = "created_at") -> list:
    """Собственный админский API продукта: URL + токен + где лежит список.

    Универсальный вариант для тех, у кого своя авторизация: клиенту достаточно
    отдать эндпоинт «список юзеров», который у него почти наверняка есть.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    doc = _get(url, headers)
    rows = _dig(doc, list_path) if list_path else doc
    if isinstance(rows, dict):
        rows = rows.get("users") or rows.get("data") or []
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        out.append({
            "id": str(r.get(id_field) or ""),
            "email": str(r.get(email_field) or "").lower(),
            "created_at": str(r.get(created_field) or ""),
            "last_seen": "",
        })
    return out


def export_rows(url: str, key: str, dataset: str, since: str = "",
                pages: int = MAX_PAGES) -> list:
    """Read-only экспорт продукта: ?dataset=&since=&limit=, ключ в X-API-Key.

    Формат, который мы просим клиентов строить (первым построил hubcontent):
    GET-only, страницы по курсору (cursor в ответе -> since следующего запроса).
    Возвращает сырые строки датасета - разбор у каждого потребителя свой.
    """
    base, out = url.rstrip("/"), []
    seen_cursors: set = set()
    for _ in range(pages):
        page_url = f"{base}?dataset={urllib.parse.quote(dataset)}&limit=1000"
        if since:
            page_url += "&since=" + urllib.parse.quote(since)
        doc = _get(page_url, {"X-API-Key": key})
        data = (doc or {}).get("data") or {}
        rows = data.get("rows") or []
        if not rows:
            break
        out.extend(r for r in rows if isinstance(r, dict))
        cursor = str(data.get("cursor") or "")
        # страж от зацикливания: курсор пуст, повторился или страница неполная
        if not cursor or cursor in seen_cursors or len(rows) < 1000:
            break
        seen_cursors.add(cursor)
        since = cursor
    return out


def export_users(url: str, key: str, pages: int = MAX_PAGES) -> list:
    """Датасет users экспорта -> формат users_import.

    Ценность против голого списка юзеров: отдаёт stripe_customer_id (прямая
    склейка со Stripe), план/статус/кредиты (в meta -> скоринг и карточка)
    и is_internal - служебные аккаунты отсекаем сразу, им не место в выручке.
    """
    out = []
    for r in export_rows(url, key, "users", pages=pages):
        if r.get("is_internal"):
            continue
        out.append({
            "id": str(r.get("id") or ""),
            "email": str(r.get("email") or "").lower(),
            "created_at": str(r.get("created_at") or ""),
            "stripe_customer_id": str(r.get("stripe_customer_id") or ""),
            "last_seen": "",
            "_meta": {k: r[k] for k in ("plan", "status", "credits_balance",
                                        "attribution_source", "usage_type")
                      if r.get(k) not in (None, "")},
        })
    return out


SOURCES = {
    "supabase": lambda cfg: supabase_users(cfg.get("url", ""), cfg.get("key", "")),
    "clerk": lambda cfg: clerk_users(cfg.get("key", "")),
    "export": lambda cfg: export_users(cfg.get("url", ""), cfg.get("key", "")),
    "json": lambda cfg: json_endpoint_users(
        cfg.get("url", ""), cfg.get("key", ""), cfg.get("list_path", ""),
        cfg.get("id_field", "id"), cfg.get("email_field", "email"),
        cfg.get("created_field", "created_at")),
}


def fetch_users(cfg: dict) -> list:
    """Единая точка: конфиг источника из tenants.json -> список юзеров."""
    kind = str((cfg or {}).get("kind") or "")
    reader = SOURCES.get(kind)
    if not reader:
        raise ValueError(f"неизвестный источник юзеров: {kind or 'не задан'}")
    return reader(cfg)


def probe(cfg: dict) -> tuple[bool, str, int]:
    """Живая проверка при подключении: (ок, причина, сколько юзеров видно)."""
    try:
        users = fetch_users(cfg)
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}", 0
    except ValueError as exc:
        return False, str(exc), 0
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__, 0
    return True, "", len(users)
