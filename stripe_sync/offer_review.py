"""Методология как код: каждый оффер проходит разбор, прежде чем попасть в дело.

ЗАЧЕМ. METHODOLOGY.md - свод правил, но документ не мешает собрать плохой
оффер: его надо помнить и применять вручную. Здесь тот же свод в исполняемом
виде. Любой оффер - собранный правилами, предложенный моделью или заведённый
владельцем руками - проходит через review() и получает разбор: что в нём
экономически неверно, чем он рискует и какой рычаг сделал бы то же дешевле.

ЧТО ЭТО НЕ. Не блокировщик. Разбор ничего не запрещает: владелец вправе выдать
дорогой подарок осознанно. Задача - чтобы решение принималось ЗРЯЧЕ, а не по
привычке «дадим 20% скидки».

ТРИ УРОВНЯ ЗАМЕЧАНИЙ:
  harmful - оффер работает против владельца: в этой экономике он уносит
            больше, чем спасает, или бьёт по тем, кто и так остался бы;
  weak    - оффер не вреден, но есть заметно более дешёвый или более стойкий
            способ добиться того же;
  note    - расчёт держится на предположении, а не на измерении.

КАЖДОЕ ЗАМЕЧАНИЕ НЕСЁТ ЗАМЕНУ. Сказать «плохо» и уйти - это не разбор.
Поэтому review() возвращает alternative: конкретный рычаг, который решает ту
же задачу, с объяснением, чем он лучше именно здесь.
"""

from __future__ import annotations

try:                                    # борд импортирует пакетом, джобы плоско
    from economics import SAFE_GIFT_SHARE, THIN_MARGIN
    from offer_value import (RETENTION_DURABILITY, TIER_CASH, TIER_NAMES,
                             TIER_OTHER_MARGIN, TIER_OWN_REVENUE, TIER_WORD,
                             offer_for_reason, tier_of, uplift_or_prior)
except ImportError:
    from stripe_sync.economics import SAFE_GIFT_SHARE, THIN_MARGIN  # type: ignore
    from stripe_sync.offer_value import (RETENTION_DURABILITY, TIER_CASH,  # type: ignore
                                         TIER_NAMES, TIER_OTHER_MARGIN,
                                         TIER_OWN_REVENUE, TIER_WORD,
                                         offer_for_reason, tier_of,
                                         uplift_or_prior)

HARMFUL, WEAK, NOTE = "harmful", "weak", "note"


def _flag(code: str, level: str, **params) -> dict:
    """Замечание - КОД С ЧИСЛАМИ, а не готовая фраза.

    Готовую фразу нельзя показать на другом языке, нельзя проверить тестом и
    нельзя переформулировать, не трогая логику. Текст живёт в словарях
    интерфейса, здесь - только правило и его числа.
    """
    return {"code": code, "level": level, "params": params}


# ── Отдельные проверки. Каждая - один вопрос методологии ─────────────────────
# Проверка возвращает список замечаний (обычно пустой). Разбита по одной на
# правило намеренно: так видно, какое правило сработало, и так их можно
# добавлять поштучно, не трогая остальные.

def _check_cost_basis(offer: dict, ctx: dict) -> list:
    """Считаем по себестоимости или по цене? Это разные числа."""
    basis = str(ctx.get("cost_basis") or "price")
    if basis in ("stated", "margin"):
        return []
    if not offer.get("monetary"):
        return []
    return [_flag("cost_is_assumed" if basis == "assumed" else "cost_is_list_price",
                  NOTE)]


def _check_gift_vs_margin(offer: dict, ctx: dict) -> list:
    """Подарок не должен стоить дороже месяца этого клиента."""
    cash = float(ctx.get("cash") or 0)
    margin = ctx.get("monthly_margin")
    if not margin or cash <= 0:
        return []
    if cash > float(margin):
        return [_flag("gift_costs_more_than_the_customer", HARMFUL,
                      cash=round(cash, 2), margin=round(float(margin), 2))]
    if cash > float(margin) * SAFE_GIFT_SHARE:
        return [_flag("gift_is_a_big_bite", WEAK,
                      cash=round(cash, 2), margin=round(float(margin), 2))]
    return []


def _check_discount_below_cost(offer: dict, ctx: dict) -> list:
    """Скидка не может продавать подписку ниже себестоимости."""
    if offer.get("executor") != "stripe_coupon":
        return []
    pct = float((offer.get("params") or {}).get("percent_off") or 0)
    margin = ctx.get("gross_margin")
    if not pct or margin is None:
        return []
    margin_pct = float(margin) * 100
    if pct >= margin_pct:
        return [_flag("discount_sells_below_cost", HARMFUL, pct=round(pct),
                      margin_pct=round(margin_pct), safe_pct=round(margin_pct / 2))]
    if pct > margin_pct / 2:
        return [_flag("discount_eats_most_of_the_margin", WEAK,
                      pct=round(pct), margin_pct=round(margin_pct))]
    return []


