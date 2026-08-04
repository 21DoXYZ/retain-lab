"""api/report_builder.py — компилятор spec → один ClickHouse GROUP BY-запрос (W5-T2).

ЧИСТЫЙ, БЕЗ БД: build_report_query(spec) → (sql, params). Никаких обращений к
ClickHouse/Flask — поэтому юнит-тестируется без базы. Исполнение и meta
(history_from, took_ms) — в api/reports.py.

Контракт spec:
    {
      "metrics": [<ключи METRICS>],           # 1..8
      "dims":    [<ключи DIMENSIONS>],         # 0..3, порядок = порядок группировки
      "filters": [{"dim","op":"in"|"not_in","value":[...]}],
      "period":  {"from":"YYYY-MM-DD","to":"YYYY-MM-DD"}   # обязателен, ≤ 366 дней
    }

Устройство multi-source:
  Метрики группируются по ИСТОЧНИКУ+ЯКОРНОЙ ДАТЕ (source, date_col) — «партиция».
  Для каждой партиции строится свой подзапрос (своя фактовая таблица + нужные
  JOIN по использованным разрезам, свой период по своей дате, GROUP BY dims).
  Партиций максимум 2 (иначе «упростите отчёт»); объединяются FULL OUTER JOIN по
  dims, NULL-разрезы после джойна нормализуются coalesce. Инвариант разбиения
  (Σ по группам == тотал без группировки) держится ПОКАЖДОЙ партиции: и период, и
  time-разрез считаются от ОДНОЙ якорной даты.

Историческая корректность: state_at-разрезы джойнят player_state_daily FINAL на
snap_date = дата СОБЫТИЯ (toDate(toTimezone(f.created_at,'Europe/Istanbul'))), а не
на текущую дату. События раньше min(snap_date) дадут дефолт-группу — это честно;
api/reports.py отдаёт meta.history_from, чтобы UI предупредил про период до начала
снапшотов.
"""
from __future__ import annotations

import datetime
from typing import Any

from .report_fields import (METRICS, DIMENSIONS, FACT, DEP_OK,
                            DERIVED, plan_metrics)

MAX_METRICS = 12
MAX_DIMS = 3
# Лимит ПАРТИЦИЙ (источник+якорная дата), не источников: reg (users/reg_date) +
# FD (users/ftd_date) + деньги (money/created_at) + игра (game/created_at) = 4.
# Столько нужно отчёту Project Performance (П6). Каждая партиция — свой скан+джойн.
MAX_SOURCES = 4
MAX_PERIOD_DAYS = 366
ROW_LIMIT = 10000
MAX_EXEC_SECONDS = 30
_TZ = "'Europe/Istanbul'"
_OPS = {'in': 'IN', 'not_in': 'NOT IN'}


# ════════════════════════════════════════════════════════════════════════════
# Ошибки спеки: код + параметры для i18n на фронте (+ рус. текст как фолбэк/лог)
# ════════════════════════════════════════════════════════════════════════════
class SpecError(ValueError):
    """Ошибка валидации spec. `code` (стабильный слаг) + `params` переводятся на
    фронте (reports.err.<code>); строковое сообщение — рус. фолбэк/для логов."""
    def __init__(self, code: str, message: str, params: dict | None = None):
        super().__init__(message)
        self.code = code
        self.params = params or {}


# ════════════════════════════════════════════════════════════════════════════
# Валидация / разбор
# ════════════════════════════════════════════════════════════════════════════
def _parse_date(s: Any) -> datetime.date:
    if not isinstance(s, str) or len(s) != 10 or s[4] != '-' or s[7] != '-':
        raise SpecError('bad_date_format',
                        f'дата должна быть в формате YYYY-MM-DD, получено: {s!r}',
                        {'value': str(s)})
    try:
        return datetime.date.fromisoformat(s)
    except ValueError as e:
        raise SpecError('bad_date', f'некорректная дата: {s!r}', {'value': str(s)}) from e


