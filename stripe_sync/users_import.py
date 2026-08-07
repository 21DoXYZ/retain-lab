"""Разовая загрузка юзеров клиента из выгрузки (CSV/JSON) - без его кода.

ЗАЧЕМ. Сниппет видит только то, что происходит ПОСЛЕ установки. У клиента,
который работает год, вся база регистраций лежит в его собственной СУБД, и мы
о ней не знаем: на экране один человек из Stripe, а их двести. Просить
разработчика писать интеграцию - долго; выгрузить таблицу юзеров в CSV может
кто угодно из админки.

ЧТО ПРИНИМАЕМ. Достаточно двух колонок: идентификатор юзера и адрес почты.
Полезные: дата регистрации, id клиента в Stripe, дата последней активности.
Имена колонок распознаём сами (id/user_id/uuid, email/e-mail/почта и т.д.).

ЧТО ДЕЛАЕМ. Каждая строка превращается в обычное событие продукта signup с
временем регистрации - дальше работает штатный конвейер: склейка личностей,
стадии, кампании. Никаких особых путей в системе.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone

ID_KEYS = ("client_user_id", "user_id", "userid", "id", "uuid", "external_id")
EMAIL_KEYS = ("email", "e-mail", "e_mail", "mail", "почта", "email_address",
              "user_email", "useremail", "primary_email", "contact_email",
              "login", "username_email", "адрес", "почта_пользователя")
CREATED_KEYS = ("created_at", "created", "signup_at", "registered_at",
                "registration_date", "date_joined", "дата регистрации")
CUSTOMER_KEYS = ("stripe_customer_id", "customer_id", "stripe_id")
SEEN_KEYS = ("last_seen", "last_login", "last_active", "updated_at")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ROWS = 50_000


def _norm_key(name: str) -> str:
    return str(name or "").strip().lower().replace(" ", "_").lstrip("﻿")


def _pick(row: dict, keys) -> str:
    for k in keys:
        for real, value in row.items():
            if _norm_key(real) == k and str(value or "").strip():
                return str(value).strip()
    return ""


def _ts(raw: str) -> str:
    """Дата регистрации в формат ClickHouse. Пусто - берём «сейчас»."""
    text = str(raw or "").strip().replace("T", " ").replace("Z", "")
    for pattern in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:26], pattern).strftime(
                "%Y-%m-%d %H:%M:%S.%f")[:-3]
        except ValueError:
            continue
    if text.isdigit() and len(text) >= 9:          # unix-секунды
        return datetime.fromtimestamp(int(text[:10]), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.%f")[:-3]
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def parse_rows(raw: str) -> list[dict]:
    """CSV или JSON -> список словарей. Разделитель CSV определяем сами."""
    text = (raw or "").strip()
    if not text:
        return []
    if text[0] in "[{":
        try:
            doc = json.loads(text)
        except ValueError:
            return []
        if isinstance(doc, dict):
            doc = doc.get("users") or doc.get("data") or []
        return [r for r in doc if isinstance(r, dict)][:MAX_ROWS]
    sample = text[:2000]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delim))[:MAX_ROWS]


def to_events(rows: list[dict], tenant: str) -> tuple[list[list], dict]:
    """Строки выгрузки -> строки saas_events (тип signup) + отчёт о разборе."""
    out, skipped, seen = [], 0, set()
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        uid = _pick(row, ID_KEYS)
        email = _pick(row, EMAIL_KEYS).lower()
        if email and not EMAIL_RE.match(email):
            email = ""
        if not uid and not email:
            skipped += 1                    # ни id, ни почты - строка бесполезна
            continue
        key = uid or email
        if key in seen:
            skipped += 1                    # дубль в выгрузке
            continue
        seen.add(key)
        ts = _ts(_pick(row, CREATED_KEYS))
        ehash = hashlib.sha256(email.encode()).hexdigest() if email else ""
        # event_id детерминирован: повторная загрузка того же файла не задвоит
        event_id = "import:" + hashlib.sha256(f"{tenant}|{key}".encode()).hexdigest()[:24]
        out.append([tenant, event_id, "signup", ts, uid, ehash, email, "import",
                    _pick(row, CUSTOMER_KEYS), ""])
    with_email = sum(1 for r in out if r[6])
    return out, {"parsed": len(rows), "imported": len(out), "skipped": skipped,
                 # БЕЗ ПОЧТЫ ЧЕЛОВЕКУ НЕЛЬЗЯ НАПИСАТЬ. Молчать об этом нечестно:
                 # база загрузится, экран наполнится, а письма никому не уйдут.
                 "with_email": with_email, "without_email": len(out) - with_email}


COLUMNS = ["tenant_id", "event_id", "event_type", "ts", "client_user_id",
           "email_hash", "email", "source", "stripe_customer_id", "meta"]


def preview(rows: list[dict], limit: int = 5) -> dict:
    """Что мы поняли в файле - ДО загрузки.

    Человек прислал выгрузку и не обязан верить нам на слово: показываем, какие
    колонки распознали, что попадёт в систему и сколько строк уйдёт в брак.
    """
    mapping, sample = {}, []
    known = {"id": ID_KEYS, "email": EMAIL_KEYS, "created_at": CREATED_KEYS,
             "stripe_customer_id": CUSTOMER_KEYS}
    first = next((r for r in rows if isinstance(r, dict)), {})
    for field, keys in known.items():
        for real in first:
            if _norm_key(real) in keys:
                mapping[field] = real
                break

    good = bad = 0
    for row in rows:
        if not isinstance(row, dict):
            bad += 1
            continue
        uid, email = _pick(row, ID_KEYS), _pick(row, EMAIL_KEYS).lower()
        if not uid and not email:
            bad += 1
            continue
        good += 1
        if len(sample) < limit:
            sample.append({"id": uid, "email": email,
                           "created_at": _ts(_pick(row, CREATED_KEYS))})
    with_email = sum(1 for r in rows
                     if isinstance(r, dict) and _pick(r, EMAIL_KEYS))
    return {"columns": list(first.keys())[:20], "mapping": mapping,
            "rows": len(rows), "usable": good, "unusable": bad,
            "with_email": with_email, "sample": sample}
