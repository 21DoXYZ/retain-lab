"""Тип экономики бизнеса: то, что сайт МОЖЕТ сказать о себестоимости.

ЗАЧЕМ. Разбор юнит-экономики одного клиента (видео-генерация: подписка продана
почти по себестоимости, маржа только в докупке) показал, что стоимость подарка
нельзя считать по цене. Но себестоимость на сайте не написана НИКОГДА - её не
публикует никто. Возникает вопрос: как получать такой же разбор для бизнеса,
про который мы знаем только сайт.

ОТВЕТ. Сайт не назовёт число, но он почти всегда выдаёт ТИП экономики, а у типа
известна форма:
  • в каком диапазоне лежит валовая маржа;
  • где эта маржа находится - в подписке, в докупке, в комиссии, в загрузке;
  • какой рычаг удержания дешёвый, а какой уносит живые деньги;
  • что в этой модели дарить нельзя вообще;
  • какие два-три числа надо спросить у владельца, чтобы догадки стали счётом.

Поэтому здесь не «угадывание себестоимости», а маршрутизация: тип -> вопросы ->
настоящая арифметика в economics.py.

ЧЕСТНОСТЬ. Диапазон маржи типа - ЯВНОЕ ПРЕДПОЛОЖЕНИЕ, оно помечается
basis='assumed' и живёт ровно до первого ответа владельца. Оно нужно только
затем, чтобы не молчать: без него система подставляет цену вместо
себестоимости, а это молчаливое допущение «маржа ноль» - худшее из возможных
для обычного софта.

ДВА ПУТИ ОПРЕДЕЛЕНИЯ. Модель (client_brief возвращает cost_archetype) и
детерминированный классификатор по словам сайта - он работает без ключа к
модели и служит проверкой её ответу.
"""

from __future__ import annotations

# margin_band  - в каком коридоре обычно лежит валовая маржа этого типа;
# margin_in    - откуда реально берётся прибыль (сюда нельзя бить скидкой);
# cheap/costly - рычаги по цене выдачи, а не по привычке;
# never        - что уничтожает модель, сколько бы ни удерживало;
# ask          - какие числа спросить, чтобы перестать предполагать.
ARCHETYPES = {
    "ai_usage": {
        "label": "оплата за генерацию",
        "margin_band": (0.10, 0.40),
        "margin_in": "overage",
        "why": ("Каждая единица ценности стоит живых денег провайдеру. Тариф "
                "часто продан почти по себестоимости, а прибыль приходит с "
                "докупки пакетов сверх лимита."),
        "cheap": ["pause", "topup_discount"],
        "costly": ["bonus_units", "credit", "trial_extension"],
        "never": ["безлимит", "постоянная скидка на тариф"],
        "ask": ["unit_cost_usd", "topup_price", "topup_units", "trial_units"],
    },
    "software_saas": {
        "label": "классический софт по подписке",
        "margin_band": (0.75, 0.90),
        "margin_in": "subscription",
        "why": ("Ещё один пользователь почти ничего не стоит. Дарить объём и "
                "функции дёшево, а скидка режет ту самую маржу, ради которой "
                "клиента и удерживают."),
        "cheap": ["bonus_units", "trial_extension", "feature_unlock", "pause"],
        "costly": ["discount", "credit"],
        "never": ["скидка навсегда"],
        "ask": ["gross_margin_pct"],
    },
    "per_seat_b2b": {
        "label": "оплата за место в команде",
        "margin_band": (0.75, 0.92),
        "margin_in": "expansion",
        "why": ("Рост выручки идёт от новых мест в тех же командах. "
                "Подаренное место убивает не себестоимость, а будущий рост: "
                "оно замещает продажу, а не расход."),
        "cheap": ["trial_extension", "feature_unlock", "pause"],
        "costly": ["discount", "credit"],
        "never": ["бесплатные места", "безлимит по местам"],
        "ask": ["gross_margin_pct", "seat_price"],
    },
    "marketplace": {
        "label": "комиссия со сделок",
        "margin_band": (0.60, 0.85),
        "margin_in": "take_rate",
        "why": ("Выручка - это комиссия, а не оборот. Отказ от комиссии на "
                "несколько сделок стоит только её саму и при этом растит "
                "оборот, с которого комиссия и берётся."),
        "cheap": ["fee_waiver", "listing_boost", "pause"],
        "costly": ["credit", "discount"],
        "never": ["комиссия ноль навсегда"],
        "ask": ["take_rate_pct", "avg_order_value"],
    },
    "ecommerce_physical": {
        "label": "физический товар",
        "margin_band": (0.25, 0.55),
        "margin_in": "order_margin",
        "why": ("Подарок - это реальная вещь плюс доставка, деньги уходят со "
                "склада и со счёта. Бесплатная доставка стоит только доставку "
                "и удерживает не хуже скидки на товар."),
        "cheap": ["free_shipping", "bundle"],
        "costly": ["free_product", "discount", "credit"],
        "never": ["подарок флагманского товара"],
        "ask": ["gross_margin_pct", "shipping_cost", "avg_order_value"],
    },
    "services": {
        "label": "услуги и работа людей",
        "margin_band": (0.30, 0.60),
        "margin_in": "capacity",
        "why": ("Подарок оплачивается не деньгами, а часами команды, которых "
                "конечное число. Дарить надо то, что делается один раз и "
                "используется многими - шаблон, разбор, доступ."),
        "cheap": ["template_access", "async_review", "pause"],
        "costly": ["extra_hours", "discount"],
        "never": ["дополнительный объём работ как подарок"],
        "ask": ["gross_margin_pct", "hour_cost"],
    },
    "infrastructure": {
        "label": "инфраструктура с оплатой по потреблению",
        "margin_band": (0.40, 0.70),
        "margin_in": "overage",
        "why": ("Потребление стоит денег, но маржа заметно шире, чем в "
                "генеративных продуктах: подарить объём можно, только зная "
                "его себестоимость."),
        "cheap": ["pause", "topup_discount", "trial_extension"],
        "costly": ["bonus_units", "credit"],
        "never": ["безлимитный объём"],
        "ask": ["unit_cost_usd", "gross_margin_pct"],
    },
}