def _validate(spec: dict) -> tuple[list[str], list[str], list[dict], str, str]:
    """Валидирует spec (whitelist) → (metrics, dims, filters, d_from, d_to).
    Любое нарушение — SpecError (code+params для i18n) с рус. фолбэк-текстом."""
    if not isinstance(spec, dict):
        raise SpecError('spec_not_object', 'spec должен быть объектом')

    metrics = spec.get('metrics') or []
    dims = spec.get('dims') or []
    filters = spec.get('filters') or []
    period = spec.get('period')

    # ── метрики (base из METRICS или производные из DERIVED) ──
    if not isinstance(metrics, list) or not (1 <= len(metrics) <= MAX_METRICS):
        raise SpecError('metrics_count', f'metrics: ожидается от 1 до {MAX_METRICS} ключей',
                        {'max': MAX_METRICS})
    for m in metrics:
        if m not in METRICS and m not in DERIVED:
            raise SpecError('unknown_metric', f'неизвестная метрика: {m!r}', {'metric': str(m)})
    # производные раскрываем в их base-зависимости — именно они идут в SQL
    base_metrics = plan_metrics(metrics)
    if len(base_metrics) > MAX_METRICS:
        raise SpecError('too_many_base_metrics',
                        f'слишком много базовых метрик ({len(base_metrics)}) с учётом '
                        f'зависимостей производных — не более {MAX_METRICS}; упростите отчёт',
                        {'count': len(base_metrics), 'max': MAX_METRICS})

    # ── разрезы ──
    if not isinstance(dims, list) or len(dims) > MAX_DIMS:
        raise SpecError('dims_count', f'dims: не более {MAX_DIMS} разрезов', {'max': MAX_DIMS})
    for d in dims:
        if d not in DIMENSIONS:
            raise SpecError('unknown_dim', f'неизвестный разрез: {d!r}', {'dim': str(d)})
    if len(set(dims)) != len(dims):
        raise SpecError('dims_duplicate', 'dims: разрезы не должны повторяться')

    # ── фильтры ──
    if not isinstance(filters, list):
        raise SpecError('filters_not_list', 'filters: ожидается список')
    for flt in filters:
        if not isinstance(flt, dict):
            raise SpecError('filter_not_object', 'filters: каждый фильтр — объект {dim, op, value}')
        fd = flt.get('dim')
        if fd not in DIMENSIONS:
            raise SpecError('filter_unknown_dim', f'фильтр по неизвестному разрезу: {fd!r}',
                            {'dim': str(fd)})
        if flt.get('op') not in _OPS:
            raise SpecError('filter_bad_op', f"фильтр {fd}: op должен быть 'in' или 'not_in'",
                            {'dim': str(fd)})
        val = flt.get('value')
        if not isinstance(val, list) or len(val) == 0:
            raise SpecError('filter_empty_value', f'фильтр {fd}: value — непустой список значений',
                            {'dim': str(fd)})

    # ── период ──
    if not isinstance(period, dict) or 'from' not in period or 'to' not in period:
        raise SpecError('period_required', 'period обязателен: {from, to} в формате YYYY-MM-DD')
    d_from = _parse_date(period['from'])
    d_to = _parse_date(period['to'])
    if d_from > d_to:
        raise SpecError('period_order', 'period: from не может быть позже to')
    span = (d_to - d_from).days + 1
    if span > MAX_PERIOD_DAYS:
        raise SpecError('period_too_long',
                        f'period: диапазон {span} дн. превышает лимит {MAX_PERIOD_DAYS} дн.',
                        {'span': span, 'max': MAX_PERIOD_DAYS})

    # ── применимость разрезов к источникам отчёта (по base-метрикам) ──
    sources = {METRICS[m].source for m in base_metrics}
    referenced = set(dims) | {flt['dim'] for flt in filters}
    for rd in referenced:
        dim = DIMENSIONS[rd]
        if not sources <= dim.applicable_sources:
            bad = sorted(sources - dim.applicable_sources)
            raise SpecError(
                'dim_not_applicable',
                f'разрез «{dim.label}» ({rd}) неприменим к метрикам источника '
                f'{bad}: например, историко-состоянийные (state_at) разрезы нельзя '
                f'считать по метрикам игроков (users), а payment_method — только по деньгам',
                {'dim': rd, 'label': dim.label, 'sources': ', '.join(bad)})

    # ── число партиций (источник+якорная дата) ──
    partitions = _partition_keys(base_metrics)
    if len(partitions) > MAX_SOURCES:
        raise SpecError('too_many_sources',
                        f'в одном отчёте не более {MAX_SOURCES} источников данных — упростите '
                        'отчёт (разнесите метрики денег / игры / игроков)', {'max': MAX_SOURCES})

    # возвращаем BASE-метрики (для SQL); порядок вывода колонок — из spec, в
    # result_columns (там base+derived в пользовательском порядке)
    return list(base_metrics), list(dims), list(filters), period['from'], period['to']


def _partition_keys(metrics: list[str]) -> list[tuple[str, str]]:
    """Упорядоченный (по первому появлению) список ключей партиций (source, date_col)."""
    seen: list[tuple[str, str]] = []
    for m in metrics:
        key = (METRICS[m].source, METRICS[m].date_col)
        if key not in seen:
            seen.append(key)
    return seen


