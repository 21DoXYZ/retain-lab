"""Сегмент аудитории: широкие фильтры -> SQL по user_actions (+фичи).

Одно определение фильтра питает и превью («сколько людей попадёт»), и
снапшот-зачисление ручной кампании - расхождение между обещанным и
зачисленным исключено по построению.

Поля фильтра (все опциональны, действует И):
  stages            список стадий (ACTIVATE..MONITOR)
  status            paying | trial | free
  plan_id           точный план из биллинга
  online            true - на сайте прямо сейчас (< 3 мин)
  seen_within_days  активны за N дней
  not_seen_days     МОЛЧАТ дольше N дней (спящие; никогда не виденные тоже)
  signup_within_days / signup_older_days   возраст аккаунта
  mrr_min / mrr_max churn_min / churn_max intent_min / intent_max
  ltv_min           деньги и скоры
  gens_min / gens_max   ценные действия за всё время (0..0 = ни разу)
  country           ISO-код страны из гео сниппета

Числа валидируются и инлайнятся (float/int - инъекция невозможна), строки
уходят биндингами {sgN:String} формата q() борда.
"""

from __future__ import annotations

ONLINE_S = 180
STAGES = ("ACTIVATE", "CONVERT", "UPGRADE", "SAVE", "DUNNING", "WINBACK", "MONITOR")

# user_actions не несёт first_seen/страну/генерации за всё время - это фичи
AUDIENCE_FROM = (
    "FROM user_actions ua "
    "LEFT JOIN user_event_features f "
    "ON ua.tenant_id = f.tenant_id AND ua.identity_id = f.identity_id"
)


def _num(raw, lo: float, hi: float) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


# ── Фильтр по типу контакта ──────────────────────────────────────────────────
# Один источник правды для «есть ли у юзера такой контакт»: питает и движок
# сегментов (кампании), и список юзеров, и превью достижимости. Требует в scope
# биндинг {t:String} и колонки user_actions (email_norm, client_user_id,
# stripe_customer_id) - alias задаётся вызывающим ("ua" в сегменте, "" в списке).
CONTACT_TOKENS = ("email", "inapp", "whatsapp", "telegram", "sms", "phone")


def contact_expr(token: str, alias: str = "ua", consent: bool = False) -> str | None:
    """SQL «у юзера есть контакт типа token». None - незнакомый токен."""
    p = f"{alias}." if alias else ""
    cc = " AND consent = 1" if consent else ""
    if token == "email":
        return f"{p}email_norm != ''"
    if token == "inapp":
        return f"{p}client_user_id != ''"
    if token in ("whatsapp", "telegram", "sms", "viber"):
        return (f"{p}client_user_id != '' AND {p}client_user_id IN "
                f"(SELECT client_user_id FROM contacts_current "
                f"WHERE tenant_id = {{t:String}} AND channel = '{token}'{cc})")
    if token == "phone":
        # любой телефон: whatsapp/sms контакт с согласием ИЛИ номер из Stripe
        return (f"({p}client_user_id IN (SELECT client_user_id FROM contacts_current "
                f"WHERE tenant_id = {{t:String}} AND channel IN ('whatsapp', 'sms'){cc}) "
                f"OR {p}stripe_customer_id IN (SELECT customer_id FROM stripe_customers "
                f"WHERE tenant_id = {{t:String}} AND phone != ''))")
    return None


def any_contact_expr(alias: str = "ua") -> str:
    """Достижим хоть каким-то каналом (для фильтра «нет контакта» = NOT этого)."""
    exprs = [contact_expr(t, alias, False)
             for t in ("email", "inapp", "phone", "telegram")]
    return "(" + " OR ".join(e for e in exprs if e) + ")"


def contact_conditions(tokens, no_contact: bool = False,
                       consent: bool = False, alias: str = "ua"):
    """(conds, unknown_tokens). Выбранные типы объединяются ИЛИ (широко: есть
    ЛЮБОЙ из отмеченных); no_contact добавляет «недостижим ничем»."""
    conds: list[str] = []
    toks = tokens if isinstance(tokens, (list, tuple)) else (
        [t for t in str(tokens or "").split(",") if t] if tokens else [])
    valid = [t for t in toks if t in CONTACT_TOKENS]
    unknown = [t for t in toks if t not in CONTACT_TOKENS]
    if valid:
        exprs = [contact_expr(t, alias, consent) for t in valid]
        conds.append("(" + " OR ".join(e for e in exprs if e) + ")")
    if no_contact:
        conds.append("NOT " + any_contact_expr(alias))
    return conds, unknown


