"""Автопобедитель A/B вариантов шага: замер -> victory-текст в overrides.

Шаг с variants: [...] делит аудиторию детерминированно (pick_variant).
Этот джоб (еженедельно, после uplift_report) сравнивает варианты по КЛИКАМ
реальных отправок (dry-run не считается - там некому открывать) и, когда у
каждого варианта >= MIN_SENDS и лидер впереди на MIN_LIFT относительных,
фиксирует победителя в knowledge kind='ab_winners' (у джобов /secrets
read-only - overrides им писать нельзя). Движок и экран накладывают
победителей поверх конфига (overrides.apply_ab_winners): все получают
victory-текст, сплит шага гаснет, источник виден бейджем 'ab'.

Не набралось - молчим и копим дальше: ранний победитель хуже отсутствия
победителя, он фиксирует шум.
"""

from __future__ import annotations

KIND = "ab_winners"

MIN_SENDS = 30       # на КАЖДЫЙ вариант
MIN_LIFT = 0.2       # лидер должен быть лучше на 20% относительных


def winner(stats: dict[int, dict]) -> int | None:
    """stats: {variant: {'sent': n, 'clicked': k}} -> индекс победителя или None.

    Клик - главный сигнал (человек сделал, что просили). Побеждает лучший
    click-rate при достатке данных у ВСЕХ вариантов и отрыве >= MIN_LIFT.
    """
    if len(stats) < 2:
        return None
    if any(v.get("sent", 0) < MIN_SENDS for v in stats.values()):
        return None
    rates = {k: (v.get("clicked", 0) / v["sent"]) for k, v in stats.items()}
    best = max(rates, key=lambda k: rates[k])
    others = [r for k, r in rates.items() if k != best]
    floor = max(others)
    if floor == 0:
        return best if rates[best] > 0 else None
    return best if (rates[best] - floor) / floor >= MIN_LIFT else None


def variant_stats(client, tenant: str, cid: str, step_idx: int,
                  n_variants: int) -> dict[int, dict]:
    """Отправки и клики по вариантам. Вариант юзера восстанавливается тем же
    хэшем, что его назначил (pick_variant) - хранить ничего не нужно."""
    from campaign_tick import pick_variant

    sent_rows = client.query(
        """
        SELECT identity_id FROM retention.campaign_send_log
        WHERE tenant_id = %(t)s AND campaign_id = %(c)s AND step_idx = %(i)s
          AND action = 'email' AND status = 'sent'
        """, parameters={"t": tenant, "c": cid, "i": step_idx}).result_rows
    emails = {r[0]: str(r[1] or "").lower() for r in client.query(
        "SELECT identity_id, email_norm FROM retention.identities_current "
        "WHERE tenant_id = %(t)s", parameters={"t": tenant}).result_rows}
    clicked = {str(r[0]).lower() for r in client.query(
        """
        SELECT address FROM retention.email_events
        WHERE tenant_id = %(t)s AND campaign_id = %(c)s AND step_idx = %(i)s
          AND event_type = 'clicked'
        """, parameters={"t": tenant, "c": cid, "i": step_idx}).result_rows}

    stats: dict[int, dict] = {k: {"sent": 0, "clicked": 0}
                              for k in range(n_variants)}
    for (ident,) in sent_rows:
        k = pick_variant(ident, cid, step_idx, n_variants)
        stats[k]["sent"] += 1
        if emails.get(ident, "") in clicked:
            stats[k]["clicked"] += 1
    return stats


def run(client, tenant: str, conf: dict) -> list[str]:
    """Пройти шаги с вариантами, зафиксировать созревших победителей."""
    try:
        from knowledge import load as kb_load
        from knowledge import save as kb_save
    except ImportError:  # pragma: no cover
        from stripe_sync.knowledge import load as kb_load  # type: ignore
        from stripe_sync.knowledge import save as kb_save  # type: ignore

    winners = kb_load(client, tenant, KIND) or {}
    decided = []
    for camp in conf.get("campaigns", []):
        cid = camp["campaign_id"]
        for i, step in enumerate(camp.get("steps", [])):
            variants = step.get("variants") or []
            key = f"{cid}#{i}"
            if len(variants) < 2 or step.get("variants_off") or key in winners:
                continue
            stats = variant_stats(client, tenant, cid, i, len(variants))
            best = winner(stats)
            if best is None:
                continue
            v = variants[best] or {}
            patch = {f: v[f] for f in ("subject", "body", "cta_label", "cta_url")
                     if v.get(f) is not None}
            winners[key] = {"variant": best, "patch": patch,
                            "sent": stats[best]["sent"],
                            "clicked": stats[best]["clicked"]}
            decided.append(f"{key} -> variant {best} "
                           f"({stats[best]['clicked']}/{stats[best]['sent']} clicks)")
    if decided:
        kb_save(client, tenant, KIND, winners, "ab_winner")
    return decided