def _check_durability(offer: dict, ctx: dict) -> list:
    """Надолго ли это удержит - или купит отсрочку."""
    executor = str(offer.get("executor") or "")
    keeps = RETENTION_DURABILITY.get(executor, 1.0)
    if keeps >= 0.6:
        return []
    return [_flag("buys_a_delay_not_a_customer", WEAK, keeps_pct=int(keeps * 100))]


def _check_cash_vs_product_currency(offer: dict, ctx: dict) -> list:
    """Деньги читаются как откуп, валюта продукта - как повод вернуться."""
    if offer.get("executor") != "balance_credit":
        return []
    return [_flag("cash_reads_as_a_payoff", WEAK)]


def _check_ladder(offer: dict, ctx: dict) -> list:
    """Не стоим ли мы на дорогой ступени, когда есть дешёвая."""
    tier = tier_of(offer, ctx.get("cash"))
    available = set(ctx.get("available_tiers") or [])
    cheaper = sorted(t for t in available if t < tier and t > TIER_WORD)
    if tier <= TIER_OTHER_MARGIN or not cheaper:
        return []
    return [_flag("cheaper_rung_exists", WEAK, tier=tier, cheaper=cheaper[0])]


def _check_sleeping_dogs(offer: dict, ctx: dict) -> list:
    """Кому это уйдёт - и не разбудит ли тех, кто остался бы сам.

    Срабатывает только когда стадия ИЗВЕСТНА и тревожна. Каталог обычно
    смотрят без конкретного человека - молотить этим замечанием по каждой
    карточке значит приучить владельца его не читать.
    """
    if not offer.get("monetary"):
        return []
    stage = str(ctx.get("stage") or "")
    if stage not in ("SAVE", "MONITOR"):
        return []
    return [_flag("may_wake_a_sleeping_dog",
                  HARMFUL if stage == "MONITOR" else NOTE, stage=stage)]


def _check_reason_fit(offer: dict, ctx: dict) -> list:
    """Соответствует ли рычаг названной причине ухода."""
    reason = str(ctx.get("reason") or "")
    wanted = offer_for_reason(reason)
    if not wanted["matched"] or not offer.get("monetary"):
        return []
    if wanted["executor"] is None:
        return [_flag("reason_is_not_about_money", HARMFUL, reason=reason)]
    if str(offer.get("executor")) != wanted["executor"]:
        return [_flag("another_lever_fits_the_reason", WEAK, reason=reason,
                      executor=wanted["executor"])]
    return []


def _check_cap_unit(offer: dict, ctx: dict) -> list:
    """Лимит в штуках одинаков для клиента за $9 и за $399."""
    if not offer.get("monetary"):
        return []
    if ctx.get("gift_budget") is not None:
        return []
    return [_flag("cap_counted_in_pieces", NOTE)]


CHECKS = (_check_cost_basis, _check_gift_vs_margin, _check_discount_below_cost,
          _check_durability, _check_cash_vs_product_currency, _check_ladder,
          _check_sleeping_dogs, _check_reason_fit, _check_cap_unit)


# ── Замена: что предложить вместо ───────────────────────────────────────────

# Пауза осмысленна только там, где человек УХОДИТ: предлагать её вместо
# активационного бонуса - бессмыслица, нечего ставить на паузу у того, кто
# ещё не начал пользоваться.
PAUSE_ROLES = ("save", "winback", "dunning")


def alternative(offer: dict, ctx: dict) -> dict | None:
    """Рычаг, решающий ту же задачу дешевле или надёжнее. None - нечего менять.

    Сказать «плохо» и уйти - не разбор. Замена подбирается из того, что у
    клиента ДЕЙСТВИТЕЛЬНО есть (без паузы в биллинге предлагать паузу нельзя)
    и подходит РОЛИ оффера (пауза не лечит активацию).
    """
    can = set(ctx.get("can_execute") or ())
    tier = tier_of(offer, ctx.get("cash"))
    if tier <= TIER_OTHER_MARGIN:
        return None

    role = str(offer.get("role") or "").lower()
    stage = str(ctx.get("stage") or "")
    leaving = role in PAUSE_ROLES or stage in ("SAVE", "WINBACK", "DUNNING")

    reason = str(ctx.get("reason") or "")
    wanted = offer_for_reason(reason)
    if leaving and wanted["matched"] and wanted["executor"] in can:
        return {"executor": wanted["executor"], "why": "reason", "reason": reason}

    if leaving and "pause_collection" in can:
        return {"executor": "pause_collection", "why": "pause_holds_longer"}
    if ctx.get("has_topup") and "client_callback" in can:
        return {"executor": "client_callback", "why": "topup_costs_no_cash"}
    if offer.get("executor") == "balance_credit" and "client_callback" in can:
        return {"executor": "client_callback", "why": "units_beat_cash"}
    return None


