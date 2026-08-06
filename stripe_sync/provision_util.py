"""Чистая логика создания рабочего пространства клиента (тестируется без БД).

Пространство (tenant) = папка данных клиента. Его id раньше заводился руками
в файлах - отсюда «hubcontent», зашитый в код. Здесь id рождается из НАЗВАНИЯ
ПРОДУКТА, которое вводит платформа/клиент при регистрации.

Правила id: только латиница/цифры, 3-32 знака, уникален среди существующих,
не пересекается со служебными именами (_default и т.п.).
"""

from __future__ import annotations

import json
import os
import re
import secrets

RESERVED = {"_default", "default", "admin", "platform", "system", "public",
            "retivo", "test"}

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def slugify_tenant(product_name: str, existing: set | None = None) -> str:
    """«Hub Content» -> hubcontent; при конфликте добавляет 2, 3, ...
    Кириллица транслитерируется, чтобы id оставался ASCII-безопасным."""
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    src = "".join(translit.get(ch, ch) for ch in str(product_name).lower())
    base = re.sub(r"[^a-z0-9]+", "", src)[:32]
    if len(base) < 3:
        base = (base + "space")[:32]
    existing = {str(e).lower() for e in (existing or set())} | RESERVED
    if base not in existing:
        return base
    n = 2
    while f"{base}{n}"[:32] in existing:
        n += 1
    return f"{base}{n}"[:32]


def validate_signup(product_name: str, owner_email: str) -> str:
    """'' - всё ок, иначе причина отказа."""
    if not str(product_name).strip():
        return "invalid_product_name"
    if len(str(product_name).strip()) > 120:
        return "invalid_product_name"
    if not EMAIL_RE.match(str(owner_email).strip().lower()):
        return "invalid_email"
    return ""


def new_token() -> str:
    """Ingest-токен пространства (публичного класса: живёт в HTML клиента)."""
    return secrets.token_urlsafe(24)


def new_password() -> str:
    """Временный пароль владельца: показывается один раз при создании."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(16))


def known_tenants(tokens: dict | None, tenants: dict | None,
                  env_tenant: str = "") -> list[str]:
    """Все пространства, которые обслуживает планировщик.

    Источники - ingest-токены (клиент завёлся) и конфиг каналов. TENANT_ID в
    окружении, если задан, сужает прогон до одного пространства (отладка).
    Служебные ключи (_default) пропускаем.
    """
    if str(env_tenant or "").strip():
        return [str(env_tenant).strip()]
    out: list[str] = []
    for src in (tokens or {}, tenants or {}):
        for key in src:
            t = str(key).strip()
            if t and not t.startswith("_") and t not in out:
                out.append(t)
    return sorted(out)


def load_known_tenants() -> list[str]:
    """known_tenants() поверх реальных файлов секретов (пустой список, если их нет)."""
    def _read(path: str) -> dict:
        try:
            with open(path) as fh:
                doc = json.load(fh)
            return doc if isinstance(doc, dict) else {}
        except (OSError, ValueError):
            return {}
    return known_tenants(
        _read(os.environ.get("TOKENS_FILE", "/secrets/tokens.json")),
        _read(os.environ.get("TENANTS_FILE", "/secrets/tenants.json")),
        os.environ.get("TENANT_ID", ""))
