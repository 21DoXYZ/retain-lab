"""SaaS-раннер кампаний K1-K5 (Phase 4, v1): стадия -> цепочка -> касания.

Один тик (идемпотентный, крон — Phase 6):
  1. ENROLL — юзеры user_actions в entry_stage кампании, не заходившие в неё
     последние 30 дней; 10% (md5-детерминированный holdout) — контроль: шаги
     не исполняются, конверсия сравнивается в uplift-отчёте.
  2. EXECUTE — у активных enrollment'ов исполняются все шаги, чей срок
     (enrolled_at + delay_h) наступил: email (saas_senders, dry-run дефолт) или
     offer (issue.py: гигиена+лог offers_issued). Контроль двигается по шагам
     молча.
  3. EXIT — стадия сменилась -> exited (атрибуция цели — Phase 6);
     шаги кончились -> done.

Отличие от плана REBUILD (§Phase 4, задокументированное): казино-движок chains/
привязан к casino_player_id UInt32 / player_features — SaaS-цепочки v1 живут в
этом лёгком раннере на общих слоях (user_actions/offers/holdout). Перенос в
automation.* с UI-конструктором — после EN-словаря SPA (остаток Phase 5).

Запуск:  docker compose ... run --rm --no-deps stripe-webhook python campaign_tick.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from executors import ExecConfig
from hygiene import holdout_split
from issue import issue_offer
from saas_senders import (EmailConfig, MessagingConfig, load_tenant_channels,
                          render, route_message, send_email, tenant_configs,
                          transient_failure)

CAMPAIGNS_PATH = Path(__file__).parent / "saas_campaigns.json"
REENTRY_DAYS = 30


def _now_dt() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


# ── чистая логика (тестируется без CH) ───────────────────────────────────────

def due_steps(steps: list[dict], enrolled_at: datetime, step_idx: int,
              now: datetime) -> list[int]:
    """Индексы созревших шагов - но НЕ вся отставшая цепочка сразу.

    Отдаём только группу шагов с ОДНОЙ И ТОЙ ЖЕ задержкой (их автор и задумывал
    как одновременные: баннер + письмо в момент несписания). Если раннер стоял
    сутки, следующая ступень уйдёт отдельным тиком, а не в ту же минуту:
    четыре письма подряд за минуту - это спам, а не цепочка.
    """
    out: list[int] = []
    first_delay = None
    for i in range(step_idx, len(steps)):
        delay = float(steps[i]["delay_h"])
        if enrolled_at + timedelta(hours=delay) > now:
            break
        if first_delay is None:
            first_delay = delay
        elif delay != first_delay:
            break
        out.append(i)
    return out


def next_step_time(steps: list[dict], enrolled_at: datetime, step_idx: int,
                   now: datetime | None = None) -> datetime:
    """Когда созреет следующий шаг.

    Обычно это «время входа + задержка шага». Но если предыдущий шаг ушёл с
    опозданием (раннер стоял), считаем от ФАКТА отправки, сохраняя задуманный
    интервал: между вторым и третьим письмом должно пройти два дня и после
    простоя тоже, иначе пауза схлопывается в ноль.
    """
    if step_idx >= len(steps):
        return enrolled_at
    planned = enrolled_at + timedelta(hours=float(steps[step_idx]["delay_h"]))
    if now is None or step_idx == 0:
        return planned
    gap_h = float(steps[step_idx]["delay_h"]) - float(steps[step_idx - 1]["delay_h"])
    return max(planned, now + timedelta(hours=max(gap_h, 0.0)))


def enroll_entry(camp: dict, stage: str, buy_intent: float,
                 churn: float) -> str:
    """Куда зачислять этого человека в эту кампанию. '' - не зачислять.

    Возвращает entry_stage для записи (по нему же считается выход). Две двери:
      • основная - человек в целевой стадии кампании И проходит сигнальные
        гейты (entry_gates: min_churn/min_buy_intent) - чтобы не тратить
        дорогую последовательность на тех, кому она не нужна;
      • also_enroll - сигнал важнее стадии: горячий на прайсинге (высокий
        buy_intent) плательщик из соседней стадии заслуживает апгрейд-толчок,
        а не общую рассылку. entry_stage для него - его СОБСТВЕННАЯ стадия
        (по ней и выйдет), цель кампании считается своим окном.
    """
    gates = camp.get("entry_gates") or {}
    if stage == camp["entry_stage"]:
        if churn < float(gates.get("min_churn", 0)):
            return ""
        if buy_intent < float(gates.get("min_buy_intent", 0)):
            return ""
        return stage
    ae = camp.get("also_enroll") or {}
    if (stage in (ae.get("from_stages") or [])
            and buy_intent >= float(ae.get("buy_intent_min", 2))):
        return stage
    return ""


def exit_status(current_stage: str, entry_stage: str, step_idx: int,
                n_steps: int) -> str | None:
    """None = остаётся active."""
    if current_stage != entry_stage:
        return "exited"
    if step_idx >= n_steps:
        return "done"
    return None


INAPP_COLUMNS = ["tenant_id", "message_id", "client_user_id", "identity_id",
                 "campaign_id", "step_idx", "title", "body", "cta_label",
                 "cta_url", "entry_stage", "kind", "expires_at", "created_at"]


MAX_SEND_RETRIES = 3

# ЧАСТОТНЫЙ ПРЕДОХРАНИТЕЛЬ. Главная причина отписок - не содержание письма, а
# их количество: около 44% отписавшихся называют частоту первой причиной.
# Ни одна отдельная кампания не может её нарушить, потому что она не знает о
# других: цепочка видит только свои шаги. Поэтому лимит стоит НАД кампаниями.
MAX_TOUCHES_PER_DAY = 1
MAX_TOUCHES_PER_WEEK = 3

# Дуннинг - исключение и единственное. Это не рассылка, а сообщение о том, что
# у человека сломалась оплата: молчать про это ради красивой частоты нельзя.
FREQ_EXEMPT = ("K3_payment_recovery",)

# ТИХИЕ ЧАСЫ. Ночное промо-сообщение раздражает везде, а кое-где оно ещё и
# незаконно: в ОАЭ промо разрешено только с 07:00 до 21:00 местного времени
# (политика TDRA о нежелательных электронных сообщениях). Часовой пояс - в
# tenants.json ("timezone": "Asia/Dubai"); без него берём UTC и НЕ угадываем.
# Дуннинг - сервисное сообщение о сломанной оплате, ограничение не про него.
QUIET_START, QUIET_END = 21, 7          # [21:00, 07:00) - молчим


def quiet_hours_block(campaign_id: str, now_utc: datetime, tz_name: str,
                      identity: str = "") -> str:
    """Можно ли слать промо СЕЙЧАС по местному времени тенанта. '' - можно.

    После тихих часов - персональный джиттер до 90 минут (детерминированный
    по identity): иначе всё, что созрело ночью, уходит залпом ровно в 07:00 -
    спайк для доставляемости и для саппорта клиента.
    """
    if campaign_id in FREQ_EXEMPT:
        return ""
    try:
        from zoneinfo import ZoneInfo
        local = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
        local = local.astimezone(ZoneInfo(tz_name or "UTC"))
    except Exception:                    # кривая зона в конфиге - не роняем тик
        local = now_utc
    if local.hour >= QUIET_START or local.hour < QUIET_END:
        return "quiet_hours"
    if identity and local.hour == QUIET_END:
        import hashlib
        jitter_min = int(hashlib.md5(identity.encode()).hexdigest()[:6], 16) % 90
        if local.minute < jitter_min:
            return "quiet_hours"
    return ""


# ── A/B варианты шага ────────────────────────────────────────────────────────
# Шаг может нести variants: [{subject, body, cta_label?, cta_url?}, ...] -
# каждому юзеру достаётся СВОЙ вариант, детерминированно (один и тот же
# навсегда: человек не должен видеть письмо A, а ресенд - письмо B).
# variants_off=true (ставит автопобедитель) - сплит выключен, текст шага уже
# заменён на победителя через overrides.

def pick_variant(identity: str, campaign_id: str, step_idx: int, n: int) -> int:
    """Стабильный индекс варианта для юзера. n<=1 - вариантов нет."""
    if n <= 1:
        return 0
    import hashlib
    seed = f"{campaign_id}:{step_idx}:{identity}".encode()
    return int(hashlib.md5(seed).hexdigest()[:8], 16) % n


def apply_variant(step: dict, identity: str, campaign_id: str,
                  step_idx: int) -> dict:
    """Шаг с наложенным вариантом юзера. Без вариантов - шаг как есть."""
    variants = step.get("variants") or []
    if not variants or step.get("variants_off"):
        return step
    k = pick_variant(identity, campaign_id, step_idx, len(variants))
    v = variants[k] or {}
    out = dict(step)
    for f in ("subject", "body", "cta_label", "cta_url"):
        if v.get(f) is not None:
            out[f] = str(v[f])
    out["_variant"] = k
    return out


SEND_TIME_MAX_WAIT_H = 20.0   # дольше письмо не ждёт «лучшего часа» никогда


def send_time_block(pref_hour: int | None, tz_name: str, now_utc: datetime,
                    matured_h: float) -> bool:
    """Отложить ли письмо до ЛИЧНОГО активного часа юзера. True - ждём.

    Мы знаем, в какой час человек обычно живёт в продукте (local_hour из
    сниппета). Письмо, пришедшее в его активный час, открывается стабильно
    лучше письма «когда созрел шаг». Окно щедрое (час до и час после), а
    ждать дольше SEND_TIME_MAX_WAIT_H нельзя: лучше неидеальный час, чем
    просроченное касание. Нет данных о часе - шлём как раньше.

    Дуннинг и триггеры сюда НЕ заходят: там момент важнее часа.
    """
    if pref_hour is None or matured_h >= SEND_TIME_MAX_WAIT_H:
        return False
    try:
        from zoneinfo import ZoneInfo
        local = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
        local_hour = local.astimezone(ZoneInfo(tz_name or "UTC")).hour
    except Exception:                    # кривая зона - не мешаем отправке
        return False
    diff = (local_hour - int(pref_hour)) % 24
    return not (diff <= 1 or diff == 23)


def frequency_block(campaign_id: str, sent_24h: int, sent_7d: int) -> str:
    """Можно ли писать этому человеку сейчас. '' - можно, иначе причина.

    Отдельная функция, потому что это правило про ЧЕЛОВЕКА, а не про кампанию,
    и его надо проверять одинаково из любой цепочки.
    """
    if campaign_id in FREQ_EXEMPT:
        return ""
    if sent_24h >= MAX_TOUCHES_PER_DAY:
        return "freq_cap_day"
    if sent_7d >= MAX_TOUCHES_PER_WEEK:
        return "freq_cap_week"
    return ""


def branch_skip(step: dict, campaign_id: str, email: str,
                engaged: set) -> str:
    """Пропустить ли шаг по поведению получателя. '' - слать.

    skip_if_opened_step / skip_if_clicked_step: N - шаг-«догонялка» нужен
    только тем, кто НЕ открыл/кликнул шаг N. Открывшему слать то же самое
    второй раз - это спам, который поднимает отписки.
    """
    mail = str(email or "").lower()
    if not mail:
        return ""
    n = step.get("skip_if_opened_step")
    if n is not None and (
            (campaign_id, int(n), mail, "opened") in engaged
            or (campaign_id, int(n), mail, "clicked") in engaged):
        return f"opened_step_{int(n)}"
    n = step.get("skip_if_clicked_step")
    if n is not None and (campaign_id, int(n), mail, "clicked") in engaged:
        return f"clicked_step_{int(n)}"
    return ""


def _retry_count(client, tenant: str, campaign_id: str, identity: str,
                 step_idx: int) -> int:
    """Сколько раз этот шаг уже откладывали из-за сбоя провайдера."""
    rows = client.query(
        "SELECT count() FROM retention.campaign_send_log "
        "WHERE tenant_id = %(t)s AND campaign_id = %(c)s AND identity_id = %(i)s "
        "AND step_idx = %(s)s AND status = 'retry'",
        parameters={"t": tenant, "c": campaign_id, "i": identity, "s": step_idx},
    ).result_rows
    return int(rows[0][0]) if rows else 0


def _safe_cta(url: str) -> str:
    """Ссылка кнопки баннера: https/относительная, никаких javascript: и
    сырых плейсхолдеров. Пустая строка = кнопки не будет - это лучше кнопки,
    ведущей в '{{app_url}}' или исполняющей код на сайте клиента."""
    url = str(url or "").strip()
    if not url or "{{" in url:
        return ""
    low = url.lower()
    if low.startswith(("https://", "http://")) or url.startswith("/"):
        return url
    return ""


def inapp_row(tenant: str, camp: dict, step: dict, step_idx: int, identity: str,
              cuid: str, now: datetime, ctx: dict) -> list:
    """Строка inapp_inbox для показа виджетом. message_id детерминированный -
    повторный тик по тому же шагу схлопнется Replacing'ом, не задвоив баннер.

    Тексты чистятся от сырых плейсхолдеров: баннер с «{{telegram_connect_url}}»
    в теле - артефакт шаблона на экране живого человека."""
    ttl = timedelta(days=float(step.get("ttl_days", 7)))
    import re as _re
    strip = lambda t: _re.sub(r"\{\{\w+\}\}", "", t).strip()  # noqa: E731
    return [tenant, f"{camp['campaign_id']}:{step_idx}:{identity}", cuid, identity,
            camp["campaign_id"], step_idx,
            strip(render(step.get("subject", ""), ctx)),
            strip(render(step["body"], ctx)),
            strip(render(step.get("cta_label", "Open"), ctx)) or "Open",
            _safe_cta(render(step.get("cta_url", "{{app_url}}"), ctx)),
            camp["entry_stage"],
            # kind: 'nps' рисуется виджетом как шкала 0-10, не баннер с кнопкой
            str(step.get("survey") or "banner"),
            now + ttl, now]


def resolve_autopilot(conf: dict, tenant_overrides: dict) -> bool:
    """Выключатель автопилота. Явный ключ autopilot в tenants.json (пишет UI,
    POST /saas/campaigns/autopilot) важнее захардкоженного в saas_campaigns.json:
    контент кампаний живёт в git, а рубильник - в рантайме."""
    if "autopilot" in tenant_overrides:
        return bool(tenant_overrides["autopilot"])
    return bool(conf.get("autopilot"))


def effective_configs(conf: dict, email_cfg: "EmailConfig",
                      exec_cfg: "ExecConfig") -> tuple["EmailConfig", "ExecConfig"]:
    """Draft-approval гейт (REBUILD §Phase 6): пока autopilot=false в конфиге
    тенанта, отправки принудительно dry-run — даже если env включил боевой режим.
    Двойной fail-closed: снять можно только явным autopilot=true в конфиге."""
    if conf.get("autopilot"):
        return email_cfg, exec_cfg
    from dataclasses import replace
    if not email_cfg.dry_run or not exec_cfg.dry_run:
        print("[campaigns] autopilot=false -> forced dry-run", flush=True)
    return replace(email_cfg, dry_run=True), replace(exec_cfg, dry_run=True)


# ── I/O ──────────────────────────────────────────────────────────────────────

def _save(client, tenant: str, camp_id: str, row: dict) -> None:
    # Владелец мог снять человека с кампании ИЗ КАРТОЧКИ, пока тик шёл по
    # снапшоту начала прогона. Save с поздним updated_at молча воскресил бы
    # зачисление - ручной exit всегда важнее машинного прогресса.
    if row.get("status") == "active":
        cur = client.query(
            "SELECT argMax(status, updated_at) FROM retention.campaign_enrollments "
            "WHERE tenant_id = %(t)s AND campaign_id = %(c)s AND identity_id = %(i)s",
            parameters={"t": tenant, "c": camp_id,
                        "i": row["identity_id"]}).result_rows
        if cur and str(cur[0][0]) == "exited":
            return
    now = _fmt(_now_dt())
    client.insert(
        "retention.campaign_enrollments",
        [[tenant, camp_id, row["identity_id"], row["control"], row["entry_stage"],
          row["step_idx"], _fmt(row["next_step_at"]), row["status"],
          _fmt(row["enrolled_at"]), now]],
        column_names=["tenant_id", "campaign_id", "identity_id", "control",
                      "entry_stage", "step_idx", "next_step_at", "status",
                      "enrolled_at", "updated_at"],
    )


def _log_send(client, tenant: str, camp_id: str, identity: str, step_idx: int,
              action: str, detail: str, status: str, reason: str = "",
              provider_id: str = "") -> None:
    client.insert(
        "retention.campaign_send_log",
        [[tenant, camp_id, identity, step_idx, action, detail, status, reason,
          provider_id, _fmt(_now_dt())]],
        column_names=["tenant_id", "campaign_id", "identity_id", "step_idx",
                      "action", "detail", "status", "reason", "provider_id", "ts"],
    )


# Отказы-«подожди» (тихие часы, частота, окно ретрая) повторяются КАЖДЫЙ тик,
# пока шаг не созреет заново: 96 тиков за ночь писали 96 одинаковых строк на
# человека - лог раздувался тысячами, а «удержано предохранителями» на
# дашборде превращалось в бессмысленное число. Пишем такой отказ раз в сутки.
RETRY_REASONS = ("quiet_hours", "freq_cap_day", "freq_cap_week",
                 "awaiting_retry", "warmup_cap")

# ПРОГРЕВ ДОМЕНА. Свежий отправитель, у которого в первый день уходит сотня
# писем с нулевой историей - спам-паттерн для Gmail. Но темп зависит от того,
# КОМУ шлём: своим зарегистрированным юзерам (тёплая база, домен уже живёт на
# Google, IP у Resend прогретые) можно в разы быстрее, чем холодной базе.
# Режим - tenants.json email_warmup: 'safe' | 'fast' (деф.) | 'off'.
# Дуннинг (FREQ_EXEMPT) под потолок не попадает в любом режиме.
WARMUP_SCHEDULES = {
    "safe": ((2, 20), (4, 40), (7, 80), (14, 150)),     # холодная/чужая база
    "fast": ((1, 60), (3, 150), (7, 300)),              # свои юзеры (деф.)
}


def warmup_cap(days_since_first_send: int | None, mode: str = "fast") -> int:
    """Потолок писем в день. None (ещё ни одной отправки) = первый день.
    'off' - потолка нет вовсе (осознанный выбор владельца)."""
    if mode == "off":
        return 10_000
    schedule = WARMUP_SCHEDULES.get(mode, WARMUP_SCHEDULES["fast"])
    days = 0 if days_since_first_send is None else int(days_since_first_send)
    for upto, cap in schedule:
        if days < upto:
            return cap
    return 10_000                        # прогрев пройден


def _logged_retries_today(client, tenant: str) -> set:
    """Best-effort: не смогли прочитать - лог просто будет многословнее."""
    try:
        return {(r[0], int(r[1]), r[2], r[3]) for r in client.query(
            "SELECT campaign_id, step_idx, identity_id, reason "
            "FROM retention.campaign_send_log "
            "WHERE tenant_id = %(t)s AND status = 'rejected' "
            "AND reason IN %(rr)s AND ts >= today()",
            parameters={"t": tenant, "rr": list(RETRY_REASONS)}).result_rows
            if len(r) >= 4}
    except Exception:  # noqa: BLE001
        return set()


def tick(client, tenant: str) -> dict[str, int]:
    cfgs = json.loads(CAMPAIGNS_PATH.read_text())
    # тенант без git-блока живёт на универсальном каркасе _default
    conf = cfgs.get(tenant) or cfgs.get("_default")
    if not conf:
        raise SystemExit(f"нет кампаний для тенанта {tenant}")
    control_pct = int(conf.get("control_pct", 10))
    conf = {**conf, "autopilot": resolve_autopilot(conf, load_tenant_channels(tenant))}
    # правки текстов/таймингов из CRM (runtime, без деплоя)
    from overrides import (apply_ab_winners, load_tenant as load_overrides,
                           merge_campaign_conf)
    conf = merge_campaign_conf(conf, load_overrides(tenant))
    # победители A/B из knowledge - поверх (ручная правка владельца главнее)
    try:
        from knowledge import load as _kb_load
        conf = apply_ab_winners(conf, _kb_load(client, tenant, "ab_winners"))
    except Exception:  # noqa: BLE001 - без знаний живём на сплите
        pass
    email_cfg, exec_cfg = effective_configs(conf, EmailConfig.from_env(),
                                            ExecConfig.from_env())
    msg_cfg = MessagingConfig.from_env()
    if not conf.get("autopilot"):
        from dataclasses import replace as _replace
        msg_cfg = _replace(msg_cfg, dry_run=True)
    # идентичность отправителя = бренд тенанта (from-домен, альфа-имя, бот)
    email_cfg, msg_cfg = tenant_configs(tenant, email_cfg, msg_cfg)
    # исполнитель бонусов = вебхук клиента из опросника (tenants.json)
    from executors import tenant_exec_config
    exec_cfg = tenant_exec_config(tenant, exec_cfg)
    # часовой пояс аудитории тенанта - для тихих часов; бот - для ссылок
    # подписки {{telegram_connect_url}} в письмах и баннерах
    _tch = load_tenant_channels(tenant)
    tenant_tz = str(_tch.get("timezone") or "UTC")
    tg_bot = str(_tch.get("telegram_bot_username") or "")
    wa_phone = str(_tch.get("wa_phone_display") or "")

    # Личный активный час юзера (send-time): мода local_hour из сниппета за
    # 30 дней + его таймзона. Нет данных - шлём по расписанию шага.
    pref_time: dict[str, tuple[int, str]] = {}
    try:
        for r in client.query(
            """
            SELECT identity_id,
                   topK(1)(JSONExtractInt(meta, 'local_hour'))[1],
                   topK(1)(JSONExtractString(meta, 'tz'))[1]
            FROM retention.saas_events_resolved
            WHERE tenant_id = %(t)s AND JSONHas(meta, 'local_hour')
              AND ts >= now() - INTERVAL 30 DAY
            GROUP BY identity_id
            """, parameters={"t": tenant}).result_rows:
            pref_time[r[0]] = (int(r[1]), str(r[2] or "UTC"))
    except Exception as exc:  # noqa: BLE001 - send-time опционален
        print(f"[tick] {tenant}: pref hours unavailable: {type(exc).__name__}",
              flush=True)

    # Дневной бюджет ЛИЧНОГО WhatsApp: сколько автокасаний номер ещё может
    # отправить сегодня. Считаем по логу (все wa-отправки суток), лимит -
    # wa_personal_daily_cap тенанта (деф. 20). Бан прилетает личному номеру
    # клиента - массовая рассылка отсюда невозможна ФИЗИЧЕСКИ, а не по
    # договорённости. Словарь мутируется сендером по мере отправок.
    if msg_cfg.wa_personal_tenant:
        wa_cap = int(_tch.get("wa_personal_daily_cap") or 20)
        wa_sent_today = int(client.query(
            "SELECT count() FROM retention.campaign_send_log "
            "WHERE tenant_id = %(t)s AND action = 'whatsapp' "
            "AND status = 'sent' AND ts >= today()",
            parameters={"t": tenant}).result_rows[0][0])
        from dataclasses import replace as _rep
        msg_cfg = _rep(msg_cfg,
                       wa_personal_budget={"left": max(0, wa_cap - wa_sent_today)})

    # Факты юзера для персональных плейсхолдеров ({{credits_left}}): остаток
    # кредитов из последнего списания, фолбэк - баланс из импорта юзеров.
    # Письмо «вы сожгли всё» с конкретным числом бьёт generic-текст всегда.
    user_facts: dict[str, dict] = {}
    try:
        for r in client.query(
            """
            SELECT identity_id, argMax(val, ts) FROM (
                SELECT identity_id, ts,
                       JSONExtractFloat(meta, 'balance_after') AS val
                FROM retention.saas_events_resolved
                WHERE tenant_id = %(t)s AND event_type = 'credit_spend'
                UNION ALL
                SELECT identity_id, ts,
                       JSONExtractFloat(meta, 'credits_balance') AS val
                FROM retention.saas_events_resolved
                WHERE tenant_id = %(t)s AND event_type = 'signup'
                  AND JSONHas(meta, 'credits_balance')
            ) GROUP BY identity_id
            """, parameters={"t": tenant}).result_rows:
            user_facts[r[0]] = {"credits_left": int(float(r[1] or 0))}
    except Exception as exc:  # noqa: BLE001 - факты опциональны, тик важнее
        print(f"[tick] {tenant}: user facts unavailable: {type(exc).__name__}",
              flush=True)

    def _user_ctx(cuid: str, identity: str = "") -> dict:
        """Плейсхолдеры, зависящие от КОНКРЕТНОГО человека. Ссылки подписки
        подписаны: голый id в ссылке позволял бы увести чужие уведомления."""
        out: dict = dict(user_facts.get(identity) or {})
        if not cuid:
            return out
        if tg_bot:
            from telegram_connect import connect_url as tg_url
            url = tg_url(tg_bot, tenant, cuid)
            if url:
                out["telegram_connect_url"] = url
        if wa_phone:
            from wa_templates import connect_url as wa_url
            url = wa_url(wa_phone, tenant, cuid)
            if url:
                out["whatsapp_connect_url"] = url
        return out
    now = _now_dt()
    stats = {"enrolled": 0, "control": 0, "steps": 0, "done": 0, "exited": 0}

    stages = {r[0]: (r[1], r[2], r[3], float(r[4] or 0), float(r[5] or 0))
              for r in client.query(
        "SELECT identity_id, stage, email_norm, client_user_id, "
        "coalesce(buy_intent, 0), coalesce(p_churn, 0) "
        "FROM retention.user_actions WHERE tenant_id = %(t)s",
        parameters={"t": tenant}).result_rows}

    # Прогрев: сколько email ещё можно сегодня. Возраст канала - дни с первой
    # РЕАЛЬНОЙ отправки; бюджет мутируется по мере отправок этого тика.
    email_budget = {"left": 10_000}
    try:
        row = client.query(
            "SELECT countIf(ts >= today()), "
            "  if(min(ts) > '1971-01-01', dateDiff('day', min(ts), now()), NULL) "
            "FROM retention.campaign_send_log "
            "WHERE tenant_id = %(t)s AND action = 'email' AND status = 'sent'",
            parameters={"t": tenant}).result_rows[0]
        sent_today = int(row[0] or 0)
        cap = warmup_cap(row[1] if row[1] is not None else None,
                         str(_tch.get("email_warmup") or "fast"))
        email_budget["left"] = max(0, cap - sent_today)
    except Exception as exc:  # noqa: BLE001 - без данных живём без прогрева
        print(f"[tick] {tenant}: warmup budget unavailable: {type(exc).__name__}",
              flush=True)

    # «подожди»-отказы уже записанные сегодня: повторно не логируем
    retry_logged = _logged_retries_today(client, tenant)

    def _log_retry(cid_, i_, identity_, channel_, subject_, reason_):
        key = (cid_, i_, identity_, reason_)
        if key in retry_logged:
            return
        retry_logged.add(key)
        _log_send(client, tenant, cid_, identity_, i_, channel_,
                  subject_, "rejected", reason_)

    # Подавление email: кому писать НЕЛЬЗЯ (отписался, пожаловался, баунс).
    # Fail-closed: сомнений нет - адрес в списке, значит письма не будет.
    suppressed = {r[0] for r in client.query(
        "SELECT address FROM retention.email_suppressions_current "
        "WHERE tenant_id = %(t)s", parameters={"t": tenant}).result_rows}

    # Сколько касаний человек уже получил - СО ВСЕХ кампаний сразу. Считаем
    # один раз за тик: отдельная цепочка не видит соседей и сама по себе
    # частоту не удержит.
    touches = {}
    for r in client.query(
        "SELECT identity_id, countIf(ts > now() - INTERVAL 1 DAY), "
        "       countIf(ts > now() - INTERVAL 7 DAY) "
        "FROM retention.campaign_send_log "
        "WHERE tenant_id = %(t)s AND status IN ('sent', 'dry_run') "
        "AND ts > now() - INTERVAL 7 DAY GROUP BY identity_id",
            parameters={"t": tenant}).result_rows:
        touches[r[0]] = (int(r[1]), int(r[2]))

    # контакты не-email каналов: (client_user_id, channel) -> (address, consent)
    contacts = {(r[0], r[1]): (r[2], int(r[3])) for r in client.query(
        "SELECT client_user_id, channel, address, consent "
        "FROM retention.contacts_current WHERE tenant_id = %(t)s",
        parameters={"t": tenant}).result_rows}

    # Следующая РЕАЛЬНАЯ попытка списания Stripe (из meta последнего
    # payment_failed). Дуннинг-догонялки шлём не раньше, чем за сутки до неё:
    # письмо «обновите карту» за 4 дня до ретрая - в никуда, за день - в точку.
    retry_at = {}
    for r in client.query(
        "SELECT identity_id, argMax(meta, ts) FROM retention.saas_events_resolved "
        "WHERE tenant_id = %(t)s AND event_type = 'billing.payment_failed' "
        "AND source = 'stripe' GROUP BY identity_id",
            parameters={"t": tenant}).result_rows:
        try:
            npa = json.loads(r[1] or "{}").get("next_payment_attempt")
            if npa:
                retry_at[r[0]] = datetime.fromtimestamp(int(npa), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

    # Открытия/клики писем: (campaign, step, email) - для ветвления шагов
    # (ресенд только неоткрывшим и т.п.). Вебхуки Resend уже пишут campaign+step.
    engaged = {(r[0], int(r[1]), str(r[2]).lower(), r[3]) for r in client.query(
        "SELECT campaign_id, step_idx, address, event_type "
        "FROM retention.email_events WHERE tenant_id = %(t)s "
        "AND event_type IN ('opened', 'clicked')",
        parameters={"t": tenant}).result_rows}

    for camp in conf["campaigns"]:
        if camp.get("_custom") and camp.get("status") == "paused":
            continue                      # владелец поставил ручную на паузу
        cid, steps = camp["campaign_id"], camp["steps"]
        # Кулдаун повторного входа СВОЙ у кампании: дуннинг обязан отработать
        # каждый новый несписанный платёж (2д), винбэк - наоборот, редкий (90д).
        reentry = int(camp.get("reentry_days", REENTRY_DAYS))

        enrolled = {r[0]: dict(zip(
            ["identity_id", "control", "entry_stage", "step_idx",
             "next_step_at", "status", "enrolled_at"], r)) for r in client.query(
            """
            SELECT identity_id, control, entry_stage, step_idx, next_step_at,
                   status, enrolled_at
            FROM retention.campaign_enrollments_current
            WHERE tenant_id = %(t)s AND campaign_id = %(c)s
              AND (status = 'active' OR enrolled_at >= now() - INTERVAL %(d)s DAY)
            """, parameters={"t": tenant, "c": cid, "d": reentry},
        ).result_rows}

        # 1. ENROLL
        for identity, (stage, _email, _cuid, _buy, _churn) in stages.items():
            if identity in enrolled:
                continue
            entry = enroll_entry(camp, stage, _buy, _churn)
            if not entry:
                continue
            control = holdout_split(tenant, cid, identity, control_pct)
            row = {"identity_id": identity, "control": 1 if control else 0,
                   "entry_stage": entry, "step_idx": 0,
                   "next_step_at": next_step_time(steps, now, 0),
                   "status": "active", "enrolled_at": now}
            _save(client, tenant, cid, row)
            enrolled[identity] = row
            stats["enrolled"] += 1
            stats["control"] += 1 if control else 0

        # 2. EXECUTE + 3. EXIT
        for identity, row in enrolled.items():
            if row["status"] != "active":
                continue
            enrolled_at = row["enrolled_at"] if isinstance(row["enrolled_at"], datetime) \
                else datetime.fromisoformat(str(row["enrolled_at"]))
            stage_now, email, cuid = stages.get(identity, ("", "", "", 0, 0))[:3]

            for i in due_steps(steps, enrolled_at, int(row["step_idx"]), now):
                # вариант юзера накладывается ДО всех веток: и email, и in-app,
                # и лестница каналов видят один и тот же текст его группы
                step = apply_variant(steps[i], identity, cid, i)
                retry_step = False
                try:
                    if not row["control"]:
                        if step["action"] in ("email", "message"):
                            # Ветвление по поведению: догонялка только тем, кто
                            # не открыл/не кликнул указанный шаг. Открывшему то
                            # же письмо второй раз - спам.
                            skip = branch_skip(step, cid, email, engaged)
                            if skip:
                                _log_send(client, tenant, cid, identity, i,
                                          step.get("channel", "email"),
                                          step.get("subject", ""), "skipped", skip)
                            elif (camp.get("align_retries")
                                    and float(step.get("delay_h", 0)) > 0
                                    and identity in retry_at
                                    and retry_at[identity].replace(tzinfo=None)
                                        - now > timedelta(hours=24)):
                                # Дуннинг-догонялка раньше, чем за сутки до
                                # РЕАЛЬНОГО ретрая Stripe, уходит в никуда:
                                # человеку не к чему действовать. Шаг дозреет
                                # в окне суток перед попыткой списания.
                                _log_retry(cid, i, identity,
                                           step.get("channel", "email"),
                                           step.get("subject", ""), "awaiting_retry")
                                retry_step = True
                            elif quiet_hours_block(cid, now, tenant_tz, identity):
                                # ночь у аудитории: шаг НЕ отработан, созреет
                                # утром. В ОАЭ ночное промо ещё и незаконно.
                                _log_retry(cid, i, identity,
                                           step.get("channel", "email"),
                                           step.get("subject", ""), "quiet_hours")
                                retry_step = True
                            elif (cid not in FREQ_EXEMPT
                                    and camp.get("entry_stage") != "TRIGGER"
                                    and not camp.get("manual_audience")
                                    and send_time_block(
                                        *(pref_time.get(identity) or (None, "")),
                                        now,
                                        (now - enrolled_at).total_seconds() / 3600
                                        - float(step.get("delay_h", 0)))):
                                # send-time: письмо подождёт ЛИЧНЫЙ активный час
                                # юзера (тихо, без спама в лог - шаг просто
                                # созреет на одном из следующих тиков)
                                retry_step = True
                            elif frequency_block(cid, *touches.get(identity, (0, 0))):
                                # Шаг НЕ отработан: он созреет снова, когда
                                # частота позволит. Иначе касание пропадало бы
                                # навсегда из-за соседней кампании.
                                _log_retry(cid, i, identity,
                                           step.get("channel", "email"),
                                           step.get("subject", ""),
                                           frequency_block(cid, *touches.get(identity, (0, 0))))
                                retry_step = True
                            else:
                                # ЛЕСТНИЦА КАНАЛОВ. Шаг может объявить
                                # channels: ["email", "whatsapp", ...] - идём по
                                # порядку, пока канал не доставит. Недоступный
                                # канал (нет адреса/согласия/шаблона) - к
                                # следующему; временный сбой - тот же канал на
                                # следующем тике. Раньше письмо в супрессии
                                # значило «никто не узнал о несписании».
                                channels = [str(c) for c in
                                            (step.get("channels")
                                             or [step.get("channel", "email")])]
                                counted = False
                                delivered = False
                                for channel in channels:
                                    if channel == "email":
                                        address, consent = email, 1
                                    else:
                                        # у Stripe-only юзера нет client_user_id -
                                        # ручной контакт лежит под identity
                                        address, consent = (
                                            contacts.get((cuid, channel))
                                            or contacts.get((identity, channel))
                                            or ("", 0))
                                    if not address:
                                        _log_send(client, tenant, cid, identity, i, channel,
                                                  step.get("subject", ""), "rejected", "no_contact")
                                        continue
                                    if channel == "email" and address.lower() in suppressed:
                                        _log_send(client, tenant, cid, identity, i, channel,
                                                  step.get("subject", ""), "rejected", "suppressed")
                                        continue
                                    if (channel == "email" and cid not in FREQ_EXEMPT
                                            and email_budget["left"] <= 0):
                                        # прогрев домена: дневной потолок исчерпан -
                                        # шаг ждёт завтрашнего бюджета (дуннинг
                                        # под прогрев не попадает)
                                        _log_retry(cid, i, identity, "email",
                                                   step.get("subject", ""), "warmup_cap")
                                        retry_step = True
                                        break
                                    if not consent:
                                        _log_send(client, tenant, cid, identity, i, channel,
                                                  step.get("subject", ""), "rejected", "no_consent")
                                        continue
                                    # счётчик частоты растёт при ПЕРВОЙ попытке
                                    # отправки: за один тик могут созреть два
                                    # шага, второй обязан увидеть первый
                                    if not counted:
                                        day, week = touches.get(identity, (0, 0))
                                        touches[identity] = (day + 1, week + 1)
                                        counted = True
                                    ok, detail = route_message(
                                        channel, address, step.get("subject", ""),
                                        step["body"], email_cfg, msg_cfg,
                                        {**_user_ctx(cuid, identity),
                                         # whatsapp шлёт ШАБЛОН по (кампания, шаг),
                                         # а не текст - ему нужен адрес шага
                                         "campaign_id": cid, "step_idx": i,
                                         "cta_label": step.get("cta_label", ""),
                                         "app_url": email_cfg.app_url,
                                         "card_update_url": email_cfg.card_update_url})
                                    if not ok and channel == "whatsapp":
                                        from whatsapp_cloud import should_suppress
                                        if should_suppress(detail):
                                            # человек запретил бизнесу писать себе:
                                            # fail-closed, как email-супрессии
                                            client.insert(
                                                "retention.contacts",
                                                [[tenant, cuid, "whatsapp", address,
                                                  0, now, now]],
                                                column_names=[
                                                    "tenant_id", "client_user_id",
                                                    "channel", "address", "consent",
                                                    "consent_ts", "updated_at"])
                                    if ok:
                                        # detail успешной отправки = id письма у
                                        # провайдера: по нему вебхуки доставки
                                        # находят это касание
                                        pid = detail if detail != "dry_run" else ""
                                        _log_send(client, tenant, cid, identity, i, channel,
                                                  step.get("subject", ""),
                                                  "dry_run" if detail == "dry_run" else "sent",
                                                  "", pid)
                                        if channel == "email" and detail != "dry_run":
                                            email_budget["left"] -= 1
                                        delivered = True
                                        break
                                    # Провайдер лёг или придушил лимитом - касание
                                    # НЕ отработано: тот же канал повторит следующий
                                    # тик. Иначе письмо о несписании терялось бы
                                    # навсегда из-за минутного 503.
                                    if (transient_failure(detail)
                                            and _retry_count(client, tenant, cid,
                                                             identity, i) < MAX_SEND_RETRIES):
                                        _log_send(client, tenant, cid, identity, i, channel,
                                                  step.get("subject", ""), "retry", detail)
                                        retry_step = True
                                        break
                                    # постоянный отказ канала - пробуем следующий
                                    _log_send(client, tenant, cid, identity, i, channel,
                                              step.get("subject", ""), "rejected", detail)
                                del delivered   # исход целиком в send_log
                        elif step["action"] == "inapp":
                            # Баннер в продукте тенанта - касание, поэтому уважает
                            # dry-run (autopilot=false -> в очередь не пишем).
                            if not cuid:
                                _log_send(client, tenant, cid, identity, i, "inapp",
                                          step.get("subject", ""), "rejected",
                                          "no_client_user_id")
                            elif email_cfg.dry_run:
                                _log_send(client, tenant, cid, identity, i, "inapp",
                                          step.get("subject", ""), "dry_run", "")
                            else:
                                ctx = {"app_url": email_cfg.app_url,
                                       "card_update_url": email_cfg.card_update_url,
                                       **_user_ctx(cuid, identity)}
                                client.insert(
                                    "retention.inapp_inbox",
                                    [inapp_row(tenant, camp, step, i, identity,
                                               cuid, now, ctx)],
                                    column_names=INAPP_COLUMNS)
                                _log_send(client, tenant, cid, identity, i, "inapp",
                                          step.get("subject", ""), "queued", "")
                        elif step["action"] == "offer" and not step.get("offer_id"):
                            # оффер не привязан (свежий тенант до опросника)
                            _log_send(client, tenant, cid, identity, i, "offer",
                                      "", "rejected", "no_offer_bound")
                        elif step["action"] == "offer":
                            status, reason = issue_offer(
                                client, tenant, identity, step["offer_id"],
                                campaign_id=cid, control_pct=0, cfg=exec_cfg)
                            _log_send(client, tenant, cid, identity, i, "offer",
                                      step["offer_id"], status, reason)
                        stats["steps"] += 1
                except Exception as exc:  # noqa: BLE001
                    # Один кривой контакт или моргнувший провайдер не имеют
                    # права уронить прогон остальных юзеров тенанта.
                    _log_send(client, tenant, cid, identity, i,
                              step.get("channel", step.get("action", "")),
                              step.get("subject", ""), "rejected",
                              f"error:{type(exc).__name__}")
                if retry_step:
                    break   # шаг остаётся созревшим - повторим на след. тике
                row["step_idx"] = i + 1

            if camp.get("manual_audience"):
                # аудиторию собрал владелец руками - смена стадии не выход,
                # человек покидает кампанию только пройдя все шаги
                status = "done" if int(row["step_idx"]) >= len(steps) else None
            else:
                status = exit_status(stage_now, row["entry_stage"],
                                     int(row["step_idx"]), len(steps))
            if status:
                row["status"] = status
                stats[status if status in ("done", "exited") else "done"] += 1
            row["next_step_at"] = next_step_time(steps, enrolled_at,
                                                 int(row["step_idx"]), now)
            row["enrolled_at"] = enrolled_at
            _save(client, tenant, cid, row)

    return stats


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
    stats = tick(client, tenant)
    print(f"[campaigns] tenant={tenant} " +
          " ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
