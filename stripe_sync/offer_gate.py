"""Методологический гейт живой выдачи оффера.

До этого модуля EV-формула, лестница уступок, спящие собаки и reason-playbook
работали только в превью на дашборде (api/saas.py) - витрине, на которую
владелец смотрит. Живая выдача (issue.py) шла мимо: оффер с отрицательным EV
мог выдаться, лестница не соблюдалась, кэп попыток не действовал. Здесь та же
математика (offer_value.rank) применяется к КОНКРЕТНОМУ человеку в момент,
когда система собирается потратить деньги.

Контекст собирается из того, что уже есть:
  • маржа тенанта - из ответов онбординга (economics), честно с basis;
  • ставка человека - его маржа x ожидаемая жизнь (1/p_churn);
  • бюджет подарков - 25% оставшейся маржи минус уже потраченное;
  • испробованные ступени и счётчик попыток - из offers_issued (пожизненно:
    серийного выпрашивателя скидок видно только на всей истории);
  • причина ухода - ЕГО причина из cancel_reasons, не самая частая по тенанту;
  • эффект оффера - ИЗМЕРЕННЫЙ uplift кампании, если он есть и достоверен,
    иначе прайор (закрывает петлю «замер заменяет догадку»).

Отказ гейта - это решение методологии, а не сбой: код причины пишется в
offers_issued.reason и виден в карточке юзера.
"""

from __future__ import annotations

import json

try:                                # джобы плоско, борд пакетом
    from economics import gross_margin
    from heuristics import expected_months
    from offer_value import (gift_budget, margin_at_stake, rank, tier_of,
                             uplift_or_prior)
    from saas_senders import load_tenant_channels
except ImportError:                 # pragma: no cover
    from stripe_sync.economics import gross_margin  # type: ignore
    from stripe_sync.heuristics import expected_months  # type: ignore
    from stripe_sync.offer_value import (gift_budget, margin_at_stake,  # type: ignore
                                         rank, tier_of, uplift_or_prior)
    from stripe_sync.saas_senders import load_tenant_channels  # type: ignore

# Стадии, где причина ухода осмысленна: человек уходит и мог её назвать.
REASON_STAGES = ("SAVE", "WINBACK")


def candidate_of(offer: dict, uplift: float) -> dict:
    """Оффер каталога -> кандидат для rank(): живые деньги отдельно от
    недополученной выручки (та же логика, что в превью каталога)."""
    cost = float(offer.get("cost_estimate") or 0.0)
    executor = str(offer.get("executor") or "")
    cash = cost if executor in ("client_callback", "balance_credit") else 0.0
    command = str((offer.get("params") or {}).get("command") or "")
    if executor == "client_callback" and command.endswith("_discount"):
        cash = 0.0                  # скидка на докупку живых денег не уносит
    return {"offer_id": offer.get("offer_id"), "executor": executor,
            "params": offer.get("params") or {}, "cash": cash,
            "revenue": max(0.0, cost - cash), "uplift": uplift}


def measured_uplift(client, tenant: str, campaign_id: str) -> dict | None:
    """Последний ДОСТОВЕРНЫЙ замер кампании из uplift_reports.

    Достоверность - обе группы >= 30 (та же планка, что в отчёте). Без этого
    петля «holdout -> замер -> решение» физически разомкнута: приоры жили бы
    вечно, а замеры лежали бы в таблице мёртвым грузом.
    """
    try:
        rows = client.query(
            """
            SELECT conv_target, conv_control, n_target, n_control
            FROM retention.uplift_reports
            WHERE tenant_id = %(t)s AND campaign_id = %(c)s
            ORDER BY computed_at DESC LIMIT 1
            """,
            parameters={"t": tenant, "c": campaign_id}).result_rows
    except Exception:               # noqa: BLE001 - нет таблицы = нет замера
        return None
    if not rows:
        return None
    ct, cc, nt, nc = float(rows[0][0]), float(rows[0][1]), int(rows[0][2]), int(rows[0][3])
    confident = nt >= 30 and nc >= 30
    return {"uplift": max(0.0, ct - cc), "confident": confident}


