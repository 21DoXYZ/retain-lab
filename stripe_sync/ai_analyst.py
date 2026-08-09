"""ИИ-аналитик результатов: факты недели -> конкретные правки кампаний.

ЧТО ДЕЛАЕТ. Раз в неделю (ops_loop, Пн 08:10 - после uplift-отчёта) собирает
ФАКТЫ по тенанту и просит LLM предложить правки. Модель НИЧЕГО не применяет:
каждая рекомендация проверяется кодом (кампания/шаг существуют, вид правки из
белого списка, значения в границах) и ложится в retention.ai_insights со
статусом new. Владелец применяет кнопкой на /campaigns - тогда правка идёт
через тот же overrides-слой, что и ручное редактирование.

ФАКТЫ (только из наших таблиц, ничего не выдумывается):
  • uplift_reports  - конверсия target vs holdout и инкремент по кампании;
  • campaign_send_log - сколько касаний ушло/отбито и ПОЧЕМУ (no_contact,
    no_consent, hygiene-отказы) по каждому шагу;
  • offers_issued   - выдачи/холдаут/отказы и стоимость по офферу;
  • campaign_enrollments_current - сколько зашло, вышло по цели (exited) и
    доехало до конца без результата (done).

Без ключа LLM (resolve_provider) джоб честно печатает «ai_not_configured» и
ничего не пишет: выдумывать рекомендации нельзя.
"""

from __future__ import annotations

import json
import os
import urllib.error
from datetime import datetime, timedelta, timezone

try:
    from ai_compose import _call_anthropic, _call_openai, resolve_provider
except ImportError:  # пакетный контекст (board)
    from stripe_sync.ai_compose import (_call_anthropic, _call_openai,
                                        resolve_provider)

KINDS = {"drop_step", "change_delay", "rewrite_copy", "cut_offer",
         "raise_cap", "scale_up", "no_action"}