def build(flt: dict) -> tuple[list[str], dict, list[str]]:
    """(условия SQL, строковые параметры, что не поняли).

    Непонятые куски НЕ игнорируются молча - имя поля возвращается в unknown,
    и превью честно скажет «этот фильтр не применён»."""
    flt = flt or {}
    conds: list[str] = []
    params: dict = {}
    unknown: list[str] = []

    stages = [s for s in (flt.get("stages") or []) if s in STAGES]
    if flt.get("stages") and not stages:
        unknown.append("stages")
    if stages:
        quoted = ", ".join(f"'{s}'" for s in stages)   # белый список - безопасно
        conds.append(f"ua.stage IN ({quoted})")

    status = str(flt.get("status") or "")
    if status == "paying":
        conds.append("ua.sub_status IN ('active', 'past_due')")
    elif status == "trial":
        conds.append("ua.sub_status = 'trialing'")
    elif status == "free":
        conds.append("ua.sub_status NOT IN ('active', 'past_due', 'trialing')")
    elif status:
        unknown.append("status")

    if flt.get("plan_id"):
        conds.append("ua.plan_id = {sg_plan:String}")
        params["sg_plan"] = str(flt["plan_id"])[:120]

    if flt.get("online"):
        conds.append("toUnixTimestamp(ua.last_seen) > 0 "
                     f"AND dateDiff('second', ua.last_seen, now()) < {ONLINE_S}")

    seen = _num(flt.get("seen_within_days"), 1, 365)
    if seen is not None:
        conds.append("toUnixTimestamp(ua.last_seen) > 0 "
                     f"AND ua.last_seen >= now() - INTERVAL {int(seen)} DAY")
    elif flt.get("seen_within_days") is not None:
        unknown.append("seen_within_days")

    quiet = _num(flt.get("not_seen_days"), 1, 365)
    if quiet is not None:
        # молчат дольше N дней; никогда не виденные - тоже молчат
        conds.append("(toUnixTimestamp(ua.last_seen) = 0 "
                     f"OR ua.last_seen < now() - INTERVAL {int(quiet)} DAY)")
    elif flt.get("not_seen_days") is not None:
        unknown.append("not_seen_days")

    young = _num(flt.get("signup_within_days"), 1, 3650)
    if young is not None:
        conds.append("toUnixTimestamp(f.first_seen) > 0 "
                     f"AND f.first_seen >= now() - INTERVAL {int(young)} DAY")
    old = _num(flt.get("signup_older_days"), 1, 3650)
    if old is not None:
        conds.append("toUnixTimestamp(f.first_seen) > 0 "
                     f"AND f.first_seen < now() - INTERVAL {int(old)} DAY")

    for key, col, lo, hi in (
            ("mrr_min", "toFloat64(ua.mrr)", 0, 1e6),
            ("mrr_max", "toFloat64(ua.mrr)", 0, 1e6),
            ("churn_min", "coalesce(ua.p_churn, 0)", 0, 1),
            ("churn_max", "coalesce(ua.p_churn, 0)", 0, 1),
            ("intent_min", "coalesce(ua.buy_intent, 0)", 0, 1),
            ("intent_max", "coalesce(ua.buy_intent, 0)", 0, 1),
            ("ltv_min", "coalesce(ua.ltv_estimate, 0)", 0, 1e7),
            ("gens_min", "coalesce(f.generations_total, 0)", 0, 1e7),
            ("gens_max", "coalesce(f.generations_total, 0)", 0, 1e7),
            ("tickets_min", "coalesce(f.support_tickets_30d, 0)", 0, 1e4),
            ("bugs_min", "coalesce(f.bug_reports_30d, 0)", 0, 1e4)):
        v = _num(flt.get(key), lo, hi)
        if v is not None:
            op = ">=" if key.endswith("_min") else "<="
            conds.append(f"{col} {op} {v}")
        elif flt.get(key) is not None:
            unknown.append(key)

    country = str(flt.get("country") or "").strip().upper()
    if country:
        if len(country) == 2 and country.isalpha():
            conds.append(f"f.geo_country = '{country}'")
        else:
            unknown.append("country")

    # Сегменты застревания (экран «Запуски»): где человек встал в воронке.
    pmin = _num(flt.get("projects_min"), 0, 1e6)
    if pmin is not None:
        conds.append(f"coalesce(f.projects_total, 0) >= {int(pmin)}")
    if flt.get("saw_pricing"):
        # упёрся в пейвол или смотрел цены - покупка была в голове
        conds.append("(coalesce(f.paywall_views, 0) > 0 OR coalesce(f.pricing_visits, 0) > 0)")
    if flt.get("no_download"):
        # получил результат, но не забрал его (окно фичи - 14 дней)
        conds.append("coalesce(f.downloads_14d, 0) = 0")

    # тип контакта: широкий фильтр «кому вообще можно написать и как»
    c_conds, c_unknown = contact_conditions(
        flt.get("contacts"), bool(flt.get("no_contact")),
        bool(flt.get("contact_consent")))
    conds += c_conds
    if c_unknown:
        unknown.append("contacts")

    return conds, params, unknown


