"""api/segments.py — конструктор сегментов: CRUD + preview + members + каталог.

Домен ⚡ Retention-автоматизации. Определения сегментов живут в Postgres
(automation.segments, 0013), членство игроков — в ClickHouse
(retention.segment_members, наполняет materialize_segments.py). Ручка компилирует
JSON-definition в CH-WHERE через api/segment_compiler и считает live-охват.

Роли (как /bonus): читают маркетинг+аналитики; пишут marketing_manager/
head_retention/super_admin. Регистрируется автоматически (переменная ``bp``).
"""
from __future__ import annotations

import csv
import io
import logging

from flask import Blueprint, request, Response

from .core import require_auth, api_json, current_user_id
from .segment_compiler import compile_definition, base_query
from . import segment_fields as sf
from . import segments_store as store

import player_board as pb

logger = logging.getLogger('api.segments')

bp = Blueprint('api_segments', __name__, url_prefix='/api/v1')

READ_ROLES = ['super_admin', 'director', 'head_retention',
              'marketing_manager', 'analyst', 'vip_manager']
WRITE_ROLES = ['marketing_manager', 'head_retention', 'super_admin']

_PREVIEW_SETTINGS = 'SETTINGS max_execution_time=10'
_BIG = 1_000_000_000_000.0   # верхняя граница для «≥ K» через between (нет gte в num-ops)


# ════════════════════════════════════════════════════════════════════════════
# Сериализация строки сегмента
# ════════════════════════════════════════════════════════════════════════════
def _seg_out(row: dict, counts: dict | None = None) -> dict:
    sys_name = row['sys_name']
    stat = (counts or {}).get(sys_name) if counts else None
    return {
        'segment_id': str(row['segment_id']),
        'name': row['name'],
        'sys_name': sys_name,
        'description': row['description'],
        'definition': row['definition'],
        'is_trigger': bool(row['is_trigger']),
        'schedule_at': str(row['schedule_at'])[:5],
        'created_by': str(row['created_by']) if row['created_by'] else None,
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
        'archived_at': row['archived_at'],
        'member_count': (stat or {}).get('count'),
        'computed_at': (stat or {}).get('computed_at'),
    }


def _member_counts() -> dict:
    """{sys_name: {count, computed_at}} из последней материализации."""
    try:
        if not pb._has_table('segment_members'):
            return {}
        _, rows = pb.q("SELECT sys_name, uniqExact(casino_player_id) AS c, "
                       "max(computed_at) AS at FROM segment_members GROUP BY sys_name")
        return {r[0]: {'count': r[1], 'computed_at': r[2]} for r in rows}
    except Exception as e:                        # CH недоступен — счётчики просто пустые
        logger.warning('segment member counts unavailable: %s', e)
        return {}


def _compile_or_422(definition):
    """Компиляция с человекочитаемой 422 при кривом JSON. → (where, params, joins) | Response."""
    try:
        return compile_definition(definition)
    except ValueError as e:
        return api_json(error=str(e), code=422)


def _validate_meta(name, sys_name):
    if not isinstance(name, str) or not name.strip():
        return 'Укажите название сегмента'
    if not isinstance(sys_name, str) or not sf_compiler_sysname_ok(sys_name):
        return ("Системное имя: латиница/цифры/_, начинается с буквы, 3–64 символа "
                "(например, second_dep_target)")
    return None


def sf_compiler_sysname_ok(s: str) -> bool:
    from .segment_compiler import _SYS_NAME_RE
    return bool(_SYS_NAME_RE.match(s))


# ════════════════════════════════════════════════════════════════════════════
# CRUD
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/segments')
@require_auth(roles=READ_ROLES)
def list_segments():
    include_archived = request.args.get('archived') in ('1', 'true', 'yes')
    try:
        rows = store.list_segments(include_archived=include_archived)
    except store.SegmentStoreError as e:
        return api_json(error=str(e), code=503)
    counts = _member_counts()
    return api_json({'segments': [_seg_out(r, counts) for r in rows]})


