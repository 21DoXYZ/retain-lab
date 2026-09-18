"""Авто-мозг кампаний: раз в день система улучшает себя сама.

Запрос владельца (2026-09-07): «нужен авторежим - сама сканирует, сама
запускает и проверяет кампании». Что делает ежедневный проход:

  1. ЗАПУСК: для каждого сегмента застревания из плейбука - если людей >= 30
     и живой авто-кампании на этот сегмент ещё нет - запускает её (копия
     логики /saas/campaigns/custom: снапшот + holdout 10%).
  2. ДОЛИВКА: в живые авто-кампании доливает НОВЫХ людей, попавших в сегмент
     после запуска (кто уже зачислялся - не трогается: re-enroll нет).
  3. ПРОВЕРКА: кампания старше 7 дней с >= 150 доставленных касаний, у которой
     конверсия в цель НЕ лучше контрольной группы, - ставится на паузу.
  4. ОТЧЁТ: одно письмо владельцу «что я сегодня сделал» (только если что-то
     делал). Молчание = делать было нечего.

Все касания по-прежнему идут через штатный тик со всеми предохранителями
(тихие часы, частоты, подавления, warmup). Мозг только решает КОГО и ЧТО.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

MIN_SEGMENT = 30          # меньше - шум, кампания не окупает внимание
EVAL_MIN_DAYS = 7
EVAL_MIN_SENT = 150
EVAL_MIN_CONTROL = 20     # меньше - одна случайная конверсия глушит кампанию
CONTROL_PCT = 10
# Второе касание через 4 дня: первый подтверждённый платёж (2026-09-08, $99)
# пришёл от человека, получившего ДВА письма. Одно касание - недожатая
# последовательность; review_sequence не даст второму пересказать первое.
FOLLOW_UP_DELAY_H = 96

# Плейбук сегментов: audience -> цель -> утверждённая копия (2026-09-07).
# Тексты человеческие (§8a), подпись добавит отправитель.
PLAYBOOK: list[dict] = [
    {
        "key": "paywall",
        "title": "Saw pricing, did not buy",
        "audience": {"status": "free", "saw_pricing": True},
        "goal_event": "billing.invoice_paid",
        "subject": "one thing about pricing",
        "body": ("Hey, I noticed you checked out our pricing but held off. "
                 "Totally fair - most people want to see one real result "
                 "first. Your account still has free credits, so make one "
                 "video and judge for yourself.\n\nIf pricing itself is the "
                 "blocker, just reply - I read every answer.\n\n"
                 "https://hubcontent.ai/app"),
        "subject_ru": "пара слов про цены",
        "body_ru": ("Привет. Видел, что вы смотрели тарифы, но так и не "
                    "решились. Это нормально - большинству сначала нужен "
                    "один готовый результат. Бесплатные кредиты на аккаунте "
                    "ещё живы: сделайте одно видео и решите сами.\n\nЕсли "
                    "смущает именно цена - просто ответьте на письмо, я "
                    "читаю каждый ответ.\n\nhttps://hubcontent.ai/app"),
        "follow_up": {
            "subject": "what held you back",
            "body": ("Following up once about the plans page. If a specific "
                     "thing stopped you - price, a missing feature, or doubt "
                     "it fits your workflow - reply with a single word and I "
                     "will answer straight.\n\nIf you simply have not needed "
                     "it yet, that is fine too. The free credits stay "
                     "yours.\n\nhttps://hubcontent.ai/app"),
            "subject_ru": "что вас остановило",
            "body_ru": ("Возвращаюсь один раз к теме тарифов. Если "
                        "остановило что-то конкретное - цена, нехватка "
                        "функции или сомнение, что подойдёт под вашу "
                        "задачу - ответьте одним словом, и я отвечу по "
                        "делу.\n\nА если просто пока не нужно - тоже "
                        "нормально, бесплатные кредиты остаются вашими."
                        "\n\nhttps://hubcontent.ai/app"),
        },
    },
    {
        "key": "no_gen",
        "title": "Project without generation",
        "audience": {"projects_min": 1, "gens_max": 0},
        "goal_event": "generation_completed",
        "subject": "your project is one click from done",
        "body": ("You set up a project but haven't rendered it yet. It takes "
                 "about a minute, and it's the fastest way to see if this "
                 "fits you.\n\nIf something got confusing along the way, "
                 "reply and tell me where - that's exactly what I want to "
                 "fix.\n\nhttps://hubcontent.ai/app"),
        "subject_ru": "ваш проект в одном клике от готового",
        "body_ru": ("Вы создали проект, но так и не запустили генерацию. "
                    "Это занимает около минуты - и это самый быстрый способ "
                    "понять, подходит ли вам инструмент.\n\nЕсли что-то по "
                    "пути запутало, ответьте и скажите где - именно это я и "
                    "хочу починить.\n\nhttps://hubcontent.ai/app"),
        "inapp": {
            "subject": "Your project is one render away",
            "body": "Press generate and see the first result - about a minute.",
            "subject_ru": "Проект в одном рендере от результата",
            "body_ru": "Нажмите «сгенерировать» и посмотрите первый результат - это займёт около минуты.",
        },
        "follow_up": {
            "subject": "your project is still saved",
            "body": ("Checking in once more: the project you created is "
                     "still there, nothing expired. If a step confused you, "
                     "reply and name it and I will walk you through.\n\nOr "
                     "open it and press generate - the render finishes fast."
                     "\n\nhttps://hubcontent.ai/app"),
            "subject_ru": "проект никуда не делся",
            "body_ru": ("Пишу ещё раз: проект, который вы создали, на "
                        "месте, ничего не сгорело. Если какой-то шаг сбил "
                        "с толку - ответьте, и я проведу за руку.\n\nИли "
                        "просто откройте его и нажмите «сгенерировать», "
                        "рендер быстрый.\n\nhttps://hubcontent.ai/app"),
        },
    },
    {
        "key": "no_download",
        "title": "Generated, not downloaded",
        "audience": {"gens_min": 1, "no_download": True, "status": "free"},
        "goal_event": "download_click",
        "subject": "your video is ready and waiting",
        "body": ("Your video rendered - but you never downloaded it. It's "
                 "sitting in your project right now. Grab it while your "
                 "credits cover it.\n\nIf the result wasn't what you "
                 "expected, reply with one line about what was off - I'll "
                 "take it to the team.\n\nhttps://hubcontent.ai/app"),
        "subject_ru": "ваше видео готово и ждёт",
        "body_ru": ("Видео срендерилось, но вы его так и не скачали. Оно "
                    "лежит в вашем проекте прямо сейчас - заберите, пока "
                    "кредиты покрывают рендер.\n\nЕсли результат не тот, "
                    "которого ждали, ответьте одной строкой, что не так - "
                    "передам команде.\n\nhttps://hubcontent.ai/app"),
        "inapp": {
            "subject": "Your video is ready",
            "body": "It is rendered and waiting in your project - one click to save it.",
            "subject_ru": "Ваше видео готово",
            "body_ru": "Оно срендерено и ждёт в проекте - заберите одним кликом.",
        },
        "follow_up": {
            "subject": "your render is still in the project",
            "body": ("One more nudge and then I will leave it alone: the "
                     "video you made is finished and sitting in your "
                     "account. Download it while the credits still cover "
                     "it.\n\nIf the result missed the mark, reply and say "
                     "what was wrong - I will pass it on.\n\n"
                     "https://hubcontent.ai/app"),
            "subject_ru": "рендер всё ещё в проекте",
            "body_ru": ("Последнее напоминание, дальше не беспокою: "
                        "готовое видео лежит в вашем аккаунте, один клик - "
                        "и оно у вас.\n\nЕсли результат разочаровал, "
                        "ответьте и скажите чем - это уйдёт прямо команде."
                        "\n\nhttps://hubcontent.ai/app"),
        },
    },
    {
        "key": "gone_quiet",
        "title": "Cooling off",
        "audience": {"not_seen_days": 14, "gens_min": 1, "status": "free"},
        "goal_event": "generation_completed",
        "subject": "still here when you need us",
        "body": ("You made a few videos with us and then went quiet - no "
                 "guilt, life happens. Your projects and credits are still "
                 "in place.\n\nIf something pushed you away, tell me in one "
                 "line - I read every reply.\n\nhttps://hubcontent.ai/app"),
        "subject_ru": "мы на месте, если что",
        "body_ru": ("Вы сделали у нас несколько видео и пропали - без "
                    "упрёка, жизнь бывает разной. Ваши проекты и кредиты "
                    "на месте.\n\nЕсли что-то оттолкнуло, напишите одной "
                    "строкой что - я читаю каждый ответ.\n\n"
                    "https://hubcontent.ai/app"),
        "follow_up": {
            "subject": "one word is enough",
            "body": ("Last note from me. If hubcontent did not click for "
                     "you, tell me why with a single word: price, quality, "
                     "time, or something else. That answer decides what we "
                     "fix next.\n\nAnd if you just got busy, your projects "
                     "are waiting where you left them.\n\n"
                     "https://hubcontent.ai/app"),
            "subject_ru": "одного слова хватит",
            "body_ru": ("Последняя весточка от меня. Если hubcontent вам "
                        "не зашёл, скажите почему одним словом: цена, "
                        "качество, время или что-то ещё. Этот ответ "
                        "решает, что мы чиним дальше.\n\nА если просто "
                        "закрутились - проекты ждут там же, где вы их "
                        "оставили.\n\nhttps://hubcontent.ai/app"),
        },
    },
]


def playbook_steps(pb: dict) -> list[dict]:
    """Сырые шаги кампании плейбука: письмо сразу + дожим через 4 дня.
    subject_ru/body_ru едут в шаг как есть - тик подставит их русскоязычным
    юзерам (campaign_tick.apply_locale)."""
    def _step(src: dict, delay: float) -> dict:
        out = {"action": "email", "subject": src["subject"],
               "body": src["body"], "cta_label": "Open the app",
               "delay_h": delay}
        for lf in ("subject_ru", "body_ru"):
            if src.get(lf):
                out[lf] = src[lf]
        return out

    steps = [_step(pb, 0)]
    ia = pb.get("inapp")
    if ia:
        # баннер в продукте тем же днём: канал бесплатный, лимитов ESP нет,
        # человек видит его в самый конвертящий момент - уже внутри продукта
        banner = {"action": "inapp", "delay_h": 0, "ttl_days": 3,
                  "subject": ia["subject"], "body": ia["body"],
                  "cta_label": "Open the app"}
        for lf in ("subject_ru", "body_ru"):
            if ia.get(lf):
                banner[lf] = ia[lf]
        steps.append(banner)
    fu = pb.get("follow_up")
    if fu:
        steps.append(_step(fu, FOLLOW_UP_DELAY_H))
    return steps


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ch():
    import clickhouse_connect
    return clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"))


def _segment_ids(ch, tenant: str, audience: dict) -> list[tuple]:
    from segment import audience_sql, build
    conds, sparams, unknown = build(dict(audience))
    if unknown:
        raise ValueError(f"unknown filters: {unknown}")
    sql = (audience_sql(conds)
           .replace("{t:String}", "%(t)s")
           .replace("{sg_plan:String}", "%(sg_plan)s"))
    return ch.query(sql, parameters={"t": tenant, **sparams}).result_rows


def _active_auto(tenant: str) -> dict[str, dict]:
    """segment_key -> conf живой авто-кампании этого тенанта."""
    import overrides as ovr
    out = {}
    for c in (ovr.load_tenant(tenant).get("custom_campaigns") or []):
        if c.get("auto_brain") and c.get("status") == "active":
            out[str(c.get("segment_key"))] = c
    return out


def _brain_keys(tenant: str) -> set[str]:
    """Сегменты, на которые мозг УЖЕ заводил кампанию - в ЛЮБОМ статусе.
    Урок 2026-09-15: пауза считалась вакансией, и launch_missing тут же
    перезапускал сегмент новой кампанией с тем же текстом - 150 человек
    получили дубль письма. Пауза - это решение, а не свободное место."""
    import overrides as ovr
    return {str(c.get("segment_key"))
            for c in (ovr.load_tenant(tenant).get("custom_campaigns") or [])
            if c.get("auto_brain")}


def _enroll(ch, tenant: str, cid: str, steps: list, rows: list,
            skip_ids: set) -> tuple[int, int]:
    from campaign_tick import holdout_split, next_step_time
    now = _now()
    first_at = next_step_time(steps, now, 0)
    cols = ["tenant_id", "campaign_id", "identity_id", "control", "entry_stage",
            "step_idx", "next_step_at", "status", "enrolled_at", "updated_at"]
    data, control_n = [], 0
    for r in rows:
        if str(r[0]) in skip_ids:
            continue
        control = holdout_split(tenant, cid, r[0], CONTROL_PCT)
        control_n += 1 if control else 0
        data.append([tenant, cid, r[0], 1 if control else 0,
                     str(r[1] or "MANUAL"), 0, first_at, "active", now, now])
    if data:
        ch.insert("retention.campaign_enrollments", data, column_names=cols)
    return len(data), control_n


def _tenant_profile(tenant: str) -> dict:
    """Профиль тенанта для copy_review (разрешённые цифры, способности)."""
    try:
        from channels_admin import load_tenants
        return (load_tenants().get(tenant, {}) or {}).get("onboarding_answers") or {}
    except Exception:  # noqa: BLE001
        return {}


def launch_missing(ch, tenant: str, actions: list) -> None:
    """Плейбук: сегмент без живой авто-кампании и с людьми - запуск."""
    import overrides as ovr
    from segment import describe, validate_steps
    taken = _brain_keys(tenant)
    for pb in PLAYBOOK:
        if pb["key"] in taken:
            continue
        rows = _segment_ids(ch, tenant, pb["audience"])
        if len(rows) < MIN_SEGMENT:
            continue
        steps, reason = validate_steps(playbook_steps(pb))
        if reason:
            actions.append(f"НЕ запустил {pb['key']}: копия не прошла валидатор ({reason})")
            continue
        # методология текстов v2: клише/цифры без источника/крик - не уходит;
        # дожим, пересказывающий первое письмо, - тоже (review_sequence)
        from copy_review import review_sequence, review_step
        profile = _tenant_profile(tenant)
        bad = [f for st in steps for f in review_step(
            st.get("subject", ""), st.get("body", ""), pb["key"],
            st.get("action", "email"), profile) if f["level"] == "fatal"]
        # русские версии - через тот же фильтр (тире, крик, цифры, ссылка)
        bad += [f for st in steps if st.get("body_ru") for f in review_step(
            st.get("subject_ru", ""), st.get("body_ru", ""), pb["key"],
            st.get("action", "email"), profile) if f["level"] == "fatal"]
        bad += [f for f in review_sequence(steps) if f["level"] == "fatal"]
        bad += [f for f in review_sequence(
            [{"body": st.get("body_ru", "")} for st in steps])
            if f["level"] == "fatal"]
        if bad:
            actions.append(f"НЕ запустил {pb['key']}: текст завален "
                           f"({', '.join(sorted({f['code'] for f in bad}))})")
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", pb["title"].lower()).strip("_")[:24]
        cid = f"M_{slug}_{_now().strftime('%m%d%H%M')}"
        ovr.add_custom_campaign(tenant, {
            "campaign_id": cid, "title": pb["title"], "status": "active",
            "goal_event": pb["goal_event"], "audience": pb["audience"],
            "audience_note": describe(pb["audience"]),
            "created_at": _now().strftime("%Y-%m-%d %H:%M:%S"),
            "steps": steps, "auto_brain": True, "segment_key": pb["key"]})
        n, c = _enroll(ch, tenant, cid, steps, rows, set())
        actions.append(f"запустил «{pb['title']}» ({cid}): {n} человек, "
                       f"{c} в контрольной группе")


def _segment_campaign_ids(tenant: str, key: str) -> list[str]:
    """ВСЕ кампании мозга этого сегмента, включая запаузенные. Аудит
    2026-09-18: seen по одной кампании не видел людей из запаузенного
    дубля - доливка отправила бы им тот же текст третий раз."""
    import overrides as ovr
    return [str(c.get("campaign_id"))
            for c in (ovr.load_tenant(tenant).get("custom_campaigns") or [])
            if c.get("auto_brain") and str(c.get("segment_key")) == key]


def top_up(ch, tenant: str, actions: list) -> None:
    """Доливка: новые люди сегмента, ещё не бывавшие в кампании."""
    for key, conf in _active_auto(tenant).items():
        pb = next((p for p in PLAYBOOK if p["key"] == key), None)
        if not pb:
            continue
        cid = conf["campaign_id"]
        seen = {str(r[0]) for r in ch.query(
            "SELECT DISTINCT identity_id FROM retention.campaign_enrollments "
            "WHERE tenant_id = %(t)s AND campaign_id IN %(cc)s",
            parameters={"t": tenant,
                        "cc": _segment_campaign_ids(tenant, key)}).result_rows}
        rows = _segment_ids(ch, tenant, pb["audience"])
        n, c = _enroll(ch, tenant, cid, conf.get("steps") or [], rows, seen)
        if n:
            actions.append(f"долил в «{conf.get('title', cid)}»: +{n} новых "
                           f"({c} в контроле)")


def evaluate(ch, tenant: str, actions: list) -> None:
    """Пауза кампаний, которые не двигают цель против контроля."""
    import overrides as ovr
    for key, conf in _active_auto(tenant).items():
        cid = conf["campaign_id"]
        goal = str(conf.get("goal_event") or "")
        if not goal:
            continue
        # ЦЕЛЬ - строго ПОСЛЕ ДОСТАВЛЕННОГО письма (урок 2026-09-15: счёт
        # «после зачисления» мешал в кучу сотни недоставленных и пауза
        # срабатывала на мусоре). Таргет = кому реально ушло письмо.
        stats = ch.query("""
            SELECT dateDiff('day', min(enrolled_at), now()),
                   uniqExactIf(identity_id, control = 1)
            FROM retention.campaign_enrollments
            WHERE tenant_id = %(t)s AND campaign_id = %(c)s
            """, parameters={"t": tenant, "c": cid}).result_rows[0]
        t_n = int(ch.query(
            "SELECT uniqExact(identity_id) FROM retention.campaign_send_log "
            "WHERE tenant_id = %(t)s AND campaign_id = %(c)s AND status = 'sent'",
            parameters={"t": tenant, "c": cid}).result_rows[0][0])
        t_hit = int(ch.query("""
            SELECT count() FROM (
              SELECT s.id FROM (
                SELECT identity_id AS id, min(ts) AS sent_at
                FROM retention.campaign_send_log
                WHERE tenant_id = %(t)s AND campaign_id = %(c)s
                  AND status = 'sent'
                GROUP BY identity_id
              ) s
              JOIN retention.saas_events_deduped p ON p.identity_id = s.id
              WHERE p.tenant_id = %(t)s AND p.event_type = %(g)s
              GROUP BY s.id, s.sent_at
              HAVING min(p.ts) > s.sent_at
            )""", parameters={"t": tenant, "c": cid, "g": goal}).result_rows[0][0])
        c_conv = ch.query("""
            SELECT countIf(hit)
            FROM (
              SELECT identity_id, min(enrolled_at) AS enr
              FROM retention.campaign_enrollments
              WHERE tenant_id = %(t)s AND campaign_id = %(c)s AND control = 1
              GROUP BY identity_id
            ) e
            LEFT JOIN (
              SELECT identity_id, min(ts) AS first_goal
              FROM retention.saas_events_deduped
              WHERE tenant_id = %(t)s AND event_type = %(g)s
              GROUP BY identity_id
            ) g ON g.identity_id = e.identity_id
            ARRAY JOIN [g.first_goal >= e.enr] AS hit
            """, parameters={"t": tenant, "c": cid, "g": goal}).result_rows[0]
        days, c_n = int(stats[0] or 0), int(stats[1] or 0)
        c_hit = int(c_conv[0] or 0)
        # Пауза только на достаточном объёме С ОБЕИХ сторон: маленький
        # контроль шумит (1 случайная конверсия из 25 = 4% и глушит любую
        # живую кампанию). Мало контроля - ждём, не судим.
        if (days < EVAL_MIN_DAYS or t_n < EVAL_MIN_SENT
                or c_n < EVAL_MIN_CONTROL):
            continue
        t_rate = t_hit / t_n if t_n else 0.0
        c_rate = c_hit / c_n if c_n else 0.0
        if t_rate <= c_rate:
            # ДЕНЕЖНЫЙ ПРЕДОХРАНИТЕЛЬ (2026-09-18): проксицель - не деньги.
            # «Проект без генерации» был запаузен по цели, принеся $423
            # оплат после писем. Кампанию, чья аудитория после доставки
            # платит больше контроля на человека, не паузим.
            t_rev = float(ch.query("""
                SELECT sum(usd) FROM (
                  SELECT s.id, i.invoice_id,
                         argMax(i.amount_paid, i.updated_at) AS usd
                  FROM (
                    SELECT identity_id AS id, min(ts) AS sent_at
                    FROM retention.campaign_send_log
                    WHERE tenant_id = %(t)s AND campaign_id = %(c)s
                      AND status = 'sent' GROUP BY identity_id
                  ) s
                  JOIN (
                    SELECT identity_id AS iid,
                           argMax(stripe_customer_id, updated_at) AS cust
                    FROM retention.identities WHERE tenant_id = %(t)s
                    GROUP BY identity_id
                  ) c2 ON c2.iid = s.id
                  JOIN retention.stripe_invoices i ON i.customer_id = c2.cust
                  WHERE i.tenant_id = %(t)s AND i.status = 'paid'
                    AND c2.cust != '' AND i.created_ts > s.sent_at
                  GROUP BY s.id, i.invoice_id
                )""", parameters={"t": tenant, "c": cid}).result_rows[0][0] or 0)
            c_rev = float(ch.query("""
                SELECT sum(usd) FROM (
                  SELECT e.id, i.invoice_id,
                         argMax(i.amount_paid, i.updated_at) AS usd
                  FROM (
                    SELECT identity_id AS id, min(enrolled_at) AS enr
                    FROM retention.campaign_enrollments
                    WHERE tenant_id = %(t)s AND campaign_id = %(c)s
                      AND control = 1 GROUP BY identity_id
                  ) e
                  JOIN (
                    SELECT identity_id AS iid,
                           argMax(stripe_customer_id, updated_at) AS cust
                    FROM retention.identities WHERE tenant_id = %(t)s
                    GROUP BY identity_id
                  ) c2 ON c2.iid = e.id
                  JOIN retention.stripe_invoices i ON i.customer_id = c2.cust
                  WHERE i.tenant_id = %(t)s AND i.status = 'paid'
                    AND c2.cust != '' AND i.created_ts > e.enr
                  GROUP BY e.id, i.invoice_id
                )""", parameters={"t": tenant, "c": cid}).result_rows[0][0] or 0)
            if t_rev / t_n > c_rev / c_n:
                actions.append(
                    f"оставил «{conf.get('title', cid)}» несмотря на слабую "
                    f"цель: деньги после писем ${t_rev:.0f} на {t_n} чел "
                    f"против ${c_rev:.0f} на {c_n} в контроле")
                continue
            ovr.set_custom_campaign_status(tenant, cid, "paused")
            actions.append(
                f"поставил на паузу «{conf.get('title', cid)}»: цель {t_rate:.1%} "
                f"({t_hit}/{t_n} доставленных) против контроля {c_rate:.1%} "
                f"({c_hit}/{c_n}) за {days}д - прироста нет")


def run_tenant(ch, tenant: str) -> list[str]:
    actions: list[str] = []
    for fn in (launch_missing, top_up, evaluate):
        try:
            fn(ch, tenant, actions)
        except Exception as exc:  # noqa: BLE001 - один блок не валит мозг
            actions.append(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
            print(f"[brain] {tenant}: {fn.__name__} failed: {exc}", flush=True)
    return actions


def main() -> None:
    tenant = os.environ.get("TENANT_ID", "").strip()
    if not tenant:
        raise SystemExit("нужен TENANT_ID")
    ch = _ch()
    actions = run_tenant(ch, tenant)
    for a in actions:
        print(f"[brain] {tenant}: {a}", flush=True)
    if not actions:
        print(f"[brain] {tenant}: nothing to do", flush=True)
        return

    to = os.environ.get("PLATFORM_ALERT_EMAIL", "").strip()
    if not to:
        return
    from saas_senders import (EmailConfig, MessagingConfig, send_email,
                              tenant_configs)
    e, _m = tenant_configs(tenant, EmailConfig.from_env(),
                           MessagingConfig.from_env())
    if not (e.resend_api_key and e.email_from):
        return
    body = (f"Привет.\n\nЧто автопилот сделал сегодня для {tenant}:\n\n"
            + "\n".join(f"- {a}" for a in actions)
            + "\n\nВсе касания по-прежнему идут через предохранители "
            "(тихие часы, частотные лимиты, подавления, контрольная группа).")
    ok, detail = send_email(to, "Автопилот: действия за день", body, e)
    print(f"[brain] {tenant}: report to={to} sent={ok} {detail}", flush=True)


if __name__ == "__main__":
    main()
