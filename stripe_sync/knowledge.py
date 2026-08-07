"""Хранилище знаний о клиентах: по пространству, с версиями, отдельно от секретов.

ПОЧЕМУ ОТДЕЛЬНО. Раньше разбор сайта складывался в тот же файл, где лежат
ключи Resend и Stripe. Это плохо по трём причинам: знание и секреты имеют
разный срок жизни и разные права доступа; файл рос без структуры; истории
изменений не было, а она нужна - тарифы у клиента меняются, и надо видеть, что
именно поменялось с прошлого разбора.

Здесь знание живёт в ClickHouse: строка на версию, изоляция по tenant_id,
история сохраняется, текущая версия читается вьюхой. Секреты остаются в
secrets/tenants.json и сюда НЕ попадают.

kind: 'brief' (разбор продукта), 'economics' (экономика подарков) и что
появится дальше. Формат payload - JSON-строка, схему держит модуль-владелец.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

TABLE = "retention.tenant_knowledge"


def save(client, tenant: str, kind: str, payload: dict, source: str = "") -> None:
    """Новая версия знания. Старые не трогаем - на них строится сравнение."""
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    version = current_version(client, tenant, kind) + 1
    client.insert(
        TABLE,
        [[tenant, kind, version, json.dumps(payload, ensure_ascii=False),
          str(source or "")[:300], now]],
        column_names=["tenant_id", "kind", "version", "payload", "source", "created_at"])


def current_version(client, tenant: str, kind: str) -> int:
    rows = client.query(
        f"SELECT max(version) FROM {TABLE} WHERE tenant_id = %(t)s AND kind = %(k)s",
        parameters={"t": tenant, "k": kind}).result_rows
    return int(rows[0][0] or 0) if rows else 0


def load(client, tenant: str, kind: str) -> dict:
    """Текущее знание пространства. {} - ещё не собирали."""
    rows = client.query(
        f"SELECT payload FROM {TABLE} WHERE tenant_id = %(t)s AND kind = %(k)s "
        "ORDER BY version DESC LIMIT 1",
        parameters={"t": tenant, "k": kind}).result_rows
    if not rows:
        return {}
    try:
        return json.loads(rows[0][0]) or {}
    except (ValueError, TypeError):
        return {}


def history(client, tenant: str, kind: str, limit: int = 10) -> list:
    """Версии знания сверху вниз - для «что изменилось» и разбора полётов."""
    rows = client.query(
        f"SELECT version, toString(created_at), source, payload FROM {TABLE} "
        "WHERE tenant_id = %(t)s AND kind = %(k)s ORDER BY version DESC LIMIT %(n)s",
        parameters={"t": tenant, "k": kind, "n": int(limit)}).result_rows
    out = []
    for version, created, source, payload in rows:
        try:
            doc = json.loads(payload) or {}
        except (ValueError, TypeError):
            doc = {}
        out.append({"version": int(version), "created_at": created,
                    "source": source, "payload": doc})
    return out