DEFAULT = "software_saas"      # самый частый и самый безопасный по последствиям

# Слова сайта -> тип. Вес: сильный признак весит больше, чем упоминание вскользь.
SIGNALS = {
    "ai_usage": [
        (3, ("credits", "credit pack", "tokens", "generations", "per generation",
             "кредит", "генерац", "токен")),
        (3, ("per second", "per minute of video", "gpu", "rendering", "inference")),
        (2, ("ai video", "text-to-video", "image generation", "voice cloning",
             "text to speech", "diffusion", "нейросет")),
        (1, ("runs out", "top up", "докупить", "пополнить баланс")),
    ],
    "per_seat_b2b": [
        (3, ("per seat", "per user / month", "per user/month", "per editor",
             "за пользователя", "за место")),
        (2, ("invite your team", "workspace members", "admin roles", "sso", "scim")),
    ],
    "marketplace": [
        (3, ("commission", "take rate", "per transaction fee", "комисси",
             "% с продаж")),
        (2, ("buyers and sellers", "list your", "vendors", "become a seller",
             "продавц", "исполнител")),
    ],
    "ecommerce_physical": [
        (3, ("free shipping", "add to cart", "in stock", "size guide",
             "доставка", "корзин", "склад")),
        (2, ("returns within", "ships in", "warehouse", "tracking number")),
    ],
    "services": [
        (3, ("book a call", "our team will", "retainer", "per hour", "consulting",
             "агентств", "под ключ", "созвон")),
        (2, ("case studies", "we deliver", "onboarding call", "dedicated manager")),
    ],
    "infrastructure": [
        (3, ("per gb", "per request", "per million", "bandwidth", "egress",
             "compute hours", "uptime sla")),
        (2, ("regions", "api rate limit", "hosting", "database cluster")),
    ],
    "software_saas": [
        (2, ("unlimited projects", "all features included", "integrations",
             "dashboards", "automation", "unlimited")),
        (1, ("cancel anytime", "14-day free trial", "no credit card required")),
    ],
}


