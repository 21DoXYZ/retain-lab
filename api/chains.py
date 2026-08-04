"""api/chains.py — домен «Цепочки автоматизации» (Этап 3, фаза 3а — W4-T3).

JSON-эндпоинты SPA для конструктора цепочек: CRUD цепочек, версионирование
definition (ввод в бой = новая версия; активные игроки доходят по старой — ТЗ
§2.5), пауза/архив/клон, шаблоны сообщений, статистика по узлам (из ClickHouse
retention.chain_events — таблицу создаёт runner в W4-T4).

Архитектура (как остальные домены api/*, см. api/__init__.py):
  • модуль-уровневый ``bp`` авто-регистрируется register_api(app);
  • auth/конверт — из api.core (require_auth, api_json); RBAC по ролям;
  • данные — из Postgres (схема automation) через api.chains_store;
  • статистика — из ClickHouse через готовый pb.q (без своих формул).

Роли (как у /bonus в api/marketing.py):
  • читают   — маркетинг/аналитика/руководство (READ_ROLES);
  • пишут    — marketing_manager · head_retention · super_admin (WRITE_ROLES).

Валидатор definition (ДО записи) — единственная «умная» часть модуля: проверяет
триггер/цель/контроль и линейный поток узлов (condition прыгает только вперёд —
никаких циклов). Ошибки — человекочитаемым текстом «путь: причина».
"""
from __future__ import annotations

import logging
import re
import uuid as _uuid

from flask import Blueprint, request

from .core import api_json, current_user_id, require_auth
from . import chains_store as store

import player_board as pb   # готовый pb.q / pb._has_table для статистики (CH)

logger = logging.getLogger('api.chains')

bp = Blueprint('api_chains', __name__, url_prefix='/api/v1')

# ── матрица ролей (зеркалит api.marketing.MARKETING_ROLES; analyst уже включён) ──
READ_ROLES = ['super_admin', 'director', 'head_retention',
              'marketing_manager', 'analyst', 'vip_manager']
WRITE_ROLES = ['marketing_manager', 'head_retention', 'super_admin']

# ── словари допустимых значений definition (whitelist) ───────────────────────
TRIGGER_KINDS = {'segment', 'event', 'schedule'}
EVENT_TYPES = {'deposit', 'deposit_failed', 'bet', 'login',
               'session_start', 'session_end', 'cashier_opened'}
GOAL_EVENTS = {'deposit', 'bet', 'login'}
NODE_KINDS = {'action', 'wait', 'condition'}
ACTION_KINDS = {'bonus_grant', 'send_message', 'desk_task', 'player_tag'}
WAIT_MODES = {'fixed', 'event', 'ml'}
CHANNELS = {'casino_webhook', 'email', 'telegram'}
EXIT_TARGETS = {'exit_converted', 'exit'}
_HHMM = re.compile(r'^([01]?\d|2[0-3]):[0-5]\d$')   # 0:00..23:59


# ════════════════════════════════════════════════════════════════════════════
# Хелперы
# ════════════════════════════════════════════════════════════════════════════
def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _uuid_or_none(v):
    """Автор действия: валидный uuid → как есть, иначе None (в dev API_AUTH_OFF
    sub='dev' — не uuid; created_by FK ON DELETE SET NULL, поэтому None безопасен)."""
    if not v:
        return None
    try:
        return str(_uuid.UUID(str(v)))
    except (ValueError, AttributeError, TypeError):
        return None


def _str_field(node: dict, key: str) -> bool:
    """True, если node[key] — непустая строка."""
    val = node.get(key)
    return isinstance(val, str) and bool(val.strip())