@bp.post('/segments')
@require_auth(roles=WRITE_ROLES)
def create_segment():
    body = request.get_json(silent=True) or {}
    name = body.get('name')
    sys_name = body.get('sys_name')
    err = _validate_meta(name, sys_name)
    if err:
        return api_json(error=err, code=422)
    definition = body.get('definition')
    compiled = _compile_or_422(definition)
    if isinstance(compiled, Response):
        return compiled
    try:
        row = store.create_segment(
            name=name.strip(), sys_name=sys_name.strip(),
            description=str(body.get('description') or '')[:2000],
            definition=definition, is_trigger=bool(body.get('is_trigger')),
            schedule_at=str(body.get('schedule_at') or '10:00')[:8],
            created_by=current_user_id())
    except store.SegmentStoreError as e:
        return api_json(error=str(e), code=409)
    return api_json(_seg_out(row))


@bp.put('/segments/<uuid:sid>')
@require_auth(roles=WRITE_ROLES)
def update_segment(sid):
    body = request.get_json(silent=True) or {}
    definition = body.get('definition')
    if definition is not None:
        compiled = _compile_or_422(definition)
        if isinstance(compiled, Response):
            return compiled
    try:
        row = store.update_segment(
            str(sid),
            name=(body.get('name').strip() if body.get('name') else None),
            description=(str(body['description'])[:2000] if 'description' in body else None),
            definition=definition,
            is_trigger=(bool(body['is_trigger']) if 'is_trigger' in body else None),
            schedule_at=(str(body['schedule_at'])[:8] if 'schedule_at' in body else None))
    except store.SegmentStoreError as e:
        return api_json(error=str(e), code=409)
    if row is None:
        return api_json(error='Сегмент не найден', code=404)
    return api_json(_seg_out(row))


@bp.post('/segments/<uuid:sid>/archive')
@require_auth(roles=WRITE_ROLES)
def archive_segment(sid):
    try:
        row = store.archive_segment(str(sid))
    except store.SegmentStoreError as e:
        return api_json(error=str(e), code=503)
    if row is None:
        return api_json(error='Сегмент не найден или уже в архиве', code=404)
    return api_json(_seg_out(row))


@bp.post('/segments/<uuid:sid>/clone')
@require_auth(roles=WRITE_ROLES)
def clone_segment(sid):
    body = request.get_json(silent=True) or {}
    name = body.get('name')
    sys_name = body.get('sys_name')
    err = _validate_meta(name, sys_name)
    if err:
        return api_json(error=err, code=422)
    try:
        row = store.clone_segment(str(sid), name.strip(), sys_name.strip(), current_user_id())
    except store.SegmentStoreError as e:
        return api_json(error=str(e), code=409)
    if row is None:
        return api_json(error='Исходный сегмент не найден', code=404)
    return api_json(_seg_out(row))


# ════════════════════════════════════════════════════════════════════════════
# Live-preview (охват + примеры)
# ════════════════════════════════════════════════════════════════════════════
@bp.post('/segments/preview')
@require_auth(roles=READ_ROLES)
def preview():
    body = request.get_json(silent=True) or {}
    compiled = _compile_or_422(body.get('definition'))
    if isinstance(compiled, Response):
        return compiled
    where, params, joins = compiled
    base = base_query(where, joins)
    try:
        count = pb.q(f"SELECT count() FROM ({base}) {_PREVIEW_SETTINGS}", params)[1][0][0]
        sample = [r[0] for r in pb.q(f"{base} ORDER BY f.casino_player_id LIMIT 10 "
                                     f"{_PREVIEW_SETTINGS}", params)[1]]
    except Exception as e:
        logger.warning('preview query failed: %s', e)
        return api_json(error='Не удалось посчитать охват (проверьте условие)', code=422)
    return api_json({'count': count, 'sample': sample})


# ════════════════════════════════════════════════════════════════════════════
# Участники + экспорт
# ════════════════════════════════════════════════════════════════════════════
_MEMBER_SQL = (
    "SELECT m.casino_player_id, f.lifecycle, f.dep_count, f.dep_sum, f.turnover, "
    "f.net, f.vip_level, f.recency_days "
    "FROM (SELECT casino_player_id FROM segment_members WHERE sys_name={s:String} "
    "GROUP BY casino_player_id ORDER BY casino_player_id LIMIT {lim:UInt32} OFFSET {off:UInt32}) m "
    "LEFT JOIN player_features f ON f.casino_player_id = m.casino_player_id")