def report_uses_state_at(spec: dict) -> bool:
    """Есть ли в отчёте хоть один state_at-разрез (в группировке или фильтрах).
    Нужен api/reports.py, чтобы решить, тянуть ли history_from в meta."""
    dims = spec.get('dims') or []
    filters = spec.get('filters') or []
    keys = set(dims) | {f.get('dim') for f in filters if isinstance(f, dict)}
    return any(DIMENSIONS[k].kind == 'state_at' for k in keys if k in DIMENSIONS)


# ════════════════════════════════════════════════════════════════════════════
# Генерация SQL
# ════════════════════════════════════════════════════════════════════════════
def _dim_expr(dkey: str, source: str, date_col: str) -> str:
    """SQL-выражение разреза для конкретного источника (подставляет {date}/{u})."""
    e = DIMENSIONS[dkey].sql
    if '{date}' in e:
        e = e.replace('{date}', f'f.{date_col}')
    if '{u}' in e:
        e = e.replace('{u}', 'f' if source == 'users' else 'u')
    return e


def _filter_param_type(dkey: str) -> str:
    return 'Array(Int64)' if DIMENSIONS[dkey].value_type == 'int' else 'Array(String)'


def _coerce_filter_values(dkey: str, value: list) -> list:
    if DIMENSIONS[dkey].value_type == 'int':
        return [int(v) for v in value]
    return [str(v) for v in value]


def _build_subquery(source: str, date_col: str, metric_keys: list[str],
                    dims: list[str], filters: list[dict],
                    filter_params: dict[int, str]) -> str:
    """Подзапрос одной партиции: FROM факт + нужные JOIN + GROUP BY dims."""
    fact = FACT[source]
    used_dims = set(dims) | {flt['dim'] for flt in filters}

    # JOIN'ы (только для money/game; для users profile-разрезы берут сам факт f)
    joins: list[str] = []
    if source in ('money', 'game') and any(DIMENSIONS[d].needs == 'users' for d in used_dims):
        joins.append('LEFT JOIN users AS u ON u.casino_player_id = f.casino_player_id')
    if any(DIMENSIONS[d].needs == 'psd' for d in used_dims):
        # снапшот НА ДАТУ СОБЫТИЯ (историческая корректность), читаем FINAL
        joins.append(
            "LEFT JOIN player_state_daily AS psd FINAL "
            "ON psd.casino_player_id = f.casino_player_id "
            f"AND psd.snap_date = toDate(toTimezone(f.created_at,{_TZ}))")

    # WHERE: период по своей якорной дате (Istanbul business day) + фильтры
    where = [f"toDate(toTimezone(f.{date_col},{_TZ})) "
             "BETWEEN {d_from:Date} AND {d_to:Date}"]
    if source == 'users':
        where.append(f"f.{date_col} IS NOT NULL")   # reg_date/ftd_date nullable
    for i, flt in enumerate(filters):
        dkey = flt['dim']
        pname = filter_params[i]
        expr = _dim_expr(dkey, source, date_col)
        where.append(f"{expr} {_OPS[flt['op']]} {{{pname}:{_filter_param_type(dkey)}}}")

    join_sql = (' ' + ' '.join(joins)) if joins else ''
    where_sql = ' WHERE ' + ' AND '.join(where)

    # ── оконный под-пасс: секвенс депозитов (uniq try RD / uniq RD и т.п.) ──
    # Метрики с window ссылаются на f._dep_try_seq / f._dep_succ_seq — бегущие
    # номера попытки/успеха депозита игрока ВНУТРИ группы (PARTITION BY pid+разрезы,
    # уникумы «за период целиком» по требованию П6). Оконные колонки нельзя считать
    # в том же SELECT, где идёт GROUP BY, поэтому окно — во вложенном запросе.
    if any(METRICS[m].window for m in metric_keys):
        dim_exprs = [_dim_expr(d, source, date_col) for d in dims]
        part_by = ', '.join(['f.casino_player_id'] + dim_exprs)
        win = (f"WINDOW w AS (PARTITION BY {part_by} ORDER BY f.{date_col} "
               "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)")
        # во вложенный SELECT — только колонки, нужные внешним money-метрикам
        # (amount/type/status/pid), разрезы-алиасы и оконные счётчики
        inner_cols = ['f.casino_player_id', 'f.type', 'f.status', 'f.amount']
        inner_cols += [f"{e} AS {d}" for e, d in zip(dim_exprs, dims)]
        inner_cols += ["countIf(f.type = 'deposit') OVER w AS _dep_try_seq",
                       f"countIf({DEP_OK}) OVER w AS _dep_succ_seq"]
        inner = f"SELECT {', '.join(inner_cols)} FROM {fact} AS f{join_sql}{where_sql} {win}"
        outer_cols = [f"{d} AS {d}" for d in dims]
        outer_cols += [f"{METRICS[m].sql} AS {m}" for m in metric_keys]
        sql = f"SELECT {', '.join(outer_cols)} FROM ( {inner} ) AS f"
        if dims:
            sql += ' GROUP BY ' + ', '.join(dims)
        return sql

    # ── обычный плоский агрегат ──
    select_parts = [f"{_dim_expr(d, source, date_col)} AS {d}" for d in dims]
    select_parts += [f"{METRICS[m].sql} AS {m}" for m in metric_keys]
    sql = f"SELECT {', '.join(select_parts)} FROM {fact} AS f{join_sql}{where_sql}"
    if dims:
        sql += ' GROUP BY ' + ', '.join(_dim_expr(d, source, date_col) for d in dims)
    return sql


