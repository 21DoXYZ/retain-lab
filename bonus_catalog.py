#!/usr/bin/env python3
"""Модуль бонусов: реестр реальных акций BillionBahis + подбор под игрока.

Реестр — bonuses.json (структурированная версия BillionBahis_бонусы.md).
Подбор — детерминированные правила поверх состояния игрока из player_features
и прогнозов моделей: lifecycle, депозиты, net, тир ценности, риск оттока.

Использование:
    from bonus_catalog import load_catalog, match_bonus
    b, why = match_bonus({'lifecycle':'at_risk','dep_count':3,'net':-5000,'early_tier':'D'})
    b['id']  ->  'vip_casino_nowager_30'

Локали (ru/en/tr): операторы клиента — турки, поэтому названия и условия акций
отдаются на языке интерфейса. Правила подбора локаль-независимы:
    • match_bonus_detail(p) → (акция, код причины, параметры) — чистое ядро;
    • render_why(code, params, locale) → строка причины на нужном языке;
    • match_bonus(p, locale=...) → (акция, причина) — обёртка, старая сигнатура.
Текстовые поля акции читать ТОЛЬКО через loc_field(b, field, locale): непереведённое
поле падает на русский базовый вариант и не ломает выдачу.
"""
import json
import os
from datetime import date

# Языки каталога. 'ru' — базовый: все поля определены на нём, остальные падают на него.
LOCALES = ('ru', 'en', 'tr')
DEFAULT_LOCALE = 'ru'

CATALOG_PATH = os.environ.get('BONUSES_JSON', os.path.join(os.path.dirname(__file__), 'bonuses.json'))

_cache = {'mtime': 0, 'data': None}


def load_catalog():
    """Реестр с hot-reload: правка bonuses.json подхватывается без рестарта."""
    try:
        mt = os.path.getmtime(CATALOG_PATH)
        if mt != _cache['mtime']:
            with open(CATALOG_PATH, encoding='utf-8') as fh:
                _cache['data'] = json.load(fh)
            _cache['mtime'] = mt
    except Exception:
        if _cache['data'] is None:
            _cache['data'] = {'bonuses': [], 'vip_tiers': []}
    return _cache['data']


def by_id(bid):
    return next((b for b in load_catalog()['bonuses'] if b['id'] == bid), None)


# ════════════════════════════════════════════════════════════════════════════
# Локализация: поля акции и причины подбора
# ════════════════════════════════════════════════════════════════════════════
def loc_field(b, field, locale=DEFAULT_LOCALE):
    """Текстовое поле акции на нужном языке с фолбэком на русский.

    Порядок поиска: `{field}_{locale}` → `{field}` → `{field}_ru`. Два шага фолбэка
    нужны, потому что в bonuses.json уживаются два соглашения об именах:
      • у названия русский вариант СУФФИКСИРОВАН  (name_ru / name_en / name_tr),
      • у условий русский вариант БАЗОВЫЙ         (wager / wager_en / wager_tr).
    Так loc_field(b,'name','ru') отдаёт name_ru, а loc_field(b,'wager','ru') — wager.
    Непереведённое поле НИКОГДА не ломает выдачу: оператор увидит русский вариант,
    а не пустоту. Числа/суммы/`game` (имя продукта) не переводятся — у них нет *_tr/*_en.
    """
    if not b:
        return ''
    if locale and locale in LOCALES:
        v = b.get(f'{field}_{locale}')
        if v:
            return v
    return b.get(field) or b.get(f'{field}_{DEFAULT_LOCALE}') or ''


def bonus_name(bid, locale=DEFAULT_LOCALE):
    """Название акции по id на нужном языке (для распределений/отчётов)."""
    b = by_id(bid)
    return loc_field(b, 'name', locale) if b else render_why('no_match_any', locale=locale)