@bp.get('/segments/<uuid:sid>/members')
@require_auth(roles=READ_ROLES)
def members(sid):
    seg = store.get_segment(str(sid))
    if seg is None:
        return api_json(error='Сегмент не найден', code=404)
    sys_name = seg['sys_name']
    page = max(0, int(request.args.get('page', '0') or 0))
    try:
        total = pb.q("SELECT uniqExact(casino_player_id) FROM segment_members "
                     "WHERE sys_name={s:String}", {'s': sys_name})[1][0][0]
        cols, rows = pb.q(_MEMBER_SQL, {'s': sys_name, 'lim': 50, 'off': page * 50})
    except Exception as e:
        logger.warning('members query failed: %s', e)
        return api_json(error='Список участников недоступен (нет материализации?)', code=503)
    items = [dict(zip(cols, r)) for r in rows]
    return api_json({'sys_name': sys_name, 'total': total, 'page': page,
                     'per_page': 50, 'members': items})


@bp.get('/segments/<uuid:sid>/export.csv')
@require_auth(roles=READ_ROLES)
def export_csv(sid):
    seg = store.get_segment(str(sid))
    if seg is None:
        return api_json(error='Сегмент не найден', code=404)
    sys_name = seg['sys_name']
    try:
        cols, rows = pb.q(_MEMBER_SQL, {'s': sys_name, 'lim': 200000, 'off': 0})
    except Exception as e:
        logger.warning('export query failed: %s', e)
        return api_json(error='Экспорт недоступен (нет материализации?)', code=503)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    w.writerows(rows)
    fname = f"segment_{sys_name}.csv"
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{fname}"'})


# ════════════════════════════════════════════════════════════════════════════
# Каталог полей для UI
# ════════════════════════════════════════════════════════════════════════════
def _resolve_values(field: sf.Field):
    """enum-значения: ('sql', query) → выполнить в CH; иначе статический список.

    Источник-запрос проверяем ПЕРВЫМ: ('sql', '...') — тоже кортеж строк, и общая
    проверка списка перехватила бы его, вернув сырой ['sql', '<query>'].
    """
    v = field.values
    if v is None:
        return None
    if isinstance(v, tuple) and len(v) == 2 and v[0] == 'sql':
        try:
            return [r[0] for r in pb.q(v[1])[1]]
        except Exception:
            return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return None


@bp.get('/segments/fields')
@require_auth(roles=READ_ROLES)
def fields():
    from .segment_compiler import OPS_BY_TYPE
    out = []
    for key, fld in sf.FIELDS.items():
        out.append({
            'key': key, 'label': fld.label, 'type': fld.type, 'section': fld.section,
            'section_label': sf.SECTIONS.get(fld.section, str(fld.section)),
            'available': fld.available, 'needs': fld.needs,
            'operators': sorted(OPS_BY_TYPE.get(fld.type, [])),
            'values': _resolve_values(fld) if fld.available and fld.type == 'enum' else None,
        })
    events = [{'key': k, 'label': k, 'table': v[0]} for k, v in sf.EVENTS.items()]
    from .i18n_catalog import loc_deep
    from .core import req_locale
    return api_json(loc_deep({'fields': out, 'sections': sf.SECTIONS,
                              'events': events,
                              'event_ops': ['gte', 'gt', 'lte', 'lt', 'eq', 'ne']}, req_locale()))


# ════════════════════════════════════════════════════════════════════════════
# Пресеты-шаблоны (8 кампаний + RFM + архетипы) → готовые definition
# ════════════════════════════════════════════════════════════════════════════
def _ge(field, k):
    return {"field": field, "op": "between", "value": [k, _BIG]}


def _le(field, k):
    return {"field": field, "op": "between", "value": [0, k]}


def _btw(field, a, b):
    return {"field": field, "op": "between", "value": [a, b]}


