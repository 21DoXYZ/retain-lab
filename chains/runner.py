#!/usr/bin/env python3
"""chain-runner — исполнитель цепочек автоматизации (poll-сервис ~5с).

Образец — signals/rt_trigger.py: тот же fail-closed PREDICTIONS_ENABLED, тот же
паттерн watermark/восстановления после рестарта, тот же принцип «сервис не должен
умирать» (try/except на тик). Определения цепочек — Postgres automation.* (0014),
факты исполнения — ClickHouse retention.chain_events / retention.send_log.

Тик:
  1) ВХОД. Для активных цепочек:
       trigger.kind=segment → diff членов segment_members (CH) минус активные/
         недавние enrollments (reentry_days). ab_group считается ВЫРАЖЕНИЕМ в CH
         (cityHash64(player,chain)%100 < control_pct) — контроль ~control_pct%.
       trigger.kind=event   → watermark по live_events (типы, что реально есть).
       trigger.kind=schedule→ пропуск (schedule-триггеры — фаза 3б).
     Новые enrollments — батч-INSERT; каждому chain_events 'enter'.
  2) ПРОДВИЖЕНИЕ. enrollments state='active' и пора будить → исполнить узлы
     definition до ближайшего wait / терминала:
       action     — control НЕ исполняет (pass reason='control'); иначе проверки
                    (checks) → отправка (senders) → send_log + chain_events;
       wait       — fixed +N ч | ml (медиана gap) | event (ждать событие/таймаут);
                    окно 11:00–22:00 по users.timezone (фолбэк Europe/Istanbul);
       condition  — компилятор сегментов точечно (WHERE casino_player_id=X);
       desk_task  — задача менеджеру в crm.player_assignments (Пульт).
     goal — целевое событие за attribution_days от входа → state='converted'.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import time
import types
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from chains import checks as C
from chains import senders as S
from chains.store import Store

# ── конфигурация (env) ────────────────────────────────────────────────────────
CH_HOST = os.environ.get('CH_HOST', 'clickhouse')
CH_PORT = int(os.environ.get('CH_PORT', '8123'))
CH_USER = os.environ.get('CH_USER', 'default')
CH_PASSWORD = os.environ.get('CH_PASSWORD', '')
CH_DB = os.environ.get('CH_DB', 'retention')

POLL_MS = int(os.environ.get('CHAINS_POLL_MS', '5000'))
BATCH = int(os.environ.get('CHAINS_ADVANCE_BATCH', '2000'))
FATIGUE_MAX = int(os.environ.get('FATIGUE_MAX_SENDS', '3'))
FATIGUE_WINDOW_DAYS = int(os.environ.get('FATIGUE_WINDOW_DAYS', '7'))
DEFAULT_CONTROL_PCT = int(os.environ.get('CHAINS_DEFAULT_CONTROL_PCT', '16'))
DEFAULT_TZ = os.environ.get('CHAINS_DEFAULT_TZ', 'Europe/Istanbul')
ML_MIN_COHORT = int(os.environ.get('CHAINS_ML_MIN_COHORT', '20'))
ENV_FILE = os.environ.get('ENV_FILE', '/host/.env')

# события, которые реально существуют в live_events (event-триггеры/wait фильтруем ими)
EVENT_TYPES = {'deposit', 'withdrawal', 'bet', 'win', 'session_start', 'session_end'}

_client = None
_enabled_state = None


# ── fail-closed рубильник (процесс-env для локального прогона, иначе .env горячо) ─
def predictions_enabled() -> bool:
    global _enabled_state
    raw = os.environ.get('PREDICTIONS_ENABLED')
    if raw is not None:
        val = raw.strip().lower() in ('1', 'true', 'yes', 'on')
        reason = f'env PREDICTIONS_ENABLED={raw!r}'
    else:
        val, reason = False, 'строки PREDICTIONS_ENABLED нет в .env'
        try:
            with open(ENV_FILE) as fh:
                for line in fh:
                    if line.startswith('PREDICTIONS_ENABLED='):
                        r = line.strip().split('=', 1)[1].strip().strip('"').strip("'")
                        val = r.lower() in ('1', 'true', 'yes', 'on')
                        reason = f'.env PREDICTIONS_ENABLED={r!r}'
        except Exception as e:                       # noqa: BLE001
            val, reason = False, f'{ENV_FILE} не прочитан ({e})'
    if val != _enabled_state:
        print(f"[chains] исполнение: {'ВКЛ' if val else f'ВЫКЛ — {reason}'}", flush=True)
        _enabled_state = val
    return val


# ── ClickHouse ────────────────────────────────────────────────────────────────
def ch():
    global _client
    if _client is None:
        import clickhouse_connect
        _client = clickhouse_connect.get_client(
            host=CH_HOST, port=CH_PORT, username=CH_USER,
            password=CH_PASSWORD, database=CH_DB)
    return _client


def q(sql: str, params: dict | None = None):
    return ch().query(sql, parameters=params).result_rows


def _now_naive() -> datetime:
    """Наивный UTC для DateTime64-колонок (гочи Asia/Makassar: только UTC-инстант)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── компилятор сегментов (для condition-узлов): грузим ФАЙЛАМИ без пакета api ──