def audience_sql(conds: list[str], limit: int = 0) -> str:
    """Полный SELECT сегмента: кто попадёт и достижим ли он письмом."""
    where = " AND ".join(["ua.tenant_id = {t:String}"] + conds)
    tail = f" LIMIT {int(limit)}" if limit else ""
    return (
        "SELECT ua.identity_id, ua.stage, ua.email_norm, ua.client_user_id "
        f"{AUDIENCE_FROM} WHERE {where} ORDER BY ua.value_at_stake DESC{tail}"
    )


MAX_STEPS = 5


def validate_steps(raw_steps: list) -> tuple[list, str]:
    """Шаги ручной кампании -> формат движка. ([], reason) при браке.

    v1 каналы: email и in-app - у них не нужен consent-контакт (email уже
    есть, in-app живёт на сниппете). Тире-правило бренда зашито кодом."""
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        return [], "steps_count"
    out = []
    for i, s in enumerate(raw_steps):
        if not isinstance(s, dict):
            return [], f"step_{i}_invalid"
        action = str(s.get("action") or "email")
        if action not in ("email", "inapp"):
            return [], f"step_{i}_channel"
        subject = str(s.get("subject") or "").strip()[:200]
        body_t = str(s.get("body") or "").strip()[:4000]
        if not subject or (action == "email" and not body_t):
            return [], f"step_{i}_empty"
        try:
            delay = float(s.get("delay_h") or 0)
        except (TypeError, ValueError):
            return [], f"step_{i}_delay"
        if not 0 <= delay <= 720:
            return [], f"step_{i}_delay"
        step = {"action": action, "delay_h": delay,
                "subject": subject.replace("—", "-").replace("–", "-"),
                "body": body_t.replace("—", "-").replace("–", "-")}
        # локализованные версии текста: тик подставит их юзерам с этой
        # локалью (campaign_tick.apply_locale), остальным уйдёт основная
        for lf in ("subject_ru", "body_ru"):
            if s.get(lf):
                step[lf] = (str(s[lf]).strip()[:4000]
                            .replace("—", "-").replace("–", "-"))
        if s.get("cta_label"):
            step["cta_label"] = str(s["cta_label"]).strip()[:80]
        if s.get("cta_url"):
            url = str(s["cta_url"]).strip()[:500]
            if not url.startswith(("https://", "http://", "{{")):
                return [], f"step_{i}_cta_url"
            step["cta_url"] = url
        out.append(step)
    return out, ""


def describe(flt: dict) -> str:
    """Человеческое описание сегмента - хранится в кампании, видно на экране."""
    parts = []
    if flt.get("stages"):
        parts.append("stage " + "/".join(flt["stages"]))
    if flt.get("status"):
        parts.append(str(flt["status"]))
    if flt.get("plan_id"):
        parts.append(f"plan {flt['plan_id']}")
    if flt.get("online"):
        parts.append("online now")
    if flt.get("seen_within_days"):
        parts.append(f"active {flt['seen_within_days']}d")
    if flt.get("not_seen_days"):
        parts.append(f"quiet {flt['not_seen_days']}d+")
    if flt.get("signup_within_days"):
        parts.append(f"joined <{flt['signup_within_days']}d")
    if flt.get("signup_older_days"):
        parts.append(f"joined >{flt['signup_older_days']}d")
    for k in ("mrr_min", "mrr_max", "churn_min", "churn_max",
              "intent_min", "intent_max", "ltv_min", "gens_min", "gens_max",
              "tickets_min", "bugs_min"):
        if flt.get(k) is not None:
            parts.append(f"{k}={flt[k]}")
    if flt.get("country"):
        parts.append(str(flt["country"]).upper())
    if flt.get("projects_min") is not None:
        parts.append(f"projects>={int(float(flt['projects_min']))}")
    if flt.get("saw_pricing"):
        parts.append("saw pricing/paywall")
    if flt.get("no_download"):
        parts.append("no download")
    toks = flt.get("contacts")
    toks = toks if isinstance(toks, (list, tuple)) else (
        [t for t in str(toks or "").split(",") if t] if toks else [])
    valid = [t for t in toks if t in CONTACT_TOKENS]
    if valid:
        tag = "has " + "/".join(valid)
        if flt.get("contact_consent"):
            tag += " (consented)"
        parts.append(tag)
    if flt.get("no_contact"):
        parts.append("no contact")
    return ", ".join(parts) or "all users"
