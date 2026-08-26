"""Недельный uplift-отчёт (Phase 6): target vs holdout → инкремент в долларах.

Формула v1 (ТЗ §4/§7): conv = доля группы с goal-событием в окне после
зачисления; для invert-целей (K4: отмена) conv = 1 - доля. Инкремент =
(conv_target - conv_control) × N_target × средний чек (MRR зачисленных).
Честность: при пустом контроле инкремент не считается (NULL-семантика — n/a),
отрицательный инкремент показывается как есть.

Запуск: python uplift_report.py [--days 7] — печать + строка в uplift_reports
+ письмо владельцу (OWNER_EMAIL; dry-run по умолчанию, как все отправки).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from saas_senders import EmailConfig, MessagingConfig, send_email, tenant_configs

CAMPAIGNS_PATH = Path(__file__).parent / "saas_campaigns.json"


# Ниже этого размера групп разница между target и контролем - шум: один
# сконвертившийся человек двигает цифру на десятки процентов. Отчёт всё равно
# показываем, но помечаем как ранний сигнал, а не как измеренный результат.
CONFIDENT_MIN_GROUP = 30


def significant_difference(n_t: int, n_c: int, k_t: int, k_c: int) -> bool:
    """Отличие конверсий реально, а не шум: z-тест двух долей на 95%.

    «n >= 30 в обеих группах» само по себе не отличает 4 п.п. аплифта от
    случайности - владелец банковал бы шум как заработанные деньги. Считаем
    объединённую дисперсию и требуем |разница| > 1.96 x SE.
    """
    if not n_t or not n_c:
        return False
    p_t, p_c = k_t / n_t, k_c / n_c
    pooled = (k_t + k_c) / (n_t + n_c)
    var = pooled * (1.0 - pooled) * (1.0 / n_t + 1.0 / n_c)
    if var <= 0:
        # обе группы 0% или 100%: разницы нет либо она вырождена
        return p_t != p_c
    se = var ** 0.5
    return abs(p_t - p_c) > 1.96 * se


def uplift_math(n_target: int, n_control: int, conv_target_cnt: int,
                conv_control_cnt: int, avg_check: float,
                invert: bool = False) -> dict:
    """Чистая математика одной кампании. incremental_usd=None при пустом контроле."""
    conv_t = conv_target_cnt / n_target if n_target else 0.0
    conv_c = conv_control_cnt / n_control if n_control else 0.0
    if invert:
        conv_t, conv_c = 1.0 - conv_t, 1.0 - conv_c
    incremental = None
    if n_target and n_control:
        incremental = round((conv_t - conv_c) * n_target * avg_check, 2)
    # «Достоверно» = группы достаточно большие И разница переживает z-тест.
    # Иначе цифра показывается, но честно помечена ранним сигналом.
    return {"conv_target": round(conv_t, 4), "conv_control": round(conv_c, 4),
            "incremental_usd": incremental,
            "confident": bool(n_target >= CONFIDENT_MIN_GROUP
                              and n_control >= CONFIDENT_MIN_GROUP
                              and significant_difference(
                                  n_target, n_control,
                                  conv_target_cnt, conv_control_cnt))}


def campaign_report(client, tenant: str, camp: dict, days: int) -> dict | None:
    goal = camp.get("goal")
    if not goal:
        return None
    window_days = int(goal["window_days"])
    # ЧЕСТНОЕ ОКНО: считаем только тех, у кого окно наблюдения уже ЗАКРЫЛОСЬ.
    # Иначе вчерашний зачисленный, у которого впереди ещё 13 дней на оплату,
    # попадал в знаменатель как «не сконвертился» и занижал результат.
    rows = client.query(
        """
        SELECT control, count() AS n, countIf(conv > 0) AS converted
        FROM (
            SELECT e.identity_id AS identity_id,
                   any(e.control) AS control,
                   countIf(ev.ts > e.enrolled_at
                           AND ev.ts <= e.enrolled_at + INTERVAL %(w)s DAY) AS conv
            FROM retention.campaign_enrollments_current e
            LEFT JOIN (
                SELECT identity_id, ts FROM retention.saas_events_resolved
                WHERE tenant_id = %(t)s AND event_type = %(g)s
            ) ev ON ev.identity_id = e.identity_id
            WHERE e.tenant_id = %(t)s AND e.campaign_id = %(c)s
              AND e.enrolled_at >= now() - INTERVAL %(dw)s DAY
              AND e.enrolled_at <= now() - INTERVAL %(w)s DAY
            GROUP BY e.identity_id
        )
        GROUP BY control
        """,
        # КОГОРТА С ЗАКРЫТЫМ ОКНОМ (аудит r3 2026-08-26): окно закрывается через
        # window_days после зачисления, и мы хотим тех, у кого оно закрылось за
        # последние `days` дней. Значит enrolled_at в [now-(days+window), now-window].
        # Было `>= now-days` - при window>=days интервал ПУСТОЙ, и uplift не
        # считался НИКОГДА (n_target=n_control=0 для всех кампаний навсегда).
        parameters={"t": tenant, "c": camp["campaign_id"],
                    "g": goal["event_type"], "w": window_days,
                    "dw": days + window_days},
    ).result_rows

    # сколько ещё «в полёте» - окно не закрылось, в расчёт не берём
    in_flight = int(client.query(
        """
        SELECT count() FROM retention.campaign_enrollments_current
        WHERE tenant_id = %(t)s AND campaign_id = %(c)s
          AND enrolled_at > now() - INTERVAL %(w)s DAY
        """,
        parameters={"t": tenant, "c": camp["campaign_id"], "w": window_days},
    ).result_rows[0][0])
    groups = {int(r[0]): (int(r[1]), int(r[2])) for r in rows}
    n_t, cv_t = groups.get(0, (0, 0))
    n_c, cv_c = groups.get(1, (0, 0))
    if n_t == 0 and n_c == 0:
        # мерить ещё нечего, но сказать «сколько зреет» - честно и полезно
        return {"campaign_id": camp["campaign_id"], "n_target": 0, "n_control": 0,
                "avg_check": 0.0, "goal_event": goal["event_type"],
                "conv_target": 0.0, "conv_control": 0.0, "incremental_usd": None,
                "confident": False, "in_flight": in_flight,
                "window_days": window_days} if in_flight else None

    # Средний чек: для платящих - их MRR, для триальных и незашедших - цена
    # плана (она лежит в value_at_stake). Раньше у активационной кампании чек
    # выходил нулевым, и любой её эффект оценивался в $0.
    avg_check = float(client.query(
        """
        SELECT coalesce(avg(nullIf(greatest(toFloat64(ua.mrr),
                                            toFloat64(ua.value_at_stake)), 0)), 0)
        FROM retention.campaign_enrollments_current e
        JOIN retention.user_actions ua
          ON ua.tenant_id = e.tenant_id AND ua.identity_id = e.identity_id
        WHERE e.tenant_id = %(t)s AND e.campaign_id = %(c)s
          AND e.enrolled_at >= now() - INTERVAL %(dw)s DAY
        """,
        parameters={"t": tenant, "c": camp["campaign_id"],
                    "dw": days + window_days},
    ).result_rows[0][0] or 0.0)

    m = uplift_math(n_t, n_c, cv_t, cv_c, avg_check, bool(goal.get("invert")))
    return {"campaign_id": camp["campaign_id"], "n_target": n_t, "n_control": n_c,
            "avg_check": round(avg_check, 2), "goal_event": goal["event_type"],
            "in_flight": in_flight, "window_days": window_days, **m}


def main() -> None:
    import clickhouse_connect

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

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
    cfgs = json.loads(CAMPAIGNS_PATH.read_text())
    conf = cfgs.get(tenant) or cfgs.get("_default") or {"campaigns": []}
    from saas_senders import load_tenant_channels
    from campaign_tick import resolve_autopilot
    autopilot_on = resolve_autopilot(conf, load_tenant_channels(tenant))
    now = datetime.now(tz=timezone.utc)
    period_start = (now - timedelta(days=args.days)).date()
    lines, rows = [], []

    for camp in conf["campaigns"]:
        rep = campaign_report(client, tenant, camp, args.days)
        if rep is None:
            continue
        if rep["n_target"] == 0 and rep["n_control"] == 0:
            # окно наблюдения ещё не закрылось ни у кого - в базу не пишем,
            # но в отчёте говорим, сколько людей «зреет»
            lines.append(f"{rep['campaign_id']:<22} ещё зреет: {rep['in_flight']} "
                         f"человек, результат будет через {rep['window_days']} дней "
                         f"после зачисления")
            continue
        incr = rep["incremental_usd"]
        lines.append(
            f"{rep['campaign_id']:<22} target {rep['conv_target']:>6.1%} (n={rep['n_target']})"
            f" | holdout {rep['conv_control']:>6.1%} (n={rep['n_control']})"
            f" | check ${rep['avg_check']:.2f}"
            f" | incremental " + (f"${incr:+.2f}" if incr is not None else "n/a (empty holdout)")
            + ("" if rep["confident"] else "  [ранний сигнал: групп мало]"))
        rows.append([tenant, rep["campaign_id"], period_start, now.date(),
                     rep["n_target"], rep["n_control"], rep["conv_target"],
                     rep["conv_control"], rep["avg_check"],
                     incr if incr is not None else 0.0, rep["goal_event"],
                     now.strftime("%Y-%m-%d %H:%M:%S.000")])

    # A/B: созревшие победители вариантов фиксируются тем же недельным ритмом
    try:
        from ab_winner import run as ab_run
        for line in ab_run(client, tenant, conf):
            lines.append(f"A/B winner: {line}")
    except Exception as exc:  # noqa: BLE001 - A/B не роняет замер
        print(f"[uplift] {tenant}: ab pass failed: {type(exc).__name__}", flush=True)

    report = f"Revenue Autopilot · uplift {period_start} → {now.date()} ({tenant})\n" + \
             ("\n".join(lines) if lines else "no enrolled cohorts in period")
    if lines and not autopilot_on:
        report += ("\n\nNOTE: autopilot was OFF (dry-run) - touches did not reach"
                   " users, so target vs holdout is NOT causal yet.")
    print(report)

    if rows:
        client.insert(
            "retention.uplift_reports", rows,
            column_names=["tenant_id", "campaign_id", "period_start", "period_end",
                          "n_target", "n_control", "conv_target", "conv_control",
                          "avg_check", "incremental_usd", "goal_event", "computed_at"])

    owner = os.environ.get("OWNER_EMAIL", "").strip()
    if owner and lines:
        ecfg, _ = tenant_configs(tenant, EmailConfig.from_env(), MessagingConfig.from_env())
        send_email(owner, f"Uplift report {now.date()} - {tenant}", report, ecfg)


if __name__ == "__main__":
    main()