def _load_compiler():
    """api/segment_compiler.py + api/segment_fields.py как синтетический пакет
    (обходим api/__init__.py → не тащим flask в runner/образ)."""
    api_dir = pathlib.Path(__file__).resolve().parent.parent / 'api'
    pkg = types.ModuleType('segcat')
    pkg.__path__ = [str(api_dir)]
    sys.modules['segcat'] = pkg
    for name in ('segment_fields', 'segment_compiler'):
        spec = importlib.util.spec_from_file_location(f'segcat.{name}', str(api_dir / f'{name}.py'))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f'segcat.{name}'] = mod
        spec.loader.exec_module(mod)
    return sys.modules['segcat.segment_compiler']


_COMPILER = None


def compiler():
    global _COMPILER
    if _COMPILER is None:
        _COMPILER = _load_compiler()
    return _COMPILER


# перевод операторов chain-condition (gte/lte) в словарь компилятора сегментов
def _translate_leaf(leaf: dict) -> dict:
    op = leaf.get('op')
    if op == 'gte':
        return {'any': [{**leaf, 'op': 'gt'}, {**leaf, 'op': 'eq'}]}
    if op == 'lte':
        return {'any': [{**leaf, 'op': 'lt'}, {**leaf, 'op': 'eq'}]}
    return leaf


def condition_true(player_id: int, cond: dict) -> bool:
    """Точечная проверка условия для одного игрока через компилятор сегментов."""
    sc = compiler()
    where, params, joins = sc.compile_definition({'all': [_translate_leaf(cond)]})
    base = sc.base_query(where, joins)
    params = {**params, '_pid': int(player_id)}
    sql = f"SELECT count() FROM ({base}) AS t WHERE t.casino_player_id = {{_pid:UInt32}}"
    rows = q(sql, params)
    return bool(rows and int(rows[0][0]) > 0)


# ── CH-журналы ────────────────────────────────────────────────────────────────
_EVENT_COLS = ['ts', 'chain_id', 'version_no', 'node_id', 'casino_player_id',
               'event', 'reason', 'ab_group']
_SEND_COLS = ['ts', 'casino_player_id', 'chain_id', 'node_id', 'channel',
              'template_id', 'status', 'reason']


def flush_events(rows: list[tuple]) -> None:
    if rows:
        ch().insert('chain_events', rows, column_names=_EVENT_COLS)


def flush_sends(rows: list[tuple]) -> None:
    if rows:
        ch().insert('send_log', rows, column_names=_SEND_COLS)


# ── ml-wait: медиана интервала до депозита №(dep_count+1) ─────────────────────
# Источник — money_transactions (deposit_ladder/repeat_deposit_model агрегируют её
# же, но БЕЗ разбивки интервалов по номеру депозита; берём медиану gap напрямую).
_ml_cache: dict[int, float | None] = {}


def ml_gap_hours(dep_count: int, fallback_hours: float) -> float:
    n = int(dep_count)
    if n < 0:
        n = 0
    if n not in _ml_cache:
        rows = q(
            "SELECT median(dateDiff('day', ds[{n:UInt32}], ds[{n:UInt32}+1])) AS med, "
            "       count() AS cohort FROM ("
            "  SELECT arraySort(groupArray(toDate(created_at))) AS ds "
            "  FROM money_transactions "
            "  WHERE type IN ('deposit','manual_deposit') AND status='completed' "
            "    AND casino_player_id IN (SELECT casino_player_id FROM users WHERE account_type='normal') "
            "  GROUP BY casino_player_id HAVING length(ds) > {n:UInt32})",
            {'n': max(n, 1)})
        med, cohort = (rows[0][0], rows[0][1]) if rows else (None, 0)
        _ml_cache[n] = float(med) if (med is not None and int(cohort) >= ML_MIN_COHORT) else None
    med = _ml_cache[n]
    return float(fallback_hours) if med is None else max(med * 24.0, 1.0)


