"""Дирижёр конвейера SaaS-контура (Phase 6): «cron в compose» с графом зависимостей.

Раньше это был тупой крон: крутил стадии по настенным часам вслепую. Если
stitch в :05 падал, scoring в 03:10 молча считал на устаревших личностях -
классический «мусор на входе -> тихо неверный результат». Теперь это ДИРИЖЁР:

  1. Стадии объявлены графом (deps): стадия не стартует, пока её вход не
     СВЕЖИЙ - то есть каждая зависимость успешно отработала не позже своего
     окна свежести. Иначе стадия ПРОПУСКАЕТСЯ (skipped, stale_dep:<кто>), а не
     выдаёт тихо неверное.
  2. Каждый прогон пишется в retention.pipeline_runs: исход, свежесть входа,
     длительность. По нему следующая стадия проверяет свежесть, а владелец
     видит здоровье всего контура (вьюха pipeline_health, экран /pipeline).

Расписание (UTC) задаётся полем `when`; зависимости - `deps`; окно свежести
выхода стадии - `fresh_h` (насколько её результат считается свежим для тех,
кто от неё зависит).

Каждая стадия гоняется ПО КАЖДОМУ пространству (tenant) отдельным процессом с
TENANT_ID в окружении. Новый клиент подхватывается сам.

Compose-сервис saas-ops (restart: unless-stopped) держит цикл живым.
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone

# ── Граф стадий ──────────────────────────────────────────────────────────────
# when(t)  - когда стадия созревает по расписанию (UTC-минута t)
# deps     - от каких стадий зависит ВХОД (должны быть свежими и успешными)
# fresh_h  - сколько часов выход стадии считается свежим для зависящих
#
# Рёбра графа (почему именно так):
#   stitch (личности)  -> scoring, campaign_tick  (без личностей user_actions пуст)
#   plans  (цена+лимит)-> scoring                  (burn_rate/LTV без тарифа врут)
#   campaign_tick      -> uplift_report            (замер по логу касаний)
#   uplift_report      -> ai_analyst               (аналитик читает СВЕЖИЙ uplift)
# Сбор (сниппет->Kafka->CH) - непрерывный, не стадия расписания.
STAGES: dict[str, dict] = {
    "stitch": {
        "argv": ["python", "stitch.py"],
        "when": lambda t: t.minute == 5,
        "deps": [], "fresh_h": 2,
    },
    "plans": {
        "argv": ["python", "plans_sync.py"],
        "when": lambda t: t.minute == 5,
        "deps": [], "fresh_h": 26,
    },
    "contacts": {
        "argv": ["python", "contacts_sync.py"],
        "when": lambda t: t.minute == 5,
        "deps": [], "fresh_h": 26,
    },
    "users_sync": {
        "argv": ["python", "users_sync.py"],
        "when": lambda t: t.minute == 35,
        "deps": [], "fresh_h": 26,
    },
    "product_sync": {
        # продуктовые события экспорта (генерации, кредиты, планы) + измеренная
        # экономика; после users_sync, чтобы новые юзеры уже были в базе
        "argv": ["python", "product_sync.py"],
        "when": lambda t: t.minute == 45,
        "deps": ["users_sync"], "fresh_h": 26,
    },
    "cancel_reasons": {
        "argv": ["python", "cancel_reasons.py"],
        "when": lambda t: t.minute == 20,
        "deps": [], "fresh_h": 26,
    },
    "scoring": {
        "argv": ["python", "scoring.py"],
        "when": lambda t: t.hour == 3 and t.minute == 10,
        "deps": ["stitch", "plans"], "fresh_h": 26,
    },
    "campaign_tick": {
        "argv": ["python", "campaign_tick.py"],
        "when": lambda t: t.minute % 15 == 0,
        "deps": ["stitch"], "fresh_h": 26,
    },
    "replenishment": {
        # Replenishment Autopilot: планы из заказов + дозревание -> события
        # replenishment_due (K7 подхватит триггером). enabled=false у тенанта -
        # джоб сам no-op, поэтому стадия дешёвая для всех остальных.
        "argv": ["python", "replenishment.py"],
        "when": lambda t: t.minute == 25,
        "deps": ["stitch"], "fresh_h": 26,
    },
    "triggers": {
        # событийные триггеры: момент интента (чекаут, кредиты, карта) не
        # живёт 15-минутными циклами - проверяем каждую минуту, это дёшево
        "argv": ["python", "trigger_tick.py"],
        "when": lambda t: True,
        "deps": [], "fresh_h": 1,
    },
    "uplift_report": {
        "argv": ["python", "uplift_report.py"],
        "when": lambda t: t.weekday() == 0 and t.hour == 8 and t.minute == 0,
        "deps": ["campaign_tick"], "fresh_h": 24,
    },
    "ai_analyst": {
        "argv": ["python", "ai_analyst.py"],
        "when": lambda t: t.weekday() == 0 and t.hour == 8 and t.minute == 10,
        "deps": ["uplift_report"], "fresh_h": 24,
    },
    "product_insights": {
        # продуктовые гипотезы: аналитика виджета + голос юзеров -> что менять
        "argv": ["python", "product_insights.py"],
        "when": lambda t: t.weekday() == 1 and t.hour == 8 and t.minute == 0,
        "deps": ["product_sync"], "fresh_h": 24 * 8,
    },
    "auto_improve": {
        # авто-мозг: сам запускает кампании на сегменты, доливает новых,
        # ставит на паузу бесполезное, шлёт владельцу отчёт (раз в день)
        "argv": ["python", "auto_improve.py"],
        "when": lambda t: t.hour == 9 and t.minute == 3,
        "deps": ["stitch"], "fresh_h": 26,
    },
    "ops_alerts": {
        # сторож молчаливых поломок: падающие триггеры, тишина приёма,
        # умирающие офферы -> письмо владельцу платформы (дедуп 24ч внутри)
        "argv": ["python", "ops_alerts.py"],
        "when": lambda t: t.minute == 7,
        "deps": [], "fresh_h": 26,
    },
    "mail_poll": {
        # ответы юзеров из Google-ящика тенанта (IMAP, BODY.PEEK): в базу,
        # цепочку ответившему стоп; без imap_app_password - тихий пропуск
        "argv": ["python", "mail_poll.py"],
        "when": lambda t: t.minute % 5 == 2,
        "deps": [], "fresh_h": 26,
    },
    "weekly_digest": {
        # письмо владельцу после свежего uplift: ценность видна без входа в CRM
        "argv": ["python", "weekly_digest.py"],
        "when": lambda t: t.weekday() == 0 and t.hour == 8 and t.minute == 20,
        "deps": ["uplift_report"], "fresh_h": 24 * 8,
    },
}

_JOB_TIMEOUT = 1800


def _ch():
    """Клиент ClickHouse для журнала прогонов. None - журнал недоступен, но
    стадии всё равно бегут (дирижёр не должен падать из-за журнала)."""
    try:
        import clickhouse_connect
        return clickhouse_connect.get_client(
            host=os.environ.get("CH_HOST", "clickhouse"),
            port=int(os.environ.get("CH_PORT", "8123")),
            username=os.environ.get("CH_USER", "default"),
            password=os.environ.get("CH_PASSWORD", ""),
            database=os.environ.get("CH_DB", "retention"))
    except Exception as exc:  # noqa: BLE001
        print(f"[ops] журнал недоступен: {type(exc).__name__}", flush=True)
        return None


def _record(ch, tenant: str, stage: str, status: str, detail: str,
            input_fresh: int, skipped_reason: str, rows: int,
            duration_s: float) -> None:
    if ch is None:
        return
    try:
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        ch.insert(
            "retention.pipeline_runs",
            [[tenant, stage, status, detail[:300], input_fresh,
              skipped_reason, rows, round(duration_s, 1), now]],
            column_names=["tenant_id", "stage", "status", "detail",
                          "input_fresh", "skipped_reason", "rows",
                          "duration_s", "started_at"])
    except Exception as exc:  # noqa: BLE001 - журнал не роняет дирижёра
        print(f"[ops] запись журнала {stage}/{tenant}: {type(exc).__name__}",
              flush=True)


def fresh_ok_ages(ch, tenant: str) -> dict[str, float]:
    """{стадия: часы с последнего УСПЕШНОГО прогона} для тенанта. Пусто -
    журнала нет: тогда свежесть не проверяем (fail-open на старте/без БД)."""
    if ch is None:
        return {}
    try:
        rows = ch.query(
            "SELECT stage, dateDiff('minute', max(started_at), now()) / 60.0 "
            "FROM retention.pipeline_runs "
            "WHERE tenant_id = %(t)s AND status = 'ok' GROUP BY stage",
            parameters={"t": tenant}).result_rows
        return {r[0]: float(r[1]) for r in rows}
    except Exception:  # noqa: BLE001
        return {}


def stale_dep(stage: str, ages: dict[str, float]) -> str:
    """Первая несвежая/неотработавшая зависимость стадии, '' если все свежи.

    Свежесть журнала пуста (нет БД/первый запуск) - НЕ блокируем: дирижёр
    не должен насмерть замкнуться, если журнал недоступен. Но если журнал
    ЕСТЬ и зависимость в нём протухла/отсутствует - стадию тормозим.
    """
    if not ages:               # журнала нет - свежесть не проверяем
        return ""
    for dep in STAGES[stage]["deps"]:
        age = ages.get(dep)
        if age is None:
            return dep         # зависимость ни разу успешно не отработала
        if age > STAGES[dep]["fresh_h"]:
            return dep         # выход зависимости протух
    return ""


def _rows_from_tail(tail: str) -> int:
    """Достать число обработанного из хвоста вывода стадии (scored=232 и т.п.)."""
    import re
    m = re.search(r"(?:scored|identities|imported|classified|"
                  r"enrolled|accepted|rows)=(\d+)", tail)
    return int(m.group(1)) if m else 0


def run_stage(ch, name: str, tenant: str, ages: dict[str, float]) -> str:
    """Запустить стадию с проверкой свежести входа. Возвращает статус."""
    blocked = stale_dep(name, ages)
    if blocked:
        reason = f"stale_dep:{blocked}"
        print(f"[ops] {name} tenant={tenant} SKIP ({reason})", flush=True)
        _record(ch, tenant, name, "skipped", "", 0, reason, 0, 0.0)
        return "skipped"

    started = time.monotonic()
    env = {**os.environ, "TENANT_ID": tenant}
    try:
        proc = subprocess.run(name_argv(name), capture_output=True, text=True,
                              timeout=_JOB_TIMEOUT, env=env)
        dur = time.monotonic() - started
        out = (proc.stdout or "").strip().splitlines()
        tail = out[-1] if out else ""
        if proc.returncode == 0:
            print(f"[ops] {name} tenant={tenant} ok {dur:.1f}s {tail}", flush=True)
            _record(ch, tenant, name, "ok", tail, 1, "",
                    _rows_from_tail(tail), dur)
            # успешный прогон освежает возраст для зависящих в этом же тике
            ages[name] = 0.0
            return "ok"
        err = (proc.stderr or "").strip().splitlines()
        etail = err[-1] if err else tail
        print(f"[ops] {name} tenant={tenant} ERROR rc={proc.returncode} {etail}",
              flush=True)
        _record(ch, tenant, name, "error", etail, 1, "", 0, dur)
        return "error"
    except subprocess.TimeoutExpired:
        dur = time.monotonic() - started
        print(f"[ops] {name} tenant={tenant} TIMEOUT", flush=True)
        _record(ch, tenant, name, "timeout", "", 1, "", 0, dur)
        return "timeout"
    except Exception as exc:  # noqa: BLE001
        dur = time.monotonic() - started
        print(f"[ops] {name} tenant={tenant} error: {type(exc).__name__}: {exc}",
              flush=True)
        _record(ch, tenant, name, "error", f"{type(exc).__name__}: {exc}",
                1, "", 0, dur)
        return "error"


def name_argv(name: str) -> list[str]:
    return STAGES[name]["argv"]


# Порядок исполнения в один тик: топологический (зависимость раньше зависящей),
# чтобы свежесть, поднятая stitch в этот же тик, сразу увидел scoring/campaign.
# ЛОВУШКА (2026-09-07): стадия, добавленная в STAGES, но забытая здесь,
# молча никогда не запустится - ops_alerts так простоял 3 дня. Санити-чек
# ниже валит процесс на старте, если списки разъехались.
_ORDER = ["stitch", "plans", "contacts", "users_sync", "product_sync",
          "cancel_reasons", "scoring", "campaign_tick", "replenishment",
          "triggers", "ops_alerts", "mail_poll", "auto_improve",
          "uplift_report", "ai_analyst", "product_insights", "weekly_digest"]
assert set(_ORDER) == set(STAGES), (
    f"_ORDER != STAGES: {set(_ORDER) ^ set(STAGES)}")


def main() -> None:
    print("[ops] дирижёр поднят (UTC): граф зависимостей + guard свежести + "
          "журнал pipeline_runs", flush=True)
    from provision_util import load_known_tenants

    last_key, warned = "", False
    while True:
        now = datetime.now(tz=timezone.utc)
        key = now.strftime("%Y%m%d%H%M")
        if key != last_key:
            last_key = key
            due = [n for n in _ORDER if STAGES[n]["when"](now)]
            if due:
                tenants = load_known_tenants()
                if not tenants:
                    if not warned:
                        print("[ops] пространств нет (secrets/tokens.json пуст) - "
                              "пропускаю", flush=True)
                        warned = True
                else:
                    warned = False
                    ch = _ch()
                    for tenant in tenants:
                        ages = fresh_ok_ages(ch, tenant)
                        for name in due:
                            run_stage(ch, name, tenant, ages)
        time.sleep(10)


if __name__ == "__main__":
    main()