# Причины подбора: код → шаблон на каждом языке. Значения подставляет match_bonus_detail
# (уже отформатированные), поэтому шаблоны — простые {placeholder} без спецификаторов.
# Термины: вейджер→wager/çevrim, кэшбэк→cashback/kayıp bonusu, безвейджерный→no-wager/çevrimsiz.
WHY = {
    'positive_player': {
        'ru': 'игрок в плюсе (касса < 0 и выигрыш на играх) → без бонуса (ревью)',
        'en': 'player is up (net cash < 0 and winning on games) → no bonus (review)',
        'tr': 'oyuncu kârda (kasa < 0 ve oyunlarda kazançta) → bonus yok (inceleme)',
    },
    'no_deposits_welcome': {
        'ru': 'нет депозитов → велком 100% (мин 100₺, макс 10 000₺)',
        'en': 'no deposits → 100% welcome (min 100₺, max 10 000₺)',
        'tr': 'yatırım yok → %100 hoşgeldin (min 100₺, maks 10 000₺)',
    },
    'no_deposits_casino_welcome': {
        'ru': 'нет депозитов → казино-велком 100%',
        'en': 'no deposits → 100% casino welcome',
        'tr': 'yatırım yok → %100 casino hoşgeldin',
    },
    'first_deposit_second': {
        'ru': '1 депозит → 200% на 2-й депозит (макс 5 000₺)',
        'en': '1 deposit → 200% on the 2nd deposit (max 5 000₺)',
        'tr': '1 yatırım → 2. yatırıma %200 (maks 5 000₺)',
    },
    'two_deposits_third': {
        'ru': '2 депозита → 3-й депозит: 60 фриспинов без вейджера',
        'en': '2 deposits → 3rd deposit: 60 no-wager freespins',
        'tr': '2 yatırım → 3. yatırım: çevrimsiz 60 freespin',
    },
    'valuable_losing': {
        'ru': 'ценный (LTV {ltv}₺) и в минусе → VIP безвейджерный до {pct}%',
        'en': 'valuable (LTV {ltv}₺) and losing → VIP no-wager up to {pct}%',
        'tr': 'değerli (LTV {ltv}₺) ve kayıpta → VIP çevrimsiz maks. %{pct}',
    },
    'churn_risk': {
        'ru': 'риск оттока {churn}% и проигрыш → мгновенный кэшбэк до {pct}%',
        'en': 'churn risk {churn}% and losing → instant cashback up to {pct}%',
        'tr': 'terk riski %{churn} ve kayıpta → anlık kayıp bonusu maks. %{pct}',
    },
    'winback_freespins': {
        'ru': 'статус «{life}» → возврат фриспинами ({game})',
        'en': '“{life}” status → win-back with freespins ({game})',
        'tr': '«{life}» durumu → freespin ile geri kazanım ({game})',
    },
    'loyalty_ladder': {
        # НЕ дублируем название акции с числом «3» рядом с реальным числом депозитов
        # игрока (путало: «74 депозита → лестница "3 депозита"»). Причина = ЛОГИКА
        # подбора; само название акции оператор видит отдельно (offer_name).
        'ru': 'лоялен: {dep_count} деп., активен — подходит промо-лестница',
        'en': 'loyal: {dep_count} deposits, active — ladder promo fits',
        'tr': 'sadık: {dep_count} yatırım, aktif — merdiven promosyonu uygun',
    },
    'weekly_loss_cashback': {
        'ru': 'недельный проигрыш → кэшбэк до {pct}%',
        'en': 'weekly loss → cashback up to {pct}%',
        'tr': 'haftalık kayıp → kayıp bonusu maks. %{pct}',
    },
    'tier_vip': {
        'ru': 'тир {tier} → VIP безвейджерный до {pct}%',
        'en': 'tier {tier} → VIP no-wager up to {pct}%',
        'tr': '{tier} seviyesi → VIP çevrimsiz maks. %{pct}',
    },
    'active_nudge': {
        'ru': 'активен → фриспины конца дня',
        'en': 'active → end-of-day freespins',
        'tr': 'aktif → gün sonu freespin',
    },
    'no_match': {
        'ru': 'подходящей акции сегодня нет',
        'en': 'no suitable promo today',
        'tr': 'bugün uygun kampanya yok',
    },
    'no_match_any': {
        'ru': 'подходящей акции нет',
        'en': 'no suitable promo',
        'tr': 'uygun kampanya yok',
    },
}