def classify(text: str, facts: dict | None = None) -> tuple[str, float, list]:
    """Тип экономики по тексту сайта: (тип, уверенность 0..1, сработавшие слова).

    Детерминированно и без сети: это и самостоятельный путь без ключа к модели,
    и проверка того, что модель не сочинила.
    """
    body = (text or "").lower()
    scores: dict[str, float] = {}
    hits: dict[str, list] = {}
    for kind, groups in SIGNALS.items():
        for weight, words in groups:
            for word in words:
                if word in body:
                    scores[kind] = scores.get(kind, 0) + weight
                    hits.setdefault(kind, []).append(word)

    # Лестница тарифов с БОЛЬШИМИ включёнными объёмами - признак оплаты за
    # потребление: «6000 кредитов» это не то же самое, что «5 проектов».
    for plan in ((facts or {}).get("plans") or []):
        try:
            units = float(plan.get("units_included") or 0)
        except (TypeError, ValueError):
            units = 0
        if units >= 1000:
            scores["ai_usage"] = scores.get("ai_usage", 0) + 2
            hits.setdefault("ai_usage", []).append("крупный лимит в тарифе")
            break

    if not scores:
        return DEFAULT, 0.0, []
    kind = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    confidence = round(scores[kind] / total, 2) if total else 0.0
    # Уверенность падает, когда второй тип почти догоняет первый
    return kind, confidence, sorted(set(hits.get(kind, [])))[:6]


def profile(kind: str) -> dict:
    """Карточка типа. Неизвестное имя не роняет систему, а даёт безопасный тип."""
    return dict(ARCHETYPES.get(kind) or ARCHETYPES[DEFAULT])


def assumed_margin(kind: str) -> float:
    """Середина коридора маржи типа - ЯВНОЕ предположение до ответа владельца.

    Нужно ровно затем, чтобы не подставлять вместо себестоимости цену: это
    равносильно допущению «маржа ноль» и в обычном софте завышает стоимость
    подарка в разы, из-за чего система отказывается от нормальных офферов.
    """
    low, high = profile(kind)["margin_band"]
    return round((low + high) / 2, 4)


def questions_for(kind: str, answers: dict | None = None) -> list:
    """Каких чисел не хватает ИМЕННО этому типу бизнеса.

    Общий опросник спрашивает всех обо всём. Здесь - только то, что меняет
    расчёт для этой модели, и только то, чего ещё нет в ответах.
    """
    have = answers or {}
    out = []
    for key in profile(kind)["ask"]:
        if have.get(key) in (None, ""):
            out.append(key)
    # маржа закрывает дыру в любом типе, если точечные числа не назвали
    if out and have.get("gross_margin_pct") in (None, "") and \
            "gross_margin_pct" not in out:
        out.append("gross_margin_pct")
    return out


def lever_fit(kind: str, lever: str) -> str:
    """Насколько рычаг подходит этому типу: 'cheap' | 'costly' | 'neutral'."""
    card = profile(kind)
    if lever in card["cheap"]:
        return "cheap"
    if lever in card["costly"]:
        return "costly"
    return "neutral"


def read(text: str, facts: dict | None = None,
         brief: dict | None = None) -> dict:
    """Полный разбор экономики по сайту: тип, предположения и что спросить.

    brief - разбор модели; если она назвала тип и он совпал с классификатором,
    уверенность растёт, если разошлись - берём классификатор и говорим об этом.
    """
    kind, conf, hits = classify(text, facts)
    said = str((brief or {}).get("cost_archetype") or "").strip().lower()
    agreement = ""
    if said in ARCHETYPES:
        if said == kind:
            conf = min(1.0, conf + 0.25)
            agreement = "модель и признаки сайта сошлись"
        elif conf < 0.4:
            kind, agreement = said, "признаков на сайте мало, взяли разбор модели"
        else:
            agreement = f"модель предложила «{ARCHETYPES[said]['label']}», признаки сайта весомее"

    card = profile(kind)
    low, high = card["margin_band"]
    return {
        "archetype": kind,
        "label": card["label"],
        "confidence": round(conf, 2),
        "signals": hits,
        "agreement": agreement,
        "why": card["why"],
        "margin_band_pct": [int(low * 100), int(high * 100)],
        "assumed_margin": assumed_margin(kind),
        "margin_in": card["margin_in"],
        "cheap_levers": card["cheap"],
        "costly_levers": card["costly"],
        "never": card["never"],
        "ask": card["ask"],
    }