def review(offer: dict, ctx: dict | None = None) -> dict:
    """Разбор одного оффера по методологии.

    ctx (всё необязательно, чего нет - та проверка молчит):
      cost_basis, gross_margin, monthly_margin, cash, gift_budget,
      stage, reason, available_tiers, can_execute, has_topup.

    Возвращает {verdict, flags, alternative, tier, durability}.
    verdict: 'harmful' | 'weak' | 'ok' - по самому строгому замечанию.
    """
    ctx = ctx or {}
    flags = []
    for check in CHECKS:
        flags.extend(check(offer, ctx))

    levels = {f["level"] for f in flags}
    verdict = HARMFUL if HARMFUL in levels else (WEAK if WEAK in levels else "ok")
    # сначала то, что вредит, потом то, что слабо, потом оговорки
    order = {HARMFUL: 0, WEAK: 1, NOTE: 2}
    flags.sort(key=lambda f: order.get(f["level"], 3))
    # Три замечания - потолок: стена из пяти пунктов на одной карточке
    # перестаёт читаться, а главное уже наверху.
    flags = flags[:3]

    executor = str(offer.get("executor") or "")
    uplift, source = uplift_or_prior(ctx.get("measured"), executor)
    return {
        "verdict": verdict,
        "flags": flags,
        "alternative": alternative(offer, ctx) if verdict != "ok" else None,
        "tier": tier_of(offer, ctx.get("cash")),
        "durability": RETENTION_DURABILITY.get(executor, 1.0),
        "uplift": uplift,
        "uplift_source": source,
    }


# Замечания про КЛИЕНТА, а не про подарок: себестоимость неизвестна, лимиты
# считаются в штуках. Повторённые на каждой карточке, они превращаются в шум и
# заслоняют то, что относится именно к этому подарку.
CATALOG_WIDE = ("cost_is_assumed", "cost_is_list_price", "cap_counted_in_pieces")


def review_catalog(offers: list, ctx: dict | None = None) -> list:
    """Разбор всего каталога сразу.

    Ступени считаются по КАТАЛОГУ: замечание «есть рычаг дешевле» имеет смысл
    только когда этот рычаг у клиента действительно есть.
    """
    ctx = ctx or {}
    # Ступени считаются ВНУТРИ РОЛИ: подарок для «не начал пользоваться» и
    # пауза для «собирается уходить» уйдут разным людям - советовать одному
    # ступень другого значит предлагать нелепое.
    tiers_by_role: dict = {}
    for o in offers or []:
        role = str(o.get("role") or "").lower()
        cash = o.get("_cash") if o.get("_cash") is not None else ctx.get("cash")
        tiers_by_role.setdefault(role, set()).add(tier_of(o, cash))
    executors = {str(o.get("executor") or "") for o in offers or []}
    shared = {**ctx, "can_execute": set(ctx.get("can_execute") or executors)}
    out = []
    for offer in offers or []:
        own = dict(shared)
        own["available_tiers"] = tiers_by_role.get(
            str(offer.get("role") or "").lower(), set())
        if offer.get("_cash") is not None:
            own["cash"] = offer["_cash"]
        if offer.get("_stage"):
            own["stage"] = offer["_stage"]
        out.append({"offer_id": offer.get("offer_id"), **review(offer, own)})
    return out


def split_catalog_notes(reviewed: list) -> tuple[list, list]:
    """(разборы без общих замечаний, общие замечания одним списком).

    Одно и то же «себестоимость неизвестна» на пяти карточках читается как
    пять разных проблем. Общее показывается один раз над списком.
    """
    seen, notes = set(), []
    for item in reviewed:
        keep = []
        for flag in item.get("flags", []):
            if flag["code"] not in CATALOG_WIDE:
                keep.append(flag)
            elif flag["code"] not in seen:
                seen.add(flag["code"])
                notes.append(flag)
        item["flags"] = keep
    # verdict не трогаем: общие замечания все уровня note и на него не влияли
    return reviewed, notes