# ════════════════════════════════════════════════════════════════════════════
# Валидатор definition (человекочитаемые ошибки «путь: причина»)
# ════════════════════════════════════════════════════════════════════════════
def _validate_action(node: dict, path: str) -> list[str]:
    action = node.get('action')
    if action not in ACTION_KINDS:
        return [f"{path}.action: ожидается одно из {sorted(ACTION_KINDS)}"]
    errors: list[str] = []
    if action == 'bonus_grant':
        if not _str_field(node, 'bonus'):
            errors.append(f"{path}.bonus: обязателен (код бонуса или 'ml_recommended')")
    elif action == 'send_message':
        if node.get('channel') not in CHANNELS:
            errors.append(f"{path}.channel: ожидается одно из {sorted(CHANNELS)}")
        if not _str_field(node, 'template'):
            errors.append(f"{path}.template: обязателен (id шаблона)")
        if 'params' in node and not isinstance(node.get('params'), dict):
            errors.append(f"{path}.params: ожидается объект {{ключ: значение}}")
    elif action == 'desk_task':
        if not _str_field(node, 'reason'):
            errors.append(f"{path}.reason: обязателен (зачем назначаем игрока на Пульт)")
        # operator_id/assign_to обязан быть UUID — кривое значение раньше зацикливало
        # runner на enrollment (находка ревью W4); ловим на этапе сохранения
        op_ref = node.get('operator_id') or node.get('assign_to')
        if op_ref is not None:
            import uuid as _uuid
            try:
                _uuid.UUID(str(op_ref))
            except (ValueError, AttributeError, TypeError):
                errors.append(f"{path}.operator_id: ожидается UUID оператора")
    elif action == 'player_tag':
        if not _str_field(node, 'tag'):
            errors.append(f"{path}.tag: обязателен (метка игрока)")
    return errors


def _validate_wait(node: dict, path: str) -> list[str]:
    errors: list[str] = []
    if node.get('mode') not in WAIT_MODES:
        errors.append(f"{path}.mode: ожидается одно из {sorted(WAIT_MODES)}")
    fb = node.get('fallback_hours')
    if not (_is_num(fb) and fb > 0):
        errors.append(f"{path}.fallback_hours: число больше 0")
    window = node.get('window')
    if window is not None:
        if not isinstance(window, dict):
            errors.append(f"{path}.window: ожидается объект {{from, to}} в формате HH:MM")
        else:
            for edge in ('from', 'to'):
                val = window.get(edge)
                if val is not None and not (isinstance(val, str) and _HHMM.match(val)):
                    errors.append(f"{path}.window.{edge}: время в формате HH:MM (00:00..23:59)")
    return errors


def _validate_condition(node: dict, path: str, idx: int, pos: dict[str, int]) -> list[str]:
    errors: list[str] = []
    if not isinstance(node.get('if'), dict):
        errors.append(f"{path}.if: обязателен объект-условие {{field, op, value}}")
    for key in ('then', 'else'):
        if key not in node:
            continue
        target = node.get(key)
        if target is None or target in EXIT_TARGETS:
            continue                       # null = следующий по порядку; exit* = терминал
        if not isinstance(target, str):
            errors.append(f"{path}.{key}: ожидается id узла, 'exit_converted', 'exit' или null")
        elif target not in pos:
            errors.append(f"{path}.{key}: ссылка на несуществующий узел '{target}'")
        elif pos[target] <= idx:
            errors.append(f"{path}.{key}: переход только ВПЕРЁД — узел '{target}' "
                          "не позже текущего (циклы запрещены)")
    return errors


def _validate_trigger(defn: dict) -> list[str]:
    trig = defn.get('trigger')
    if not isinstance(trig, dict):
        return ['trigger: обязателен и должен быть объектом']
    kind = trig.get('kind')
    if kind not in TRIGGER_KINDS:
        return [f"trigger.kind: ожидается одно из {sorted(TRIGGER_KINDS)}"]
    errors: list[str] = []
    if kind == 'segment':
        if not (isinstance(trig.get('sys_name'), str) and trig['sys_name'].strip()):
            errors.append('trigger.sys_name: обязателен (строка) для триггера-сегмента')
        rd = trig.get('reentry_days')
        if rd is not None and not (_is_int(rd) and 0 <= rd <= 365):
            errors.append('trigger.reentry_days: целое 0..365')
    elif kind == 'event':
        if trig.get('type') not in EVENT_TYPES:
            errors.append(f"trigger.type: ожидается одно из {sorted(EVENT_TYPES)}")
    elif kind == 'schedule':
        cron = trig.get('cron')
        if not (isinstance(cron, str) and len(cron.split()) == 5):
            errors.append('trigger.cron: cron-строка из 5 полей (мин час день месяц день_недели)')
    return errors


