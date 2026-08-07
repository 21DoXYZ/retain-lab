"""Предложения по офферам НА ОСНОВАНИИ ДАННЫХ клиента (не по вкусу модели).

Каталог собирается один раз на онбординге и дальше стоит мёртвым грузом, пока
владелец сам не догадается его поправить. Этот модуль смотрит на живую картину
и говорит: «вот здесь ты теряешь деньги, вот конкретное действие, вот факты».

ПРАВИЛО ЧЕСТНОСТИ: каждое предложение обязано нести ФАКТЫ из данных клиента
(сколько людей, сколько отказов, какие суммы). Нет фактов - нет предложения.
Ни одно предложение не применяется само: владелец жмёт кнопку.

Чистые функции: на вход снимок данных, на выходе список предложений. Без БД,
без сети - поэтому тестируется целиком.
"""

from __future__ import annotations

ROLE_STAGE = {
    "activation": "ACTIVATE",
    "conversion": "CONVERT",
    "dunning": "DUNNING",
    "save": "SAVE",
    "upgrade": "UPGRADE",
    "winback": "WINBACK",
}

# Сколько денег в месяц стоит рычаг, если его не закрыть: берём людей на
# стадии и то, что у них на кону (уже посчитано вьюхой user_actions).
MIN_PEOPLE = 1          # ниже этого предлагать нечего - это шум
CAP_HIT_THRESHOLD = 3   # столько отказов по лимиту за 30 дней = пора поднимать


def _fmt_money(x: float) -> str:
    return f"${x:,.0f}" if x >= 100 else f"${x:,.2f}".rstrip("0").rstrip(".")


def suggest(catalog: list, stages: dict, stage_value: dict, rejects: dict,
            answers: dict, avg_price: float, composed: list) -> list:
    """Список предложений, самые дорогие сверху.

    catalog      - действующие офферы тенанта (как на экране офферов);
    stages       - {стадия: сколько людей} из user_actions;
    stage_value  - {стадия: сумма value_at_stake} - деньги на кону;
    rejects      - {(offer_id, reason): сколько раз за 30 дней};
    answers      - ответы опросника (лимиты, потолок скидки, юнит);
    avg_price    - средний чек;
    composed     - что собрали бы правила compose_offers на этих ответах
                   (готовые к добавлению офферы под каждую роль).
    """
    out: list = []
    have_roles = {str(o.get("role") or "") for o in catalog if not o.get("disabled")}
    by_role = {str(o.get("role") or ""): o for o in composed}
    enabled_ids = {o["offer_id"] for o in catalog}

    # 1. СТАДИЯ ЕСТЬ, ОФФЕРА НЕТ. Самое дорогое: люди уходят, а предложить
    #    нечего - шаг цепочки отбивается как no_offer_bound.
    for role, stage in ROLE_STAGE.items():
        people = int(stages.get(stage) or 0)
        if people < MIN_PEOPLE or role in have_roles:
            continue
        ready = by_role.get(role)
        if not ready or ready["offer_id"] in enabled_ids:
            continue
        money = float(stage_value.get(stage) or 0)
        out.append({
            "id": f"role_gap:{role}",
            "kind": "add_offer",
            "priority": money or people,
            "title": ready.get("title") or ready["offer_id"],
            "why": (f"На стадии «{stage}» сейчас {people} чел., "
                    f"на кону {_fmt_money(money)}/мес, а предложить им нечего: "
                    f"шаг цепочки отбивается как «оффер не привязан»."),
            "offer": ready,
        })

    # 2. ОФФЕР УПИРАЕТСЯ В СВОЙ ЛИМИТ. Люди доходили до подарка, но мы им
    #    отказывали своей же настройкой.
    for (offer_id, reason), count in rejects.items():
        if reason not in ("offer_limit_30d", "monetary_cap_14d") or count < CAP_HIT_THRESHOLD:
            continue
        current = next((o for o in catalog if o["offer_id"] == offer_id), None)
        if not current:
            continue
        cap = int(current.get("max_per_user_30d") or 0)
        out.append({
            "id": f"cap:{offer_id}:{reason}",
            "kind": "raise_cap",
            "priority": count * float(current.get("cost_estimate") or 1),
            "title": current.get("title") or offer_id,
            "why": (f"За 30 дней {count} раз не выдали этот оффер: "
                    + ("уже давали монетарный подарок за последние 14 дней."
                       if reason == "monetary_cap_14d"
                       else f"упёрлись в лимит {cap} раз(а) на человека.")
                    + " Люди доходили до подарка, а мы отказывали своей настройкой."),
            "offer": {"offer_id": offer_id, "max_per_user_30d": max(cap + 1, 2)},
        })

    # 3. НЕТ ИСПОЛНИТЕЛЯ. Оффер настроен, но выдать его технически нечем.
    broken = {}
    for (offer_id, reason), count in rejects.items():
        if reason in ("callback_not_configured", "stripe_not_configured",
                      "offer_not_found", "offer_disabled"):
            broken[(offer_id, reason)] = count
    for (offer_id, reason), count in broken.items():
        out.append({
            "id": f"broken:{offer_id}:{reason}",
            "kind": "fix",
            "priority": count * 10,
            "title": offer_id,
            "why": (f"{count} раз(а) за 30 дней оффер не удалось выдать: "
                    + ("не задан адрес начисления бонусов в вашем продукте."
                       if reason == "callback_not_configured"
                       else "не подключён ключ Stripe для купонов."
                       if reason == "stripe_not_configured"
                       else "оффер выключен или удалён, а шаг цепочки на него ссылается.")),
            "offer": None,
        })

    # 4. ДЕШЁВЫЙ РЫЧАГ ВМЕСТО ДОРОГОГО. Если единственное, что мы умеем на
    #    удержание - скидка, это самый дорогой способ: он режет выручку
    #    навсегда. Предлагаем бесплатную альтернативу.
    monetary = [o for o in catalog if o.get("monetary") and not o.get("disabled")]
    free_saves = [o for o in catalog
                  if str(o.get("role")) == "save" and not o.get("monetary")]
    if monetary and not free_saves and by_role.get("save"):
        ready = by_role["save"]
        if ready["offer_id"] not in enabled_ids:
            cost = sum(float(o.get("cost_estimate") or 0) for o in monetary)
            out.append({
                "id": "cheap_first:save",
                "kind": "add_offer",
                "priority": cost or 1,
                "title": ready.get("title") or ready["offer_id"],
                "why": (f"Все ваши удерживающие офферы стоят денег "
                        f"(себестоимость до {_fmt_money(cost)} за выдачу). "
                        f"Пауза подписки ничего не стоит и часто удерживает "
                        f"не хуже скидки - её честно попробовать первой."),
                "offer": ready,
            })

    # 5. ПУСТОЙ КАТАЛОГ. Ничего не собрано - предлагать по одному бессмысленно,
    #    отправляем на опросник (он соберёт весь набор за три минуты).
    if not catalog:
        people = sum(int(v or 0) for v in stages.values())
        out = [{
            "id": "empty_catalog",
            "kind": "questionnaire",
            "priority": 10_000,
            "title": "Собрать стартовый набор офферов",
            "why": (f"Каталог пуст, а система уже видит {people} чел. "
                    if people else "Каталог пуст. ")
                   + "Девять вопросов о продукте - и набор соберётся по вашим "
                     "лимитам, чеку и потолку скидки.",
            "offer": None,
        }]

    out.sort(key=lambda x: -float(x["priority"]))
    return out[:6]