# ── окно отправки 11:00–22:00 по tz игрока ───────────────────────────────────
def _parse_hhmm(s: str, default: dtime) -> dtime:
    try:
        h, m = str(s).split(':')
        return dtime(int(h), int(m))
    except Exception:                                # noqa: BLE001
        return default


def _tz(name: str | None):
    try:
        return ZoneInfo(name) if name else ZoneInfo(DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo(DEFAULT_TZ)


def shift_into_window(base_utc: datetime, window: dict | None, tz_name: str | None) -> datetime:
    """Если base вне окна [from,to] в tz игрока — сдвинуть на ближайшее начало окна."""
    if not window:
        return base_utc
    frm = _parse_hhmm(window.get('from', '11:00'), dtime(11, 0))
    to = _parse_hhmm(window.get('to', '22:00'), dtime(22, 0))
    tz = _tz(tz_name)
    local = base_utc.astimezone(tz)
    t = local.timetz().replace(tzinfo=None)
    if frm <= t <= to:
        return base_utc
    start = local.replace(hour=frm.hour, minute=frm.minute, second=0, microsecond=0)
    if t > to:                                       # уже после окна — начало следующего дня
        start += timedelta(days=1)
    return start.astimezone(timezone.utc)


# ── проверки перед действием ─────────────────────────────────────────────────
def _query_ch(sql: str, params: dict):
    return ch().query(sql, parameters=params).result_rows


def run_send_checks(player: dict, channel: str, template: dict | None) -> tuple[bool, str]:
    """(ok, reason). При ok=True reason может нести ИНФОРМАЦИОННУЮ пометку
    (например 'consent_unknown' в режиме CHAINS_CONSENT_MODE=info) — она
    доезжает до send_log, но отправку не блокирует."""
    pid = int(player['casino_player_id'])
    notes: list[str] = []
    for ok, reason in (
        C.check_consent(player),
        C.check_channel(channel, player),
        (C.check_template_language(template, str(player.get('language') or 'tr'))
         if channel in ('email', 'telegram') else (True, '')),
        C.check_not_in_session(pid, _query_ch),
        C.check_fatigue(pid, _query_ch, FATIGUE_MAX, FATIGUE_WINDOW_DAYS),
        C.check_safety_segment(pid, _query_ch),
    ):
        if not ok:
            return False, reason
        if reason:
            notes.append(reason)
    return True, ';'.join(notes)


def run_grant_checks(player: dict) -> tuple[bool, str]:
    pid = int(player['casino_player_id'])
    for ok, reason in (
        C.check_not_restricted(player),
        C.check_safety_segment(pid, _query_ch),
        C.check_fatigue(pid, _query_ch, FATIGUE_MAX, FATIGUE_WINDOW_DAYS),
        C.check_not_in_session(pid, _query_ch),
    ):
        if not ok:
            return False, reason
    return True, ''


# ── контекст игроков (users + dep_count + язык) для батча продвижения ─────────
def load_players(pids: list[int]) -> dict[int, dict]:
    if not pids:
        return {}
    rows = ch().query(
        "SELECT f.casino_player_id AS casino_player_id, f.dep_count AS dep_count, "
        "       u.marketing_consent AS marketing_consent, u.opt_out AS opt_out, "
        "       u.do_not_contact AS do_not_contact, u.self_excluded AS self_excluded, "
        "       u.email AS email, u.telegram_id AS telegram_id, u.timezone AS timezone, "
        "       gs.language AS language "
        "FROM player_features f "
        "LEFT JOIN users u ON u.casino_player_id = f.casino_player_id "
        "LEFT JOIN (SELECT casino_player_id, argMax(language, started_at) AS language "
        "           FROM game_sessions WHERE casino_player_id IN {ids:Array(UInt32)} "
        "           GROUP BY casino_player_id) gs ON gs.casino_player_id = f.casino_player_id "
        "WHERE f.casino_player_id IN {ids:Array(UInt32)}",
        parameters={'ids': pids})
    cols = [c for c in rows.column_names]
    out = {}
    for r in rows.result_rows:
        d = dict(zip(cols, r))
        d['language'] = d.get('language') or 'tr'
        out[int(d['casino_player_id'])] = d
    return out


# ════════════════════════════════════════════════════════════════════════════
# ФАЗА 1 — вход в цепочки
# ════════════════════════════════════════════════════════════════════════════
def enroll_segment(store: Store, chain: dict, trigger: dict, control_pct: int,
                   events: list) -> int:
    sys_name = trigger.get('sys_name')
    if not sys_name:
        return 0
    reentry = int(trigger.get('reentry_days', 30))
    rows = q(
        "SELECT casino_player_id, "
        "  if(cityHash64(casino_player_id, {chain:String}) % 100 < {pct:UInt32}, 'control', 'main') AS ab "
        "FROM (SELECT DISTINCT casino_player_id FROM segment_members WHERE sys_name = {s:String})",
        {'chain': chain['chain_id'], 'pct': int(control_pct), 's': sys_name})
    if not rows:
        return 0
    recent = store.enrolled_recently(chain['chain_id'], reentry)
    fresh = [(int(pid), ab) for pid, ab in rows if int(pid) not in recent]
    if not fresh:
        return 0
    first_node = chain['definition']['nodes'][0]['id']
    inserted = store.insert_enrollments(chain['chain_id'], chain['version_id'], first_node, fresh)
    ts = _now_naive()
    for pid, ab in inserted:
        events.append((ts, chain['chain_id'], chain['version_no'], first_node, pid, 'enter', '', ab))
    return len(inserted)


def enroll_event(store: Store, chain: dict, trigger: dict, control_pct: int,
                 wm: str, events: list) -> int:
    etype = trigger.get('type')
    if etype not in EVENT_TYPES:
        return 0
    reentry = int(trigger.get('reentry_days', 1))
    rows = q(
        "SELECT DISTINCT casino_player_id, "
        "  if(cityHash64(casino_player_id, {chain:String}) % 100 < {pct:UInt32}, 'control', 'main') AS ab "
        "FROM live_events WHERE event_type = {t:String} AND ingested_at > toDateTime64({wm:String}, 3)",
        {'chain': chain['chain_id'], 'pct': int(control_pct), 't': etype, 'wm': wm})
    if not rows:
        return 0
    recent = store.enrolled_recently(chain['chain_id'], reentry)
    fresh = [(int(pid), ab) for pid, ab in rows if int(pid) not in recent]
    if not fresh:
        return 0
    first_node = chain['definition']['nodes'][0]['id']
    inserted = store.insert_enrollments(chain['chain_id'], chain['version_id'], first_node, fresh)
    ts = _now_naive()
    for pid, ab in inserted:
        events.append((ts, chain['chain_id'], chain['version_no'], first_node, pid, 'enter', '', ab))
    return len(inserted)


def phase_enroll(store: Store, chains: list[dict], event_wm: str, events: list) -> tuple[int, str]:
    total = 0
    new_wm = event_wm
    for chain in chains:
        defn = chain.get('definition') or {}
        nodes = defn.get('nodes') or []
        if not nodes:
            continue
        trigger = defn.get('trigger') or {}
        control_pct = int(defn.get('control_pct', DEFAULT_CONTROL_PCT))
        kind = trigger.get('kind')
        try:
            if kind == 'segment':
                total += enroll_segment(store, chain, trigger, control_pct, events)
            elif kind == 'event':
                total += enroll_event(store, chain, trigger, control_pct, event_wm, events)
            elif kind == 'schedule':
                pass  # schedule-триггеры — фаза 3б (MVP пропускает)
        except Exception as e:                       # noqa: BLE001 — один кривой триггер не рушит тик
            print(f"[chains] enroll «{chain.get('name')}» error: {e}", flush=True)
    # сдвигаем watermark событий вперёд (как rt_trigger)
    try:
        new_wm = q("SELECT toString(greatest(max(ingested_at), now64(3) - INTERVAL 10 SECOND)) "
                   "FROM live_events")[0][0]
    except Exception:                                # noqa: BLE001
        pass
    return total, new_wm


# ════════════════════════════════════════════════════════════════════════════
# ФАЗА 2 — продвижение
# ════════════════════════════════════════════════════════════════════════════
def _node_index(defn: dict) -> tuple[dict, list]:
    nodes = defn.get('nodes') or []
    return {n['id']: n for n in nodes}, nodes


def _next_id(nodes: list, node: dict) -> str | None:
    """Явный next или следующий по порядку. None → конец потока (done)."""
    if node.get('next'):
        return node['next']
    ids = [n['id'] for n in nodes]
    try:
        i = ids.index(node['id'])
        return ids[i + 1] if i + 1 < len(ids) else None
    except ValueError:
        return None


_TERMINALS = {
    'exit': ('exited', 'exit'),
    'exit_exited': ('exited', 'exit'),
    'exit_done': ('done', 'exit'),
    'done': ('done', 'exit'),
    'exit_converted': ('converted', 'goal'),
}


def goal_reached(enr: dict, defn: dict) -> bool:
    goal = defn.get('goal') or {}
    ev = goal.get('event')
    if ev not in EVENT_TYPES:
        return False
    attribution_days = int(goal.get('attribution_days', 14))
    secs = (datetime.now(timezone.utc) - enr['entered_at']).total_seconds()
    if secs > attribution_days * 86400:
        return False
    secs = max(int(secs), 1)
    rows = q("SELECT count() FROM live_events WHERE casino_player_id = {pid:UInt32} "
             "AND event_type = {t:String} AND ts >= now64(3) - INTERVAL {s:UInt32} SECOND",
             {'pid': int(enr['casino_player_id']), 't': ev, 's': secs})
    return bool(rows and int(rows[0][0]) > 0)


def event_seen(player_id: int, node: dict) -> bool:
    etype = node.get('event_type') or node.get('type')
    if etype not in EVENT_TYPES:
        return False
    hours = float(node.get('fallback_hours', 24))
    rows = q("SELECT count() FROM live_events WHERE casino_player_id = {pid:UInt32} "
             "AND event_type = {t:String} AND ts >= now64(3) - INTERVAL {h:UInt32} HOUR",
             {'pid': int(player_id), 't': etype, 'h': int(hours)})
    return bool(rows and int(rows[0][0]) > 0)


def do_action(enr: dict, node: dict, player: dict, templates: dict,
              sctx: S.SenderConfig, events: list, sends: list) -> str:
    """Исполнить action-узел. Возвращает 'continue' (идём к next) или 'exit'
    (проверка не пройдена — выходим). Пишет chain_events + send_log."""
    ts = _now_naive()
    chain_id, vno, ab = enr['chain_id'], enr['version_no'], enr['ab_group']
    pid, nid = int(enr['casino_player_id']), node['id']
    action = node.get('action')

    def ev(kind, reason):
        events.append((ts, chain_id, vno, nid, pid, kind, reason, ab))

    def sl(channel, template_id, status, reason):
        sends.append((ts, pid, chain_id, nid, channel, template_id, status, reason))

    # контрольная группа: действия НЕ исполняем (но конверсию меряем)
    if ab == 'control':
        ev('pass', 'control')
        return 'continue'

    if action == 'desk_task':
        operator_id = node.get('operator_id') or node.get('assign_to')
        if not operator_id:
            ev('drop', 'no_operator')
            return 'exit'
        ok, reason = run_grant_checks(player)          # не задачить самоисключённых/restricted
        if not ok:
            ev('drop', reason)
            return 'exit'
        # add_assignment НЕ должен ронять advance: кривой operator_id (не-UUID и т.п.)
        # иначе оставлял бы enrollment active/next_wake_at=NULL — вечный цикл каждые
        # ~5с (находка ревью W4). Терминируем с причиной вместо зацикливания.
        try:
            created = STORE.add_assignment(pid, str(operator_id))
        except Exception as exc:                        # noqa: BLE001 — причина в журнал
            print(f'[chains] desk_task: не удалось назначить pid={pid} ({exc})', flush=True)
            ev('drop', 'bad_operator')
            return 'exit'
        ev('pass', 'assigned' if created else 'assign_dup')
        return 'continue'

    if action == 'bonus_grant':
        ok, reason = run_grant_checks(player)
        if not ok:
            ev('drop', reason)
            sl('bonus_grant', '', 'skipped', reason)
            return 'exit'
        params = {'bonus': node.get('bonus', 'ml_recommended'), **(node.get('params') or {})}
        sok, sreason = S.send('bonus_grant', player, None, params, sctx)
        sl('bonus_grant', '', 'sent' if sok else 'failed', sreason)
        ev('pass', sreason if sok else f'send_failed:{sreason}')
        return 'continue'

    if action == 'send_message':
        channel = node.get('channel', 'casino_webhook')
        template = templates.get(str(node.get('template') or ''))
        ok, reason = run_send_checks(player, channel, template)
        if not ok:
            ev('drop', reason)
            sl(channel, str(node.get('template') or ''), 'skipped', reason)
            return 'exit'
        sok, sreason = S.send(channel, player, template, node.get('params') or {}, sctx)
        # информационные пометки проверок (consent_unknown и т.п.) — в журнал
        note = ';'.join(x for x in (sreason, reason) if x)
        sl(channel, str(node.get('template') or ''), 'sent' if sok else 'failed', note)
        ev('pass', note if sok else f'send_failed:{sreason}')
        return 'continue'

    ev('drop', f'unknown_action:{action}')
    return 'exit'


def advance(enr: dict, player: dict, templates: dict, sctx: S.SenderConfig,
            events: list, sends: list, fresh_start: bool) -> None:
    """Продвинуть один enrollment до ближайшего wait / терминала. Пишет журналы
    и обновляет состояние enrollment одним финальным update."""
    defn = enr['definition']
    index, nodes = _node_index(defn)
    chain_id, vno, ab = enr['chain_id'], enr['version_no'], enr['ab_group']
    pid = int(enr['casino_player_id'])
    ts = _now_naive()

    # цель: если целевое событие уже произошло — конверсия (приоритет над узлами)
    if goal_reached(enr, defn):
        events.append((ts, chain_id, vno, enr['current_node'], pid, 'goal', '', ab))
        STORE.update_enrollment(enr['enrollment_id'], enr['current_node'], 'converted', None, 'goal')
        return

    node_id = enr['current_node']
    fresh = fresh_start                              # True: только вошли в узел; False: проснулись после wait
    guard = len(nodes) + 3
    while guard > 0:
        guard -= 1
        if node_id in _TERMINALS:
            state, kind = _TERMINALS[node_id]
            events.append((ts, chain_id, vno, node_id, pid, kind, '' if kind == 'goal' else node_id, ab))
            STORE.update_enrollment(enr['enrollment_id'], node_id, state, None, node_id)
            return
        node = index.get(node_id)
        if node is None:                            # конец потока
            events.append((ts, chain_id, vno, str(node_id), pid, 'exit', 'end', ab))
            STORE.update_enrollment(enr['enrollment_id'], str(node_id), 'done', None, 'end')
            return
        kind = node.get('kind')

        if kind == 'wait':
            mode = node.get('mode', 'fixed')
            if fresh:                               # только вошли — планируем пробуждение
                if mode == 'ml':
                    hours = ml_gap_hours(int(player.get('dep_count', 0)),
                                         float(node.get('fallback_hours', 24)))
                elif mode == 'event':
                    hours = float(node.get('fallback_hours', 24))
                else:                               # fixed
                    hours = float(node.get('hours', node.get('fallback_hours', 24)))
                wake = datetime.now(timezone.utc) + timedelta(hours=hours)
                wake = shift_into_window(wake, node.get('window'), player.get('timezone'))
                STORE.update_enrollment(enr['enrollment_id'], node_id, 'active', wake, None)
                return
            # проснулись — wait окончен
            if mode == 'event':
                node_id = (node.get('then') if event_seen(pid, node) else node.get('else')) \
                    or _next_id(nodes, node)
            else:
                node_id = _next_id(nodes, node)
            fresh = True
            continue

        if kind == 'condition':
            cond = node.get('if') or {}
            try:
                hit = condition_true(pid, cond)
            except Exception as e:                  # noqa: BLE001 — кривое условие = else-ветка
                print(f"[chains] condition error pid={pid}: {e}", flush=True)
                hit = False
            node_id = node.get('then') if hit else node.get('else')
            if not node_id:
                node_id = _next_id(nodes, node)
            fresh = True
            continue

        if kind == 'action':
            outcome = do_action(enr, node, player, templates, sctx, events, sends)
            if outcome == 'exit':
                STORE.update_enrollment(enr['enrollment_id'], node_id, 'exited', None,
                                        'check_failed')
                return
            node_id = _next_id(nodes, node)
            fresh = True
            continue

        if kind in ('exit', 'goal', 'terminal'):
            events.append((ts, chain_id, vno, node_id, pid, 'exit', kind, ab))
            STORE.update_enrollment(enr['enrollment_id'], node_id, 'done', None, kind)
            return

        # неизвестный узел — безопасно завершаем
        events.append((ts, chain_id, vno, node_id, pid, 'exit', f'unknown_kind:{kind}', ab))
        STORE.update_enrollment(enr['enrollment_id'], node_id, 'done', None, 'unknown_kind')
        return

    # защита от циклов
    events.append((ts, chain_id, vno, node_id, pid, 'exit', 'loop_guard', ab))
    STORE.update_enrollment(enr['enrollment_id'], node_id, 'done', None, 'loop_guard')


def phase_advance(store: Store, sctx: S.SenderConfig, events: list, sends: list) -> int:
    due = store.due_enrollments(BATCH)
    if not due:
        return 0
    # fresh = enrollment ещё ни разу не «засыпал» на текущем узле (next_wake_at был NULL);
    # due_enrollments отдаёт и NULL, и наступившие — определяем по entered_at? нет: по
    # тому, что due-выборка не различает. Помечаем свежесть отдельным запросом-флагом.
    templates = store.templates()
    players = load_players([int(e['casino_player_id']) for e in due])
    n = 0
    for enr in due:
        pid = int(enr['casino_player_id'])
        player = players.get(pid, {'casino_player_id': pid})
        # свежесть узла: next_wake_at IS NULL ⇒ только вошли (не просыпаемся после wait)
        fresh_start = enr.get('next_wake_at') is None
        try:
            advance(enr, player, templates, sctx, events, sends, fresh_start)
            n += 1
        except Exception as e:                       # noqa: BLE001
            print(f"[chains] advance enr={enr['enrollment_id']} pid={pid} error: {e}", flush=True)
    return n


# ════════════════════════════════════════════════════════════════════════════
STORE: Store = None  # type: ignore[assignment]


def main() -> None:
    global STORE
    print(f"[chains] старт: poll={POLL_MS}ms fatigue={FATIGUE_MAX}/{FATIGUE_WINDOW_DAYS}d "
          f"control_default={DEFAULT_CONTROL_PCT}% dry_run={S.SenderConfig.from_env().dry_run}",
          flush=True)
    STORE = Store()
    try:
        event_wm = q("SELECT toString(greatest(max(ingested_at), now64(3) - INTERVAL 10 SECOND)) "
                     "FROM live_events")[0][0]
    except Exception:                                # noqa: BLE001
        event_wm = '1970-01-01 00:00:00'

    while True:
        t0 = time.monotonic()
        try:
            if not predictions_enabled():
                # рубильник выключен — двигаем watermark, ничего не исполняем
                try:
                    event_wm = q("SELECT toString(greatest(max(ingested_at), now64(3) - "
                                 "INTERVAL 10 SECOND)) FROM live_events")[0][0]
                except Exception:                    # noqa: BLE001
                    pass
                time.sleep(max(0.0, POLL_MS / 1000.0 - (time.monotonic() - t0)))
                continue

            sctx = S.SenderConfig.from_env()
            events: list = []
            sends: list = []

            chains = STORE.active_chains()
            enrolled, event_wm = phase_enroll(STORE, chains, event_wm, events)
            advanced = phase_advance(STORE, sctx, events, sends)

            flush_events(events)
            flush_sends(sends)
            if enrolled or advanced:
                print(f"[chains] тик: +{enrolled} enroll · {advanced} advance · "
                      f"{len(events)} events · {len(sends)} sends", flush=True)
        except Exception as e:                       # noqa: BLE001 — сервис не должен умирать
            global _client
            _client = None
            if STORE is not None:
                STORE.reset()
            print(f"[chains] tick error: {e}", flush=True)
        time.sleep(max(0.0, POLL_MS / 1000.0 - (time.monotonic() - t0)))


if __name__ == '__main__':
    main()