def _flag(field, val=True):
    return {"field": field, "op": "is", "value": val}


# Кампании pb.SEGMENTS переведены в JSON по каталогу (условия из player_board.py).
_CAMPAIGN_DEFS = {
    's1': {"all": [_flag('is_depositor'), {"field": "dep_count", "op": "eq", "value": 1},
                   _le('recency_days', 30)]},
    's2': {"all": [_flag('is_depositor'), _ge('avg_bet', 200), _btw('recency_days', 14, 60)]},
    's3': {"all": [_flag('is_depositor'), _btw('recency_days', 30, 90)]},
    's4': {"all": [_ge('freespin_ratio', 0.5), _le('recency_days', 14)]},
    's5': {"all": [_ge('avg_bet', 1000), _le('recency_days', 30)]},
    's6': {"all": [_ge('dep_count', 2), _le('recency_days', 14)]},
    's7': {"all": [_flag('is_depositor', False), _flag('ever_played'),
                   _le('recency_days', 14), _ge('active_days', 2)]},
    's8': {"all": [_flag('ever_played'), _btw('recency_days', 7, 21), _ge('active_days', 2)]},
}

# Архетипы (PERSONA_SQL) — прямые правила типажа (multiIf присваивает первым
# сработавшим правилом, здесь правила независимы → note о неточности).
_ARCHETYPE_DEFS = [
    ('🐋 Хайроллер', {"all": [_ge('avg_bet', 1000)]}),
    ('🎁 Бонусник', {"all": [_ge('freespin_ratio', 0.5)]}),
    ('⚙️ Грайндер', {"all": [_ge('bets_per_active_day', 300), _ge('active_days', 4)]}),
    ('🦉 Ночной', {"all": [_ge('night_share', 0.5)]}),
    ('🧭 Исследователь', {"all": [_ge('distinct_games', 10)]}),
    ('📌 Моногам', {"all": [_le('distinct_games', 2), _ge('active_days', 2)]}),
    ('💨 Разовый', {"all": [{"field": "active_days", "op": "eq", "value": 1}]}),
    ('💤 Не играл', {"all": [_flag('ever_played', False)]}),
]

# RFM — приближённо (истинный RFM = ранжирование ntile по всей базе; здесь пороги).
_RFM_NOTE = ('приближённо: истинный RFM считается ранжированием (ntile) по всей базе; '
             'здесь — пороги по recency/частоте/обороту')
_RFM_DEFS = [
    ('Champions', {"all": [_le('recency_days', 7), _ge('active_days', 5),
                           {"field": "turnover", "op": "top_pct", "value": 20}]}),
    ('Loyal', {"all": [_le('recency_days', 21), _ge('active_days', 4)]}),
    ('New', {"all": [_le('recency_days', 14), _le('active_days', 2)]}),
    ('At-Risk', {"all": [_btw('recency_days', 30, 90), _ge('active_days', 4)]}),
    ('Hibernating', {"all": [_ge('recency_days', 60)]}),
]


@bp.get('/segments/presets')
@require_auth(roles=READ_ROLES)
def presets():
    items = []
    for key, ic, name, who, offer, _sql in pb.SEGMENTS:
        items.append({'key': f'campaign_{key}', 'kind': 'campaign', 'icon': ic,
                      'name': name, 'description': who, 'offer': offer,
                      'definition': _CAMPAIGN_DEFS[key], 'note': None})
    for name, defn in _ARCHETYPE_DEFS:
        emoji, _, label = name.partition(' ')
        items.append({'key': f'archetype_{label}', 'kind': 'archetype', 'icon': emoji,
                      'name': label, 'description': pb.PERSONA_DESC.get(name, ''),
                      'offer': None, 'definition': defn,
                      'note': 'приближённо: архетип присваивается первым сработавшим правилом multiIf'})
    for name, defn in _RFM_DEFS:
        items.append({'key': f'rfm_{name.lower()}', 'kind': 'rfm', 'icon': '🎯',
                      'name': name, 'description': 'RFM-сегмент', 'offer': None,
                      'definition': defn, 'note': _RFM_NOTE})
    return api_json({'presets': items})
