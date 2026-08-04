"""api/segment_compiler.py — JSON-дерево условий → безопасный ClickHouse-WHERE.

Вход — `definition` (дерево групп И/ИЛИ из условий по каталогу `segment_fields`).
Выход — `(where_sql, params, used_joins)`:
  • where_sql — строка WHERE с плейсхолдерами {name:Type} (server-side params CH);
  • params    — dict значений для этих плейсхолдеров;
  • used_joins — множество алиасов JOIN, которые нужно подключить (base_query).

БЕЗОПАСНОСТЬ (инъекция невозможна by design):
  • имена полей/операторов/таблиц берутся ТОЛЬКО из whitelist (FIELDS/OPS_BY_TYPE/
    EVENTS) — пользовательские строки туда не попадают;
  • ВСЕ пользовательские значения уходят исключительно параметрами {name:Type};
  • sys_name/поле event валидируются регуляркой до подстановки.

Ошибки — `ValueError` с человекочитаемой русской причиной (ловит ручка → 422).
"""
from __future__ import annotations

import re

from .segment_fields import FIELDS, JOINS, ML_JOINS, EVENTS, Field

# Операторы, допустимые по типу поля (ТЗ §1.2).
OPS_BY_TYPE: dict[str, frozenset[str]] = {
    'num':  frozenset({'eq', 'ne', 'gt', 'lt', 'between', 'top_pct'}),
    'date': frozenset({'before', 'after', 'between', 'days_ago_gt', 'days_ago_lt'}),
    'enum': frozenset({'in', 'not_in'}),
    'flag': frozenset({'is', 'is_null'}),
    'str':  frozenset({'eq', 'ne', 'contains', 'in', 'not_in'}),
}

EVENT_COUNT_OPS = {'gte': '>=', 'gt': '>', 'lte': '<=', 'lt': '<', 'eq': '=', 'ne': '!='}

_SYS_NAME_RE = re.compile(r'^[a-z][a-z0-9_]{2,63}$')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_TRUTHY = "('t','true','1','yes','y','on')"

MAX_DEPTH = 2


class _Ctx:
    """Счётчик уникальных имён параметров + аккумулятор джойнов."""
    __slots__ = ('n', 'params', 'joins')

    def __init__(self) -> None:
        self.n = 0
        self.params: dict = {}
        self.joins: set[str] = set()

    def param(self, value, ch_type: str) -> str:
        name = f'p{self.n}'
        self.n += 1
        self.params[name] = value
        return '{' + f'{name}:{ch_type}' + '}'


# ── публичный вход ───────────────────────────────────────────────────────────
def compile_definition(definition) -> tuple[str, dict, set[str]]:
    """JSON-дерево → (where_sql, params, used_joins). См. модульный docstring."""
    if not isinstance(definition, dict) or not ('all' in definition or 'any' in definition):
        raise ValueError("Определение сегмента должно быть группой с 'all' или 'any'")
    ctx = _Ctx()
    where = _compile_group(definition, ctx, depth=1)
    return where, ctx.params, ctx.joins


def base_query(where: str, used_joins) -> str:
    """SELECT id из player_features с нужными джойнами и account_type='normal'."""
    join_sql = ' '.join(JOINS[a] for a in sorted(used_joins))
    join_part = (' ' + join_sql) if join_sql else ''
    return ("SELECT f.casino_player_id FROM player_features AS f" + join_part +
            " WHERE f.account_type = 'normal' AND (" + where + ")")


# ── группы И / ИЛИ ───────────────────────────────────────────────────────────
def _compile_group(group: dict, ctx: _Ctx, depth: int) -> str:
    if depth > MAX_DEPTH:
        raise ValueError("Слишком глубокая вложенность групп (максимум 2 уровня) — упростите условие")
    if 'all' in group:
        joiner, items = ' AND ', group['all']
    elif 'any' in group:
        joiner, items = ' OR ', group['any']
    else:
        raise ValueError("Группа условий должна быть 'all' или 'any'")
    if not isinstance(items, list):
        raise ValueError("Список условий группы должен быть массивом")
    parts = [_compile_item(it, ctx, depth) for it in items]
    if not parts:
        return '1'
    return '(' + joiner.join(parts) + ')'