def build_report_query(spec: dict) -> tuple[str, dict]:
    """Компилирует spec в один ClickHouse-запрос. → (sql, params)."""
    metrics, dims, filters, d_from, d_to = _validate(spec)

    params: dict[str, Any] = {'d_from': d_from, 'd_to': d_to}
    # имена параметров фильтров — общие для всех подзапросов (значение одно)
    filter_params: dict[int, str] = {}
    for i, flt in enumerate(filters):
        pname = f'flt{i}'
        filter_params[i] = pname
        params[pname] = _coerce_filter_values(flt['dim'], flt['value'])

    partitions = _partition_keys(metrics)
    # метрики каждой партиции — в порядке появления в spec
    part_metrics = {p: [m for m in metrics if (METRICS[m].source, METRICS[m].date_col) == p]
                    for p in partitions}

    settings = f'LIMIT {ROW_LIMIT} SETTINGS max_execution_time = {MAX_EXEC_SECONDS}'

    subs = [_build_subquery(src, dc, part_metrics[(src, dc)], dims, filters, filter_params)
            for (src, dc) in partitions]

    if len(partitions) == 1:
        sql = f"SELECT * FROM ( {subs[0]} ) AS r"
        if dims:
            sql += ' ORDER BY ' + ', '.join(dims)
        sql += f' {settings}'
        return sql, params

    # ── N партиций (2..MAX_SOURCES): цепочка FULL OUTER JOIN по разрезам ──
    # каждая сторона s0..s{N-1} даёт свои метрики; разрезы совпадают по значению,
    # но NULL с любой стороны после аутер-джойна → coalesce по ВСЕМ сторонам.
    side_of = {}
    for idx, p in enumerate(partitions):
        for m in part_metrics[p]:
            side_of[m] = f's{idx}'

    n = len(partitions)
    out_cols = [f"coalesce({', '.join(f's{i}.{d}' for i in range(n))}) AS {d}" for d in dims]
    out_cols += [f"{side_of[m]}.{m} AS {m}" for m in metrics]

    body = f"( {subs[0]} ) AS s0"
    for i in range(1, n):
        if dims:
            # ключ соединения — coalesce уже присоединённых сторон s0..s{i-1}
            on = ' AND '.join(
                f"coalesce({', '.join(f's{j}.{d}' for j in range(i))}) = s{i}.{d}"
                for d in dims)
            body += f" FULL OUTER JOIN ( {subs[i]} ) AS s{i} ON {on}"
        else:
            # тоталы (dims=[]): по одной строке с каждой стороны → перекрёстное соединение
            body += f" CROSS JOIN ( {subs[i]} ) AS s{i}"

    tail = (' ORDER BY ' + ', '.join(dims)) if dims else ''
    sql = f"SELECT {', '.join(out_cols)} FROM {body}{tail} {settings}"
    return sql, params


def result_columns(spec: dict) -> list[dict]:
    """Порядок и типы колонок результата: разрезы (в порядке dims), затем метрики
    в ПОЛЬЗОВАТЕЛЬСКОМ порядке spec (base + derived вперемешку). Производные
    колонки досчитываются в api/reports.py. Используется для {columns} и экспорта."""
    from .report_fields import metric_col_type, metric_label, dim_col_type
    dims = spec.get('dims') or []
    metrics = spec.get('metrics') or []
    cols = [{'key': d, 'label': DIMENSIONS[d].label, 'type': dim_col_type(d)} for d in dims]
    cols += [{'key': m, 'label': metric_label(m), 'type': metric_col_type(m)} for m in metrics]
    return cols
