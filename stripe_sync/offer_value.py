"""Универсальная логика расчёта офферов: что дать, кому и стоит ли вообще.

ЗАЧЕМ ЭТОТ МОДУЛЬ. Каталог офферов собирался правилами: «есть триал - будет
продление, есть потолок скидки - будет скидка». Это отвечает на вопрос «что мы
УМЕЕМ дать», но не на вопрос «что дать ЭТОМУ человеку СЕЙЧАС и не потеряем ли
мы на этом деньги». Разбор юнит-экономики клиента с видео-генерацией показал,
что второй вопрос главный: один и тот же подарок в одном бизнесе бесплатен, а
в другом дороже самого клиента.

ОДИН ПРИНЦИП, ИЗ КОТОРОГО СЛЕДУЕТ ВСЁ ОСТАЛЬНОЕ.

    Оффер - это сделка: мы отдаём часть маржи сейчас, чтобы сохранить поток
    маржи потом. Он оправдан ровно тогда, когда сохранённая маржа больше
    отданной.

        EV = прирост_удержания x маржа_на_кону
             - живые_деньги
             - вероятность_остаться x недополученная_выручка

АСИММЕТРИЯ, КОТОРУЮ ВСЕ ПУТАЮТ. В этой формуле два расхода вычитаются
ПО-РАЗНОМУ, и это не тонкость, а суть:

  • ЖИВЫЕ ДЕНЬГИ (себестоимость подаренного, кредит на баланс, товар) уходят
    ВСЕГДА - и когда человек остался, и когда ушёл. Их платят вперёд, и они
    не возвращаются.
  • НЕДОПОЛУЧЕННАЯ ВЫРУЧКА (скидка, бесплатная доставка, отказ от комиссии)
    возникает ТОЛЬКО ЕСЛИ человек остался и заплатил. Если ушёл - вы не
    потеряли ничего.

Отсюда универсальный вывод: скидка сама себя финансирует, подарок
себестоимостью - нет. Поэтому при равной силе всегда сначала предлагают то,
что режет маржу, и лишь потом то, что уносит деньги.

ЛЕСТНИЦА УСТУПОК. Из той же асимметрии следует порядок, годный любому бизнесу:

  0 слово         - написать, напомнить, объяснить, позвать. Стоит нуля.
  1 отсрочка      - пауза, продление, разморозка. Выручка сдвигается, не гибнет.
  2 чужая маржа   - скидка на докупку, отказ от комиссии, доставка. Режем
                    маржу конкретной сделки, живых денег не тратим.
  3 своя выручка  - скидка на подписку. Платим только если человек остался.
  4 живые деньги  - бонус себестоимостью, денежный кредит, физический товар.
                    Платим независимо от результата.

Правило: НЕ ПЕРЕПРЫГИВАТЬ СТУПЕНЬ, пока предыдущая не испробована на этом
человеке. И: максимальная доступная ступень зависит от того, сколько маржи на
кону. На клиенте за $9 в месяц живые деньги не тратят никогда.

БЮДЖЕТ ВМЕСТО ЧАСТОТЫ. «Не чаще раза в 30 дней» - неверная единица измерения:
она одинакова для клиента за $9 и за $399. Правильная единица - доля от маржи,
которую этот человек ещё принесёт. Бюджет подарков человеку это
SAFE_SHARE x его_оставшаяся_маржа, и он тратится, а не обнуляется календарём.

ЧЕМ ЗАПОЛНЯТЬ ЧИСЛА, КОГДА ИХ НЕТ. Три источника по убыванию честности:
измеренный uplift кампании -> ответ владельца -> прайор типа бизнеса
(archetypes). Источник всегда возвращается вместе с числом: решение, принятое
на прайоре, обязано выглядеть иначе, чем решение на измерении.
"""

from __future__ import annotations

# Доля оставшейся маржи человека, которую вообще допустимо отдать подарками.
# Выше этого удержание перестаёт быть выгодным арифметически, а не по вкусу.
SAFE_BUDGET_SHARE = 0.25

# Ступени лестницы уступок - от бесплатного к необратимому.
TIER_WORD, TIER_DEFER, TIER_OTHER_MARGIN, TIER_OWN_REVENUE, TIER_CASH = range(5)

TIER_NAMES = {
    TIER_WORD: "слово",
    TIER_DEFER: "отсрочка",
    TIER_OTHER_MARGIN: "маржа сделки",
    TIER_OWN_REVENUE: "своя выручка",
    TIER_CASH: "живые деньги",
}

