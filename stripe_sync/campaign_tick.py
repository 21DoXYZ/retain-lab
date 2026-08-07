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
                 "cta_url", "entry_stage", "expires_at", "created_at"]


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


def inapp_row(tenant: str, camp: dict, step: dict, step_idx: int, identity: str,
              cuid: str, now: datetime, ctx: dict) -> list:
    """Строка inapp_inbox для показа виджетом. message_id детерминированный -
    повторный тик по тому же шагу схлопнется Replacing'ом, не задвоив баннер."""
    ttl = timedelta(days=float(step.get("ttl_days", 7)))
    return [tenant, f"{camp['campaign_id']}:{step_idx}:{identity}", cuid, identity,
            camp["campaign_id"], step_idx,
            render(step.get("subject", ""), ctx), render(step["body"], ctx),
            render(step.get("cta_label", "Open"), ctx),
            render(step.get("cta_url", "{{app_url}}"), ctx),
            camp["entry_stage"], now + ttl, now]


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


def tick(client, tenant: str) -> dict[str, int]:
    cfgs = json.loads(CAMPAIGNS_PATH.read_text())
    # тенант без git-блока живёт на универсальном каркасе _default
    conf = cfgs.get(tenant) or cfgs.get("_default")
    if not conf:
        raise SystemExit(f"нет кампаний для тенанта {tenant}")
    control_pct = int(conf.get("control_pct", 10))
    conf = {**conf, "autopilot": resolve_autopilot(conf, load_tenant_channels(tenant))}
    # правки текстов/таймингов из CRM (runtime, без деплоя)
    from overrides import load_tenant as load_overrides, merge_campaign_conf
    conf = merge_campaign_conf(conf, load_overrides(tenant))
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
    now = _now_dt()
    stats = {"enrolled": 0, "control": 0, "steps": 0, "done": 0, "exited": 0}

    stages = {r[0]: (r[1], r[2], r[3]) for r in client.query(
        "SELECT identity_id, stage, email_norm, client_user_id FROM retention.user_actions "
        "WHERE tenant_id = %(t)s", parameters={"t": tenant}).result_rows}

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

    for camp in conf["campaigns"]:
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
        for identity, (stage, _email, _cuid) in stages.items():
            if stage != camp["entry_stage"] or identity in enrolled:
                continue
            control = holdout_split(tenant, cid, identity, control_pct)
            row = {"identity_id": identity, "control": 1 if control else 0,
                   "entry_stage": stage, "step_idx": 0,
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
            stage_now, email, cuid = stages.get(identity, ("", "", ""))

            for i in due_steps(steps, enrolled_at, int(row["step_idx"]), now):
                step = steps[i]
                retry_step = False
                try:
                    if not row["control"]:
                        if step["action"] in ("email", "message"):
                            channel = step.get("channel", "email")
                            if channel == "email":
                                address, consent = email, 1
                            else:
                                address, consent = contacts.get((cuid, channel), ("", 0))
                            if not address:
                                _log_send(client, tenant, cid, identity, i, channel,
                                          step.get("subject", ""), "rejected", "no_contact")
                            elif channel == "email" and address.lower() in suppressed:
                                _log_send(client, tenant, cid, identity, i, channel,
                                          step.get("subject", ""), "rejected", "suppressed")
                            elif not consent:
                                _log_send(client, tenant, cid, identity, i, channel,
                                          step.get("subject", ""), "rejected", "no_consent")
                            elif frequency_block(cid, *touches.get(identity, (0, 0))):
                                # Шаг НЕ отработан: он созреет снова, когда
                                # частота позволит. Иначе касание пропадало бы
                                # навсегда из-за соседней кампании.
                                _log_send(client, tenant, cid, identity, i, channel,
                                          step.get("subject", ""), "rejected",
                                          frequency_block(cid, *touches.get(identity, (0, 0))))
                                retry_step = True
                            else:
                                # счётчик растёт СРАЗУ: за один тик могут созреть
                                # два шага, и второй обязан увидеть первый
                                day, week = touches.get(identity, (0, 0))
                                touches[identity] = (day + 1, week + 1)
                                ok, detail = route_message(
                                    channel, address, step.get("subject", ""),
                                    step["body"], email_cfg, msg_cfg)
                                # Провайдер лёг или придушил лимитом - касание НЕ
                                # отработано: шаг остаётся созревшим, следующий тик
                                # повторит. Иначе письмо о несписании терялось бы
                                # навсегда из-за минутного 503.
                                if (not ok and transient_failure(detail)
                                        and _retry_count(client, tenant, cid,
                                                         identity, i) < MAX_SEND_RETRIES):
                                    _log_send(client, tenant, cid, identity, i, channel,
                                              step.get("subject", ""), "retry", detail)
                                    retry_step = True
                                else:
                                    # detail успешной отправки = id письма у провайдера:
                                    # по нему вебхуки доставки находят это касание
                                    pid = detail if (ok and detail != "dry_run") else ""
                                    _log_send(client, tenant, cid, identity, i, channel,
                                              step.get("subject", ""),
                                              "dry_run" if detail == "dry_run" else ("sent" if ok else "rejected"),
                                              "" if ok else detail, pid)
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
                                       "card_update_url": email_cfg.card_update_url}
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
