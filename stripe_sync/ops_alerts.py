"""Сторож платформы: молчаливые поломки будят владельца письмом.

Урок недели: триггер T2 падал каждую минуту НЕЗАМЕЧЕННЫМ, support-события
молча отбрасывались, офферы K1 умирали на ненастроенном callback. Экраны
это не показывали - узнавали случайно. Этот джоб раз в час собирает такие
вещи и шлёт ОДНО письмо на PLATFORM_ALERT_EMAIL.

Проверки:
  A. pipeline_runs со status='error' за 2 часа (включая trigger:* - их
     теперь пишет trigger_tick) - что-то падает прямо сейчас;
  B. тишина приёма: у живого тенанта (события были) max(ts) старше 6 часов;
  C. send_log: всплеск reason 'error:*' за сутки (канал деградирует);
  D. офферы умирают: callback_not_configured за 48 часов.

Дедуп: retention.ops_alert_log - один и тот же ключ не чаще суток, поэтому
джоб можно гонять хоть каждую минуту и на каждом тенанте.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

RESEND_WINDOW_H = 24
FEED_SILENCE_MIN = 360
SEND_ERROR_SPIKE = 20


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def collect_problems(client) -> list[tuple[str, str]]:
    """[(alert_key, человеческая строка)] по всем тенантам сразу."""
    out: list[tuple[str, str]] = []

    # A. свежие ошибки конвейера (стадии и триггеры)
    for t, stage, detail, n in client.query("""
        SELECT tenant_id, stage, anyLast(detail), count()
        FROM retention.pipeline_runs
        WHERE status = 'error' AND started_at >= now() - INTERVAL 2 HOUR
        GROUP BY tenant_id, stage
        """).result_rows:
        out.append((f"{t}|pipe|{stage}",
                    f"[{t}] {stage}: {n} ошибок за 2ч - {str(detail)[:160]}"))

    # B. поток событий встал (только у тенантов, где события вообще были)
    for t, mins in client.query("""
        SELECT tenant_id, dateDiff('minute', max(ts), now())
        FROM retention.saas_events GROUP BY tenant_id
        HAVING count() > 100
        """).result_rows:
        if int(mins) > FEED_SILENCE_MIN:
            out.append((f"{t}|feed",
                        f"[{t}] приём событий молчит {int(mins) // 60}ч - "
                        "проверить экспорт-ключ/вебхуки/сниппет"))

    # C. канал деградирует: много технических отказов отправки
    for t, n in client.query("""
        SELECT tenant_id, count() FROM retention.campaign_send_log
        WHERE status = 'rejected' AND reason LIKE 'error:%%'
          AND ts >= now() - INTERVAL 1 DAY
        GROUP BY tenant_id
        """).result_rows:
        if int(n) >= SEND_ERROR_SPIKE:
            out.append((f"{t}|senderr",
                        f"[{t}] {n} технических отказов отправки за сутки"))

    # D. офферы умирают молча: исполнитель callback не настроен у тенанта
    for t, n in client.query("""
        SELECT tenant_id, count() FROM retention.campaign_send_log
        WHERE reason = 'callback_not_configured'
          AND ts >= now() - INTERVAL 2 DAY
        GROUP BY tenant_id
        """).result_rows:
        out.append((f"{t}|callback",
                    f"[{t}] {n} офферов за 48ч не выданы: callback начисления "
                    "не настроен у клиента"))

    return out


def fresh_only(client, problems: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Отсечь ключи, по которым алерт уже уходил в окне RESEND_WINDOW_H."""
    if not problems:
        return []
    sent = {str(r[0]) for r in client.query(f"""
        SELECT alert_key FROM retention.ops_alert_log
        GROUP BY alert_key
        HAVING max(sent_at) >= now() - INTERVAL {RESEND_WINDOW_H} HOUR
        """).result_rows}
    return [(k, msg) for k, msg in problems if k not in sent]


def main() -> None:
    import clickhouse_connect
    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"))

    problems = collect_problems(client)
    fresh = fresh_only(client, problems)
    print(f"[alerts] найдено {len(problems)}, новых {len(fresh)}", flush=True)
    if not fresh:
        return

    to = os.environ.get("PLATFORM_ALERT_EMAIL", "").strip()
    if not to:
        print("[alerts] PLATFORM_ALERT_EMAIL не задан - алерты только в лог:",
              flush=True)
        for _k, msg in fresh:
            print(f"[alerts]   {msg}", flush=True)
        return

    from saas_senders import EmailConfig, MessagingConfig, send_email, tenant_configs
    cfg = EmailConfig.from_env()
    if not cfg.resend_api_key:
        # платформенного ключа нет - письма ходят через ключи тенантов;
        # берём первый живой email-конфиг (alert важнее чистоплюйства)
        from channels_admin import load_tenants
        for _tid in load_tenants():
            e, _m = tenant_configs(_tid, EmailConfig.from_env(),
                                   MessagingConfig.from_env())
            if e.resend_api_key and e.email_from:
                cfg = e
                break
    body = ("Hi,\n\nRevenue Autopilot noticed problems that do not show up "
            "on the screens:\n\n"
            + "\n".join(f"- {msg}" for _k, msg in fresh)
            + "\n\nEach item repeats at most once a day while it persists.")
    ok, detail = send_email(to, "Autopilot alert: silent failures", body, cfg)
    print(f"[alerts] to={to} sent={ok} {detail}", flush=True)
    if ok:
        client.insert("retention.ops_alert_log",
                      [[k, _now()] for k, _m in fresh],
                      column_names=["alert_key", "sent_at"])


if __name__ == "__main__":
    main()