SYSTEM = """You are a subscription-retention analyst reviewing ONE tenant's
weekly campaign results. You output ONLY valid JSON:
{"insights": [{"campaign_id": "...", "step_idx": -1, "kind": "...",
"title": "...", "rationale": "...", "suggestion": {...}}]}

kind is exactly one of: drop_step | change_delay | rewrite_copy | cut_offer |
raise_cap | scale_up | no_action

suggestion shapes (only these, values must be inside the stated bounds):
- drop_step:     {} (the step is removed by the owner)
- change_delay:  {"delay_h": <0..720>}
- rewrite_copy:  {"subject": "...", "body": "..."} - keep {{card_update_url}}
                 and {{app_url}} placeholders where the original had links
- cut_offer:     {} (stop attaching this offer)
- raise_cap:     {"max_per_user_30d": <0..100>}
- scale_up:      {} (works - keep and consider more volume)
- no_action:     {}

step_idx: the step the insight is about, or -1 for the campaign as a whole.

Hard rules:
- EVERY rationale must cite concrete numbers from the FACTS given to you
  (conversion %, n, rejected counts, $ incremental, cost). No vague advice.
- Never invent numbers that are not in the facts. If a campaign has too little
  data (n_target < 20 or no holdout), say so with kind "no_action" instead of
  guessing.
- A rejected-heavy step (no_contact / no_consent) is a CHANNEL problem, not a
  copy problem - say that plainly.
- Negative or zero incremental with enough data -> propose drop_step or
  cut_offer on the weakest element, not a rewrite.
- At most 6 insights, ordered by money impact. No emoji, no em-dash.
"""


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def collect_facts(client, tenant: str, days: int = 7) -> dict:
    """Факты недели по кампаниям - вход для модели и evidence в записи."""
    uplift = [dict(zip(["campaign_id", "n_target", "n_control", "conv_target",
                        "conv_control", "avg_check", "incremental_usd"], r))
              for r in client.query(
        """
        SELECT campaign_id,
               argMax(n_target, computed_at), argMax(n_control, computed_at),
               argMax(conv_target, computed_at), argMax(conv_control, computed_at),
               argMax(avg_check, computed_at), argMax(incremental_usd, computed_at)
        FROM retention.uplift_reports
        WHERE tenant_id = %(t)s AND computed_at >= now() - INTERVAL %(d)s DAY
        GROUP BY campaign_id
        """, parameters={"t": tenant, "d": days}).result_rows]

    steps = [dict(zip(["campaign_id", "step_idx", "action", "sent", "rejected",
                       "retried", "top_reason"], r))
             for r in client.query(
        """
        SELECT campaign_id, step_idx, any(action) AS action,
               countIf(status IN ('sent', 'queued', 'issued', 'dry_run')) AS sent,
               countIf(status = 'rejected') AS rejected,
               countIf(status = 'retry') AS retried,
               topK(1)(if(status = 'rejected', reason, '')) AS reasons
        FROM retention.campaign_send_log
        WHERE tenant_id = %(t)s AND ts >= now() - INTERVAL %(d)s DAY
        GROUP BY campaign_id, step_idx
        ORDER BY campaign_id, step_idx
        """, parameters={"t": tenant, "d": days}).result_rows]
    for s in steps:
        r = s.get("top_reason")
        s["top_reason"] = (r[0] if isinstance(r, (list, tuple)) and r else "") or ""

    offers = [dict(zip(["offer_id", "issued", "holdout", "rejected", "cost"], r))
              for r in client.query(
        """
        SELECT offer_id,
               countIf(status IN ('issued', 'dry_run')) AS issued,
               countIf(status = 'holdout') AS holdout,
               countIf(status = 'rejected') AS rejected,
               round(sumIf(toFloat64(cost_estimate), status = 'issued'), 2) AS cost
        FROM retention.offers_issued
        WHERE tenant_id = %(t)s AND issued_at >= now() - INTERVAL %(d)s DAY
        GROUP BY offer_id
        """, parameters={"t": tenant, "d": days}).result_rows]

    enroll = [dict(zip(["campaign_id", "enrolled", "exited", "done", "active"], r))
              for r in client.query(
        """
        SELECT campaign_id, count() AS enrolled,
               countIf(status = 'exited') AS exited,
               countIf(status = 'done') AS done,
               countIf(status = 'active') AS active
        FROM retention.campaign_enrollments_current
        WHERE tenant_id = %(t)s AND enrolled_at >= now() - INTERVAL %(d)s DAY
        GROUP BY campaign_id
        """, parameters={"t": tenant, "d": days}).result_rows]

    return {"period_days": days, "uplift": uplift, "steps": steps,
            "offers": offers, "enrollments": enroll}


def has_data(facts: dict) -> bool:
    """Есть ли о чём говорить: хоть одна кампания с зачислениями."""
    return bool(facts.get("enrollments"))


