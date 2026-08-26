"""Продуктовые гипотезы недели: аналитика виджета + голос юзеров -> что менять.

ЗАЧЕМ. Сниппет уже собирает продуктовую правду (rage clicks и js-ошибки по
страницам, воронка до денег, INP), экспорт - жалобы и тикеты, виджет - NPS.
Но владелец видит эти сигналы порознь. Этот джоб раз в неделю сводит их в
3-5 ГИПОТЕЗ («что менять в продукте и почему»), каждая обязана опираться на
конкретные цифры и цитаты из входа - выдумки отбрасываются валидатором.

§9: вызов LLM только через llm_stage.call с business_context.
Выход - knowledge kind='product_insights' -> экран /insights + дайджест.

Запуск: TENANT_ID=<пространство> python product_insights.py (ops_loop, Вт 08:00).
"""

from __future__ import annotations

import json
import os

MAX_QUOTES = 25


def collect_facts(client, tenant: str) -> dict:
    """Все продуктовые сигналы одним словарём - вход промпта И валидатора."""
    q = lambda s: client.query(s, parameters={"t": tenant}).result_rows

    friction = [
        {"page": r[0], "rage_clicks": int(r[1]), "js_errors": int(r[2])}
        for r in q("""
            SELECT page, countIf(event_type = 'rage_click'),
                   countIf(event_type = 'js_error')
            FROM retention.saas_events_deduped
            WHERE tenant_id = %(t)s AND ts >= now() - INTERVAL 14 DAY
              AND event_type IN ('rage_click', 'js_error') AND page != ''
            GROUP BY page ORDER BY count() DESC LIMIT 8""")]

    fw = q("""
        SELECT count(),
               countIf(coalesce(f.projects_total, 0) > 0),
               countIf(coalesce(f.generations_total, 0) > 0),
               countIf(ua.sub_status IN ('active', 'past_due'))
        FROM retention.user_actions ua
        LEFT JOIN retention.user_event_features f
          ON f.tenant_id = ua.tenant_id AND f.identity_id = ua.identity_id
        WHERE ua.tenant_id = %(t)s""")[0]
    funnel = {"signed_up": int(fw[0]), "created_project": int(fw[1]),
              "got_value": int(fw[2]), "paying": int(fw[3])}

    voice = [{"kind": r[0], "category": r[1], "text": str(r[2])[:220]}
             for r in q("""
        SELECT event_type, JSONExtractString(meta, 'category'),
               JSONExtractString(meta, 'message')
        FROM retention.saas_events_deduped
        WHERE tenant_id = %(t)s AND event_type = 'feedback'
          AND JSONExtractString(meta, 'message') != ''
        ORDER BY ts DESC LIMIT {n}""".format(n=MAX_QUOTES))]

    nps_rows = q("""
        SELECT toInt32(JSONExtractInt(meta, 'score')), count()
        FROM retention.saas_events_deduped
        WHERE tenant_id = %(t)s AND event_type = 'survey_answer'
          AND JSONExtractString(meta, 'survey') = 'nps'
          AND ts >= now() - INTERVAL 90 DAY
        GROUP BY 1""")
    answers = sum(int(r[1]) for r in nps_rows)
    prom = sum(int(r[1]) for r in nps_rows if int(r[0]) >= 9)
    det = sum(int(r[1]) for r in nps_rows if int(r[0]) <= 6)
    nps = {"answers": answers,
           "nps": round((prom - det) / answers * 100) if answers else None,
           "detractors": det}

    slow = [{"page": r[0], "inp_ms": int(r[1])} for r in q("""
        SELECT page, max(JSONExtractInt(meta, 'inp'))
        FROM retention.saas_events_deduped
        WHERE tenant_id = %(t)s AND ts >= now() - INTERVAL 14 DAY
          AND JSONExtractInt(meta, 'inp') > 500 AND page != ''
        GROUP BY page ORDER BY 2 DESC LIMIT 5""")]

    return {"friction_pages": friction, "funnel": funnel, "voice": voice,
            "nps": nps, "slow_pages": slow}