# Локализация lifecycle-кода в тексте причины (иначе оператору показывался сырой
# 'at_risk'/'dormant' в русской подсказке winback).
LIFECYCLE_WHY = {
    'active':   {'ru': 'активен', 'en': 'active', 'tr': 'aktif'},
    'cooling':  {'ru': 'остывает', 'en': 'cooling', 'tr': 'soğuyor'},
    'at_risk':  {'ru': 'под риском', 'en': 'at risk', 'tr': 'risk altında'},
    'dormant':  {'ru': 'спящий', 'en': 'dormant', 'tr': 'uykuda'},
    'churned':  {'ru': 'отток', 'en': 'churned', 'tr': 'kayıp'},
}


def render_why(code, params=None, locale=DEFAULT_LOCALE):
    """Причина подбора (код + параметры) → строка на нужном языке.

    Неизвестный код/локаль → русский фолбэк, пустая строка вместо исключения:
    подсказка оператору не должна ронять карточку игрока.
    """
    row = WHY.get(code)
    if not row:
        return ''
    tpl = row.get(locale) or row.get(DEFAULT_LOCALE) or ''
    params = dict(params or {})
    # сырой lifecycle-код → слово на языке подсказки
    life = params.get('life')
    if life:
        params['life'] = (LIFECYCLE_WHY.get(life, {}).get(locale)
                          or LIFECYCLE_WHY.get(life, {}).get(DEFAULT_LOCALE) or life)
    try:
        return tpl.format(**params)
    except Exception:       # шире, чем Key/Index/Value: подсказка НИКОГДА не роняет карточку
        return tpl


def _available_today(b, today=None):
    """Акция доступна сегодня по дню недели."""
    days = b.get('days', ['all'])
    if 'all' in days:
        return True
    wd = (today or date.today()).strftime('%A').lower()
    return wd in days


# Тир ценности (early_tier) -> VIP-уровень казино. Приблизительное соответствие:
# у казино VIP определяется их внутренней программой, у нас — ценностью игрока.
TIER_TO_VIP = {'A': 'silver', 'B': 'gold', 'C': 'platinum', 'D': 'royal'}


def vip_percent(b, tier):
    """Процент бонуса для игрока с данным тиром (для VIP-акций)."""
    vp = b.get('vip_percent')
    if not vp:
        return b.get('percent')
    return vp.get(TIER_TO_VIP.get(tier, 'silver'))


REVIEW_CODE = 'positive_player'   # «игрок в плюсе → без бонуса»: не оффер, а ревью


