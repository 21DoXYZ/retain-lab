"""Гигиена офферов (ТЗ §121) — чистые функции в стиле chains/checks.py.

Каждая проверка получает данные явно и возвращает (ok, reason): reason пуст при
ok, иначе короткий машинный код (пишется в offers_issued.reason).

Правила:
  • high_p_convert   — монетарный оффер не выдаётся НЕплатящему с высоким
                       P(convert): купит и без скидки (антиканнибализация).
                       К платящим (DUNNING/SAVE) не применяется — там P=1.0
                       по определению, а оффер спасает revenue, не конвертирует.
  • monetary_cap_14d — не чаще 1 монетарного оффера в 14 дней на юзера
                       (считаются issued/dry_run; holdout и rejected — нет).
  • offer_limit_30d  — max_per_user_30d из каталога (по конкретному offer_id).

Holdout: детерминированный сплит md5(tenant:campaign:identity) % 100 <
control_pct — тот же контракт, что cityHash64-механизм chains/runner.py.
"""

from __future__ import annotations

import hashlib
from typing import Any

PAYING_STATUSES = {"active", "past_due"}


def check_p_convert_cap(offer: dict, user: dict, cap: float) -> tuple[bool, str]:
    if not offer.get("monetary"):
        return True, ""
    if (user.get("sub_status") or "") in PAYING_STATUSES:
        return True, ""
    if float(user.get("p_convert") or 0.0) >= cap:
        return False, "high_p_convert"
    return True, ""


def check_monetary_cap_14d(offer: dict, history_14d: list[dict]) -> tuple[bool, str]:
    """history_14d: строки offers_issued этого юзера за 14 дней."""
    if not offer.get("monetary"):
        return True, ""
    for row in history_14d:
        if row.get("monetary") and row.get("status") in ("issued", "dry_run"):
            return False, "monetary_cap_14d"
    return True, ""


def check_offer_limit_30d(offer: dict, history_30d: list[dict]) -> tuple[bool, str]:
    limit = int(offer.get("max_per_user_30d") or 0)
    if limit <= 0:
        return True, ""
    count = sum(1 for row in history_30d
                if row.get("offer_id") == offer["offer_id"]
                and row.get("status") in ("issued", "dry_run"))
    if count >= limit:
        return False, "offer_limit_30d"
    return True, ""


# Стадии, которые САМИ по себе означают подтверждённый риск: их считает живая
# вьюха по событиям, а скор p_churn пересчитывается раз в сутки. Если человек
# открыл отмену в 10 утра, ночной скор про это ещё не знает - и гейт «дарим
# только рискующим» зарубил бы именно то касание, ради которого всё строилось.
RISK_STAGES = ("SAVE", "DUNNING", "WINBACK")


def check_churn_floor(offer: dict, user: dict, floor: float) -> tuple[bool, str]:
    """Деньги не дарим спокойным: монетарный оффер платящему юзеру с низким
    P(churn) - трата без причины (он и так остаётся). Порог 0 = выключено.
    Зеркало p_convert_cap с другой стороны воронки: там «купит и без скидки»,
    тут «останется и без подарка»."""
    if not offer.get("monetary") or floor <= 0:
        return True, ""
    if str(user.get("sub_status") or "") not in PAYING_STATUSES:
        return True, ""   # неплатящих этот гейт не касается
    if str(user.get("stage") or "") in RISK_STAGES:
        return True, ""   # риск уже подтверждён событиями, скор вторичен
    p_churn = user.get("p_churn")
    if p_churn is None:
        return True, ""   # скора нет (джоб ещё не считал) - не блокируем
    if float(p_churn) < floor:
        return False, "low_churn_risk"
    return True, ""


def run_checks(offer: dict, user: dict, history_14d: list[dict],
               history_30d: list[dict], p_convert_cap: float,
               churn_floor: float = 0.0) -> tuple[bool, str]:
    """Все проверки по порядку; первый отказ — итог."""
    for ok, reason in (
        check_p_convert_cap(offer, user, p_convert_cap),
        check_churn_floor(offer, user, churn_floor),
        check_monetary_cap_14d(offer, history_14d),
        check_offer_limit_30d(offer, history_30d),
    ):
        if not ok:
            return False, reason
    return True, ""


def holdout_split(tenant_id: str, campaign_id: str, identity_id: str,
                  control_pct: int) -> bool:
    """True = контрольная группа (оффер логируется, но НЕ исполняется)."""
    if control_pct <= 0:
        return False
    digest = hashlib.md5(f"{tenant_id}:{campaign_id}:{identity_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100 < control_pct