# Исполнитель -> ступень. Ступень определяется ТЕМ, ЧЕМ ПЛАТИМ, а не тем, как
# подарок называется у клиента.
EXECUTOR_TIER = {
    "message": TIER_WORD,
    "pause_collection": TIER_DEFER,
    "trial_extend": TIER_DEFER,
    "stripe_coupon": TIER_OWN_REVENUE,
    "balance_credit": TIER_CASH,
}

# Сколько маржи на кону нужно, чтобы ступень вообще стала доступна. Тратить
# живые деньги на клиента за $9/мес нельзя ни при какой вероятности спасения.
TIER_MIN_STAKE = {
    TIER_WORD: 0.0,
    TIER_DEFER: 0.0,
    TIER_OTHER_MARGIN: 5.0,
    TIER_OWN_REVENUE: 15.0,
    TIER_CASH: 40.0,
}


def tier_of(offer: dict, cash: float | None = None) -> int:
    """На какой ступени лестницы стоит оффер.

    client_callback универсален: им начисляют и бонус себестоимостью, и скидку
    на докупку. Поэтому ступень решает не исполнитель, а деньги: уходит живое -
    верхняя ступень, режется маржа сделки - средняя.
    """
    executor = str(offer.get("executor") or "")
    if executor in EXECUTOR_TIER:
        tier = EXECUTOR_TIER[executor]
        # продление триала в продукте с реальной себестоимостью - уже не отсрочка
        if executor == "trial_extend" and (cash or 0) > 0:
            return TIER_CASH
        return tier
    if executor == "client_callback":
        params = offer.get("params") or {}
        if str(params.get("command") or "").endswith("_discount"):
            return TIER_OTHER_MARGIN
        return TIER_CASH if (cash is None or cash > 0) else TIER_DEFER
    return TIER_OWN_REVENUE


def margin_at_stake(monthly_margin: float | None, expected_months: float | None,
                    churn_risk: float | None = None) -> float | None:
    """Сколько МАРЖИ этот человек принесёт, если останется.

    Это и есть приз, ради которого делается подарок. Считать его в выручке -
    та же ошибка, что считать стоимость подарка в цене: приз раздувается, и
    любая уступка начинает выглядеть оправданной.
    """
    # margin==0.0 - это ИЗМЕРЕННЫЙ ноль («маржи нет»), НЕ «неизвестно»: ставка
    # честно 0, и её нельзя схлопывать в None - иначе все экономические гарды
    # в rank() (stake_too_small/budget/negative_value) молча отключаются, и
    # cash-подарок выдаётся в худшем для бизнеса состоянии (аудит 2026-08-26).
    if monthly_margin is None or not expected_months:
        return None
    stake = float(monthly_margin) * float(expected_months)
    if churn_risk is not None:
        # то, что и так почти наверняка уйдёт, стоит меньше: приз взвешивается
        # вероятностью, что он вообще достанется
        stake *= max(0.0, 1.0 - float(churn_risk))
    return round(stake, 2)


def gift_budget(stake: float | None, spent: float = 0.0,
                share: float = SAFE_BUDGET_SHARE) -> float | None:
    """Сколько ещё можно потратить на этого человека.

    Заменяет календарный лимит «раз в 30 дней»: тот одинаков для клиента за $9
    и за $399, а бюджет масштабируется сам.
    """
    if stake is None:
        return None
    return round(max(0.0, float(stake) * share - float(spent)), 2)


def expected_value(cash: float | None, revenue: float | None,
                   uplift: float | None, stake: float | None,
                   base_stay: float = 0.5, executor: str = "") -> dict:
    """Стоит ли оффер того. Возвращает EV и разобранные слагаемые.

    uplift    - НАСКОЛЬКО оффер поднимает удержание (0.06 = на 6 п.п.);
    stake     - маржа, которую человек принесёт, если останется;
    base_stay - вероятность остаться БЕЗ оффера (нужна, чтобы понять, с какой
                вероятностью мы вообще заплатим по скидке).

    Живые деньги вычитаются целиком: они уходят и при провале. Недополученная
    выручка - только с вероятностью, что человек останется и заплатит.
    """
    if stake is None or uplift is None:
        return {"ev": None, "gain": None, "cost": None,
                "note": "не хватает маржи на кону или замера эффекта"}

    # Сохранённая маржа - НЕ вся маржа на кону: удержанный скидкой уходит в
    # 70-80% случаев, удержанный паузой в основном возвращается к обычной
    # оплате. Без этой поправки скидка всегда выигрывает у паузы на бумаге.
    keeps = RETENTION_DURABILITY.get(executor, 1.0) if executor else 1.0
    gain = float(stake) * float(uplift) * keeps
    stay = min(1.0, max(0.0, float(base_stay) + float(uplift)))
    cash_cost = float(cash or 0)
    rev_cost = float(revenue or 0) * stay
    ev = round(gain - cash_cost - rev_cost, 2)

    if ev > 0:
        note = (f"сохраняет ${gain:.2f} маржи, стоит ${cash_cost + rev_cost:.2f} - "
                f"остаётся ${ev:.2f}")
    else:
        note = (f"стоит ${cash_cost + rev_cost:.2f}, а сохраняет только "
                f"${gain:.2f} - в минус на ${-ev:.2f}")
    return {"ev": ev, "gain": round(gain, 2), "durability": keeps,
            "cost": round(cash_cost + rev_cost, 2),
            "cash": round(cash_cost, 2), "revenue_expected": round(rev_cost, 2),
            "stay_probability": round(stay, 3), "note": note}