def validate_definition(defn) -> list[str]:
    """JSON-схему цепочки → список человекочитаемых ошибок (пусто = ок).

    Проверяет: (а) триггер; (б) control_pct 0..50; (в) goal + attribution_days;
    (г) узлы (уникальные id, виды, обязательные поля); (д) линейный поток —
    condition прыгает только вперёд (никаких циклов). Существование сегмента НЕ
    проверяем (каталог сегментов — параллельная задача W4-T1).
    """
    if not isinstance(defn, dict):
        return ['definition: ожидается объект (JSON-словарь)']
    errors = _validate_trigger(defn)

    cp = defn.get('control_pct', 16)
    if not (_is_num(cp) and 0 <= cp <= 50):
        errors.append('control_pct: число 0..50 (дефолт 16)')

    goal = defn.get('goal')
    if not isinstance(goal, dict):
        errors.append('goal: обязателен и должен быть объектом')
    else:
        if goal.get('event') not in GOAL_EVENTS:
            errors.append(f"goal.event: ожидается одно из {sorted(GOAL_EVENTS)}")
        ad = goal.get('attribution_days', 14)
        if not (_is_int(ad) and 1 <= ad <= 90):
            errors.append('goal.attribution_days: целое 1..90 (дефолт 14)')

    nodes = defn.get('nodes')
    if not isinstance(nodes, list) or not nodes:
        errors.append('nodes: обязателен непустой массив узлов')
        return errors

    # id: собрать, проверить уникальность, построить карту позиций (для forward-check)
    ids = [n['id'] for n in nodes if isinstance(n, dict) and isinstance(n.get('id'), str)]
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        errors.append(f"nodes.id: идентификаторы не уникальны: {', '.join(dupes)}")
    pos: dict[str, int] = {}
    for i, n in enumerate(nodes):
        if isinstance(n, dict) and isinstance(n.get('id'), str):
            pos.setdefault(n['id'], i)

    for i, node in enumerate(nodes):
        path = f"nodes[{i}]"
        if not isinstance(node, dict):
            errors.append(f"{path}: ожидается объект узла")
            continue
        if not (isinstance(node.get('id'), str) and node['id'].strip()):
            errors.append(f"{path}.id: обязателен (непустая строка)")
        kind = node.get('kind')
        if kind not in NODE_KINDS:
            errors.append(f"{path}.kind: ожидается одно из {sorted(NODE_KINDS)}")
            continue
        if kind == 'action':
            errors += _validate_action(node, path)
        elif kind == 'wait':
            errors += _validate_wait(node, path)
        elif kind == 'condition':
            errors += _validate_condition(node, path, i, pos)
    return errors


# ════════════════════════════════════════════════════════════════════════════
# Цепочки: CRUD + версионирование + статусы
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/chains')
@require_auth(roles=READ_ROLES)
def chains_list():
    return api_json({'chains': store.list_chains()})


@bp.post('/chains')
@require_auth(roles=WRITE_ROLES)
def chains_create():
    body = request.get_json(silent=True) or {}
    name = str(body.get('name') or '').strip()
    if not name:
        return api_json(error='name: обязателен (непустое имя цепочки)', code=422)
    description = str(body.get('description') or '')
    chain_id = store.create_chain(name[:200], description, _uuid_or_none(current_user_id()))
    if chain_id is None:
        return api_json(error=f'Имя «{name}» уже занято', code=409)
    return api_json(store.get_chain(chain_id))


@bp.get('/chains/<uuid:chain_id>')
@require_auth(roles=READ_ROLES)
def chains_get(chain_id):
    chain = store.get_chain(str(chain_id))
    if chain is None:
        return api_json(error='Цепочка не найдена', code=404)
    return api_json(chain)


@bp.put('/chains/<uuid:chain_id>')
@require_auth(roles=WRITE_ROLES)
def chains_update(chain_id):
    body = request.get_json(silent=True) or {}
    name = body.get('name')
    description = body.get('description')
    if name is not None:
        name = str(name).strip()
        if not name:
            return api_json(error='name: непустое имя', code=422)
        name = name[:200]
    if description is not None:
        description = str(description)
    res = store.update_chain(str(chain_id), name, description)
    if res == 'not_found':
        return api_json(error='Цепочка не найдена', code=404)
    if res == 'not_draft':
        return api_json(error='Редактировать имя/описание можно только у черновика', code=409)
    if res == 'name_taken':
        return api_json(error='Имя уже занято', code=409)
    return api_json(store.get_chain(str(chain_id)))


