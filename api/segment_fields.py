"""api/segment_fields.py — реестр v1 полей конструктора сегментов.

Каталог «что можно спросить про игрока» для JSON-конструктора сегментов. Каждое
поле — `Field` с SQL-выражением над алиасами витрин; компилятор
(`api/segment_compiler.py`) собирает из этих кусочков безопасный ClickHouse-WHERE.

АЛИАСЫ (JOIN-план в JOINS):
  f   — player_features   (основная витрина, всегда есть, БЕЗ джойна)
  u   — users             (профиль/контакты/consent, которых нет в витрине)
  ch  — player_churn_ml   ·  ltv — player_ltv (view)  ·  ltq — player_ltv_quantiles
  rp  — player_repeat_ml  ·  nd  — player_next_deposit_ml  ·  bml — player_bonus_ml
  vc  — player_vip_churn_ml · ev — player_early_vip_ml · np — player_non_promising_vip_ml

NULL-СЕМАНТИКА ML (образец — player_state_daily.sql): LEFT JOIN подставляет 0
несопоставленным строкам, а не NULL. Поэтому предикат по ML-полю компилятор
дополнительно гейтит `<alias>.casino_player_id != 0` — «нет скора» ≠ «скор 0»,
фильтр по скору матчит ТОЛЬКО игроков, у которых скор есть (см. ML_JOINS).

ТИПЫ полей → операторы (ТЗ §1.2, задаются в segment_compiler.OPS_BY_TYPE):
  num  eq/ne/gt/lt/between/top_pct · date before/after/between/days_ago_gt/days_ago_lt
  enum in/not_in · flag is/is_null · str eq/ne/contains/in/not_in

Русские `label` живут прямо тут (i18n экрана — отдельная задача W4-T2). v1 собран
из УЖЕ существующих данных; полный каталог 158 фильтров Василия домержит W4-T0.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type: str                     # 'num'|'date'|'enum'|'flag'|'str'
    sql: str | None               # выражение над алиасом (f./u./ch. …); None у заглушек
    section: int
    join: str | None = None       # алиас нужного JOIN (None = только player_features)
    values: Any = None            # enum: list[str] ИЛИ ('sql', '<query>')
    available: bool = True
    needs: str | None = None      # чего не хватает, если available=False
    flag_kind: str = 'str'        # для type='flag': 'str' (колонка 't'/'f') | 'bool' (UInt8)
    catalog_n: int | tuple[int, ...] | None = None  # № фильтра Василия (трассировка)


# ── JOIN-план: алиас → SQL-фрагмент LEFT JOIN ────────────────────────────────
JOINS: dict[str, str] = {
    'u':   "LEFT JOIN users AS u ON u.casino_player_id = f.casino_player_id",
    'ch':  "LEFT JOIN player_churn_ml AS ch ON ch.casino_player_id = f.casino_player_id",
    'ltv': "LEFT JOIN player_ltv AS ltv ON ltv.casino_player_id = f.casino_player_id",
    'ltq': "LEFT JOIN player_ltv_quantiles AS ltq ON ltq.casino_player_id = f.casino_player_id",
    'rp':  "LEFT JOIN player_repeat_ml AS rp ON rp.casino_player_id = f.casino_player_id",
    'nd':  "LEFT JOIN player_next_deposit_ml AS nd ON nd.casino_player_id = f.casino_player_id",
    'bml': "LEFT JOIN player_bonus_ml AS bml ON bml.casino_player_id = f.casino_player_id",
    'vc':  "LEFT JOIN player_vip_churn_ml AS vc ON vc.casino_player_id = f.casino_player_id",
    'ev':  "LEFT JOIN player_early_vip_ml AS ev ON ev.casino_player_id = f.casino_player_id",
    'np':  "LEFT JOIN player_non_promising_vip_ml AS np ON np.casino_player_id = f.casino_player_id",
}

# Джойны, для которых «нет строки» = честный NULL (нужен гейт alias.id != 0).
# users НЕ здесь: player_features строится ИЗ users, строка всегда есть.
ML_JOINS: frozenset[str] = frozenset({'ch', 'ltv', 'ltq', 'rp', 'nd', 'bml', 'vc', 'ev', 'np'})

# Белый список событий (§0) → (таблица, фильтр-типа, колонка-времени).
EVENTS: dict[str, tuple[str, str, str]] = {
    'deposit':       ('money_transactions', "type IN ('deposit','manual_deposit')", 'created_at'),
    'withdrawal':    ('money_transactions', "type IN ('withdrawal','manual_withdrawal')", 'created_at'),
    'bonus':         ('money_transactions', "type IN ('bonus','manual_bonus','freespin')", 'created_at'),
    'bet':           ('game_transactions',  "transaction_type IN ('bet','freespins_bet')", 'created_at'),
    'session_start': ('live_events',        "event_type = 'session_start'", 'ts'),
    'session_end':   ('live_events',        "event_type = 'session_end'", 'ts'),
}


def _f(key, label, ftype, sql, section, **kw) -> tuple[str, Field]:
    return key, Field(key=key, label=label, type=ftype, sql=sql, section=section, **kw)


# ── реестр v1 ────────────────────────────────────────────────────────────────
# Сгруппирован по разделам ТЗ (§1 профиль … §10 предиктивные). Порядок = порядок
# показа в UI (segments/fields сохраняет вставку dict в Python 3.7+).
_ROWS: list[tuple[str, Field]] = [
    # ─────────────── §1 Профиль ───────────────
    _f('country', 'Страна', 'enum', 'f.country', 1,
       values=('sql', "SELECT country FROM player_features WHERE account_type='normal' AND country!='' GROUP BY country ORDER BY count() DESC LIMIT 60")),
    _f('currency', 'Валюта', 'enum', 'f.currency', 1,
       values=('sql', "SELECT currency FROM player_features WHERE account_type='normal' AND currency!='' GROUP BY currency ORDER BY count() DESC LIMIT 30")),
    _f('account_type', 'Тип аккаунта', 'enum', 'f.account_type', 1,
       values=['normal', 'service', 'test_or_service', 'blocked', 'test']),
    _f('activity_status', 'Статус активности', 'enum', 'f.activity_status', 1,
       values=('sql', "SELECT activity_status FROM player_features WHERE activity_status!='' GROUP BY activity_status ORDER BY count() DESC LIMIT 20")),
    _f('reg_date', 'Дата регистрации', 'date', 'f.reg_date', 1),
    _f('tenure_days', 'Стаж (дней с регистрации)', 'num', 'f.tenure_days', 1),
    _f('vip_level', 'VIP-уровень (0–5)', 'num', 'f.vip_level', 1),
    _f('phone_verified', 'Телефон подтверждён', 'flag', 'f.phone_verified', 1),
    _f('email_verified', 'Email подтверждён', 'flag', 'f.email_verified', 1),
    _f('is_active', 'Аккаунт активен', 'flag', 'f.is_active', 1),
    _f('timezone', 'Часовой пояс', 'str', 'u.timezone', 1, join='u'),
    _f('marketing_consent', 'Согласие на маркетинг', 'flag', 'u.marketing_consent', 1, join='u'),
    _f('opt_out', 'Отписан (opt-out)', 'flag', 'u.opt_out', 1, join='u'),
    _f('do_not_contact', 'Не беспокоить', 'flag', 'u.do_not_contact', 1, join='u'),
    _f('self_excluded', 'Самоисключение', 'flag', 'u.self_excluded', 1, join='u'),
    _f('telegram_id_present', 'Есть Telegram', 'flag', "(u.telegram_id != '' AND u.telegram_id != '0')", 1,
       join='u', flag_kind='bool'),
    _f('has_whatsapp', 'Есть WhatsApp', 'flag', 'u.has_whatsapp', 1, join='u'),
    _f('has_viber', 'Есть Viber', 'flag', 'u.has_viber', 1, join='u'),

    # ─────────────── §2 Привлечение ───────────────
    _f('affiliate_code', 'Код аффилиата', 'str', 'f.affiliate_code', 2),
    _f('affiliate_type', 'Тип аффилиата', 'enum', 'f.affiliate_type', 2,
       values=('sql', "SELECT affiliate_type FROM player_features WHERE affiliate_type!='' GROUP BY affiliate_type ORDER BY count() DESC LIMIT 30")),
    _f('registration_source', 'Источник регистрации', 'str', 'u.registration_source', 2, join='u'),
    _f('traffic_sub_id', 'Sub ID трафика', 'str', 'u.traffic_sub_id', 2, join='u'),

    # ─────────────── §3 Депозиты ───────────────
    _f('dep_count', 'Кол-во депозитов', 'num', 'f.dep_count', 3),
    _f('dep_sum', 'Сумма депозитов', 'num', 'f.dep_sum', 3),
    _f('dep_failed', 'Неудачных депозитов', 'num', 'f.dep_failed', 3),
    _f('is_depositor', 'Депозитор', 'flag', 'f.is_depositor', 3, flag_kind='bool'),
    _f('ftd_date', 'Дата первого депозита (FTD)', 'date', 'f.ftd_date', 3),
    _f('ftd_amount', 'Сумма первого депозита', 'num', 'f.ftd_amount', 3),
    _f('first_deposit_date', 'Дата первого депозита (по транзакциям)', 'date', 'f.first_deposit_date', 3),
    _f('last_deposit_date', 'Дата последнего депозита', 'date', 'f.last_deposit_date', 3),
    _f('deposit_recency_days', 'Давность последнего депозита (дней)', 'num', 'f.deposit_recency_days', 3),
    _f('primary_payment_method', 'Основной способ оплаты', 'enum', 'f.primary_payment_method', 3,
       values=('sql', "SELECT primary_payment_method FROM player_features WHERE primary_payment_method NOT IN ('','(none)') GROUP BY primary_payment_method ORDER BY count() DESC LIMIT 40")),
    _f('cash_deposits', 'Кэш-депозиты (сумма)', 'num', 'f.cash_deposits', 3),
    _f('net_cash', 'Net cash (депозиты − выводы)', 'num', 'f.net_cash', 3),
    _f('expected_next_deposit_days', 'Ожидаемый следующий депозит (дней)', 'num', '', 3,
       available=False, needs='ml_expected_gap'),

    # ─────────────── §4 Выводы ───────────────
    _f('wd_count', 'Кол-во выводов', 'num', 'f.wd_count', 4),
    _f('wd_sum', 'Сумма выводов', 'num', 'f.wd_sum', 4),
    _f('wd_rejected', 'Отклонённых выводов', 'num', 'f.wd_rejected', 4),
    _f('withdrawals_abs', 'Выводы (кэш, ABS)', 'num', 'f.withdrawals_abs', 4),

    # ─────────────── §5 Финансы / риск ───────────────
    _f('net', 'Net игрока (игра)', 'num', 'f.net', 5),
    _f('balance', 'Баланс', 'num', 'f.balance', 5),
    _f('bonus_balance', 'Бонусный баланс', 'num', 'f.bonus_balance', 5),
    _f('bonus_cost', 'Стоимость бонусов (кост)', 'num', 'f.bonus_cost', 5),

    # ─────────────── §6 Игра ───────────────
    _f('bets', 'Кол-во ставок', 'num', 'f.bets', 6),
    _f('turnover', 'Оборот (сумма ставок)', 'num', 'f.turnover', 6),
    _f('avg_bet', 'Средняя ставка', 'num', 'f.avg_bet', 6),
    _f('max_bet', 'Максимальная ставка', 'num', 'f.max_bet', 6),
    _f('distinct_games', 'Разных игр', 'num', 'f.distinct_games', 6),
    _f('active_days', 'Активных дней', 'num', 'f.active_days', 6),
    _f('recency_days', 'Давность последней ставки (дней)', 'num', 'f.recency_days', 6),
    _f('last_bet_date', 'Дата последней ставки', 'date', 'f.last_bet_date', 6),
    _f('favourite_game', 'Любимая игра (uuid)', 'str', 'f.favourite_game', 6),
    _f('stuck_game', 'Игра-залипание (uuid)', 'str', 'f.stuck_game', 6),
    _f('game_concentration', 'Концентрация на игре (0–1)', 'num', 'f.game_concentration', 6),
    _f('freespin_ratio', 'Доля фриспинов (0–1)', 'num', 'f.freespin_ratio', 6),
    _f('night_share', 'Доля ночной игры (0–1)', 'num', 'f.night_share', 6),
    _f('primary_provider', 'Основной провайдер', 'enum', 'f.primary_provider', 6,
       values=('sql', "SELECT primary_provider FROM player_features WHERE primary_provider!='' GROUP BY primary_provider ORDER BY count() DESC LIMIT 40")),
    _f('sessions_count', 'Кол-во сессий', 'num', 'f.sessions_count', 6),
    _f('avg_session_min', 'Средняя длительность сессии (мин)', 'num', 'f.avg_session_min', 6),
    _f('bets_per_active_day', 'Ставок в активный день', 'num', 'f.bets_per_active_day', 6),
    _f('ever_played', 'Хоть раз играл', 'flag', 'f.ever_played', 6, flag_kind='bool'),

    # ─────────────── §9 Лайфсайкл ───────────────
    _f('lifecycle', 'Стадия жизненного цикла', 'enum', 'f.lifecycle', 9,
       values=['never', 'active', 'cooling', 'at_risk', 'dormant', 'churned']),
    _f('churned_30d', 'Отток 30 дней', 'flag', 'f.churned_30d', 9, flag_kind='bool'),
    _f('churned_90d', 'Отток 90 дней', 'flag', 'f.churned_90d', 9, flag_kind='bool'),
    _f('login_recency_days', 'Давность логина (дней)', 'num', 'f.login_recency_days', 9),
    _f('activity_recency_days', 'Давность активности (дней)', 'num', 'f.activity_recency_days', 9),
    _f('activation_lag_days', 'Лаг активации (рег→1-я ставка, дней)', 'num', 'f.activation_lag_days', 9),

    # ─────────────── §10 Предиктивные (ML) ───────────────
    _f('p_churn', 'Вероятность оттока', 'num', 'ch.p_churn', 10, join='ch'),
    _f('pred_ltv_d90', 'Прогноз LTV D90', 'num', 'ltv.pred_ltv_d90', 10, join='ltv'),
    _f('ltv_headroom', 'Потенциал LTV (headroom)', 'num', 'ltv.ltv_headroom', 10, join='ltv'),
    _f('early_tier', 'Ранний тир (A–D)', 'enum', 'ltv.early_tier', 10, join='ltv',
       values=['A', 'B', 'C', 'D']),
    _f('ltv_p10', 'LTV прогноз p10', 'num', 'ltq.ltv_p10', 10, join='ltq'),
    _f('ltv_p90', 'LTV прогноз p90', 'num', 'ltq.ltv_p90', 10, join='ltq'),
    _f('p_2nd_ml', 'Вероятность 2-го депозита', 'num', 'rp.p_2nd_ml', 10, join='rp'),
    _f('p_next_deposit', 'Вероятность следующего депозита', 'num', 'nd.p_next_deposit', 10, join='nd'),
    _f('rec_bonus', 'Рекомендованный бонус (ML)', 'enum', 'bml.rec_bonus', 10, join='bml',
       values=('sql', "SELECT rec_bonus FROM player_bonus_ml WHERE rec_bonus!='' GROUP BY rec_bonus ORDER BY count() DESC LIMIT 30")),
    _f('p_vip_churn', 'VIP: риск оттока', 'num', 'vc.p_vip_churn', 10, join='vc'),
    _f('p_early_vip', 'VIP: станет VIP рано', 'num', 'ev.p_early_vip', 10, join='ev'),
    _f('p_non_promising', 'VIP: неперспективный', 'num', 'np.p_non_promising', 10, join='np'),
]

# ── трассировка v1-полей к номерам каталога Василия (W4-T0) ──────────────────
# key → n (или кортеж n): «для ЦРМ.xlsx», 158 фильтров, tools/filter_catalog_map.json.
# Поля БЕЗ записи здесь — наши поведенческие/ML-признаки, у которых нет прямого
# номера в списке Василия (catalog_n=None): timezone, opt_out, do_not_contact,
# reg_date, is_active, activity_status, registration_source, traffic_sub_id,
# has_whatsapp/has_viber (вариации n22), first_deposit_date (дубль ftd_date/n34),
# cash_deposits, bonus_cost, wd_sum/wd_rejected/withdrawals_abs (часть n51/n59),
# max_bet, active_days, favourite_game/stuck_game, game_concentration,
# bets_per_active_day, ever_played, login_recency_days/activity_recency_days/
# activation_lag_days, churned_30d/churned_90d (часть n117), ltv_headroom/
# early_tier/ltv_p10/ltv_p90 (часть n127), p_2nd_ml/p_next_deposit/p_vip_churn/
# p_non_promising (наши модели сверх generic n126-130).
_V1_CATALOG_N: dict[str, int | tuple[int, ...]] = {
    'country': 7, 'currency': 9, 'account_type': 11, 'vip_level': (16, 115),
    'self_excluded': 18, 'email_verified': 19, 'phone_verified': 20,
    'telegram_id_present': 22, 'marketing_consent': 23, 'tenure_days': 25,
    'affiliate_code': 28, 'affiliate_type': 29,
    'dep_failed': 31, 'last_deposit_date': (33, 40), 'ftd_date': 34,
    'ftd_amount': 35, 'dep_count': 36, 'dep_sum': 37, 'deposit_recency_days': 41,
    'primary_payment_method': 42, 'expected_next_deposit_days': 45,
    'wd_count': 51, 'net': (56, 77), 'balance': 57, 'net_cash': 58,
    'last_bet_date': 66, 'recency_days': 67, 'turnover': 68, 'avg_bet': 69,
    'bets': 70, 'primary_provider': 72, 'distinct_games': 73,
    'sessions_count': 74, 'avg_session_min': 75, 'night_share': 76,
    'bonus_balance': 91, 'freespin_ratio': 97,
    'is_depositor': (112, 113), 'lifecycle': (116, 117), 'p_early_vip': 124,
    'p_churn': 126, 'pred_ltv_d90': 127, 'rec_bonus': 129,
}
_ROWS = [(k, replace(f, catalog_n=_V1_CATALOG_N[k]) if k in _V1_CATALOG_N else f)
         for k, f in _ROWS]


def _stub(key, label, ftype, section, needs, catalog_n, **kw) -> tuple[str, Field]:
    """Field-заглушка: available=False, sql=None (ждёт события/справочника/фазы 3а)."""
    return key, Field(key=key, label=label, type=ftype, sql=None, section=section,
                      available=False, needs=needs, catalog_n=catalog_n, **kw)


# ── домерж каталога Василия (W4-T0): номера, не закрытые v1-полями ────────────
# available=True — работает над имеющимися данными (проверено preview);
# available=False+needs='derived_v2' — вычислимо, но требует подзапросов/витрины;
# available=False+needs='<событие>' — ждёт события/справочника от казино/фазы 3а.
_CATALOG_ROWS: list[tuple[str, Field]] = [
    # ─────────────── §0 События (универсальный фильтр) ───────────────
    # n1/30/32 покрыты типом условия `event` в компиляторе (deposit/withdrawal/
    # bonus/bet/session_*), а не скалярным полем — needs='event_builder' сигналит
    # UI показывать это как конструктор событий, НЕ как серую «дыру казино».
    _stub('event_occurred', 'Событие за период (deposit/withdrawal/bonus/bet/session)',
          'num', 0, 'event_builder', (1, 30, 32)),
    _stub('event_params', 'Параметры события: сумма/метод (вертикаль/турнир/канал — нет)',
          'num', 0, 'event_builder', 2),
    _f('first_bet_date', 'Дата первой ставки', 'date', 'f.first_bet_date', 0, catalog_n=3),
    _f('days_since_ftd', 'Дней с первого депозита (годовщина FTD)', 'num',
       "dateDiff('day', toDate(f.ftd_date), today())", 0, catalog_n=4),

    # ─────────────── §1 Профиль ───────────────
    _f('player_id', 'Player ID (casino_player_id)', 'num', 'f.casino_player_id', 1, catalog_n=5),
    _stub('player_name', 'Имя игрока (PII, маскирование по ролям)', 'str', 1, 'pii', 6),
    _stub('language_ui', 'Язык интерфейса (прокси game_sessions.language)', 'enum', 1,
          'derived_v2', 8),
    _stub('device_platform', 'Устройство / платформа (iOS/Android/web/desktop)', 'enum', 1,
          'device', 10),
    _stub('kyc_status', 'KYC-статус (не пройден/в процессе/верифиц./отклонён)', 'enum', 1,
          'kyc', 12),
    _stub('age', 'Возраст', 'num', 1, 'birthdate', 13),
    _stub('gender', 'Пол', 'enum', 1, 'gender', 14),
    _stub('brand', 'Бренд / лицензия (мультибренд)', 'enum', 1, 'multibrand', 15),
    _stub('multiaccount', 'Наличие мультиаккаунтов', 'flag', 1, 'device_ip', 17),
    _stub('push_token', 'Валидный push-токен / приложение установлено', 'flag', 1, 'push', 21),
    _stub('birthday', 'Дней до дня рождения', 'num', 1, 'birthdate', 24),
    _f('time_to_ftd', 'Время от регистрации до FTD (дней)', 'num',
       "dateDiff('day', toDate(f.reg_date), toDate(f.ftd_date))", 1, catalog_n=26),
    _stub('geo_mismatch_vpn', 'Несовпадение гео регистрации и IP (VPN-флаг)', 'flag', 1,
          'device_ip', 27),

    # ─────────────── §3 Депозиты ───────────────
    _f('avg_deposit', 'Средний чек (депозит)', 'num',
       'if(f.dep_count > 0, f.dep_sum / f.dep_count, 0)', 3, catalog_n=38),
    _stub('max_deposit', 'Максимальный депозит', 'num', 3, 'derived_v2', 39),
    _stub('failed_deposit_streak', 'Failed-депозитов подряд (за период)', 'num', 3,
          'derived_v2', 43),
    _f('avg_deposit_interval_days', 'Средний интервал между депозитами (дней)', 'num',
       "if(f.dep_count > 1, dateDiff('day', toDate(f.first_deposit_date), "
       "toDate(f.last_deposit_date)) / (toInt64(f.dep_count) - 1), NULL)", 3, catalog_n=44),
    _stub('first_deposit_method', 'Метод первого депозита', 'enum', 3, 'derived_v2', 46),
    _stub('unique_payment_methods', 'Кол-во уникальных методов оплаты', 'num', 3,
          'derived_v2', 47),
    _stub('chargeback', 'Chargeback-флаг / история чарджбеков', 'flag', 3, 'chargeback', 48),
    _f('crypto_player', 'Крипто-игрок (по методу оплаты)', 'flag',
       "(positionCaseInsensitive(f.primary_payment_method, 'crypto') > 0 "
       "OR positionCaseInsensitive(f.primary_payment_method, 'usdt') > 0 "
       "OR positionCaseInsensitive(f.primary_payment_method, 'btc') > 0 "
       "OR positionCaseInsensitive(f.primary_payment_method, 'eth') > 0 "
       "OR positionCaseInsensitive(f.primary_payment_method, 'trx') > 0)", 3,
       catalog_n=49, flag_kind='bool'),
    _stub('deposit_streak', 'Депозитный стрик (дней подряд с депозитом)', 'num', 3,
          'derived_v2', 50),

    # ─────────────── §4 Выводы ───────────────
    _stub('last_withdrawal_date', 'Дата последнего вывода', 'date', 4, 'derived_v2', 52),
    _stub('withdrawal_processing_time', 'Среднее время обработки вывода', 'num', 4,
          'withdrawal_status', 53),
    _stub('pending_withdrawals', 'Pending-выводы (есть/сумма/возраст)', 'flag', 4,
          'withdrawal_status', 54),
    _stub('cancelled_withdrawal_reason', 'Отменённые выводы (причина)', 'enum', 4,
          'withdrawal_status', 55),

    # ─────────────── §5 Финансы / риск ───────────────
    _f('withdrawal_deposit_ratio', 'Отношение выводов к депозитам (%)', 'num',
       'if(f.cash_deposits > 0, f.withdrawals_abs / f.cash_deposits * 100, 0)', 5, catalog_n=59),
    _stub('balance_below_x', 'Баланс упал ниже X (реал, live-триггер)', 'num', 5,
          'balance_after', 60),
    _stub('zero_balance_after_loss', 'Нулевой баланс после проигранной сессии', 'flag', 5,
          'derived_v2', 61),
    _stub('big_win_session', 'Крупный выигрыш за сессию / день', 'num', 5, 'derived_v2', 62),
    _stub('big_loss_period', 'Крупный проигрыш за период', 'num', 5, 'derived_v2', 63),
    _stub('losing_streak', 'Серия проигрышей подряд (N ставок / дней)', 'num', 5,
          'derived_v2', 64),
    _stub('jackpot_winner', 'Джекпот-виннер (да/нет, дата)', 'flag', 5, 'jackpot', 65),

    # ─────────────── §6 Игра ───────────────
    _stub('favourite_vertical', 'Любимая вертикаль (slots/live/sports/crash)', 'enum', 6,
          'vertical', 71),
    _stub('unfinished_session_freespins', 'Вышел с неиспользованными фриспинами', 'flag', 6,
          'bonus_events', 78),
    _stub('new_game_release', 'Релиз новой игры любимого провайдера', 'flag', 6,
          'game_releases_ref', 79),
    _stub('vertical_switch', 'Смена любимой вертикали (казино↔спорт)', 'flag', 6,
          'derived_v2', 80),
    _stub('first_bet_new_vertical', 'Первая ставка / игра в новой вертикали', 'flag', 6,
          'derived_v2', 81),

    # ─────────────── §7 Спорт (спортбук не в фиде) ───────────────
    _stub('sport_tournament', 'Ставки по конкретному турниру / лиге', 'flag', 7, 'sport', 82),
    _stub('sport_preferred', 'Предпочитаемый спорт', 'enum', 7, 'sport', 83),
    _stub('sport_teams', 'Предпочитаемые команды', 'str', 7, 'sport', 84),
    _stub('sport_next_match', 'Ближайший матч любимой команды', 'date', 7, 'sport', 85),
    _stub('sport_bet_type', 'Тип ставок (ординар/экспресс, live/prematch), кэф', 'enum', 7,
          'sport', 86),
    _stub('sport_last_result', 'Результат последней ставки (win/lose/cashout)', 'enum', 7,
          'sport', 87),
    _stub('sport_unfinished_coupon', 'Незавершённый купон (собрал, не подтвердил)', 'flag', 7,
          'sport', 88),

    # ─────────────── §8 Бонусы и лояльность ───────────────
    _stub('active_bonus_any', 'Активные бонусы (есть / нет)', 'flag', 8, 'bonus_events', 89),
    _stub('active_bonus_specific', 'Активные бонусы (конкретные)', 'enum', 8, 'bonus_events', 90),
    _stub('wagering_progress', 'Wagering-прогресс (% отыгрыша)', 'num', 8, 'bonus_events', 92),
    _f('bonus_count', 'Кол-во полученных бонусов (lifetime)', 'num', 'f.bonus_count', 8,
       catalog_n=93),
    _stub('wagered_bonuses_sum', 'Сумма отыгранных бонусов (lifetime)', 'num', 8,
          'bonus_events', 94),
    _f('freespins_bets', 'Оборот на бонусные средства (прокси: фриспин-ставки)', 'num',
       'f.freespins_bets', 8, catalog_n=95),
    _f('real_bets', 'Оборот на реальные средства (прокси: реал-ставки)', 'num',
       'f.real_bets', 8, catalog_n=96),
    _stub('bonus_cost_ggr', 'Бонус-кост (отыгранные бонусы к GGR)', 'num', 8, 'bonus_events', 98),
    _stub('bonus_abuse', 'Bonus abuse-флаг (архетип «бонусник» + net>0)', 'flag', 8,
          'derived_v2', 99),
    _stub('offer_response', 'Отреагировал на последний оффер (≤7д)', 'flag', 8, 'derived_v2', 100),
    _stub('offers_declined_streak', 'Отклонённых офферов подряд', 'num', 8, 'derived_v2', 101),
    _stub('tournaments_participation', 'Участие в турнирах / лотереях / миссиях', 'flag', 8,
          'tournaments', 102),
    _stub('loyalty_points', 'Loyalty-поинты / рейкбек-баланс', 'num', 8, 'loyalty', 103),
    _stub('freespins_remainder', 'Freespins — остаток', 'num', 8, 'bonus_events', 104),
    _stub('bonus_expiring', 'Бонус сгорает через N часов / дней', 'flag', 8, 'bonus_events', 105),
    _stub('bonus_not_activated', 'Начисленный бонус не активирован N часов', 'flag', 8,
          'bonus_events', 106),
    _stub('wagering_threshold', 'Wagering-прогресс пересёк порог (>80%)', 'flag', 8,
          'bonus_events', 107),
    _stub('next_cashback', 'Дата / сумма ближайшего кэшбека', 'date', 8, 'bonus_ref', 108),
    _stub('to_vip_threshold_pct', 'До VIP-порога осталось X (%)', 'num', 8, 'derived_v2', 109),
    _stub('tournament_position', 'Позиция в турнире / близость к призам', 'num', 8,
          'tournaments', 110),
    _stub('mission_stuck', 'Прогресс миссии застрял (N дней)', 'flag', 8, 'missions', 111),

    # ─────────────── §9 Лайфсайкл ───────────────
    _f('second_dep_pending', '2nd-deposit pending (ждём второй депозит)', 'flag',
       '(f.dep_count = 1)', 9, catalog_n=114, flag_kind='bool'),
    _stub('reactivated', 'Реактивирован (дата последней реактивации)', 'flag', 9,
          'derived_v2', 118),
    _stub('deposit_trend', 'Тренд активности по депозитам (растёт/падает)', 'enum', 9,
          'derived_v2', 119),
    _stub('bet_trend', 'Тренд активности по ставкам (растёт/падает)', 'enum', 9,
          'derived_v2', 120),
    _stub('days_in_lifecycle', 'Дней в текущем лайфсайкл-статусе', 'num', 9, 'derived_v2', 121),
    _stub('reactivations_count', 'Кол-во реактиваций lifetime / дата чурна', 'num', 9,
          'derived_v2', 122),
    _stub('pre_churn', 'Pre-churn (активность падает, ещё не дормант)', 'flag', 9,
          'derived_v2', 123),
    _stub('manager_assigned', 'Персональный менеджер назначен (да/нет)', 'flag', 9,
          'crm_assignments', 125),

    # ─────────────── §10 Предиктивные (ML) ───────────────
    _stub('next_best_action', 'Predictive next-best-action', 'enum', 10, 'derived_v2', 128),
    _stub('rfm_segment', 'RFM-сегмент', 'enum', 10, 'derived_v2', 130),

    # ─────────────── §11 Коммуникации и оркестрация ───────────────
    _stub('msg_status_by_channel', 'Статусы по каналам (доставлено/прочитано/клик)', 'enum', 11,
          'delivery_events', 131),
    _stub('open_rate', 'Open rate', 'num', 11, 'delivery_events', 132),
    _stub('click_rate', 'Click rate', 'num', 11, 'delivery_events', 133),
    _stub('last_open_click', 'Дата последнего открытия / клика', 'date', 11,
          'delivery_events', 134),
    _stub('opt_out_by_channel', 'Отписки по каналам', 'enum', 11, 'delivery_events', 135),
    _stub('freq_capping', 'Частота контактов (frequency capping)', 'num', 11, 'phase3a', 136),
    _stub('channel_reaction', 'Реакция на канал (что конвертит)', 'enum', 11,
          'delivery_events', 137),
    _stub('push_undelivered', 'Недоставленные push (токен протух)', 'flag', 11, 'push', 138),
    _stub('in_active_chain', 'Находится в активной цепочке (в какой)', 'flag', 11, 'phase3a', 139),
    _stub('control_group', 'Контрольная группа / global holdout', 'flag', 11, 'phase3a', 140),
    _stub('ab_group', 'A/B-группа внутри цепочки', 'enum', 11, 'phase3a', 141),
    _stub('last_contact_date', 'Дата последнего контакта любым каналом', 'date', 11,
          'phase3a', 142),
    _stub('send_time_optimal', 'Оптимальное время отправки (send-time)', 'num', 11,
          'ml_send_time', 143),
    _f('reachable_any', 'Достижимость: есть хотя бы один канал', 'flag',
       "(f.email_verified IN ('t','true','1','yes','y','on') "
       "OR f.phone_verified IN ('t','true','1','yes','y','on') "
       "OR (u.telegram_id != '' AND u.telegram_id != '0') "
       "OR u.has_whatsapp IN ('t','true','1','yes','y','on') "
       "OR u.has_viber IN ('t','true','1','yes','y','on'))", 11,
       catalog_n=144, join='u', flag_kind='bool'),

    # ─────────────── §12 Поведенческие и технические события ───────────────
    _stub('login_attempts', 'Логины (успешные / неуспешные попытки)', 'num', 12,
          'login_events', 145),
    _f('last_login_date', 'Дата последнего логина', 'date', 'u.last_login', 12,
       catalog_n=146, join='u'),
    _stub('forgot_password', 'Забытый пароль (не смог войти / попытка)', 'flag', 12,
          'auth_events', 147),
    _stub('support_contacts', 'Обращения в саппорт (кол-во + темы)', 'num', 12,
          'support_events', 148),
    _stub('complaints', 'Жалобы', 'num', 12, 'support_events', 149),
    _stub('online_during_incident', 'Был онлайн во время сбоя', 'flag', 12, 'incident_log', 150),
    _stub('unfinished_deposit', 'Незавершённый депозит (открыл кассу, не пришёл)', 'flag', 12,
          'cashier_opened', 151),
    _stub('abandoned_registration', 'Брошенная регистрация / не довнесены данные', 'flag', 12,
          'reg_funnel', 152),

    # ─────────────── §13 Рефералка и комьюнити ───────────────
    _stub('referred_friends', 'Пригласил друзей (кол-во, сколько до FTD)', 'num', 13,
          'referral', 153),
    _stub('came_via_referral', 'Сам пришёл по рефералке (да/нет, от кого)', 'flag', 13,
          'referral', 154),

    # ─────────────── §14 Исключения / комплаенс ───────────────
    _stub('open_ticket', 'Открытая жалоба / тикет в работе', 'flag', 14, 'support_events', 155),
    _stub('kyc_requested', 'Запрошены KYC-документы (ждём от игрока)', 'flag', 14, 'kyc', 156),
    _stub('fraud_aml', 'Фрод-флаг / AML-review в процессе', 'flag', 14, 'fraud_aml', 157),
    _stub('rg_limit_usage', '% использования лимита депозита (RG)', 'num', 14, 'rg_limits', 158),
]

FIELDS: dict[str, Field] = dict(_ROWS + _CATALOG_ROWS)

# Русские подписи разделов (для группировки в UI; i18n экрана — W4-T2).
SECTIONS: dict[int, str] = {
    0: 'События',
    1: 'Профиль',
    2: 'Привлечение',
    3: 'Депозиты',
    4: 'Выводы',
    5: 'Финансы / риск',
    6: 'Игра',
    7: 'Спорт',
    8: 'Бонусы и лояльность',
    9: 'Жизненный цикл',
    10: 'Предиктивные (ML)',
    11: 'Коммуникации',
    12: 'Технические события',
    13: 'Рефералка',
    14: 'Исключения / комплаенс',
}

# Человекочитаемые бейджи для needs (UI, W4-T2). 'event_builder' — НЕ дыра, а
# отдельный тип условия; 'derived_v2' — вычислимо, ждёт витрины/подзапросов;
# 'phase3a' — появится с send_log/enrollments; остальное — ждёт события/справочника казино.
NEEDS_LABELS: dict[str, str] = {
    'event_builder': 'конструктор событий',
    'derived_v2': 'расширение витрины (v2)',
    'phase3a': 'фаза 3а (send_log/цепочки)',
    'ml_send_time': 'модель send-time (фаза 3б)',
    'ml_expected_gap': 'модель интервала депозитов',
    'pii': 'PII — доступ по ролям',
    'crm_assignments': 'связка с Пультом',
    'balance_after': 'событие balance_after',
    'device': 'поле устройства/платформы',
    'device_ip': 'device/IP-поля (тех-фид)',
    'kyc': 'KYC-статус',
    'birthdate': 'дата рождения',
    'gender': 'пол',
    'multibrand': 'мультибренд',
    'push': 'push-токены',
    'chargeback': 'чарджбеки',
    'withdrawal_status': 'статусы вывода',
    'jackpot': 'джекпот-события',
    'vertical': 'вертикали (спорт/казино)',
    'game_releases_ref': 'справочник релизов игр',
    'bonus_events': 'события бонусов',
    'bonus_ref': 'справочник бонусов',
    'tournaments': 'турниры',
    'loyalty': 'loyalty-поинты',
    'missions': 'миссии',
    'delivery_events': 'статусы доставки',
    'login_events': 'логин-события',
    'auth_events': 'auth-события',
    'support_events': 'саппорт/тикеты',
    'incident_log': 'журнал сбоев',
    'cashier_opened': 'cashier_opened',
    'reg_funnel': 'воронка регистрации',
    'referral': 'рефералка',
    'fraud_aml': 'фрод/AML-флаги',
    'rg_limits': 'RG-лимиты',
    'sport': 'спортбук',
}