def _compile_item(item, ctx: _Ctx, depth: int) -> str:
    if not isinstance(item, dict):
        raise ValueError("Условие должно быть объектом")
    if 'all' in item or 'any' in item:
        return _compile_group(item, ctx, depth + 1)
    if 'not_segment' in item:
        return _compile_not_segment(item['not_segment'], ctx)
    if 'event' in item:
        return _compile_event(item['event'], ctx)
    if 'field' in item:
        return _compile_leaf(item, ctx)
    raise ValueError("Неизвестный тип условия (ожидается field / all / any / not_segment / event)")


# ── лист: {field, op, value} ─────────────────────────────────────────────────
def _compile_leaf(item: dict, ctx: _Ctx) -> str:
    key = item.get('field')
    op = item.get('op')
    val = item.get('value')

    fld = FIELDS.get(key)
    if fld is None:
        raise ValueError(f"Неизвестное поле: {key!r}")
    if not fld.available:
        raise ValueError(f"Поле {fld.label!r} пока недоступно ({fld.needs or 'нет данных'})")
    allowed = OPS_BY_TYPE.get(fld.type, frozenset())
    if op not in allowed:
        raise ValueError(f"Оператор {op!r} недопустим для поля {fld.label!r} (тип {fld.type})")

    if fld.join:
        ctx.joins.add(fld.join)
    guard = f"{fld.join}.casino_player_id != 0 AND " if fld.join in ML_JOINS else ''

    body = _dispatch(fld, op, val, ctx)
    return f"({guard}{body})" if guard else f"({body})"


def _dispatch(fld: Field, op: str, val, ctx: _Ctx) -> str:
    if fld.type == 'num':
        return _num(fld, op, val, ctx)
    if fld.type == 'date':
        return _date(fld, op, val, ctx)
    if fld.type == 'enum':
        return _enum(fld, op, val, ctx)
    if fld.type == 'flag':
        return _flag(fld, op, val)
    if fld.type == 'str':
        return _str(fld, op, val, ctx)
    raise ValueError(f"Неизвестный тип поля: {fld.type}")


def _num(fld: Field, op: str, val, ctx: _Ctx) -> str:
    col = fld.sql
    if op == 'between':
        lo, hi = _pair(val)
        return f"{col} BETWEEN {ctx.param(lo, 'Float64')} AND {ctx.param(hi, 'Float64')}"
    if op == 'top_pct':
        pct = _num_val(val)
        if not (0 < pct < 100):
            raise ValueError("top_pct: процент должен быть в диапазоне (0, 100)")
        if not col.startswith('f.'):
            raise ValueError(f"top_pct доступен только для полей витрины player_features (не для {fld.key})")
        raw = col[2:]   # колонка без алиаса f.
        q = ctx.param(1.0 - pct / 100.0, 'Float64')
        return (f"{col} >= (SELECT quantile({q})({raw}) "
                f"FROM player_features WHERE account_type = 'normal')")
    sym = {'eq': '=', 'ne': '!=', 'gt': '>', 'lt': '<'}[op]
    return f"{col} {sym} {ctx.param(_num_val(val), 'Float64')}"


def _date(fld: Field, op: str, val, ctx: _Ctx) -> str:
    col = f"toDate({fld.sql})"
    if op == 'between':
        lo, hi = _pair(val)
        return f"{col} BETWEEN {ctx.param(_date_val(lo), 'Date')} AND {ctx.param(_date_val(hi), 'Date')}"
    if op == 'before':
        return f"{col} < {ctx.param(_date_val(val), 'Date')}"
    if op == 'after':
        return f"{col} > {ctx.param(_date_val(val), 'Date')}"
    if op in ('days_ago_gt', 'days_ago_lt'):
        n = ctx.param(int(_num_val(val)), 'UInt32')
        # «более N дней назад» = дата раньше (today − N); «менее N дней назад» = позже/равно.
        sym = '<' if op == 'days_ago_gt' else '>='
        return f"{col} {sym} today() - {n}"
    raise ValueError(f"Оператор {op} не реализован для дат")


def _enum(fld: Field, op: str, val, ctx: _Ctx) -> str:
    items = _str_list(val)
    p = ctx.param(items, 'Array(String)')
    return f"{fld.sql} {'NOT IN' if op == 'not_in' else 'IN'} {p}"


