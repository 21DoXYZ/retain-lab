"""Недельный дайджест владельцу на почту: ценность видна без входа в CRM.

Продукт продаётся за долю от прироста - владелец обязан ВИДЕТЬ работу машины,
а не верить на слово. Раз в неделю письмо: что случилось с базой, что машина
сделала, воронка, что ждёт решения. Тон - человеческий, цифры - только
измеренные (§8/§9: не выдумываем и не приукрашиваем).

Получатель: tenants.json owner_email; нет адреса - молчим и говорим почему.
Запуск: TENANT_ID=<пространство> python weekly_digest.py (ops_loop, Пн 08:20).
"""

from __future__ import annotations

import os


def build_digest(client, tenant: str) -> str:
    q = lambda s, p=None: client.query(s, parameters=p or {"t": tenant}).result_rows

    ev = q("""
        SELECT uniqExactIf(identity_id, event_type = 'signup'),
               uniqExactIf(identity_id, event_type = 'billing.invoice_paid'),
               uniqExactIf(identity_id, event_type = 'generation_completed'),
               countIf(event_type = 'generation_completed'),
               countIf(event_type = 'support_ticket'),
               countIf(event_type = 'feedback'
                       AND JSONExtractString(meta, 'category') IN ('bug', 'complaint'))
        FROM retention.saas_events_deduped
        WHERE tenant_id = %(t)s AND ts >= now() - INTERVAL 7 DAY""")[0]
    fw = q("""
        SELECT count(),
               countIf(coalesce(f.projects_total, 0) > 0),
               countIf(coalesce(f.generations_total, 0) > 0),
               countIf(ua.sub_status IN ('active', 'past_due'))
        FROM retention.user_actions ua
        LEFT JOIN retention.user_event_features f
          ON f.tenant_id = ua.tenant_id AND f.identity_id = ua.identity_id
        WHERE ua.tenant_id = %(t)s""")[0]
    mach = q("""
        SELECT countIf(status = 'sent'), countIf(status = 'dry_run'),
               countIf(status = 'rejected')
        FROM retention.campaign_send_log
        WHERE tenant_id = %(t)s AND ts >= now() - INTERVAL 7 DAY""")[0]
    uplift = q("""
        SELECT coalesce(sum(inc), 0) FROM (
          SELECT campaign_id, argMax(incremental_usd, computed_at) AS inc
          FROM retention.uplift_reports WHERE tenant_id = %(t)s
          GROUP BY campaign_id)""")[0][0]

    lines = [
        "Your week at a glance:",
        "",
        f"- {int(ev[0])} new signups, {int(ev[2])} people created value "
        f"({int(ev[3])} actions total)",
        f"- {int(ev[1])} started paying" if int(ev[1]) else "- no new paying customers this week",
        f"- Funnel: {int(fw[0])} signed up -> {int(fw[1])} created a project -> "
        f"{int(fw[2])} got value -> {int(fw[3])} paying",
    ]
    if int(ev[4]) or int(ev[5]):
        lines.append(f"- Support: {int(ev[5])} bug reports, {int(ev[4])} tickets")
    sent, dry, rej = int(mach[0]), int(mach[1]), int(mach[2])
    if sent:
        lines.append(f"- Autopilot sent {sent} touches "
                     f"({rej} held back by guardrails)")
    elif dry:
        lines.append(f"- Autopilot prepared {dry} touches, all dry-run: "
                     "flip it on and they start reaching people")
    if float(uplift) > 0:
        lines.append(f"- Proven uplift so far: +${float(uplift):.2f} "
                     "(measured against the holdout)")

    # Письма -> деньги: строгая атрибуция (оплата ПОСЛЕ доставленного
    # письма, инвойсы этой недели). Та же математика, что на экране
    # Кампаний, - владелец видит доход машины без входа в CRM.
    money = q("""
        SELECT campaign_id, uniqExactIf(id, usd > 0) AS buyers,
               round(sum(usd)) AS revenue
        FROM (
            SELECT s.campaign_id AS campaign_id, s.id AS id,
                   sumIf(inv.usd, inv.created_ts > s.sent_at) AS usd
            FROM (
                SELECT campaign_id, identity_id AS id, min(ts) AS sent_at
                FROM retention.campaign_send_log
                WHERE tenant_id = %(t)s AND status = 'sent'
                GROUP BY campaign_id, identity_id
            ) AS s
            LEFT JOIN (
                SELECT c2.iid AS iid, i.created_ts AS created_ts,
                       argMax(i.amount_paid, i.updated_at) AS usd
                FROM (
                    SELECT identity_id AS iid,
                           argMax(stripe_customer_id, updated_at) AS cust
                    FROM retention.identities WHERE tenant_id = %(t)s
                    GROUP BY identity_id
                ) AS c2
                JOIN retention.stripe_invoices i ON i.customer_id = c2.cust
                WHERE i.tenant_id = %(t)s AND i.status = 'paid'
                  AND c2.cust != ''
                  AND i.created_ts >= now() - INTERVAL 7 DAY
                GROUP BY c2.iid, i.invoice_id, i.created_ts
            ) AS inv ON inv.iid = s.id
            GROUP BY s.campaign_id, s.id
        )
        GROUP BY campaign_id HAVING revenue > 0
        ORDER BY revenue DESC LIMIT 6""")
    if money:
        # Тотал - ОТДЕЛЬНЫМ дедуп-запросом: строки money по кампаниям, один
        # человек бывает тронут несколькими кампаниями, и сумма строк задвоила
        # бы и покупателей, и доллары в заголовке. Здесь клиент и инвойс
        # считаются один раз (оплата после самого раннего нашего письма).
        total = q("""
            SELECT uniqExactIf(id, usd > 0), round(sum(usd))
            FROM (
                SELECT s.id AS id,
                       sumIf(inv.usd, inv.created_ts > s.sent_at) AS usd
                FROM (
                    SELECT identity_id AS id, min(ts) AS sent_at
                    FROM retention.campaign_send_log
                    WHERE tenant_id = %(t)s AND status = 'sent'
                    GROUP BY identity_id
                ) AS s
                LEFT JOIN (
                    SELECT c2.iid AS iid, i.created_ts AS created_ts,
                           argMax(i.amount_paid, i.updated_at) AS usd
                    FROM (
                        SELECT identity_id AS iid,
                               argMax(stripe_customer_id, updated_at) AS cust
                        FROM retention.identities WHERE tenant_id = %(t)s
                        GROUP BY identity_id
                    ) AS c2
                    JOIN retention.stripe_invoices i ON i.customer_id = c2.cust
                    WHERE i.tenant_id = %(t)s AND i.status = 'paid'
                      AND c2.cust != ''
                      AND i.created_ts >= now() - INTERVAL 7 DAY
                    GROUP BY c2.iid, i.invoice_id, i.created_ts
                ) AS inv ON inv.iid = s.id
                GROUP BY s.id
            )""")
        trow = (total or [[0, 0]])[0]
        total_b, total_r = int(trow[0] or 0), float(trow[1] or 0)
        noun = "customer" if total_b == 1 else "customers"
        lines += ["", f"Paid after our emails this week: {total_b} {noun}, "
                      f"${total_r:.0f} (campaign lines overlap when several "
                      "campaigns touched the same person):"]
        lines += [f"  - {r[0]}: {int(r[1])} paid, ${float(r[2]):.0f}"
                  for r in money]

    lines += ["", "Full picture: https://retivo.digital/home"]
    return "\n".join(lines)


def main() -> None:
    import clickhouse_connect

    tenant = os.environ.get("TENANT_ID", "").strip()
    if not tenant:
        raise SystemExit("нужен TENANT_ID")
    from saas_senders import (EmailConfig, MessagingConfig,
                              load_tenant_channels, send_email, tenant_configs)
    tch = load_tenant_channels(tenant)
    owner = str(tch.get("owner_email") or "").strip()
    if not owner:
        print(f"[digest] tenant={tenant} owner_email не задан - пропуск", flush=True)
        return

    client = clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "clickhouse"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", ""),
        database=os.environ.get("CH_DB", "retention"))
    body = build_digest(client, tenant)
    e, _m = tenant_configs(tenant, EmailConfig.from_env(), MessagingConfig.from_env())
    ok, detail = send_email(owner, "Your retention week in numbers", body, e)
    print(f"[digest] tenant={tenant} to={owner} sent={ok} {detail}", flush=True)


if __name__ == "__main__":
    main()