@bp.post('/chains/<uuid:chain_id>/definition')
@require_auth(roles=WRITE_ROLES)
def chains_save_definition(chain_id):
    body = request.get_json(silent=True) or {}
    definition = body.get('definition')
    errors = validate_definition(definition)
    if errors:
        return api_json(error='; '.join(errors), code=422)
    res = store.save_definition(str(chain_id), definition, _uuid_or_none(current_user_id()))
    if res == 'not_found':
        return api_json(error='Цепочка не найдена', code=404)
    if res == 'archived':
        return api_json(error='Цепочка в архиве — редактирование недоступно', code=409)
    return api_json({'chain_id': str(chain_id), **res})


@bp.post('/chains/<uuid:chain_id>/activate')
@require_auth(roles=WRITE_ROLES)
def chains_activate(chain_id):
    res = store.activate(str(chain_id))
    if res == 'not_found':
        return api_json(error='Цепочка не найдена', code=404)
    if res == 'no_draft':
        return api_json(error='Нет черновика для активации — сначала сохраните definition', code=409)
    return api_json({'chain_id': str(chain_id), 'status': 'active', **res})


@bp.post('/chains/<uuid:chain_id>/pause')
@require_auth(roles=WRITE_ROLES)
def chains_pause(chain_id):
    res = store.pause(str(chain_id))
    if res == 'not_found':
        return api_json(error='Цепочка не найдена', code=404)
    if res == 'not_active':
        return api_json(error='Поставить на паузу можно только активную цепочку', code=409)
    return api_json({'chain_id': str(chain_id), 'status': 'paused'})


@bp.post('/chains/<uuid:chain_id>/archive')
@require_auth(roles=WRITE_ROLES)
def chains_archive(chain_id):
    res = store.archive(str(chain_id))
    if res == 'not_found':
        return api_json(error='Цепочка не найдена', code=404)
    if res == 'already':
        return api_json(error='Цепочка уже в архиве', code=409)
    return api_json({'chain_id': str(chain_id), 'status': 'archived'})


@bp.post('/chains/<uuid:chain_id>/clone')
@require_auth(roles=WRITE_ROLES)
def chains_clone(chain_id):
    body = request.get_json(silent=True) or {}
    name = str(body.get('name') or '').strip()
    if not name:
        return api_json(error='name: обязателен (имя новой цепочки)', code=422)
    res = store.clone(str(chain_id), name[:200], _uuid_or_none(current_user_id()))
    if res == 'src_not_found':
        return api_json(error='Исходная цепочка не найдена', code=404)
    if res == 'no_version':
        return api_json(error='У исходной цепочки ещё нет ни одной версии definition', code=409)
    if res == 'name_taken':
        return api_json(error=f'Имя «{name}» уже занято', code=409)
    return api_json(store.get_chain(res))