def match_bonus_detail(p, today=None):
    """Ядро подбора: (bonus | None, код причины, параметры причины).

    Локаль-независимо — возвращает КОД причины, а не текст. Строку собирает
    render_why(code, params, locale). Так одни и те же правила обслуживают все
    языки, а вызывающий код отличает «в плюсе → ревью» по коду, а не по подстроке.

    p: dict с ключами lifecycle, dep_count, dep_sum, net, net_cash, early_tier,
       pred_ltv_d90, p_churn (любые могут отсутствовать).
    Правила идут по приоритету: первое подходящее выигрывает.
    """
    dep_count = int(p.get('dep_count') or 0)
    net = float(p.get('net') or 0)              # игра: wins − turnover (>0 = игрок выиграл)
    net_cash = float(p.get('net_cash') or 0)    # касса: deposits − withdrawals (<0 = казино в минусе по кэшу)
    tier = p.get('early_tier') or ''
    life = p.get('lifecycle') or ''
    ltv = float(p.get('pred_ltv_d90') or 0)
    churn = p.get('p_churn')
    churn = float(churn) if churn is not None else None

    def ok(bid):
        b = by_id(bid)
        return b if (b and _available_today(b, today)) else None

    # 0) GUARD: игрок в плюсе для казино (вывел кэша больше, чем внёс, И выиграл на играх)
    #    — не поощряем бонусом, отправляем на ревью. Та же метка, что в player_actions.
    if net_cash < 0 and net > 0:
        return None, REVIEW_CODE, {}

    # 1) Лестница депозитов 1→2→3 (акции завязаны друг на друга)
    if dep_count == 0:
        b = ok('welcome_deposit_100')      # мин 100₺, макс 10 000₺ — низкий порог входа
        if b:
            return b, 'no_deposits_welcome', {}
        return ok('welcome_casino_100'), 'no_deposits_casino_welcome', {}
    if dep_count == 1:
        b = ok('second_deposit_200')
        if b:
            return b, 'first_deposit_second', {}
    if dep_count == 2:
        b = ok('third_deposit_300_fs')
        if b:
            return b, 'two_deposits_third', {}

    # 2) Ценный игрок в минусе — срочно удержать безвейджерным VIP-оффером.
    if ltv >= 10000 and net < 0:
        b = ok('vip_casino_nowager_30')
        if b:
            return b, 'valuable_losing', {'ltv': f'{ltv:.0f}', 'pct': vip_percent(b, tier)}

    # 3) Высокий риск оттока — мгновенный кэшбэк на проигрыш.
    if churn is not None and churn >= 0.7 and net < 0:
        b = ok('cashback_instant_30')
        if b:
            return b, 'churn_risk', {'churn': f'{churn*100:.0f}', 'pct': vip_percent(b, tier)}

    # 4) Спящие / отток — сначала вернуть (важнее, чем лестница лояльности).
    if life in ('dormant', 'churned', 'at_risk'):
        b = ok('end_of_day_freespin') or ok('monday_freespin_200')
        if b:
            # life — сырой код lifecycle, game — имя продукта: не переводятся.
            return b, 'winback_freespins', {'life': life, 'game': b['game']}

    # 5) Ценный тир (C/D) — достойный VIP-оффер. ВЫШЕ лестницы лояльности: у кита
    #    депозитов почти всегда ≥3, и generic-промо «4-й от нас» (макс 2 000₺) для
    #    него — недо-оффер. Раньше правило стояло ниже лестницы и почти не срабатывало.
    if tier in ('C', 'D'):
        b = ok('vip_casino_nowager_30')
        if b:
            return b, 'tier_vip', {'tier': tier, 'pct': vip_percent(b, tier)}

    # 6) Три и более депозита, активен, НЕ кит (A/B) — лестница лояльности «4-й от нас».
    #    Тир-гейт дублирует приоритет правила 5 (пояс+подтяжки: устойчиво к перестановке).
    if dep_count >= 3 and tier not in ('C', 'D'):
        b = ok('loyalty_4th_deposit')
        if b:
            return b, 'loyalty_ladder', {'dep_count': dep_count}

    # 7) Понедельник + недельный проигрыш — недельный кэшбэк.
    if net <= -1000:
        b = ok('weekly_cashback_10')
        if b:
            return b, 'weekly_loss_cashback', {'pct': vip_percent(b, tier)}

    # 8) Активные и здоровые — фриспины конца дня как мягкий нудж.
    b = ok('end_of_day_freespin')
    if b:
        return b, 'active_nudge', {}
    return None, 'no_match', {}


def match_bonus(p, today=None, locale=DEFAULT_LOCALE):
    """Подобрать одну акцию под игрока. Возвращает (bonus | None, причина-строка).

    Обёртка над match_bonus_detail: сигнатура и русский дефолт сохранены, чтобы
    старые вызовы (борд, скрипты) работали без изменений.
    """
    b, code, params = match_bonus_detail(p, today)
    return b, render_why(code, params, locale)


def match_by_code(code, today=None):
    """Фолбэк: подобрать акцию по нашему коду рекомендации (fits_codes)."""
    for b in load_catalog()['bonuses']:
        if code in b.get('fits_codes', []) and _available_today(b, today):
            return b
    return None