def build_context(client, tenant: str, user: dict, campaign_id: str) -> dict:
    """Всё, что нужно rank(), про ЭТОГО человека. Ошибки данных не валят
    выдачу: отсутствующий кусок контекста = None, и rank() его не применяет."""
    ctx: dict = {"stake": None, "budget": None, "tried_tiers": set(),
                 "attempts": 0, "reason": "", "base_stay": 0.5,
                 "churn_risk": None, "measured": None}

    # Риск ухода осмыслен только у ПЛАТЯЩЕГО: у триала/фримиума p_churn = 0
    # по определению («нечего отменять»), и спящая собака из этого нуля
    # глушила бы все активационные подарки.
    p_churn = user.get("p_churn")
    paying = str(user.get("sub_status") or "") in ("active", "past_due")
    if p_churn is not None and paying:
        ctx["churn_risk"] = float(p_churn)
        ctx["base_stay"] = max(0.05, 1.0 - float(p_churn))

    # ставка: месячная маржа человека x ожидаемая жизнь
    try:
        answers = (load_tenant_channels(tenant).get("onboarding_answers") or {})
        margin = gross_margin(answers)
        mrr = float(user.get("mrr") or 0.0)
        if margin is not None and mrr > 0:
            months = expected_months(float(p_churn)) if p_churn else 12.0
            ctx["stake"] = margin_at_stake(round(mrr * margin, 2), months)
    except Exception:               # noqa: BLE001
        pass

    # история подарков: ступени, попытки, потраченное - ПОЖИЗНЕННО.
    # Серийный выпрашиватель скидок на 14-дневном окне невидим.
    try:
        rows = client.query(
            """
            SELECT offer_id, executor, params, monetary, cost_estimate
            FROM retention.offers_issued
            WHERE tenant_id = %(t)s AND identity_id = %(i)s
              AND status IN ('issued', 'dry_run')
            """,
            parameters={"t": tenant, "i": user["identity_id"]}).result_rows
        spent = 0.0
        for oid, executor, params_raw, monetary, cost in rows:
            try:
                params = json.loads(params_raw or "{}")
            except ValueError:
                params = {}
            past = candidate_of({"offer_id": oid, "executor": executor,
                                 "params": params, "cost_estimate": cost}, 0.0)
            ctx["tried_tiers"].add(tier_of(past, past["cash"]))
            if int(monetary or 0):
                ctx["attempts"] += 1
                spent += float(cost or 0.0)
        if ctx["stake"] is not None:
            ctx["budget"] = gift_budget(ctx["stake"], spent)
    except Exception:               # noqa: BLE001
        pass

    # причина ухода ЭТОГО человека (последняя названная), только на стадиях,
    # где она осмысленна
    if str(user.get("stage") or "") in REASON_STAGES:
        try:
            rows = client.query(
                "SELECT category FROM retention.cancel_reasons "
                "WHERE tenant_id = %(t)s AND identity_id = %(i)s "
                "AND category != 'other' ORDER BY ts DESC LIMIT 1",
                parameters={"t": tenant, "i": user["identity_id"]}).result_rows
            ctx["reason"] = str(rows[0][0]) if rows else ""
        except Exception:           # noqa: BLE001
            ctx["reason"] = ""

    ctx["measured"] = measured_uplift(client, tenant, campaign_id)
    return ctx


def gate(client, tenant: str, offer: dict, user: dict, campaign_id: str,
         catalog_offers: list | None = None) -> tuple[bool, str]:
    """(ok, код отказа). Методология против конкретной выдачи.

    В rank() уходит ВЕСЬ набор офферов той же роли из каталога: лестница
    уступок осмысленна только на полном наборе - «есть ли ступень дешевле»
    нельзя спросить у одинокого кандидата.
    """
    ctx = build_context(client, tenant, user, campaign_id)

    def lift_of(o: dict) -> float:
        v, _src = uplift_or_prior(ctx["measured"], str(o.get("executor") or ""))
        return v

    role = str(offer.get("role") or "")
    peers = [o for o in (catalog_offers or [])
             if str(o.get("role") or "") == role
             and not o.get("_disabled")
             and o.get("offer_id") != offer.get("offer_id")]
    cands = [candidate_of(offer, lift_of(offer))] + \
            [candidate_of(o, lift_of(o)) for o in peers]
    ranked = rank(cands, ctx["stake"], ctx["budget"], ctx["tried_tiers"],
                  ctx["base_stay"], ctx["churn_risk"], ctx["reason"],
                  attempts=ctx["attempts"])
    mine = next(r for r in ranked if r["offer_id"] == offer.get("offer_id"))
    if mine["blocked"] is None:
        return True, ""
    return False, "methodology:" + json.dumps(mine["blocked"],
                                              separators=(",", ":"),
                                              ensure_ascii=False)
