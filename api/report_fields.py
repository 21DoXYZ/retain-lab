"""api/report_fields.py — реестры МЕТРИК и РАЗРЕЗОВ конструктора отчётов (W5-T2).

Это единый whitelist-каталог полей: только ключи из METRICS/DIMENSIONS попадают
в компилятор (`api/report_builder.py`), значения фильтров идут параметрами. Модуль
НАМЕРЕННО не импортирует player_board — чтобы компилятор и его юнит-тесты были
чистыми (без ClickHouse/Flask). SQL-условия успешных операций скопированы 1-в-1 с
`player_board.py:116-124` (единый источник правды по спеке казино) и лишь
квалифицированы префиксом `f.` (фактовая таблица), т.к. в JOIN-запросах колонки
`type`/`status`/`amount` иначе неоднозначны (users тоже имеет `status`).

Метрика:  source ∈ money|game|users, date_col — якорная дата периода/time-разреза.
Разрез:   kind ∈ time|profile|transaction|state_at, sql — шаблон с плейсхолдерами
          {date} (якорная дата факта) и {u} (алиас таблицы users), applicable_sources
          — к каким источникам разрез применим (payment_method — только money;
          hour/state_at — money/game; state_at к users-метрикам неприменим).

Историческая корректность (дифференциатор): разрезы state_at (vip_level_at/
lifecycle_at/early_tier_at) джойнят снапшот retention.player_state_daily НА ДАТУ
СОБЫТИЯ (см. report_builder), поэтому «VIP в феврале» = кто БЫЛ VIP в феврале.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── источники (совпадают с фактовыми таблицами retention.*) ──
FACT: dict[str, str] = {
    'money': 'money_transactions',
    'game': 'game_transactions',
    'users': 'users',
}
ALL_SOURCES = frozenset({'money', 'game', 'users'})
MG = frozenset({'money', 'game'})          # money+game (у обоих есть событие created_at)
MONEY_ONLY = frozenset({'money'})

# ── SQL-условия успешных операций (вокабуляр из api/casino_vocab.py, per-tenant
#    через env; дефолты = BillionBahis). Префикс f. — фактовая таблица в JOIN. ──
from . import casino_vocab as _v

_SUCCESS = _v.in_list("f.status", _v.SUCCESS_STATUSES)
DEP_OK = f"{_v.in_list('f.type', _v.DEPOSIT_TYPES)} AND {_SUCCESS}"
WD_OK = f"{_v.in_list('f.type', _v.WITHDRAWAL_TYPES)} AND {_SUCCESS}"
BONUS_OK = f"{_v.in_list('f.type', _v.BONUS_TYPES)} AND {_SUCCESS}"
# «Попытка вывода» (out try, ТЗ П6): ЛЮБАЯ инициированная заявка на тип вывода
# — включая rejected/cancelled/pending. Совместимо с WD_OK (тот же тип, любой статус).
WD_TRY = _v.in_list("f.type", _v.WITHDRAWAL_TYPES)
# Бонус, отыгранный/сконвертированный на реальный баланс — «релизнутые на реал»
# из формулы bonus cost Василия.
BONUS_WAGED = f"{_v.in_list('f.type', _v.BONUS_WAGED_TYPES)} AND {_v.in_list('f.status', _v.GAME_SUCCESS_STATUSES)}"
# игровые: pending/rejected НЕ в итоги (успех = GAME_SUCCESS_STATUSES), как в
# player_features.sql и /ggr (_ggr_kpis: gw содержит GSUCCESS).
_GSUCCESS = _v.in_list("f.status", _v.GAME_SUCCESS_STATUSES)
BET_OK = f"{_v.in_list('f.transaction_type', _v.BET_TYPES)} AND {_GSUCCESS}"
WIN_OK = f"{_v.in_list('f.transaction_type', _v.WIN_TYPES)} AND {_GSUCCESS}"

_TZ = "'Europe/Istanbul'"


@dataclass(frozen=True)
class Metric:
    key: str
    label: str          # рус.
    source: str         # 'money' | 'game' | 'users'
    fmt: str            # 'try' | 'int' | 'pct'
    sql: str            # агрегат, f-квалифицированный
    date_col: str       # якорная дата: 'created_at' | 'reg_date' | 'ftd_date'
    window: str = ''    # '' | 'dep_seq' — нужен оконный под-пасс (секвенс депозитов);
                        # sql может ссылаться на f._dep_try_seq / f._dep_succ_seq


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str          # рус.
    kind: str           # 'time' | 'profile' | 'transaction' | 'state_at'
    sql: str            # шаблон с {date}/{u}
    applicable_sources: frozenset  # источники, к которым применим
    value_type: str     # 'str' | 'int' | 'date' (тип значения/фильтра)
    needs: str          # '' | 'users' | 'psd' (какой JOIN нужен факту money/game)


# ════════════════════════════════════════════════════════════════════════════
# METRICS — 22 метрики (money / game / users); pct = процент (margin, wd/dep, конверсии)
# ════════════════════════════════════════════════════════════════════════════
METRICS: dict[str, Metric] = {
    # ── деньги (money_transactions, период по created_at) ──
    'deposits_sum': Metric(
        'deposits_sum', 'Депозиты, ₺', 'money', 'try',
        f"round(sumIf(f.amount, {DEP_OK}), 2)", 'created_at'),
    'deposits_count': Metric(
        'deposits_count', 'Кол-во депозитов', 'money', 'int',
        f"countIf({DEP_OK})", 'created_at'),
    'depositors': Metric(
        'depositors', 'Депозиторы (уник.)', 'money', 'int',
        f"uniqExactIf(f.casino_player_id, {DEP_OK})", 'created_at'),
    'withdrawals_sum': Metric(
        'withdrawals_sum', 'Выводы, ₺', 'money', 'try',
        f"round(sumIf(abs(f.amount), {WD_OK}), 2)", 'created_at'),
    # ── новые деньги-метрики (ТЗ П6, все однопартиционные по money) ──
    'withdrawals_count': Metric(       # out cnt — успешные выводы
        'withdrawals_count', 'Кол-во выводов', 'money', 'int',
        f"countIf({WD_OK})", 'created_at'),
    'out_try_count': Metric(           # out try cnt — все заявки на вывод (любой статус)
        'out_try_count', 'Попытки вывода', 'money', 'int',
        f"countIf({WD_TRY})", 'created_at'),
    'withdrawers': Metric(             # uniq out — уник. успешно выводившие
        'withdrawers', 'Выводящие (уник.)', 'money', 'int',
        f"uniqExactIf(f.casino_player_id, {WD_OK})", 'created_at'),
    'withdraw_attempters': Metric(     # uniq try out — уник. пытавшиеся вывести
        'withdraw_attempters', 'Пытались вывести (уник.)', 'money', 'int',
        f"uniqExactIf(f.casino_player_id, {WD_TRY})", 'created_at'),
    'out_conversion': Metric(          # out try→out — конверсия заявки в успешный вывод
        'out_conversion', 'Вывод: заявка→успех, %', 'money', 'pct',
        f"round(100 * countIf({WD_OK}) / nullIf(countIf({WD_TRY}), 0), 1)", 'created_at'),
    'uniq_out_ratio': Metric(          # uniq try out→uniq out — соотношение уникумов вывода
        'uniq_out_ratio', 'Вывод: уник. успех/заявка, %', 'money', 'pct',
        f"round(100 * uniqExactIf(f.casino_player_id, {WD_OK})"
        f" / nullIf(uniqExactIf(f.casino_player_id, {WD_TRY}), 0), 1)", 'created_at'),
    'avg_deposit': Metric(             # avg deposit — средний успешный депозит
        'avg_deposit', 'Средний депозит, ₺', 'money', 'try',
        f"round(sumIf(f.amount, {DEP_OK}) / nullIf(countIf({DEP_OK}), 0), 2)", 'created_at'),
    'wd_dep_ratio': Metric(            # out/dep sum — выводы/депозиты (Д3, здоровье гео)
        'wd_dep_ratio', 'Выводы/депозиты, %', 'money', 'pct',
        f"round(100 * sumIf(abs(f.amount), {WD_OK}) / nullIf(sumIf(f.amount, {DEP_OK}), 0), 1)", 'created_at'),
    'bonus_waged': Metric(             # bonus waged — отыграно/сконвертировано на реал
        'bonus_waged', 'Бонусы отыграно, ₺', 'money', 'try',
        f"round(sumIf(abs(f.amount), {BONUS_WAGED}), 2)", 'created_at'),
    # ── секвенс депозитов (окно PARTITION BY pid+разрезы): уники повторных депозитов ──
    # _dep_try_seq = порядковый номер ПОПЫТКИ депозита игрока внутри группы;
    # _dep_succ_seq = порядковый номер УСПЕШНОГО депозита. >=2 → повторный (RD).
    'uniq_try_rd': Metric(             # uniq try RD (кол.7) — уник. с попыткой 2-го+ депозита
        'uniq_try_rd', 'Уник. попытка повт. депозита', 'money', 'int',
        "uniqExactIf(f.casino_player_id, f.type = 'deposit' AND f._dep_try_seq >= 2)",
        'created_at', window='dep_seq'),
    'uniq_rd': Metric(                 # uniq RD (кол.8) — уник. с успешным 2-м+ депозитом
        'uniq_rd', 'Уник. повторный депозит', 'money', 'int',
        f"uniqExactIf(f.casino_player_id, {DEP_OK} AND f._dep_succ_seq >= 2)",
        'created_at', window='dep_seq'),
    'try_rd_to_rd': Metric(            # try RD→RD (кол.9) — конверсия попытки повт. в успех
        'try_rd_to_rd', 'Повт. депозит: попытка→успех, %', 'money', 'pct',
        f"round(100 * uniqExactIf(f.casino_player_id, {DEP_OK} AND f._dep_succ_seq >= 2)"
        " / nullIf(uniqExactIf(f.casino_player_id, f.type = 'deposit' AND f._dep_try_seq >= 2), 0), 1)",
        'created_at', window='dep_seq'),
    'bonus_cost': Metric(
        'bonus_cost', 'Бонус-косты, ₺', 'money', 'try',
        f"round(sumIf(abs(f.amount), {BONUS_OK}), 2)", 'created_at'),
    # производная: депозиты − выводы, одним SQL-выражением
    'net_cash': Metric(
        'net_cash', 'Чистый кэш, ₺', 'money', 'try',
        f"round(sumIf(f.amount, {DEP_OK}) - sumIf(abs(f.amount), {WD_OK}), 2)", 'created_at'),
    # ── игра (game_transactions, период по created_at) ──
    'ggr': Metric(
        'ggr', 'GGR, ₺', 'game', 'try',
        f"round(sumIf(f.bet_amount, {BET_OK}) - sumIf(f.win_amount, {WIN_OK}), 2)", 'created_at'),
    'turnover': Metric(
        'turnover', 'Оборот, ₺', 'game', 'try',
        f"round(sumIf(f.bet_amount, {BET_OK}), 2)", 'created_at'),
    'bet_count': Metric(               # bet cnt — число ставок
        'bet_count', 'Кол-во ставок', 'game', 'int',
        f"countIf({BET_OK})", 'created_at'),
    'margin': Metric(                  # margin — GGR / оборот, %
        'margin', 'Маржа (GGR/оборот), %', 'game', 'pct',
        f"round(100 * (sumIf(f.bet_amount, {BET_OK}) - sumIf(f.win_amount, {WIN_OK}))"
        f" / nullIf(sumIf(f.bet_amount, {BET_OK}), 0), 2)", 'created_at'),
    'active_players': Metric(
        'active_players', 'Активные игроки', 'game', 'int',
        f"uniqExactIf(f.casino_player_id, {BET_OK})", 'created_at'),
    # ── игроки (users, период по своей дате события) ──
    'ftd_count': Metric(
        'ftd_count', 'FTD (первые депозиты)', 'users', 'int',
        "uniqExact(f.casino_player_id)", 'ftd_date'),
    'registrations': Metric(
        'registrations', 'Регистрации', 'users', 'int',
        "uniqExact(f.casino_player_id)", 'reg_date'),
}


# ════════════════════════════════════════════════════════════════════════════
# DIMENSIONS — 14 разрезов (time / profile / transaction / state_at)
# ════════════════════════════════════════════════════════════════════════════
DIMENSIONS: dict[str, Dimension] = {
    # ── time (по якорной дате события, Istanbul business day) ──
    'day': Dimension(
        'day', 'День', 'time', f"toDate(toTimezone({{date}},{_TZ}))", ALL_SOURCES, 'date', ''),
    'week': Dimension(
        'week', 'Неделя', 'time', f"toMonday(toTimezone({{date}},{_TZ}))", ALL_SOURCES, 'date', ''),
    'month': Dimension(
        'month', 'Месяц', 'time', f"toStartOfMonth(toTimezone({{date}},{_TZ}))", ALL_SOURCES, 'date', ''),
    'weekday': Dimension(
        'weekday', 'День недели', 'time', f"toDayOfWeek(toTimezone({{date}},{_TZ}))", ALL_SOURCES, 'int', ''),
    'hour': Dimension(
        'hour', 'Час', 'time', f"toHour(toTimezone({{date}},{_TZ}))", MG, 'int', ''),
    # ── profile (JOIN users; {u} = алиас users, для source=users это сам факт f) ──
    'country': Dimension(
        'country', 'Страна', 'profile', "{u}.country_iso_estimated", ALL_SOURCES, 'str', 'users'),
    'currency': Dimension(
        'currency', 'Валюта', 'profile', "{u}.currency", ALL_SOURCES, 'str', 'users'),
    'affiliate_code': Dimension(
        'affiliate_code', 'Аффилиат (код)', 'profile', "{u}.affiliate_code", ALL_SOURCES, 'str', 'users'),
    'affiliate_type': Dimension(   # '(none)'-нормализация как player_features.sql:23
        'affiliate_type', 'Тип аффилиата', 'profile',
        "if({u}.affiliate_account_type = '', '(none)', {u}.affiliate_account_type)",
        ALL_SOURCES, 'str', 'users'),
    'registration_source': Dimension(
        'registration_source', 'Источник регистрации', 'profile',
        "substring({u}.registration_source, 1, 42)", ALL_SOURCES, 'str', 'users'),
    'account_type': Dimension(
        'account_type', 'Тип аккаунта', 'profile', "{u}.account_type", ALL_SOURCES, 'str', 'users'),
    # ── transaction (только money) ──
    'payment_method': Dimension(
        'payment_method', 'Метод оплаты', 'transaction', "f.payment_method", MONEY_ONLY, 'str', ''),
    # ── state_at (ИСТОРИЧЕСКИ КОРРЕКТНЫЕ: снапшот на дату события; только money/game) ──
    'vip_level_at': Dimension(
        'vip_level_at', 'VIP-уровень на дату', 'state_at', "psd.vip_level", MG, 'int', 'psd'),
    'lifecycle_at': Dimension(
        'lifecycle_at', 'Жизненный цикл на дату', 'state_at', "psd.lifecycle", MG, 'str', 'psd'),
    'early_tier_at': Dimension(
        'early_tier_at', 'Ранний тир на дату', 'state_at', "psd.early_tier", MG, 'str', 'psd'),
}


# ════════════════════════════════════════════════════════════════════════════
# DERIVED — производные колонки (отношения base-метрик, считаются POST-AGG в
# api/reports.py, а НЕ в SQL). Для кросс-партиционных отношений (напр. reg (users/
# reg_date) ÷ FD (users/ftd_date), или bonus (money) ÷ GGR (game)) — их нельзя
# выразить одним sumIf. Компилятор раскрывает derived → его deps (base-метрики для
# SQL), reports.py досчитывает отношение по строке/тоталам/экспорту.
# ════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Derived:
    key: str
    label: str          # рус.
    fmt: str            # 'pct'
    deps: tuple         # базовые ключи METRICS, нужные для вычисления
    fn: Any             # callable(row: dict) -> float | None  (post-agg)


def _ratio_pct(num: Any, den: Any) -> Any:
    """100 * num / den, округл. до 0.1; None если знаменатель 0 (нет базы)."""
    n = float(num or 0)
    d = float(den or 0)
    if not d:
        return None
    res = round(100 * n / d, 1)
    return res if res != 0 else 0.0   # нормализуем -0.0 → 0.0


DERIVED: dict[str, Derived] = {
    'reg_to_fd': Derived(          # кол.4 — сквозная конверсия FD cnt / reg cnt
        'reg_to_fd', 'Конверсия reg→FD, %', 'pct',
        ('registrations', 'ftd_count'),
        lambda r: _ratio_pct(r.get('ftd_count'), r.get('registrations'))),
    'bonus_cost_ratio': Derived(   # кол.38 — Released / (GGR total − Released)
        'bonus_cost_ratio', 'Bonus cost, %', 'pct',
        ('bonus_waged', 'ggr'),
        lambda r: _ratio_pct(r.get('bonus_waged'),
                             float(r.get('ggr') or 0) - float(r.get('bonus_waged') or 0))),
}


def is_derived(key: str) -> bool:
    return key in DERIVED


def plan_metrics(metrics: list[str]) -> list[str]:
    """Базовые METRICS-ключи для SQL: выбранные base + зависимости derived,
    без дублей, в порядке первого появления. Порядок ВЫВОДА колонок — это
    исходный spec['metrics'] (base+derived), собирается в result_columns."""
    base: list[str] = []
    for m in metrics:
        deps = DERIVED[m].deps if m in DERIVED else (m,)
        for k in deps:
            if k not in base:
                base.append(k)
    return base


def compute_derived(row: dict, keys: list[str]) -> dict:
    """Досчитать derived-колонки в row (мутирует и возвращает его же)."""
    for k in keys:
        if k in DERIVED:
            row[k] = DERIVED[k].fn(row)
    return row


# ── типы колонок результата (для UI/экспорта) ──
def metric_col_type(key: str) -> str:
    if key in DERIVED:
        return {'try': 'money', 'pct': 'pct'}.get(DERIVED[key].fmt, 'int')
    return {'try': 'money', 'pct': 'pct'}.get(METRICS[key].fmt, 'int')


def metric_label(key: str) -> str:
    return DERIVED[key].label if key in DERIVED else METRICS[key].label


def dim_col_type(key: str) -> str:
    vt = DIMENSIONS[key].value_type
    return {'date': 'date', 'int': 'int'}.get(vt, 'string')


def describe_fields() -> dict[str, Any]:
    """Оба реестра в JSON-safe виде — для GET /reports/fields (UI строит панель)."""
    metrics = {
        k: {'key': m.key, 'label': m.label, 'source': m.source,
            'fmt': m.fmt, 'type': metric_col_type(k), 'derived': False}
        for k, m in METRICS.items()
    }
    # производные — отдельным «источником» derived (UI группирует и помечает ∑)
    metrics.update({
        k: {'key': d.key, 'label': d.label, 'source': 'derived',
            'fmt': d.fmt, 'type': metric_col_type(k), 'derived': True,
            'deps': list(d.deps)}
        for k, d in DERIVED.items()
    })
    return {
        'metrics': metrics,
        'dimensions': {
            k: {'key': d.key, 'label': d.label, 'kind': d.kind,
                'value_type': d.value_type, 'type': dim_col_type(k),
                'applicable_sources': sorted(d.applicable_sources)}
            for k, d in DIMENSIONS.items()
        },
    }