def rank(candidates: list, stake: float | None, budget: float | None = None,
         tried_tiers: set | None = None, base_stay: float = 0.5,
         churn_risk: float | None = None, reason: str = "",
         attempts: int = 0, tier_name: str = "regular") -> list:
    """Упорядочить офферы для конкретного человека: сначала дешёвые и годные.

    candidates - [{offer_id, executor, params, cash, revenue, uplift}];
    stake      - маржа на кону у этого человека;
    budget     - сколько ещё можно на него потратить;
    tried_tiers- какие ступени ему уже предлагали (лестницу не перепрыгиваем).

    Возвращает тот же список, обогащённый ступенью, EV и причиной отказа.
    Ничего не отбрасывает молча: отклонённые остаются с полем `blocked`.
    """
    tried = tried_tiers or set()
    tiers = {c.get("offer_id"): tier_of(c, c.get("cash")) for c in candidates or []}
    # Вход в лестницу - самая дешёвая ступень СРЕДИ ИМЕЮЩИХСЯ и ещё не
    # испробованных. Считать его от абстрактной нулевой ступени нельзя: если
    # оффера-«слова» в каталоге нет, заблокированным окажется вообще всё.
    lowest_untried = min((t for t in tiers.values() if t not in tried),
                         default=TIER_CASH)

    wanted = offer_for_reason(reason)

    out = []
    for c in candidates or []:
        cash = c.get("cash")
        executor = str(c.get("executor") or "")
        tier = tiers[c.get("offer_id")]
        value = expected_value(cash, c.get("revenue"), c.get("uplift"),
                               stake, base_stay, executor)
        # Причина отказа - КОД с числами, а не готовая фраза. Готовую фразу
        # нельзя показать в интерфейсе на другом языке, а логика отказа нужна
        # и экрану, и логам, и тестам.
        blocked = None
        if tier >= TIER_OTHER_MARGIN and give_up(attempts, tier_name):
            # человек уже решил; каждая следующая выдача по отдельности
            # выглядит оправданной, и именно так уходит весь бюджет
            blocked = {"code": "enough_attempts", "attempts": int(attempts)}
        elif wakes_a_sleeping_dog(executor, churn_risk, tier >= TIER_OTHER_MARGIN):
            # он и так остаётся - подарок ему не нужен, а напоминание о том,
            # что он платит, может стоить нам этого человека
            blocked = {"code": "would_stay_anyway",
                       "risk": round(float(churn_risk), 2)}
        elif wanted["matched"] and wanted["executor"] is None \
                and tier >= TIER_OTHER_MARGIN:
            # причина ухода известна, и деньги под неё не работают
            blocked = {"code": "reason_needs_no_gift", "reason": reason}
        elif wanted["matched"] and wanted["executor"] \
                and executor != wanted["executor"] and tier >= TIER_OTHER_MARGIN:
            blocked = {"code": "reason_wants_another_lever", "reason": reason,
                       "executor": wanted["executor"]}
        elif stake is not None and stake < TIER_MIN_STAKE.get(tier, 0):
            blocked = {"code": "stake_too_small", "stake": round(stake, 2),
                       "tier": tier}
        elif budget is not None and (cash or 0) + (c.get("revenue") or 0) > budget:
            blocked = {"code": "budget_spent", "budget": round(budget, 2)}
        elif tier > lowest_untried:
            blocked = {"code": "cheaper_rung_first", "tier": lowest_untried}
        elif value["ev"] is not None and value["ev"] <= 0:
            blocked = {"code": "negative_value", "gain": value["gain"],
                       "cost": value["cost"]}
        out.append({**c, "tier": tier, "tier_name": TIER_NAMES[tier],
                    **value, "blocked": blocked})

    # годные вперёд; среди годных - дешёвая ступень раньше, при равной ступени
    # больший EV раньше
    out.sort(key=lambda x: (bool(x["blocked"]), x["tier"], -(x["ev"] or 0)))
    return out