def _flag(fld: Field, op: str, val) -> str:
    col = fld.sql
    if op == 'is_null':
        if fld.flag_kind == 'bool':
            raise ValueError(f"Оператор is_null неприменим к флагу {fld.label!r}")
        return f"{col} = ''"
    # op == 'is' — значение фиксированный литерал (не пользовательская строка).
    want = _as_bool(val)
    if fld.flag_kind == 'bool':
        return f"({col}) = {1 if want else 0}"
    return f"{col} IN {_TRUTHY}" if want else f"{col} NOT IN {_TRUTHY}"


def _str(fld: Field, op: str, val, ctx: _Ctx) -> str:
    col = fld.sql
    if op in ('in', 'not_in'):
        p = ctx.param(_str_list(val), 'Array(String)')
        return f"{col} {'NOT IN' if op == 'not_in' else 'IN'} {p}"
    if op == 'contains':
        return f"positionCaseInsensitive({col}, {ctx.param(_scalar_str(val), 'String')}) > 0"
    sym = '=' if op == 'eq' else '!='
    return f"{col} {sym} {ctx.param(_scalar_str(val), 'String')}"


# ── not_segment ──────────────────────────────────────────────────────────────
def _compile_not_segment(sys_name, ctx: _Ctx) -> str:
    if not isinstance(sys_name, str) or not _SYS_NAME_RE.match(sys_name):
        raise ValueError(f"not_segment: недопустимое sys_name {sys_name!r}")
    p = ctx.param(sys_name, 'String')
    return ("f.casino_player_id NOT IN (SELECT casino_player_id "
            f"FROM segment_members WHERE sys_name = {p})")


# ── event (§0): «событие X было N раз за период» ──────────────────────────────
def _compile_event(ev, ctx: _Ctx) -> str:
    if not isinstance(ev, dict):
        raise ValueError("event: ожидается объект")
    etype = ev.get('type')
    spec = EVENTS.get(etype)
    if spec is None:
        raise ValueError(f"event: неизвестный тип события {etype!r} "
                         f"(допустимо: {', '.join(sorted(EVENTS))})")
    table, type_filter, ts_col = spec

    within = int(_num_val(ev.get('within_days', 30)))
    if within <= 0:
        raise ValueError("event.within_days должен быть положительным")
    op = ev.get('op', 'gte')
    if op not in EVENT_COUNT_OPS:
        raise ValueError(f"event.op недопустим: {op!r}")
    count = int(_num_val(ev.get('count', 1)))

    conds = [type_filter]
    status = ev.get('status')
    if status:
        conds.append(f"status = {ctx.param(_scalar_str(status), 'String')}")
    # Окно считаем от ДАТЫ ДАННЫХ таблицы (max ts), а не от now(): датасет
    # исторический (cutoff), окно от now() дало бы 0. На живом потоке max≈now.
    win = ctx.param(within, 'UInt32')
    conds.append(f"{ts_col} >= (SELECT max({ts_col}) FROM {table}) - toIntervalDay({win})")
    having = f"count() {EVENT_COUNT_OPS[op]} {ctx.param(count, 'UInt32')}"
    return ("f.casino_player_id IN (SELECT casino_player_id "
            f"FROM {table} WHERE {' AND '.join(conds)} "
            f"GROUP BY casino_player_id HAVING {having})")


# ── валидация значений ───────────────────────────────────────────────────────
def _num_val(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"Ожидается число, получено: {v!r}")
    return v


def _pair(v):
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError("between: ожидается массив из двух значений [от, до]")
    return v[0], v[1]


def _date_val(v):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise ValueError(f"Ожидается дата в формате YYYY-MM-DD, получено: {v!r}")
    return v


def _str_list(v):
    if not isinstance(v, (list, tuple)) or not v:
        raise ValueError("Ожидается непустой список значений")
    return [str(x) for x in v]


def _scalar_str(v):
    if isinstance(v, (list, tuple, dict)):
        raise ValueError("Ожидается одиночное значение")
    return str(v)


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ('1', 'true', 'yes', 'y', 'on', 't')
    raise ValueError(f"Ожидается булево значение для флага, получено: {v!r}")
