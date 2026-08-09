"""Причины отмены: свободный текст юзера -> фиксированная категория (LLM).

ВХОД: событие `cancel_reason` из шины - клиент передаёт то, что юзер написал
в своём cancel-флоу: {"event_type":"cancel_reason", "meta":"{\\"text\\":\\"...\\"}"}
(поле text | reason | comment - берём первое непустое).

ВЫХОД: retention.cancel_reasons - категория из ЗАКРЫТОГО списка + однофразовый
пересказ + исходный текст + MRR юзера. Дальше это агрегат «почему уходят» на
экране утечек: не догадки, а слова самих юзеров, сгруппированные машиной.

Почему LLM: категорий мало, но формулировки живые («дорого для меня сейчас»,
«нашёл дешевле», «проект закончился»). Регулярки на этом ломаются, а модель
классифицирует устойчиво. Категория ВНЕ списка отбрасывается кодом.

Идемпотентность: обрабатываем только события, которых ещё нет в таблице
(Replacing по event_id страхует от гонок). Без ключа - ничего не делаем.
"""

from __future__ import annotations

import json
import os
import urllib.error
from datetime import datetime, timezone

try:
    from ai_compose import _call_anthropic, _call_openai, resolve_provider
except ImportError:
    from stripe_sync.ai_compose import (_call_anthropic, _call_openai,
                                        resolve_provider)

CATEGORIES = {"price", "missing_feature", "one_time_need", "switched",
              "quality", "support", "other"}

SYSTEM = """You classify subscription cancellation reasons written by users.
Output ONLY valid JSON: {"items": [{"id": "<given id>", "category": "...",
"summary": "..."}]}

category is exactly one of:
- price           - too expensive, budget, not worth the money
- missing_feature - a needed capability is absent or limited
- one_time_need   - the task/project is finished, seasonal, no longer needed
- switched        - moved to a competitor or an in-house solution
- quality         - bugs, slow, unreliable, bad results
- support         - support or onboarding experience
- other           - anything that fits none of the above

summary: one short neutral phrase in the user's own language, max 90 chars,
no quotes, no emoji, no em-dash. Never invent details that are not in the text.
Return one item per input id, in the same order."""


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def extract_text(meta: str) -> str:
    """meta события -> текст юзера. Пусто, если поля нет."""
    try:
        m = json.loads(meta or "{}")
    except ValueError:
        return ""
    if not isinstance(m, dict):
        return ""
    for key in ("text", "reason", "comment", "feedback"):
        val = str(m.get(key) or "").strip()
        if val:
            return val[:1000]
    return ""


def parse_classification(text: str, allowed_ids: set) -> tuple[dict, list]:
    """JSON модели -> {id: (category, summary)}. Чужие id и категории режем."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        doc = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}, ["ai_json_parse_failed"]
    out, rejected = {}, []
    for raw in (doc.get("items") or []):
        eid = str(raw.get("id", ""))
        if eid not in allowed_ids:
            rejected.append(f"{eid}:unknown_id")
            continue
        cat = str(raw.get("category", "")).lower()
        if cat not in CATEGORIES:
            rejected.append(f"{eid}:unknown_category:{cat}")
            continue
        summary = (str(raw.get("summary", "")).replace("—", " - ")
                   .replace("–", "-").strip()[:90])
        out[eid] = (cat, summary)
    return out, rejected


def pending(client, tenant: str, limit: int = 50) -> list:
    """События cancel_reason с текстом, ещё не разобранные."""
    rows = client.query(
        """
        SELECT e.event_id, e.identity_id, e.meta, toString(e.ts),
               coalesce(ua.mrr, 0) AS mrr
        FROM retention.saas_events_resolved e
        LEFT JOIN retention.user_actions ua
          ON ua.tenant_id = e.tenant_id AND ua.identity_id = e.identity_id
        WHERE e.tenant_id = %(t)s AND e.event_type = 'cancel_reason'
          AND e.meta != ''
          AND e.event_id NOT IN (
              SELECT event_id FROM retention.cancel_reasons WHERE tenant_id = %(t)s)
        ORDER BY e.ts DESC
        LIMIT %(l)s
        """, parameters={"t": tenant, "l": limit}).result_rows
    out = []
    for event_id, identity_id, meta, ts, mrr in rows:
        txt = extract_text(meta)
        if txt:
            out.append({"event_id": event_id, "identity_id": identity_id,
                        "text": txt, "ts": ts, "mrr": float(mrr or 0)})
    return out


def classify(items: list, context: dict | None = None) -> tuple[dict, str]:
    if not items:
        return {}, "nothing_to_do"
    provider, api_key = resolve_provider()
    if not provider:
        return {}, "ai_not_configured"
    call = _call_anthropic if provider == "anthropic" else _call_openai
    payload = [{"id": i["event_id"], "text": i["text"]} for i in items]
    # Продуктовый контекст обязателен: «не хватает функции» и «плохое
    # качество» различимы только на языке КОНКРЕТНОГО продукта.
    try:
        from business_context import context_block
    except ImportError:
        from stripe_sync.business_context import context_block  # type: ignore
    ctx_text = context_block(context) + "\n" if context else ""
    try:
        text = call(api_key, SYSTEM,
                    ctx_text + "Classify these cancellation reasons:\n"
                    + json.dumps(payload, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        return {}, f"ai_http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return {}, f"ai_{type(exc).__name__}"
    out, rejected = parse_classification(text, {i["event_id"] for i in items})
    if rejected:
        print(f"[cancel_reasons] отбраковано: {rejected}", flush=True)
    return out, ("" if out else "ai_empty")


def save(client, tenant: str, items: list, classified: dict) -> int:
    now = _now()
    rows = [[tenant, i["event_id"], i["identity_id"], classified[i["event_id"]][0],
             classified[i["event_id"]][1], i["text"], round(i["mrr"], 2),
             i["ts"], now]
            for i in items if i["event_id"] in classified]
    if rows:
        client.insert(
            "retention.cancel_reasons", rows,
            column_names=["tenant_id", "event_id", "identity_id", "category",
                          "summary", "verbatim", "mrr", "ts", "created_at"])
    return len(rows)


def main() -> None:
    import clickhouse_connect

    tenant = os.environ.get("TENANT_ID", "").strip()
    if not tenant:
        raise SystemExit("нужен TENANT_ID: джоб работает в пространстве клиента")
    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"),
    )
    items = pending(client, tenant)
    from business_context import business_context
    classified, note = classify(items, context=business_context(client, tenant))
    n = save(client, tenant, items, classified) if classified else 0
    print(f"[cancel_reasons] tenant={tenant} pending={len(items)} classified={n}"
          + (f" ({note})" if note else ""))


if __name__ == "__main__":
    main()