def validate_hypotheses(raw: list, facts: dict) -> tuple[list, int]:
    """Гипотеза без опоры на вход - выдумка, в мусор. Проверяем, что evidence
    цитирует реальные страницы/тексты/цифры из facts."""
    haystack = json.dumps(facts, ensure_ascii=False).lower()
    kept, rejected = [], 0
    for h in raw if isinstance(raw, list) else []:
        if not isinstance(h, dict):
            rejected += 1
            continue
        theme = str(h.get("theme") or "").strip()[:120]
        hyp = str(h.get("hypothesis") or "").strip()[:400]
        change = str(h.get("suggested_change") or "").strip()[:400]
        evidence = [str(e).strip()[:200] for e in (h.get("evidence") or [])][:4]
        if not (theme and hyp and change and evidence):
            rejected += 1
            continue
        grounded = sum(1 for e in evidence
                       if any(tok in haystack for tok in
                              [e.lower()[:60]] + [w for w in e.lower().split()
                                                  if len(w) > 5][:3]))
        if grounded < len(evidence) / 2:
            rejected += 1
            continue
        kept.append({"theme": theme, "hypothesis": hyp,
                     "suggested_change": change, "evidence": evidence})
    return kept[:5], rejected


def run(client, tenant: str) -> dict:
    try:
        from business_context import business_context, context_block
        from llm_stage import call, record_run
    except ImportError:                     # pragma: no cover
        from stripe_sync.business_context import (business_context,  # type: ignore
                                                  context_block)
        from stripe_sync.llm_stage import call, record_run  # type: ignore
    from knowledge import save as kb_save

    facts = collect_facts(client, tenant)
    if not (facts["voice"] or facts["friction_pages"]
            or facts["nps"]["answers"]):
        return {"status": "no_data"}

    ctx = context_block(business_context(None, tenant, None))
    system = (
        "You are a blunt product analyst. From the FACTS below produce 3-5 "
        "product hypotheses: what to change in the product and why. STRICT "
        "RULES: every hypothesis must be grounded ONLY in the facts given - "
        "quote exact pages, numbers or user phrases in `evidence`; never "
        "invent data; if facts are thin, return fewer hypotheses. Respond "
        "with a JSON array of objects: {theme, hypothesis, suggested_change, "
        "evidence: [strings copied from facts]}. No prose around the JSON.")
    user_body = (ctx + "\n\nFACTS:\n"
                 + json.dumps(facts, ensure_ascii=False, indent=1))

    raw_text, note = call(system, user_body)
    if note:
        record_run(client, tenant, "product", "error", 0, 0, note)
        return {"status": note}
    try:
        raw = json.loads(raw_text[raw_text.find("["):raw_text.rfind("]") + 1])
    except Exception as exc:  # noqa: BLE001
        record_run(client, tenant, "product", "error", 0, 0, str(exc)[:200])
        return {"status": f"llm_failed:{type(exc).__name__}"}

    kept, rejected = validate_hypotheses(raw, facts)
    record_run(client, tenant, "product", "ok", len(kept), rejected, "")
    payload = {"hypotheses": kept, "facts_summary": {
        "funnel": facts["funnel"], "nps": facts["nps"],
        "friction_top": facts["friction_pages"][:3]}}
    kb_save(client, tenant, "product_insights", payload, "product_insights")
    return {"status": "ok", "kept": len(kept), "rejected": rejected}


def main() -> None:
    import clickhouse_connect
    tenant = os.environ.get("TENANT_ID", "").strip()
    if not tenant:
        raise SystemExit("нужен TENANT_ID")
    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"))
    print(f"[product] tenant={tenant} {run(client, tenant)}", flush=True)


if __name__ == "__main__":
    main()