# ════════════════════════════════════════════════════════════════════════════
# Статистика по узлам (ClickHouse retention.chain_events — создаёт runner W4-T4)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/chains/<uuid:chain_id>/stats')
@require_auth(roles=READ_ROLES)
def chains_stats(chain_id):
    """Вошло/прошло/выпало по узлам + конверсия main vs control.

    Таблицы retention.chain_events ещё нет (её создаёт исполнитель, W4-T4) →
    отдаём {available:false, nodes:[]}; фронт покажет «статистика появится после
    запуска исполнителя».
    """
    chain = store.get_chain(str(chain_id))
    if chain is None:
        return api_json(error='Цепочка не найдена', code=404)
    if not pb._has_table('chain_events'):
        return api_json({'available': False, 'nodes': []})

    cid = str(chain_id)
    try:
        # узлы активной версии (или последней, если ещё ничего не активировали)
        versions = chain.get('versions') or []
        active = [v for v in versions if v.get('activated_at')]
        chosen = (active[-1] if active else (versions[-1] if versions else None))
        node_ids = [n['id'] for n in ((chosen or {}).get('definition') or {}).get('nodes', [])
                    if isinstance(n, dict) and isinstance(n.get('id'), str)]

        counts = {r[0]: r for r in pb.q(
            "SELECT node_id, countIf(event='enter'), countIf(event='pass'), countIf(event='drop') "
            "FROM chain_events WHERE chain_id={cid:String} GROUP BY node_id",
            {'cid': cid})[1]}
        reasons: dict[str, dict] = {}
        for nid, reason, n in pb.q(
                "SELECT node_id, reason, count() FROM chain_events "
                "WHERE chain_id={cid:String} AND event='drop' GROUP BY node_id, reason",
                {'cid': cid})[1]:
            reasons.setdefault(str(nid), {})[str(reason)] = int(n)

        nodes_out = []
        for nid in node_ids or list(counts.keys()):
            _, entered, passed, dropped = counts.get(nid, (nid, 0, 0, 0))
            nodes_out.append({
                'node_id': nid, 'entered': int(entered), 'passed': int(passed),
                'dropped': int(dropped), 'drop_reasons': reasons.get(nid, {})})

        goal = {'main': {'n': 0, 'conv': 0}, 'control': {'n': 0, 'conv': 0}}
        for grp, n, conv in pb.q(
                "SELECT ab_group, uniqExactIf(casino_player_id, event='enter'), "
                "uniqExactIf(casino_player_id, event='goal') FROM chain_events "
                "WHERE chain_id={cid:String} GROUP BY ab_group", {'cid': cid})[1]:
            if str(grp) in goal:
                goal[str(grp)] = {'n': int(n), 'conv': int(conv)}
        return api_json({'available': True, 'nodes': nodes_out, 'goal': goal})
    except Exception as e:                    # таблица есть, но запрос упал — не роняем экран
        logger.warning('chain stats failed (chain=%s): %s', cid, e)
        return api_json({'available': False, 'nodes': []})


# ════════════════════════════════════════════════════════════════════════════
# Шаблоны сообщений (CRUD)
# ════════════════════════════════════════════════════════════════════════════
def _valid_texts(v):
    """texts → dict (языковые версии) или None при ошибке типа."""
    if v is None:
        return {}
    return v if isinstance(v, dict) else None


@bp.get('/chains/templates')
@require_auth(roles=READ_ROLES)
def templates_list():
    return api_json({'templates': store.list_templates()})


@bp.post('/chains/templates')
@require_auth(roles=WRITE_ROLES)
def templates_create():
    body = request.get_json(silent=True) or {}
    name = str(body.get('name') or '').strip()
    if not name:
        return api_json(error='name: обязателен (имя шаблона)', code=422)
    channel_kind = body.get('channel_kind')
    if channel_kind not in CHANNELS:
        return api_json(error=f"channel_kind: ожидается одно из {sorted(CHANNELS)}", code=422)
    texts = _valid_texts(body.get('texts'))
    if texts is None:
        return api_json(error='texts: ожидается объект {ru, en, tr}', code=422)
    tid = store.create_template(name[:200], channel_kind, texts, _uuid_or_none(current_user_id()))
    if tid is None:
        return api_json(error=f'Шаблон «{name}» уже существует', code=409)
    return api_json(store.get_template(tid))


@bp.put('/chains/templates/<uuid:template_id>')
@require_auth(roles=WRITE_ROLES)
def templates_update(template_id):
    body = request.get_json(silent=True) or {}
    name = body.get('name')
    if name is not None:
        name = str(name).strip()
        if not name:
            return api_json(error='name: непустое имя', code=422)
        name = name[:200]
    channel_kind = body.get('channel_kind')
    if channel_kind is not None and channel_kind not in CHANNELS:
        return api_json(error=f"channel_kind: ожидается одно из {sorted(CHANNELS)}", code=422)
    texts = body.get('texts')
    if texts is not None and not isinstance(texts, dict):
        return api_json(error='texts: ожидается объект {ru, en, tr}', code=422)
    res = store.update_template(str(template_id), name, channel_kind, texts)
    if res == 'not_found':
        return api_json(error='Шаблон не найден', code=404)
    if res == 'name_taken':
        return api_json(error='Имя уже занято', code=409)
    return api_json(store.get_template(str(template_id)))


@bp.delete('/chains/templates/<uuid:template_id>')
@require_auth(roles=WRITE_ROLES)
def templates_delete(template_id):
    if not store.delete_template(str(template_id)):
        return api_json(error='Шаблон не найден', code=404)
    return api_json({'template_id': str(template_id), 'deleted': True})