def choose(candidates: list, stake: float | None, budget: float | None = None,
           tried_tiers: set | None = None, base_stay: float = 0.5,
           churn_risk: float | None = None, reason: str = "") -> dict | None:
    """Один оффер, который надо выдать сейчас. None - не выдавать ничего.

    «Не выдавать ничего» - полноправный ответ, а не сбой: если всё, что мы
    умеем, в минусе, честнее промолчать, чем подарить деньги.
    """
    ranked = rank(candidates, stake, budget, tried_tiers, base_stay,
                  churn_risk, reason)
    for item in ranked:
        if not item["blocked"]:
            return item
    return None


def uplift_or_prior(measured: dict | None, executor: str,
                    archetype: str = "") -> tuple[float, str]:
    """Эффект оффера: измеренный, иначе прайор. Всегда с указанием источника.

    Решение на измерении и решение на прайоре обязаны выглядеть по-разному,
    иначе догадка через месяц читается как факт.

    Прайоры откалиброваны по публичным замерам, а не по вкусу: паузой
    пользуется около половины тех, кто собирался отменить, и три четверти из
    них возвращаются - поэтому у неё эффект заметно выше, чем у скидки.
    """
    if measured and measured.get("confident") and measured.get("uplift") is not None:
        return float(measured["uplift"]), "measured"
    # Переоценка эффекта - главный способ обосновать подарок, который на деле
    # ничего не меняет, поэтому прайоры осознанно скромные.
    # ВАЛЮТА ПРОДУКТА БЬЁТ ДЕНЬГИ. В A/B на 2000 спящих игроков подарок во
    # внутренней валюте дал 14.9% возврата против 5.4% у денежного бонуса
    # ТОЙ ЖЕ стоимости - втрое, при меньшей воспринимаемой щедрости. Деньги
    # читаются как откуп, а валюта продукта - как повод вернуться в продукт.
    priors = {"pause_collection": 0.18, "trial_extend": 0.08,
              "client_callback": 0.09, "stripe_coupon": 0.06,
              "balance_credit": 0.03, "message": 0.03}
    return priors.get(executor, 0.04), "prior"


# ВНИМАНИЕ РАЗНОЙ ЦЕНЫ. В нишах с самым долгим опытом удержания (iGaming)
# «затих» - это не одно событие: у крупного клиента неделя тишины уже тревога,
# у разового покупателя это норма. Реакция на первый день тишины возвращает до
# 27% ушедших, а ожидание до тридцатого дня стоит в пять раз дороже за
# возврат - но только для тех, кого стоит ловить так рано.
#
# Одинаковый порог тишины для всех - это одновременно и ложная тревога по
# мелким, и опоздание по крупным.
QUIET_WINDOW_DAYS = {"top": 7, "regular": 14, "light": 30}


def value_tier(monthly_margin: float | None, median_margin: float | None) -> str:
    """Насколько этот клиент дороже обычного: 'top' | 'regular' | 'light'.

    Считается от МЕДИАНЫ по базе, а не от абсолютных сумм: «крупный» у одного
    клиента $400 в месяц, у другого $40, и зашивать это числом нельзя.
    """
    if not monthly_margin or not median_margin:
        return "regular"
    ratio = float(monthly_margin) / float(median_margin)
    if ratio >= 2.0:
        return "top"
    if ratio < 0.5:
        return "light"
    return "regular"


def quiet_window(tier: str) -> int:
    """Через сколько дней тишины этот клиент считается тревожным."""
    return QUIET_WINDOW_DAYS.get(tier, QUIET_WINDOW_DAYS["regular"])


# КОГДА ПЕРЕСТАТЬ ПЛАТИТЬ. Операторы ставят жёсткий предел в 3-5 попыток
# вернуть человека, после чего он уходит в спящий список и бюджет
# перераспределяется. Без такого предела система бесконечно тратит на тех,
# кто уже решил, и это не видно ни в одном отчёте: каждая выдача по
# отдельности выглядит оправданной.
MAX_SAVE_ATTEMPTS = 4