def parse_insights(text: str, campaigns: dict) -> tuple[list, list]:
    """JSON модели -> валидные инсайты (+ причины отбраковки).
    campaigns: {campaign_id: число_шагов} - проверка существования."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        doc = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return [], ["ai_json_parse_failed"]

    out, rejected = [], []
    for raw in (doc.get("insights") or [])[:6]:
        cid = str(raw.get("campaign_id", ""))
        if cid not in campaigns:
            rejected.append(f"{cid}:unknown_campaign")
            continue
        kind = str(raw.get("kind", ""))
        if kind not in KINDS:
            rejected.append(f"{cid}:unknown_kind:{kind}")
            continue
        try:
            idx = int(raw.get("step_idx", -1))
        except (TypeError, ValueError):
            idx = -1
        if idx >= campaigns[cid]:
            rejected.append(f"{cid}:step_out_of_range:{idx}")
            continue
        title = _clean(str(raw.get("title", "")))[:160]
        rationale = _clean(str(raw.get("rationale", "")))[:800]
        if not title or not rationale:
            rejected.append(f"{cid}:empty_text")
            continue

        sug = raw.get("suggestion") or {}
        if not isinstance(sug, dict):
            sug = {}
        clean_sug = {}
        if kind == "change_delay":
            try:
                d = float(sug.get("delay_h"))
            except (TypeError, ValueError):
                rejected.append(f"{cid}:bad_delay")
                continue
            if not 0 <= d <= 720:
                rejected.append(f"{cid}:delay_out_of_range")
                continue
            clean_sug["delay_h"] = d
        elif kind == "rewrite_copy":
            subj = _clean(str(sug.get("subject", "")))[:200]
            body = _clean(str(sug.get("body", "")))[:2000]
            if not body:
                rejected.append(f"{cid}:empty_body")
                continue
            clean_sug = {"subject": subj, "body": body}
        elif kind == "raise_cap":
            try:
                cap = int(sug.get("max_per_user_30d"))
            except (TypeError, ValueError):
                rejected.append(f"{cid}:bad_cap")
                continue
            if not 0 <= cap <= 100:
                rejected.append(f"{cid}:cap_out_of_range")
                continue
            clean_sug["max_per_user_30d"] = cap

        out.append({"campaign_id": cid, "step_idx": idx, "kind": kind,
                    "title": title, "rationale": rationale,
                    "suggestion": clean_sug})
    return out, rejected


def _clean(txt: str) -> str:
    return txt.replace("—", " - ").replace("–", "-").strip()


def analyze(client, tenant: str, campaigns: dict, days: int = 7) -> tuple[list, str]:
    facts = collect_facts(client, tenant, days)
    if not has_data(facts):
        return [], "no_data"
    provider, api_key = resolve_provider()
    if not provider:
        return [], "ai_not_configured"
    call = _call_anthropic if provider == "anthropic" else _call_openai
    # Бизнес-контекст обязателен: rewrite_copy без него советует голосом
    # генерик-SaaS, а не ЭТОГО продукта (методология §8).
    try:
        from business_context import business_context, context_block
    except ImportError:
        from stripe_sync.business_context import (business_context,  # type: ignore
                                                  context_block)
    ctx = business_context(client, tenant)
    user = (context_block(ctx)
            + "\nFACTS (last %d days, tenant %s):\n" % (days, tenant)
            + json.dumps(facts, ensure_ascii=False, default=str)
            + "\nCampaign step counts: " + json.dumps(campaigns)
            + "\nProduce the insights now.")
    try:
        text = call(api_key, SYSTEM, user)
    except urllib.error.HTTPError as exc:
        return [], f"ai_http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return [], f"ai_{type(exc).__name__}"
    insights, rejected = parse_insights(text, campaigns)
    if rejected:
        print(f"[ai_analyst] отбраковано: {rejected}", flush=True)
    return [{**i, "evidence": facts} for i in insights], ("" if insights else "ai_empty")


def save(client, tenant: str, insights: list, days: int) -> int:
    now = datetime.now(tz=timezone.utc)
    p_start = (now - timedelta(days=days)).date()
    rows = []
    for i in insights:
        iid = f"{p_start}:{i['campaign_id']}:{i['step_idx']}:{i['kind']}"
        rows.append([tenant, iid, p_start, now.date(), i["campaign_id"],
                     int(i["step_idx"]), i["kind"], i["title"], i["rationale"],
                     json.dumps(i.get("evidence") or {}, ensure_ascii=False, default=str),
                     json.dumps(i.get("suggestion") or {}, ensure_ascii=False),
                     "new", _now()])
    if rows:
        client.insert(
            "retention.ai_insights", rows,
            column_names=["tenant_id", "insight_id", "period_start", "period_end",
                          "campaign_id", "step_idx", "kind", "title", "rationale",
                          "evidence", "suggestion", "status", "created_at"])
    return len(rows)


def main() -> None:
    import clickhouse_connect
    from pathlib import Path

    tenant = os.environ.get("TENANT_ID", "").strip()
    if not tenant:
        raise SystemExit("нужен TENANT_ID: джоб работает в пространстве клиента")
    days = int(os.environ.get("ANALYST_DAYS", "7"))

    cfgs = json.loads((Path(__file__).parent / "saas_campaigns.json").read_text())
    conf = cfgs.get(tenant) or cfgs.get("_default") or {"campaigns": []}
    campaigns = {c["campaign_id"]: len(c.get("steps", []))
                 for c in conf.get("campaigns", [])}

    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"),
    )
    insights, note = analyze(client, tenant, campaigns, days)
    n = save(client, tenant, insights, days) if insights else 0
    print(f"[analyst] tenant={tenant} insights={n}" + (f" ({note})" if note else ""))
    for i in insights:
        print(f"  [{i['kind']}] {i['campaign_id']}#{i['step_idx']}: {i['title']}")


if __name__ == "__main__":
    main()