def give_up(attempts: int, tier: str = "regular") -> bool:
    """Пора ли перестать тратить на этого человека.

    Крупному клиенту даём на одну попытку больше: там на кону заметно больше
    маржи, и это единственная причина, по которой предел вообще двигается.
    """
    limit = MAX_SAVE_ATTEMPTS + (1 if tier == "top" else 0)
    return int(attempts or 0) >= limit


# СПАСЁННЫЙ СПАСЁННОМУ РОЗНЬ. Удержание скидкой заканчивается уходом в 70-80%
# случаев, а сама скидка снижает пожизненную ценность примерно на треть:
# человек остаётся до конца акции и уходит, как только она кончается. Пауза
# наоборот - три четверти вернувшихся возвращаются к обычной оплате.
#
# Поэтому сохранённая маржа умножается на ДОЛГОВЕЧНОСТЬ рычага. Без этого
# скидка выглядит в расчёте сильнее, чем она есть, и всегда побеждает.
RETENTION_DURABILITY = {
    "message": 1.0,
    "pause_collection": 0.75,
    "trial_extend": 0.7,
    "client_callback": 0.6,
    "balance_credit": 0.35,
    "stripe_coupon": 0.25,
}

# СПЯЩИЕ СОБАКИ. В замерах удерживающих кампаний 4-5% людей уходят ИМЕННО
# ПОТОМУ, что их потревожили: они бы остались, но письмо «мы заметили, что вы
# собираетесь уйти, вот скидка» напомнило им, что они платят. Целиться по
# «риску ухода» - худший способ их найти: там они и сидят.
#
# Правило: денежный подарок не уходит тому, чей риск ухода низкий. Ему нечего
# спасать, а разбудить его можно.
SLEEPING_DOG_RISK_FLOOR = 0.25


def durable_gain(stake: float | None, uplift: float | None,
                 executor: str) -> float | None:
    """Сколько маржи рычаг сохраняет НА САМОМ ДЕЛЕ, с поправкой на долговечность."""
    if stake is None or uplift is None:
        return None
    return round(float(stake) * float(uplift)
                 * RETENTION_DURABILITY.get(executor, 0.6), 2)


def wakes_a_sleeping_dog(executor: str, churn_risk: float | None,
                         monetary: bool = True) -> bool:
    """Разбудит ли это касание того, кто и так собирался остаться."""
    if not monetary or executor == "message":
        return False
    if churn_risk is None:
        return False
    return float(churn_risk) < SLEEPING_DOG_RISK_FLOOR


# ЧТО ПРЕДЛАГАТЬ ПОД КОНКРЕТНУЮ ПРИЧИНУ УХОДА. Общий оффер спасает 5-10%
# уходящих, подобранный под названную причину - 15-30%. Это самый дешёвый
# известный способ удвоить спасение: причину человек уже сам написал.
#
# offer=None значит НЕ ПРЕДЛАГАТЬ НИЧЕГО. Это не пробел, а вывод: тому, кто
# уходит из-за отсутствующей функции, скидка не помогает, и настаивать -
# значит превращать удержание в тёмный паттерн.
REASON_PLAYBOOK = {
    "price": {"executor": "stripe_coupon", "why": "уходит из-за денег - "
              "единственный случай, где скидка действительно к месту"},
    "one_time_need": {"executor": "pause_collection", "why": "задача кончилась, "
                      "а не продукт разонравился: пауза сохраняет человека "
                      "до следующего раза, скидка ему не нужна"},
    "missing_feature": {"executor": None, "why": "скидка не заменяет функцию: "
                        "таким людям помогает письмо о выходе нужной "
                        "возможности, а не деньги"},
    "quality": {"executor": None, "why": "платить человеку за то, что продукт "
                "работал плохо - это откуп, а не удержание"},
    "support": {"executor": None, "why": "проблема была в людях, а не в цене: "
                "деньгами она не закрывается"},
    "switched": {"executor": "pause_collection", "why": "уже пробует другое: "
                 "пауза оставляет дверь открытой, а скидка сейчас проиграет "
                 "гонку предложений"},
}


def offer_for_reason(reason: str) -> dict:
    """Какой рычаг уместен под названную причину ухода.

    Причина неизвестна - обычный порядок лестницы: гадать вредно, а
    подобранный «на всякий случай» подарок и есть та самая раздача.
    """
    card = REASON_PLAYBOOK.get(str(reason or "").strip().lower())
    if not card:
        return {"executor": None, "why": "", "matched": False}
    return {**card, "matched": True}
