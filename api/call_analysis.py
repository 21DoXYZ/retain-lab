"""api/call_analysis.py — портальный API модуля «Анализ звонков» (Call Analyzer).

Единственный слой, из которого SPA берёт ВСЕ данные экранов модуля. Спеки:
call_analyzer_interface_spec_FINAL.md (§7 вердикт, §10 экраны, §12 что каждый
экран требует) + call_analyzer_dev_spec.md §4–5.

Архитектура (как у остальных доменов api/*, см. докстринг api/__init__.py):
  • модуль-уровневый ``bp`` авто-регистрируется register_api(app);
  • auth/конверт — из api.core (require_auth, api_json); RBAC по ролям заказчика;
  • данные — из Postgres (схема analyzer + crm) через api.call_analysis_store;
  • подсчёт баллов — ТОЛЬКО call_analyzer.scoring (своей арифметики нет);
  • аудио — стрим через tegsoft get_provider().stream_recording (не в браузер напрямую);
  • перевод — on-demand у пайплайн-сервиса (ANALYZER_URL /internal/translate).

Ключевое правило §7 (условие рендера, энфорсит СЕРВЕР, не фронт): пока
analyzer.settings.verdict_unlocked=false —
  • оператору НЕ отдаём балл/тренд (только карточки с approved_at IS NOT NULL);
  • владельцу НЕ отдаём средний балл (только факты обзвона).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, Response, g, request

from .core import api_json, current_role, require_auth
from .core import current_user_id as _core_current_user_id
from . import call_analysis_store as store

from call_analyzer.scoring import (CRITERIA, overall_score, pass_fail,
                                    recompute_after_override)

logger = logging.getLogger('api.call_analysis')

bp = Blueprint('api_call_analysis', __name__, url_prefix='/api/v1')

# ── Роли (СОГЛАСОВАНО С ЗАКАЗЧИКОМ, см. задание) ─────────────────────────────
OPERATOR_LIKE = {'operator', 'vip_manager'}     # свои звонки/карточки, TR
MANAGE_DEPT = {'head_department'}               # свой отдел + override
MANAGE_ALL = {'head_retention'}                 # всё + override + скрипт
READONLY = {'analyst'}                          # обзор/отчёты, без аудио/правок
OWNER = {'director'}                            # только сводка (§10.12)
ADMIN = {'super_admin'}                         # всё + вердикт/веса/настройки
TRANSLATION = {'translation_reviewer'}          # только проверка перевода (§10.11)
MANAGE = MANAGE_DEPT | MANAGE_ALL

# Наборы ролей на ручку (require_auth принимает список).
R_OVERVIEW = sorted(MANAGE | READONLY | ADMIN)
R_QUEUE = sorted(MANAGE | ADMIN)
R_CARD = sorted(MANAGE | ADMIN | READONLY | OPERATOR_LIKE)
# НЕ analyst, НЕ director (§10.3/§10.4). translation_reviewer ОБЯЗАН слушать:
# его единственная работа — сверить текст с записью (§10.11).
R_AUDIO = sorted(MANAGE | ADMIN | TRANSLATION)
R_REVIEW = sorted(MANAGE | ADMIN)
R_REPORT = sorted(MANAGE | ADMIN | READONLY | OPERATOR_LIKE)
R_MYCARDS = sorted(OPERATOR_LIKE)
R_APPROVE = sorted(MANAGE | ADMIN)
R_COVERAGE = sorted(MANAGE | ADMIN)
R_WHATWORKS = sorted(MANAGE_ALL | ADMIN)
R_SUMMARY = sorted(OWNER | MANAGE_ALL | ADMIN)
R_SCRIPT_GET = sorted(MANAGE_ALL | ADMIN | OPERATOR_LIKE)
R_SCRIPT_WRITE = sorted(MANAGE_ALL | ADMIN)
R_ADMIN = sorted(ADMIN)
R_TRANSLATION = sorted(TRANSLATION | ADMIN)

# Пороги действий (переопределяются analyzer.settings.config; §10.1/§10.7).
GOOD_SCORE_5 = 4.0          # критерий «в норме» (1..5)
WEAK_SPOT_MAX = 3.5         # ниже — показываем как «слабое место»
DEFAULT_DROP = 10           # падение балла нед-к-нед → «требует действия»
DEFAULT_OVERDUE_DAYS = 3    # «срок вышел» для «не набирали» (нет дедлайна в схеме)
DEFAULT_MIN_TALKS = 10      # порог данных для «что работает» (§10.6)
AGREEMENT_HINT = 0.92       # ориентир согласия из чужой практики (§7, не порог)
IMPORTANCE_WEIGHT = {'critical': 3, 'normal': 2, 'minor': 1}


class TranslationUnavailable(RuntimeError):
    """Пайплайн-сервис перевода недоступен (§10.3) → человеческий 503."""


# ════════════════════════════════════════════════════════════════════════════
# Утилиты
# ════════════════════════════════════════════════════════════════════════════
def guarded(fn):
    """Единая обёртка ошибок: БД недоступна → 503, прочее → 500 — но по-человечески,
    без «Internal error» (§11.1: ошибки не мямлят)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except store.AnalyzerStoreError as e:
            logger.error('store error in %s: %s', fn.__name__, e)
            return api_json(error='База анализатора временно недоступна. Повторите позже.',
                            code=503)
        except TranslationUnavailable as e:
            logger.warning('translate unavailable in %s: %s', fn.__name__, e)
            return api_json(error='Сервис перевода сейчас недоступен. '
                                  'Оригинал на турецком доступен, перевод повторите позже.',
                            code=503)
        except Exception as e:                # noqa: BLE001
            logger.exception('unhandled in %s: %s', fn.__name__, e)
            return api_json(error='Не удалось выполнить запрос. Мы уже разбираемся.', code=500)
    return wrapper


def _scrub(o):
    """UUID → str рекурсивно (api_json._clean не знает про UUID). date/Decimal он покроет."""
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_scrub(v) for v in o]
    if isinstance(o, _uuid.UUID):
        return str(o)
    return o


def ok(data=None, code: int = 200):
    return api_json(_scrub(data), code=code)


def _valid_uuid(v):
    """sub → UUID-строка или None. В dev-режиме (API_AUTH_OFF) sub='dev' — не
    UUID; тогда operator_id пишем NULL, чтобы фиксация рекомендации не падала."""
    try:
        return str(_uuid.UUID(str(v))) if v else None
    except (ValueError, TypeError):
        return None


# Нулевой UUID — актор dev-режима: в схеме analyzer поля акторов UUID NOT NULL,
# а API_AUTH_OFF даёт sub='dev'. В проде сюда всегда приходит реальный UUID.
_DEV_ACTOR = '00000000-0000-0000-0000-000000000000'


def current_user_id() -> str:
    """UUID-безопасный актор: реальный sub из JWT, в dev-режиме — нулевой UUID.
    Тень над core.current_user_id — все записи модуля (сверка, аудит доступа,
    апрув карточек) требуют валидный UUID и не должны падать локально."""
    return _valid_uuid(_core_current_user_id()) or _DEV_ACTOR


def _parse_dt(raw: str | None):
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _period():
    """Период отчёта из ?from&to; дефолт — последняя неделя (§10.1)."""
    now = datetime.now(timezone.utc)
    dt_to = _parse_dt(request.args.get('to')) or now
    dt_from = _parse_dt(request.args.get('from')) or (dt_to - timedelta(days=7))
    return dt_from, dt_to


def _prev_period(dt_from: datetime, dt_to: datetime):
    span = dt_to - dt_from
    return dt_from - span, dt_from


def _operator_scope():
    """Область видимости операторов по роли (§4):
      None → все; список UUID → отдел главы; [sub] → свои; [] → никого."""
    role, uid = current_role(), current_user_id()
    if role in MANAGE_ALL or role in ADMIN or role in READONLY or role in OWNER:
        return None
    if role in MANAGE_DEPT:
        return store.dept_operator_ids(uid)
    if role in OPERATOR_LIKE:
        return [uid] if uid else []
    return []


def _call_out_of_scope(call) -> bool:
    """Звонок вне зоны текущей роли? Единый гейт для ПРЯМЫХ ручек по call_id
    (карточка/аудио/confirm/override): списочные ручки скоупятся в SQL, а
    прямые обязаны проверять то же самое — иначе head_department дотягивается
    до чужого отдела перебором id (IDOR через границу отдела)."""
    scope = _operator_scope()
    return scope is not None and str(call.get('operator_id')) not in scope


def _ts_to_sec(ts: str):
    """'mm:ss' | 'hh:mm:ss' → секунды (float). None при мусоре."""
    try:
        parts = [float(p) for p in str(ts).split(':')]
    except ValueError:
        return None
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def _ts_range(evidence_ts: str):
    """'mm:ss-mm:ss' → (lo, hi) секунды."""
    if not evidence_ts or '-' not in str(evidence_ts):
        one = _ts_to_sec(evidence_ts)
        return (one, one) if one is not None else None
    a, _, b = str(evidence_ts).partition('-')
    lo, hi = _ts_to_sec(a), _ts_to_sec(b)
    if lo is None or hi is None:
        return None
    return (lo, hi) if lo <= hi else (hi, lo)


def _quote_from_words(words, evidence_ts: str) -> str:
    """TR-цитата из транскрипта по окну evidence_ts (подсветка = доказательство, §10.3)."""
    rng = _ts_range(evidence_ts)
    if not rng or not isinstance(words, list):
        return ''
    lo, hi = rng
    toks = []
    for w in words:
        if not isinstance(w, dict):
            continue
        st = w.get('start')
        if st is None:
            continue
        try:
            st = float(st)
        except (TypeError, ValueError):
            continue
        if lo <= st <= hi:
            tok = w.get('w')
            if tok:
                toks.append(str(tok))
    return ' '.join(toks)


# ── перевод on-demand у пайплайн-сервиса (§10.3) ─────────────────────────────
def _analyzer_url() -> str:
    return os.environ.get('ANALYZER_URL', 'http://127.0.0.1:8090').rstrip('/')


def _fetch_translation(call_id: str, lang: str) -> str:
    """POST ANALYZER_URL/internal/translate {call_id, lang} → {text}. urllib (без requests)."""
    url = f'{_analyzer_url()}/internal/translate'
    token = os.environ.get('ANALYZER_SERVICE_TOKEN', '')
    body = json.dumps({'call_id': str(call_id), 'lang': lang}).encode('utf-8')
    req = urllib.request.Request(
        url, data=body, method='POST',
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (внутренний хост)
            payload = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        raise TranslationUnavailable(str(e)) from e
    text = payload.get('text')
    if not text:
        raise TranslationUnavailable('пустой ответ перевода')
    return str(text)


def _translation(call_id: str, transcript: dict, lang: str) -> str:
    """Кэш (transcripts.translation_*) → иначе дёрнуть пайплайн и закэшировать."""
    cached = transcript.get('translation_ru' if lang == 'ru' else 'translation_en')
    if cached:
        return cached
    text = _fetch_translation(call_id, lang)
    try:
        store.save_translation(call_id, lang, text)   # страховка, если пайплайн не записал
    except store.AnalyzerStoreError:
        pass
    return text


def _valid_scores(scores) -> tuple[dict[str, int] | None, str | None]:
    """Проверка {criterion: 1..5}: ключ из 9 канонических, значение целое 1..5."""
    if not isinstance(scores, dict) or not scores:
        return None, 'scores: ожидается непустой объект {критерий: 1..5}'
    clean: dict[str, int] = {}
    for k, v in scores.items():
        if k not in CRITERIA:
            return None, f'scores: неизвестный критерий {k!r} (не из 9 канонических)'
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return None, f'scores[{k}]: ожидается целое 1..5'
        if not 1 <= iv <= 5:
            return None, f'scores[{k}]: {iv} вне диапазона 1..5'
        clean[k] = iv
    return clean, None


def _weak_spot(crit_scores: dict[str, list]):
    """Критерий с худшим средним (§10.1). None, если данных нет или всё в норме."""
    worst_name, worst_avg = None, None
    for name, vals in crit_scores.items():
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        if worst_avg is None or avg < worst_avg:
            worst_name, worst_avg = name, avg
    if worst_name is None or worst_avg is None or worst_avg > WEAK_SPOT_MAX:
        return None
    return {'criterion': worst_name, 'avg': round(worst_avg, 2)}


def _aggregate_operators(rows):
    """rows из completed_audits → {op: {avg, n, crit:{criterion:[scores]}}} (§10.1)."""
    per_op: dict[str, dict] = {}
    for r in rows:
        op = str(r['operator_id'])
        agg = per_op.setdefault(op, {'scores': [], 'crit': {}})
        # предпочитаем человеческий балл, если правка была (он и есть «истина» после сверки)
        score = r.get('human_override_score')
        if score is None:
            score = r.get('score')
        if score is not None:
            agg['scores'].append(score)
        for dim in (r.get('dimensions') or []):
            if not isinstance(dim, dict):
                continue
            name, sc = dim.get('name'), dim.get('score')
            if name in CRITERIA and sc is not None and not dim.get('needs_human'):
                agg['crit'].setdefault(name, []).append(sc)
    out = {}
    for op, agg in per_op.items():
        avg = round(sum(agg['scores']) / len(agg['scores'])) if agg['scores'] else None
        out[op] = {'avg': avg, 'n': len(agg['scores']),
                   'weak_spot': _weak_spot(agg['crit']), 'crit': agg['crit']}
    return out


def _verdict_metrics(review_rows, weights):
    """Сверка (§7, §10.13): проверено / случайных / согласие / дельты по критериям.

    Согласие = доля counted-подтверждений + правок, где человеческий итог == модельного.
    Дельта по критерию = средняя |человек − модель| среди counted-правок.
    """
    counted = [r for r in review_rows if r.get('counted')]
    checked = {str(r['call_id']) for r in counted}
    random_calls = {str(r['call_id']) for r in counted if r.get('was_random_sample')}
    agree = 0
    crit_deltas: dict[str, list] = {}
    for r in counted:
        if r['kind'] == 'confirm':
            agree += 1
            continue
        scores = r.get('scores') or {}
        model_dims = r.get('model_dims') or []
        model_score = r.get('model_score')
        human_scores = {k: int(v) for k, v in scores.items()
                        if k in CRITERIA and v is not None}
        human_score = recompute_after_override(model_dims, human_scores, weights)
        if human_score == model_score:
            agree += 1
        model_by = {d.get('name'): d.get('score') for d in model_dims
                    if isinstance(d, dict)}
        for crit, hv in human_scores.items():
            mv = model_by.get(crit)
            if mv is not None:
                crit_deltas.setdefault(crit, []).append(abs(int(hv) - int(mv)))
    total = len(counted)
    per_crit = {c: round(sum(v) / len(v), 3) for c, v in crit_deltas.items() if v}
    all_d = [d for v in crit_deltas.values() for d in v]
    return {
        'checked': len(checked),
        'random': len(random_calls),
        'reviews_counted': total,
        'agreement': round(agree / total, 4) if total else None,
        'avg_delta': round(sum(all_d) / len(all_d), 3) if all_d else None,
        'per_criterion_delta': per_crit,
    }


def _compliance_ok(compliance) -> bool | None:
    """Все обязательные фразы прозвучали? None — если полосы нет (нечего считать)."""
    if not compliance or not isinstance(compliance, list):
        return None
    return all(c.get('present') for c in compliance if isinstance(c, dict))


def _versions(audit: dict) -> dict:
    return {'prompt': audit.get('prompt_version'), 'rubric': audit.get('rubric_version'),
            'script': audit.get('script_version'), 'model': audit.get('model_used')}


# ════════════════════════════════════════════════════════════════════════════
# 1. GET /overview (§10.1, §12)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/overview')
@require_auth(roles=R_OVERVIEW)
@guarded
def overview():
    scope = _operator_scope()
    settings = store.get_settings()
    weights = store.get_weights(settings)
    unlocked = bool(settings['verdict_unlocked'])
    overdue = store.config_int(settings, 'assignment_overdue_days', DEFAULT_OVERDUE_DAYS)
    drop = store.config_int(settings, 'score_drop_threshold', DEFAULT_DROP)
    dt_from, dt_to = _period()
    prev_from, prev_to = _prev_period(dt_from, dt_to)

    cur_agg = _aggregate_operators(store.completed_audits(scope, dt_from, dt_to))
    prev_agg = _aggregate_operators(store.completed_audits(scope, prev_from, prev_to))
    counts = {str(c['operator_id']): c for c in store.call_status_counts(scope, dt_from, dt_to)}
    never = {str(n['operator_id']): int(n['n'])
             for n in store.never_called_counts(scope, overdue)}
    names = store.operator_names(scope)

    op_ids = set(counts) | set(cur_agg) | set(names)
    operators, score_drops = [], []
    tot_calls = tot_analyzed = tot_needs = tot_manual = tot_failed = 0
    for op in op_ids:
        c = counts.get(op, {})
        cur = cur_agg.get(op, {})
        prev = prev_agg.get(op, {})
        avg, prev_avg = cur.get('avg'), prev.get('avg')
        trend = (avg - prev_avg) if (avg is not None and prev_avg is not None) else None
        total = int(c.get('total') or 0)
        analyzed = int(c.get('analyzed') or 0)
        tot_calls += total
        tot_analyzed += analyzed
        tot_needs += int(c.get('needs_review') or 0)
        tot_manual += int(c.get('manual_review') or 0)
        tot_failed += int(c.get('failed') or 0)
        if trend is not None and trend <= -drop:
            score_drops.append({'operator_id': op, 'operator_name': names.get(op),
                                'from': prev_avg, 'to': avg})
        operators.append({
            'operator_id': op, 'operator_name': names.get(op),
            'connected': total, 'analyzed': analyzed,
            'avg_score': avg, 'trend': trend,
            'weak_spot': cur.get('weak_spot'),
            'never_called': never.get(op, 0),
        })
    operators.sort(key=lambda o: (o['avg_score'] is None, o['avg_score'] or 0))

    disputed = store.cards_disputed(scope)
    metrics = _verdict_metrics(store.review_rows(store.CASINO_ID), weights)

    return ok({
        'period': {'from': dt_from, 'to': dt_to},
        'verdict_unlocked': unlocked,
        'reconciliation': {'checked': metrics['checked'], 'agreement': metrics['agreement']},
        'totals': {'connected': tot_calls, 'analyzed': tot_analyzed,
                   'never_called': sum(never.values())},
        'needs_action': {
            'never_called': sum(never.values()),
            'queue_needs_review': tot_needs,
            'cards_pending_approve': store.cards_pending_approve(scope),
            'score_drops': score_drops,
            'disputed_cards': len(disputed),
            'manual_review': tot_manual,
            'failed_records': tot_failed,
        },
        'operators': operators,
    })


# ════════════════════════════════════════════════════════════════════════════
# 2. GET /queue (§10.2)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/queue')
@require_auth(roles=R_QUEUE)
@guarded
def queue():
    scope = _operator_scope()
    rows = store.queue_calls(scope)
    # Серии repeated_pattern схлопываем в одну строку с вложенным списком (§10.2/§11.4).
    series: dict[str, dict] = {}
    items = []
    for r in rows:
        flags = r.get('flags') or []
        member = {'call_id': str(r['call_id']), 'duration_s': r.get('duration_s'),
                  'at': r.get('at')}
        if 'repeated_pattern' in flags:
            key = str(r['operator_id'])
            grp = series.setdefault(key, {
                'kind': 'repeated_pattern', 'operator_id': key,
                'operator_name': r.get('operator_name'), 'members': []})
            grp['members'].append(member)
            continue
        items.append({
            'call_id': str(r['call_id']),
            'operator_id': str(r['operator_id']) if r.get('operator_id') else None,
            'operator_name': r.get('operator_name'),
            'player_id': r.get('casino_player_id'),
            'status': r.get('status'), 'flags': flags,
            'duration_s': r.get('duration_s'), 'at': r.get('at'),
            'score': r.get('score'), 'pass_fail': r.get('pass_fail'),
            'needs_human': r.get('needs_human'),
        })
    # Оспоренные карточки — тоже отдельный тип работы в очереди (§10.2).
    disputed = [{
        'card_id': str(d['card_id']), 'call_id': str(d['call_id']),
        'operator_id': str(d['operator_id']) if d.get('operator_id') else None,
        'operator_name': d.get('operator_name'),
        'reason': d.get('op_dispute_reason'), 'responded_at': d.get('responded_at'),
    } for d in store.cards_disputed(scope)]

    return ok({'items': items, 'series': list(series.values()), 'disputed_cards': disputed})


# ════════════════════════════════════════════════════════════════════════════
# 3. GET /calls/<uuid:call_id> — карточка звонка (§10.3)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/calls/<uuid:call_id>')
@require_auth(roles=R_CARD)
@guarded
def call_card(call_id):
    cid = str(call_id)
    role, uid = current_role(), current_user_id()
    call = store.get_call(cid)
    if call is None:
        return api_json(error='Звонок не найден', code=404)

    is_operator = role in OPERATOR_LIKE
    if _call_out_of_scope(call):
        # оператор — только свои; head_department — только свой отдел
        return api_json(error='Это не ваш звонок', code=403)

    settings = store.get_settings()
    unlocked = bool(settings['verdict_unlocked'])
    audit = store.latest_audit(cid)
    transcript = store.get_transcript(cid)

    store.log_access(uid, cid, 'view_transcript')

    # балл: оператор при заблокированном вердикте его не видит (§7)
    score_visible = unlocked or not is_operator

    audit_out = None
    if audit is not None:
        # §7: пока вердикт заблокирован, оператор не видит ЧИСЕЛ, которыми его
        # судят, — включая поштучные 1..5 (иначе общий балл реконструируется).
        # Конкретика (justification/evidence_ts) остаётся — по ней он учится.
        dims = audit['dimensions']
        if not score_visible:
            dims = [{k: v for k, v in d.items() if k not in ('score', 'needs_human')}
                    for d in dims]
        audit_out = {
            'score': audit['overall_score_100'] if score_visible else None,
            'pass_fail': audit['pass_fail'] if score_visible else None,
            'needs_human': audit['needs_human'] if score_visible else None,
            'dimensions': dims,
            'objections': audit['objections'],
            'compliance': audit['compliance'],
            'offer_outcome': audit['offer_outcome'],
            'versions': _versions(audit),
        }
        if not is_operator:
            audit_out['coaching_narrative'] = audit.get('coaching_narrative')
            audit_out['highlights'] = audit.get('highlights')
            audit_out['improvement_areas'] = audit.get('improvement_areas')
            audit_out['human'] = {
                'reviewed': audit.get('human_reviewed'),
                'override_score': audit.get('human_override_score'),
                'reviewer_id': audit.get('human_reviewer_id'),
                'notes': audit.get('human_notes'),
            }

    tr_out = None
    if transcript is not None:
        tr_out = {'language': transcript.get('language'),
                  'text': transcript.get('text_redacted'),
                  'words': transcript.get('words'),
                  'translation_verified': transcript.get('translation_verified')}
        # Перевод (§10.3): оператору — только TR-оригинал; остальным — по ?lang=ru|en.
        # Спека §5: «оригинал доступен мгновенно, перевод по требованию» — поэтому
        # недоступный сервис перевода НЕ рушит карточку (был 503 на весь ответ):
        # отдаём оригинал TR + флаг translation_unavailable, фронт покажет TR.
        lang = (request.args.get('lang') or '').strip().lower()
        if lang in ('ru', 'en') and not is_operator:
            try:
                tr_out['translation'] = {'lang': lang,
                                         'text': _translation(cid, transcript, lang)}
            except TranslationUnavailable:
                tr_out['translation_unavailable'] = True

    payload = {
        'call': {
            'call_id': cid,
            'operator_id': str(call['operator_id']) if call.get('operator_id') else None,
            'player_id': call.get('casino_player_id'),
            'status': call.get('status'),
            'duration_s': call.get('duration_s'),
            'started_at': call.get('started_at'),
            'flags': call.get('flags') or [],
            'recommended_offer_id': call.get('recommended_offer_id'),
        },
        'audit': audit_out,
        'transcript': tr_out,
        'verdict_unlocked': unlocked,
        # аудио доступно только ролям R_AUDIO (не analyst/оператор) — ссылка-подсказка
        'can_play_audio': role in set(R_AUDIO),
    }
    if not is_operator:
        payload['offer_signal'] = store.offer_signal(cid)
        payload['reviews'] = store.call_reviews(cid)
        # реакция после звонка: через сколько минут деп / вернулся в игру (≤7д)
        if call.get('casino_player_id') and call.get('started_at'):
            payload['reaction'] = reaction_after_call(call['casino_player_id'], call['started_at'])
    return ok(payload)


# ════════════════════════════════════════════════════════════════════════════
# 4. GET /calls/<id>/audio — стрим записи (§10.3). Роли: MANAGE_*, ADMIN.
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/calls/<uuid:call_id>/audio')
@require_auth(roles=R_AUDIO)
@guarded
def call_audio(call_id):
    cid = str(call_id)
    call = store.get_call(cid)
    if call is None:
        return api_json(error='Звонок не найден', code=404)
    if _call_out_of_scope(call):
        return api_json(error='Звонок вне вашей зоны', code=403)
    ref = call.get('audio_ref')
    if not ref:
        return api_json(error='У звонка нет записи', code=404)

    from tegsoft import get_provider           # ленивый импорт (как api/calls.py)
    from tegsoft.adapter import CallProviderError
    provider = get_provider()
    try:
        stream = provider.stream_recording(ref)
        first = next(stream, b'')
    except CallProviderError as e:
        return api_json(error=f'Запись недоступна: {e}', code=502)

    store.log_access(current_user_id(), cid, 'view_audio')

    def _body():
        if first:
            yield first
        yield from stream

    return Response(_body(), mimetype='audio/wav')


# ════════════════════════════════════════════════════════════════════════════
# 5. POST /calls/<id>/confirm — подтверждение оценки (§7). Идемпотентно.
# ════════════════════════════════════════════════════════════════════════════
@bp.post('/call-analysis/calls/<uuid:call_id>/confirm')
@require_auth(roles=R_REVIEW)
@guarded
def confirm_call(call_id):
    cid = str(call_id)
    body = request.get_json(silent=True) or {}
    try:
        review_time_s = int(body.get('review_time_s'))
    except (TypeError, ValueError):
        return api_json(error='review_time_s: ожидается целое число секунд', code=422)
    if review_time_s < 0:
        return api_json(error='review_time_s: не может быть отрицательным', code=422)

    call = store.get_call(cid)
    if call is None:
        return api_json(error='Звонок не найден', code=404)
    if _call_out_of_scope(call):
        return api_json(error='Звонок вне вашей зоны', code=403)
    audit = store.latest_audit(cid)
    if audit is None:
        return api_json(error='У звонка ещё нет оценки — подтверждать нечего', code=409)

    settings = store.get_settings()
    counted = review_time_s >= int(settings['min_review_time_s'])
    was_random = 'random_review' in (call.get('flags') or [])
    reviewer = current_user_id()

    # Идемпотентность: повторное подтверждение того же ревьюера не падает и не дублирует.
    existing = store.find_review(str(audit['audit_id']), reviewer, 'confirm')
    if existing is not None:
        return ok({'call_id': cid, 'review_id': str(existing['review_id']),
                   'counted': counted, 'idempotent': True})

    review_id = store.insert_review(str(audit['audit_id']), reviewer, 'confirm',
                                    None, None, review_time_s, counted, was_random)
    store.log_access(reviewer, cid, 'confirm')
    return ok({'call_id': cid, 'review_id': review_id, 'counted': counted,
               'min_review_time_s': int(settings['min_review_time_s'])})


# ════════════════════════════════════════════════════════════════════════════
# 6. POST /calls/<id>/override — правка оценки по критериям (§10.4).
# ════════════════════════════════════════════════════════════════════════════
@bp.post('/call-analysis/calls/<uuid:call_id>/override')
@require_auth(roles=R_REVIEW)
@guarded
def override_call(call_id):
    cid = str(call_id)
    body = request.get_json(silent=True) or {}
    reason = (body.get('reason') or '').strip()
    if not reason:
        return api_json(error='Причина обязательна — она уходит в сверку (§10.4)', code=422)
    scores, err = _valid_scores(body.get('scores'))
    if err:
        return api_json(error=err, code=422)
    try:
        review_time_s = int(body.get('review_time_s'))
    except (TypeError, ValueError):
        return api_json(error='review_time_s: ожидается целое число секунд', code=422)

    call = store.get_call(cid)
    if call is None:
        return api_json(error='Звонок не найден', code=404)
    if _call_out_of_scope(call):
        return api_json(error='Звонок вне вашей зоны', code=403)
    audit = store.latest_audit(cid)
    if audit is None:
        return api_json(error='У звонка ещё нет оценки — править нечего', code=409)

    settings = store.get_settings()
    weights = store.get_weights(settings)
    model_dims = audit['dimensions'] or []
    human_score = recompute_after_override(model_dims, scores, weights)   # ТОЛЬКО scoring

    counted = review_time_s >= int(settings['min_review_time_s'])
    was_random = 'random_review' in (call.get('flags') or [])
    reviewer = current_user_id()

    store.insert_review(str(audit['audit_id']), reviewer, 'override',
                        scores, reason, review_time_s, counted, was_random)
    store.apply_override(str(audit['audit_id']), cid, human_score, reviewer, reason)
    store.log_access(reviewer, cid, 'override')
    return ok({'call_id': cid, 'model_score': audit['overall_score_100'],
               'human_score': human_score, 'counted': counted})


# ════════════════════════════════════════════════════════════════════════════
# 7. GET /operators/<uuid:op>/report (§10.5)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/operators/<uuid:op>/report')
@require_auth(roles=R_REPORT)
@guarded
def operator_report(op):
    op_id = str(op)
    role, uid = current_role(), current_user_id()
    settings = store.get_settings()
    unlocked = bool(settings['verdict_unlocked'])

    # Гейт видимости (§10.5): оператор — только свой отчёт И только при разблок. вердикте.
    if role in OPERATOR_LIKE:
        if str(uid) != op_id:
            return api_json(error='Доступен только ваш отчёт', code=403)
        if not unlocked:
            return api_json(error='Отчёт станет доступен, когда вердикт разблокирован', code=403)
    elif role in MANAGE_DEPT:
        if op_id not in set(store.dept_operator_ids(uid)):
            return api_json(error='Оператор не из вашего отдела', code=403)

    dt_from, dt_to = _period()
    prev_from, prev_to = _prev_period(dt_from, dt_to)
    weekly = store.operator_weekly_scores(op_id, dt_from, dt_to)

    cur = _aggregate_operators(store.completed_audits([op_id], dt_from, dt_to)).get(op_id, {})
    prev = _aggregate_operators(store.completed_audits([op_id], prev_from, prev_to)).get(op_id, {})
    cur_crit, prev_crit = cur.get('crit', {}), prev.get('crit', {})
    criteria = []
    for name in CRITERIA:
        cvals = cur_crit.get(name) or []
        if not cvals:
            continue
        cavg = sum(cvals) / len(cvals)
        pvals = prev_crit.get(name) or []
        pavg = (sum(pvals) / len(pvals)) if pvals else None
        criteria.append({'criterion': name, 'avg': round(cavg, 2),
                         'delta': round(cavg - pavg, 2) if pavg is not None else None})
    criteria.sort(key=lambda c: c['avg'])

    return ok({
        'operator_id': op_id,
        'operator_name': store.operator_names([op_id]).get(op_id),
        'period': {'from': dt_from, 'to': dt_to},
        'weekly': [{'week': w['week'], 'avg_score': w['avg_score'], 'n': w['n']}
                   for w in weekly],
        'criteria': criteria,
        'worst_calls': [{'call_id': str(r['call_id']), 'score': r['score'],
                         'offer_outcome': r['offer_outcome'], 'duration_s': r['duration_s'],
                         'at': r['at']} for r in store.operator_worst_calls(op_id, dt_from, dt_to)],
        # обязательная отметка смены версии скрипта (§10.5): без неё падение балла врёт
        'script_changes': [{'version': s['version'], 'activated_at': s['activated_at']}
                           for s in store.script_activations(store.CASINO_ID, dt_from, dt_to)],
    })


# ════════════════════════════════════════════════════════════════════════════
# 8. GET /my/cards + POST /cards/<id>/respond + POST /cards/<id>/approve (§10.10)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/my/cards')
@require_auth(roles=R_MYCARDS)
@guarded
def my_cards():
    uid = current_user_id()
    settings = store.get_settings()
    unlocked = bool(settings['verdict_unlocked'])
    cards = store.operator_cards(uid, only_approved=not unlocked)

    # Пометить доставку при первом чтении (§10.10 — замыкает фидбек-луп).
    for c in cards:
        if c.get('delivered_at') is None:
            store.mark_card_delivered(str(c['card_id']))

    out = {'verdict_unlocked': unlocked,
           'cards': [{'card_id': str(c['card_id']), 'call_id': str(c['call_id']),
                      'tips': c['tips'], 'approved_at': c['approved_at'],
                      'op_response': c['op_response'], 'responded_at': c['responded_at'],
                      'player_id': c['casino_player_id'], 'created_at': c['created_at']}
                     for c in cards]}
    # Средний балл/тренд + баллы в списке звонков — только при разблок. вердикте (§7).
    recent = store.operator_recent_calls(uid, include_scores=unlocked)
    out['recent_calls'] = [{'call_id': str(r['call_id']), 'player_id': r['casino_player_id'],
                            'duration_s': r['duration_s'], 'at': r['at'],
                            'score': r['score']} for r in recent]
    if unlocked:
        dt_from, dt_to = _period()
        prev_from, prev_to = _prev_period(dt_from, dt_to)
        cur = _aggregate_operators(store.completed_audits([uid], dt_from, dt_to)).get(uid, {})
        prev = _aggregate_operators(store.completed_audits([uid], prev_from, prev_to)).get(uid, {})
        avg, pavg = cur.get('avg'), prev.get('avg')
        out['score'] = {'avg': avg,
                        'trend': (avg - pavg) if (avg is not None and pavg is not None) else None,
                        'weak_spot': cur.get('weak_spot')}
    return ok(out)


@bp.post('/call-analysis/cards/<uuid:card_id>/respond')
@require_auth(roles=R_MYCARDS)
@guarded
def respond_card(card_id):
    cid = str(card_id)
    uid = current_user_id()
    body = request.get_json(silent=True) or {}
    response = (body.get('response') or '').strip()
    if response not in ('acknowledged', 'disputed'):
        return api_json(error="response: ожидается 'acknowledged' или 'disputed'", code=422)
    reason = (body.get('reason') or '').strip() or None
    if response == 'disputed' and not reason:
        return api_json(error='При несогласии причина обязательна (§10.10)', code=422)

    card = store.get_card_for_operator(cid, uid)
    if card is None:
        return api_json(error='Карточка не найдена', code=404)
    store.respond_card(cid, uid, response, reason)
    return ok({'card_id': cid, 'response': response})


@bp.post('/call-analysis/cards/<uuid:card_id>/approve')
@require_auth(roles=R_APPROVE)
@guarded
def approve_card(card_id):
    cid = str(card_id)
    role, uid = current_role(), current_user_id()
    card = store.get_card(cid)
    if card is None:
        return api_json(error='Карточка не найдена', code=404)
    # head_department апрувит только карточки операторов своего отдела (§4).
    if role in MANAGE_DEPT:
        if str(card['operator_id']) not in set(store.dept_operator_ids(uid)):
            return api_json(error='Оператор не из вашего отдела', code=403)
    if card.get('approved_at') is not None:
        return ok({'card_id': cid, 'already_approved': True})
    store.approve_card(cid, uid)
    return ok({'card_id': cid, 'approved': True})


# ════════════════════════════════════════════════════════════════════════════
# 9. GET /coverage (§10.7)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/coverage')
@require_auth(roles=R_COVERAGE)
@guarded
def coverage():
    scope = _operator_scope()
    settings = store.get_settings()
    overdue = store.config_int(settings, 'assignment_overdue_days', DEFAULT_OVERDUE_DAYS)
    dt_from, dt_to = _period()
    rows = store.coverage(scope, dt_from, dt_to, overdue)
    names = store.operator_names(scope)

    scheduled = store.coverage_scheduled_counts()   # назначено перезвонов на будущее
    per_op, totals = [], {'assigned': 0, 'attempts': 0, 'connected': 0,
                          'talks': 0, 'never_called': 0, 'in_review': 0, 'scheduled': 0}
    for r in rows:
        r = dict(r)
        r['operator_name'] = names.get(r['operator_id'])
        r['scheduled'] = scheduled.get(str(r['operator_id']), 0)
        per_op.append(r)
        for k in totals:
            totals[k] += int(r.get(k) or 0)
    per_op.sort(key=lambda o: o['never_called'], reverse=True)
    return ok({'period': {'from': dt_from, 'to': dt_to},
               'totals': totals, 'operators': per_op})


@bp.get('/call-analysis/coverage/operator/<uuid:op_id>')
@require_auth(roles=R_COVERAGE)
@guarded
def coverage_operator(op_id):
    """Дриллдаун: по каждому игроку оператора — попытки, дозвонился ли,
    последний исход, когда назначен следующий звонок (§10.7, вопрос заказчика:
    «кому дозвонился, кому нет, кому назначил перезвон»)."""
    op = str(op_id)
    # dept-scope: head_department видит только свой отдел
    scope = _operator_scope()
    if scope is not None and op not in scope:
        return api_json(error='Оператор вне вашей зоны', code=403)
    rows = store.coverage_operator_detail(op)
    name = store.operator_names([op]).get(op)
    for r in rows:
        r['last_at'] = r['last_at'].isoformat() if r.get('last_at') else None
        r['next_at'] = r['next_at'].isoformat() if r.get('next_at') else None
    return ok({'operator_id': op, 'operator_name': name, 'players': rows})


# ── «когда звонить»: рекомендация + фиксация принятия ─────────────────────────
def _best_time_slot(peak_hour, base_day):
    """Ближайший момент на пиковый час игрока. peak_hour — СТАМБУЛЬСКИЙ час
    (heatmap считается в Europe/Istanbul), поэтому строим слот в этой зоне и
    возвращаем aware — иначе «пик 20:00» превращался в 23:00 по Стамбулу."""
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    ist = ZoneInfo('Europe/Istanbul')
    hour = int(peak_hour) if peak_hour is not None else 12
    base_ist = base_day.astimezone(ist)
    slot = base_ist.replace(hour=hour, minute=0, second=0, microsecond=0)
    if slot <= base_ist:
        slot = slot + timedelta(days=1)
    return slot


@bp.get('/call-analysis/players/<int:pid>/when-to-call')
@require_auth(roles=sorted(OPERATOR_LIKE | MANAGE | ADMIN))
@guarded
def when_to_call(pid: int):
    """Рекомендация времени звонка + ФИКСАЦИЯ её (обучающие данные).

    v1 — правила на наших данных:
      • не дозвонились → перезвонить через N часов, но в час с высоким дозвоном;
      • иначе → на пик активности игрока (heatmap peak_hour/peak_day).
    Каждая выдача пишется в analyzer.call_recommendations; принятие отметит
    оператор, запланировав звонок. Модель тайминга придёт на этих данных.
    """
    from api.core import ensure_player_access  # noqa: PLC0415 — anti-IDOR как в core
    import player_board as pb  # noqa: PLC0415
    denied = ensure_player_access(pid)
    if denied:
        return denied
    uid = _valid_uuid(g.api_user.get('sub') if hasattr(g, 'api_user') else None)
    now = datetime.now(timezone.utc)
    hist = store.last_call_and_attempts(pid)
    settings = store.get_settings()
    retry_hours = store.config_int(settings, 'retry_after_hours', 4)

    # пик активности игрока — из heatmap-статистики борда (тот же расчёт, что подсказка)
    try:
        _rd, rst = pb._rhythm("casino_player_id={pid:UInt32} AND "
                              "transaction_type IN ('bet','freespins_bet')", {'pid': pid})
        peak_hour, peak_day = rst.get('peak_hour'), rst.get('peak_day')
    except Exception:  # noqa: BLE001 — нет истории игры → дефолт
        peak_hour, peak_day = None, None

    if hist['last_outcome'] in ('no_answer', 'busy'):
        kind, basis = 'retry', 'retry_rule'
        slot = now + timedelta(hours=retry_hours)
        ctx = {'attempt': hist['attempts_today'] + 1, 'prev_outcome': hist['last_outcome'],
               'retry_hours': retry_hours, 'peak_hour': peak_hour}
    else:
        kind, basis = 'best_time', 'peak_hour'
        slot = _best_time_slot(peak_hour, now)
        ctx = {'peak_hour': peak_hour, 'peak_day': peak_day}

    rec_id = store.log_recommendation(pid, uid, kind, slot, basis, ctx)
    return ok({'rec_id': rec_id, 'kind': kind, 'slot': slot.isoformat(),
               'basis': basis, 'context': ctx,
               'answer_by_hour': store.answer_rate_by_hour()})


@bp.post('/call-analysis/recommendations/<uuid:rec_id>/accept')
@require_auth(roles=sorted(OPERATOR_LIKE | MANAGE | ADMIN))
@guarded
def accept_recommendation(rec_id):
    """Оператор запланировал звонок по рекомендации → фиксируем принятие."""
    body = request.get_json(silent=True) or {}
    # оператор принимает только СВОИ рекомендации (руководителю/админу — любые)
    restrict = current_user_id() if current_role() in OPERATOR_LIKE else None
    ok_ = store.accept_recommendation(str(rec_id), body.get('schedule_id'),
                                      restrict_operator=restrict)
    if not ok_:
        return api_json(error='Рекомендация не найдена', code=404)
    return ok({'rec_id': str(rec_id), 'accepted': True})


# ════════════════════════════════════════════════════════════════════════════
# 10. GET /what-works (§10.6) — ранжирование по принятым офферам, приёмы по шагам
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/what-works')
@require_auth(roles=R_WHATWORKS)
@guarded
def what_works():
    settings = store.get_settings()
    min_talks = store.config_int(settings, 'what_works_min_talks', DEFAULT_MIN_TALKS)
    dt_from, dt_to = _period()

    # Ранжирование ПО РЕЗУЛЬТАТУ (accepted), НЕ по баллу (§10.6).
    accept = store.offer_acceptance(dt_from, dt_to)
    names = store.operator_names(None)
    ranking = []
    for a in accept:
        presented = int(a['presented'] or 0)
        accepted = int(a['accepted'] or 0)
        ranking.append({'operator_id': str(a['operator_id']),
                        'operator_name': names.get(str(a['operator_id'])),
                        'presented': presented, 'accepted': accepted,
                        'accept_rate': round(accepted / presented, 3) if presented else None})
    ranking.sort(key=lambda r: (r['accept_rate'] is None, -(r['accept_rate'] or 0)))

    # Активные шаги = критерии активного скрипта (check_level='meaning'); нет скрипта → все 9.
    active = store.active_script(store.CASINO_ID)
    if active and active.get('blocks'):
        active_crit = [b['criterion'] for b in active['blocks']
                       if isinstance(b, dict) and b.get('criterion') in CRITERIA
                       and b.get('check_level') == 'meaning']
        active_crit = list(dict.fromkeys(active_crit)) or list(CRITERIA)
    else:
        active_crit = list(CRITERIA)

    audits = store.step_audits(dt_from, dt_to)
    steps = []
    for crit in active_crit:
        # собираем по критерию: баллы на оператора + лучшие звонки с evidence
        by_op: dict[str, list] = {}
        examples: dict[str, list] = {}
        talks = 0
        for a in audits:
            for dim in (a.get('dimensions') or []):
                if not isinstance(dim, dict) or dim.get('name') != crit:
                    continue
                sc = dim.get('score')
                if sc is None or dim.get('needs_human'):
                    continue
                op = str(a['operator_id'])
                by_op.setdefault(op, []).append(sc)
                talks += 1
                if sc >= GOOD_SCORE_5:
                    ev = (dim.get('evidence_ts') or [None])[0]
                    examples.setdefault(op, []).append({
                        'call_id': str(a['call_id']), 'score': sc, 'evidence_ts': ev,
                        'quote_tr': _quote_from_words(a.get('words'), ev) if ev else '',
                        'quote_translation': (a.get('translation_ru') or a.get('translation_en')),
                    })
        if talks < min_talks:
            steps.append({'criterion': crit, 'enough_data': False, 'talks': talks})
            continue
        # % команды, кто отрабатывает (средний балл >= норма)
        performers = sum(1 for v in by_op.values() if (sum(v) / len(v)) >= GOOD_SCORE_5)
        team_pct = round(performers / len(by_op), 3) if by_op else None
        best_op = max(by_op, key=lambda o: sum(by_op[o]) / len(by_op[o])) if by_op else None
        steps.append({
            'criterion': crit, 'enough_data': True, 'talks': talks,
            'team_coverage': team_pct,
            'best_operator': {'operator_id': best_op, 'operator_name': names.get(best_op),
                              'examples': (examples.get(best_op) or [])[:3]} if best_op else None,
        })

    return ok({'period': {'from': dt_from, 'to': dt_to},
               'ranking': ranking, 'steps': steps})


# ════════════════════════════════════════════════════════════════════════════
# 11. GET /summary — сводка владельцу (§10.12)
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/summary')
@require_auth(roles=R_SUMMARY)
@guarded
def summary():
    settings = store.get_settings()
    unlocked = bool(settings['verdict_unlocked'])
    dt_from, dt_to = _period()
    prev_from, prev_to = _prev_period(dt_from, dt_to)

    facts = store.dialing_facts(dt_from, dt_to)
    prev_facts = store.dialing_facts(prev_from, prev_to)

    cur_audits = store.completed_audits(None, dt_from, dt_to)
    analyzed = 0
    compliance_ok = 0
    scores = []
    for a in cur_audits:
        analyzed += 1
        c = _compliance_ok(a.get('compliance'))
        if c:
            compliance_ok += 1
        s = a.get('human_override_score')
        if s is None:
            s = a.get('score')
        if s is not None:
            scores.append(s)
    needs_review = sum(int(c.get('needs_review') or 0)
                       for c in store.call_status_counts(None, dt_from, dt_to))

    out = {
        'period': {'from': dt_from, 'to': dt_to},
        'verdict_unlocked': unlocked,
        'facts': facts,
        'prev_facts': prev_facts,
        'analyzed': analyzed,
        'compliance_pct': round(compliance_ok / analyzed, 3) if analyzed else None,
        'needs_review': needs_review,
        # динамика по неделям + назначенные перезвоны — факты CRM/звонилки,
        # от модели и сверки не зависят → владельцу можно всегда (§10.12)
        'weekly': store.weekly_dialing_facts(),
        'scheduled_upcoming': store.scheduled_upcoming_count(),
    }
    # Средний балл + тренд — ТОЛЬКО при разблокированном вердикте (§7, §10.12).
    if unlocked:
        avg = round(sum(scores) / len(scores)) if scores else None
        prev_scores = [(x.get('human_override_score') if x.get('human_override_score') is not None
                        else x.get('score')) for x in store.completed_audits(None, prev_from, prev_to)]
        prev_scores = [s for s in prev_scores if s is not None]
        pavg = round(sum(prev_scores) / len(prev_scores)) if prev_scores else None
        out['avg_score'] = avg
        out['avg_score_trend'] = (avg - pavg) if (avg is not None and pavg is not None) else None
    return ok(out)


# ════════════════════════════════════════════════════════════════════════════
# 12. Скрипт (§10.8/§10.9): GET /script, POST draft/activate/dry-run
# ════════════════════════════════════════════════════════════════════════════
def _script_out(row: dict | None):
    if not row:
        return None
    return {'script_id': str(row['script_id']), 'version': row.get('version'),
            'status': row.get('status'), 'blocks': row.get('blocks'),
            'activated_at': row.get('activated_at'), 'created_at': row.get('created_at')}


_WINDOW_S = 7 * 86400   # окно атрибуции «после звонка» — 7 дней


def _events_after(players: list[int]):
    """Депозиты и ставки игроков из ClickHouse: {pid: [ts]} × 2 словаря.

    «Что случилось ПОСЛЕ звонка» живёт в CH (money/game_transactions), звонки —
    в Postgres: сверяем в Python. Единственная опора, не зависящая от нашей
    рубрики (спека §10.6: по результату, не по баллу).
    """
    import player_board as pb  # noqa: PLC0415 — CH-доступ борда
    deps: dict[int, list] = {}
    for pid, ts in pb.q(
            "SELECT casino_player_id, toTimezone(created_at,'Europe/Istanbul') "
            "FROM money_transactions WHERE type IN ('deposit','manual_deposit') "
            "AND status='completed' AND casino_player_id IN {ids:Array(UInt32)}",
            {'ids': players})[1]:
        deps.setdefault(int(pid), []).append(ts)
    bets: dict[int, list] = {}
    for pid, ts in pb.q(
            "SELECT casino_player_id, min(toTimezone(created_at,'Europe/Istanbul')) "
            "FROM game_transactions WHERE transaction_type IN ('bet','freespins_bet') "
            "AND casino_player_id IN {ids:Array(UInt32)} "
            "GROUP BY casino_player_id, toStartOfHour(created_at)",
            {'ids': players})[1]:
        bets.setdefault(int(pid), []).append(ts)
    return deps, bets


def _first_after(events: list, started) -> float | None:
    """Минуты от звонка до первого события в окне атрибуции (None = не было).

    События из CH приходят naive в Europe/Istanbul (toTimezone в запросе), а
    started_at из PG — aware UTC. Сначала приводим звонок к стенным часам
    Стамбула, иначе вся атрибуция уезжает на +3 часа (депозит ЗА 5 минут ДО
    звонка засчитался бы как «через 175 минут после»)."""
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    start = started.astimezone(ZoneInfo('Europe/Istanbul')).replace(tzinfo=None)
    hits = [(e - start).total_seconds() for e in events
            if 0 <= (e - start).total_seconds() <= _WINDOW_S]
    return round(min(hits) / 60) if hits else None


def reaction_after_call(pid: int, started) -> dict:
    """Реакция игрока после конкретного звонка: через сколько минут деп/игра."""
    try:
        deps, bets = _events_after([int(pid)])
    except Exception as e:  # noqa: BLE001 — CH недоступен → без реакции
        logger.warning('reaction: ClickHouse недоступен (%s)', e)
        return {}
    return {'deposit_min': _first_after(deps.get(int(pid), []), started),
            'played_min': _first_after(bets.get(int(pid), []), started)}


def _outcomes_by_version(calls: list[tuple]) -> dict[int, dict]:
    """Агрегат по версии: депозит ≤7д, вернулся в игру ≤7д, медиана минут до депа."""
    if not calls:
        return {}
    try:
        deps, bets = _events_after(sorted({int(p) for _, p, _ in calls}))
    except Exception as e:  # noqa: BLE001
        logger.warning('outcomes: ClickHouse недоступен (%s) — колонки пропущены', e)
        return {}
    out: dict[int, dict] = {}
    for ver, pid, started in calls:
        d = out.setdefault(ver, {'dep7d': 0, 'play7d': 0, '_dep_mins': []})
        dep_min = _first_after(deps.get(int(pid), []), started)
        if dep_min is not None:
            d['dep7d'] += 1
            d['_dep_mins'].append(dep_min)
        if _first_after(bets.get(int(pid), []), started) is not None:
            d['play7d'] += 1
    for d in out.values():
        mins = sorted(d.pop('_dep_mins'))
        d['dep_median_min'] = mins[len(mins) // 2] if mins else None
    return out


@bp.get('/call-analysis/script')
@require_auth(roles=R_SCRIPT_GET)
@guarded
def get_script():
    role = current_role()
    # ?group_id — редактируем/смотрим скрипт конкретной группы (A/B); нет → казино-дефолт.
    # Оператору группа не нужна: он видит скрипт, назначенный ЕГО оператору.
    if role in OPERATOR_LIKE:
        gv = store.resolve_script_version(store.CASINO_ID, current_user_id())
        active = store.active_script_by_version(store.CASINO_ID, gv) if gv else None
        return ok({'active': _script_out(active)})
    # 0011: правим конкретный именованный скрипт (?script_ref=), легаси ?group_id
    # маппится на скрипт группы; без параметров — дефолт казино.
    script_ref = _script_ref_of(request.args)
    active = store.active_script(store.CASINO_ID, script_ref)
    stats, calls = store.script_version_stats(store.CASINO_ID)
    outcomes = _outcomes_by_version(calls)
    versions_stats = [{
        'version': s['version'], 'status': s['status'],
        'group_id': str(s['group_id']) if s.get('group_id') else None,
        'group_name': s.get('group_name'),      # None = скрипт казино по умолчанию
        'script_name': s.get('script_name'),    # имя именованного скрипта (0011)
        'activated_at': s['activated_at'].isoformat() if s['activated_at'] else None,
        'analyzed': int(s['analyzed'] or 0),
        'presented': int(s['presented'] or 0),
        'accepted': int(s['accepted'] or 0),
        'accept_rate': (round(s['accepted'] / s['presented'] * 100)
                        if s['presented'] else None),
        'dep7d': outcomes.get(s['version'], {}).get('dep7d'),
        'play7d': outcomes.get(s['version'], {}).get('play7d'),
        'dep_median_min': outcomes.get(s['version'], {}).get('dep_median_min'),
        'avg_score': int(s['avg_score']) if s['avg_score'] is not None else None,
    } for s in stats]
    ref = script_ref or store.default_script_ref(store.CASINO_ID)
    meta = store.script_by_ref(store.CASINO_ID, ref) if ref else None
    return ok({'active': _script_out(active),
               'draft': _script_out(store.draft_script(store.CASINO_ID, script_ref)),
               'versions_stats': versions_stats,
               'script_ref': ref,
               'script_name': meta['name'] if meta else None,
               'group_id': _valid_uuid(request.args.get('group_id'))})


def _validate_blocks(blocks):
    if not isinstance(blocks, list):
        return 'blocks: ожидается список блоков'
    for i, b in enumerate(blocks):
        if not isinstance(b, dict):
            return f'блок {i}: ожидается объект'
        crit = b.get('criterion')
        if crit is not None and crit not in CRITERIA:
            return f'блок {i}: criterion должен быть одним из 9 канонических или null'
        cl = b.get('check_level')
        if cl is not None and cl not in store.CHECK_LEVELS:
            return f'блок {i}: check_level ∈ {store.CHECK_LEVELS} или null'
        imp = b.get('importance')
        if imp is not None and imp not in store.IMPORTANCE:
            return f'блок {i}: importance ∈ {store.IMPORTANCE} или null'
    return None


def _group_id(body) -> str | None:
    """group_id из тела — валидный UUID или None (скрипт казино по умолчанию)."""
    return _valid_uuid(body.get('group_id'))


def _script_ref_of(src) -> str | None:
    """script_ref из тела/квери (0011). Легаси: пришёл только group_id →
    скрипт, назначенный группе. None → дефолт казино (резолвит store)."""
    ref = _valid_uuid(src.get('script_ref'))
    if ref:
        return ref
    gid = _valid_uuid(src.get('group_id'))
    return store.group_script_ref(gid) if gid else None


@bp.post('/call-analysis/script/draft')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def script_draft():
    body = request.get_json(silent=True) or {}
    blocks = body.get('blocks')
    err = _validate_blocks(blocks)
    if err:
        return api_json(error=err, code=422)
    # script_ref → черновик именованного скрипта (0011); None → дефолт казино
    script_id = store.save_draft(store.CASINO_ID, blocks, current_user_id(), _script_ref_of(body))
    return ok({'script_id': script_id, 'status': 'draft'})


@bp.post('/call-analysis/script/activate')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def script_activate():
    body = request.get_json(silent=True) or {}
    version = store.activate_draft(store.CASINO_ID, _script_ref_of(body))
    if version is None:
        return api_json(error='Нет черновика для ввода в бой', code=409)
    return ok({'version': version, 'status': 'active'})


# ── Именованные скрипты (0011): реестр + «какой скрипт куда идёт» ─────────────
@bp.get('/call-analysis/scripts')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def scripts_list():
    """Реестр скриптов: имя, активная версия, черновик, дефолт, каким группам назначен."""
    scripts = [{
        'script_ref': str(s['script_ref']), 'name': s['name'],
        'active_version': s.get('active_version'),
        'has_draft': bool(s.get('has_draft')),
        'is_default': bool(s.get('is_default')),
        'groups': list(s.get('groups') or []),
        'created_at': s['created_at'].isoformat() if s.get('created_at') else None,
    } for s in store.list_scripts(store.CASINO_ID)]
    return ok({'scripts': scripts,
               'default_ref': store.default_script_ref(store.CASINO_ID)})


@bp.post('/call-analysis/scripts')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def scripts_create():
    """Создать новый именованный скрипт (пустой: дальше draft → в бой)."""
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return api_json(error='Название скрипта обязательно', code=422)
    ref = store.create_script(store.CASINO_ID, name, current_user_id())
    if ref is None:
        return api_json(error='Скрипт с таким названием уже есть', code=409)
    return ok({'script_ref': ref, 'name': name})


@bp.patch('/call-analysis/scripts/<uuid:script_ref>')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def scripts_rename(script_ref):
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return api_json(error='Название скрипта обязательно', code=422)
    if not store.script_by_ref(store.CASINO_ID, str(script_ref)):
        return api_json(error='Скрипт не найден', code=404)
    if not store.rename_script(store.CASINO_ID, str(script_ref), name):
        return api_json(error='Скрипт с таким названием уже есть', code=409)
    return ok({'script_ref': str(script_ref), 'name': name})


@bp.post('/call-analysis/scripts/<uuid:script_ref>/duplicate')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def scripts_duplicate(script_ref):
    """«Создать на основе»: копия блоков (draft > active) черновиком нового скрипта."""
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return api_json(error='Название копии обязательно', code=422)
    if not store.script_by_ref(store.CASINO_ID, str(script_ref)):
        return api_json(error='Скрипт не найден', code=404)
    new_ref = store.duplicate_script(store.CASINO_ID, str(script_ref), name, current_user_id())
    if new_ref is None:
        return api_json(error='Скрипт с таким названием уже есть', code=409)
    return ok({'script_ref': new_ref, 'name': name})


@bp.post('/call-analysis/scripts/<uuid:script_ref>/archive')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def scripts_archive(script_ref):
    """Архив (не удаление): версии остаются в статистике. Дефолт/назначенные — нельзя."""
    err = store.archive_script(store.CASINO_ID, str(script_ref))
    if err == 'default':
        return api_json(error='Это скрипт по умолчанию — сначала назначьте дефолтом другой', code=422)
    if err == 'assigned':
        return api_json(error='Скрипт назначен группе — сначала переназначьте группу', code=422)
    if err == 'not_found':
        return api_json(error='Скрипт не найден', code=404)
    return ok({'script_ref': str(script_ref), 'archived': True})


@bp.post('/call-analysis/script/default')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def script_set_default():
    """Скрипт казино по умолчанию: его получают операторы без группы и группы
    без назначенного скрипта."""
    body = request.get_json(silent=True) or {}
    ref = _valid_uuid(body.get('script_ref'))
    if not ref or not store.script_by_ref(store.CASINO_ID, ref):
        return api_json(error='script_ref: скрипт не найден', code=422)
    store.set_default_script(store.CASINO_ID, ref)
    return ok({'default_ref': ref})


@bp.post('/call-analysis/script/groups/<uuid:group_id>/script')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def script_group_assign(group_id):
    """«Какой скрипт идёт этой группе»: script_ref или null (наследует дефолт)."""
    body = request.get_json(silent=True) or {}
    raw = body.get('script_ref')
    ref = _valid_uuid(raw) if raw else None
    if raw and (not ref or not store.script_by_ref(store.CASINO_ID, ref)):
        return api_json(error='script_ref: скрипт не найден', code=422)
    store.assign_group_script(str(group_id), ref)
    return ok({'group_id': str(group_id), 'script_ref': ref})


# ── A/B-группы (§8/§10.8): разные скрипты разным группам операторов ───────────
@bp.get('/call-analysis/script/groups')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def script_groups_list():
    """Список групп + число операторов + активная версия скрипта каждой,
    плюс операторы БЕЗ группы (кандидаты на назначение)."""
    groups = store.list_script_groups(store.CASINO_ID)
    for g in groups:
        g['group_id'] = str(g['group_id'])
        g['created_at'] = g['created_at'].isoformat() if g.get('created_at') else None
        g['members_list'] = [{'operator_id': str(m['operator_id']),
                              'name': m.get('full_name'), 'department': m.get('department')}
                             for m in store.group_members(g['group_id'])]
    return ok({'groups': groups, 'ungrouped': store.ungrouped_operators(store.CASINO_ID)})


@bp.post('/call-analysis/script/groups')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def script_group_create():
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return api_json(error='Название группы обязательно', code=422)
    gid = store.create_script_group(store.CASINO_ID, name, current_user_id())
    return ok({'group_id': gid, 'name': name})


@bp.delete('/call-analysis/script/groups/<uuid:group_id>')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def script_group_delete(group_id):
    # удаление каскадит участников и скрипты группы (0010 ON DELETE CASCADE)
    if not store.delete_script_group(str(group_id)):
        return api_json(error='Группа не найдена', code=404)
    return ok({'group_id': str(group_id), 'deleted': True})


@bp.post('/call-analysis/script/groups/<uuid:group_id>/members')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def script_group_add_member(group_id):
    """Назначить оператора в группу (оператор в ОДНОЙ группе — перезапишет прошлую)."""
    body = request.get_json(silent=True) or {}
    op = _valid_uuid(body.get('operator_id'))
    if not op:
        return api_json(error='operator_id: ожидается UUID', code=422)
    store.set_operator_group(op, str(group_id))
    return ok({'group_id': str(group_id), 'operator_id': op})


@bp.delete('/call-analysis/script/groups/members/<uuid:operator_id>')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def script_group_remove_member(operator_id):
    store.set_operator_group(str(operator_id), None)
    return ok({'operator_id': str(operator_id), 'removed': True})


def _weights_from_blocks(blocks):
    """Веса из важности блоков «по смыслу», нормируем к 100 (§10.8). Выключенные критерии
    (нет блока или check_level≠meaning) естественно выпадают из overall_score."""
    raw = {}
    for b in blocks:
        if not isinstance(b, dict):
            continue
        crit, cl = b.get('criterion'), b.get('check_level')
        if crit in CRITERIA and cl == 'meaning':
            raw[crit] = IMPORTANCE_WEIGHT.get(b.get('importance') or 'normal', 2)
    total = sum(raw.values())
    if not total:
        return {}
    return {k: round(v / total * 100) for k, v in raw.items()}


@bp.post('/call-analysis/script/dry-run')
@require_auth(roles=R_SCRIPT_WRITE)
@guarded
def script_dry_run():
    """ЭФЕМЕРНЫЙ прогон черновика на последних 20 разобранных звонках (§10.8).
    Пересчёт через scoring с новыми весами. В БАЗУ НЕ ПИШЕТ."""
    body = request.get_json(silent=True) or {}
    blocks = body.get('blocks')
    err = _validate_blocks(blocks)
    if err:
        return api_json(error=err, code=422)
    weights = _weights_from_blocks(blocks) or None
    rows = store.last_completed_dimensions(store.CASINO_ID, 20)
    calls, cur_sum, cur_n, draft_sum, draft_n = [], 0, 0, 0, 0
    for r in rows:
        cur = r.get('current_score')
        draft = overall_score(r.get('dimensions') or [], weights)
        if cur is not None:
            cur_sum += cur
            cur_n += 1
        if draft is not None:
            draft_sum += draft
            draft_n += 1
        calls.append({'call_id': str(r['call_id']), 'current': cur, 'draft': draft,
                      'delta': (draft - cur) if (draft is not None and cur is not None) else None})
    return ok({
        'avg_current': round(cur_sum / cur_n) if cur_n else None,
        'avg_draft': round(draft_sum / draft_n) if draft_n else None,
        'sample_size': len(calls),
        'calls': calls,
        'persisted': False,     # честно: в базу не писали
    })


# ════════════════════════════════════════════════════════════════════════════
# 13. Вердикт и веса (§10.13). Роли: ADMIN only.
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/verdict-stats')
@require_auth(roles=R_ADMIN)
@guarded
def verdict_stats():
    settings = store.get_settings()
    weights = store.get_weights(settings)
    metrics = _verdict_metrics(store.review_rows(store.CASINO_ID), weights)
    verified = store.translation_verified_count(store.CASINO_ID)
    return ok({
        'verdict_unlocked': bool(settings['verdict_unlocked']),
        'checked': metrics['checked'],
        'random': metrics['random'],
        'agreement': metrics['agreement'],
        'avg_delta': metrics['avg_delta'],
        'per_criterion_delta': metrics['per_criterion_delta'],
        'translation_verified': verified,
        'random_sample_per_day': settings['random_sample_per_day'],
        'min_review_time_s': settings['min_review_time_s'],
        'hints': {'agreement': AGREEMENT_HINT, 'delta': 0.3},   # из чужой практики, не порог
        # динамика согласия по неделям — видно, СХОДИТСЯ ли модель, а не только среднее
        'agreement_weekly': store.agreement_weekly(),
        # последние правки с причинами — где модель ошиблась и почему (наводка на промпт)
        'recent_disagreements': store.recent_disagreements(),
    })


@bp.post('/call-analysis/verdict/unlock')
@require_auth(roles=R_ADMIN)
@guarded
def verdict_unlock():
    settings = store.get_settings()
    weights = store.get_weights(settings)
    metrics = _verdict_metrics(store.review_rows(store.CASINO_ID), weights)
    updated = store.unlock_verdict(store.CASINO_ID, current_user_id())
    warning = None
    agreement = metrics['agreement']
    if agreement is not None and agreement < AGREEMENT_HINT:
        # предупреждаем, но НЕ блокируем (§10.13: решение за человеком)
        warning = (f'Согласие {round(agreement * 100)}% ниже ориентира '
                   f'{round(AGREEMENT_HINT * 100)}%. Вердикт разблокирован, но сверка ещё слабая.')
    return ok({'verdict_unlocked': updated['verdict_unlocked'],
               'agreement': agreement, 'warning': warning})


@bp.post('/call-analysis/settings')
@require_auth(roles=R_ADMIN)
@guarded
def update_settings():
    body = request.get_json(silent=True) or {}
    rs = body.get('random_sample_per_day')
    mr = body.get('min_review_time_s')

    def _opt_int(v, name):
        if v is None:
            return None, None
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return None, f'{name}: ожидается целое число'
        if iv < 0:
            return None, f'{name}: не может быть отрицательным'
        return iv, None

    rs_v, err = _opt_int(rs, 'random_sample_per_day')
    if err:
        return api_json(error=err, code=422)
    mr_v, err = _opt_int(mr, 'min_review_time_s')
    if err:
        return api_json(error=err, code=422)
    if rs_v is None and mr_v is None:
        return api_json(error='Нечего обновлять: передайте random_sample_per_day и/или min_review_time_s',
                        code=422)
    updated = store.update_settings(store.CASINO_ID, rs_v, mr_v)
    return ok({'random_sample_per_day': updated['random_sample_per_day'],
               'min_review_time_s': updated['min_review_time_s']})


# ════════════════════════════════════════════════════════════════════════════
# 14. Проверка перевода (§10.11). Роли: TRANSLATION, ADMIN.
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/call-analysis/translation-check/next')
@require_auth(roles=R_TRANSLATION)
@guarded
def translation_check_next():
    row = store.next_unverified_translation(store.CASINO_ID)
    remaining = store.unverified_translation_count(store.CASINO_ID)
    if row is None:
        return ok({'call': None, 'remaining': 0})
    return ok({
        'call': {
            'call_id': str(row['call_id']),
            'player_id': row.get('casino_player_id'),
            'duration_s': row.get('duration_s'),
            'has_audio': bool(row.get('audio_ref')),
            'language': row.get('language'),
            'text': row.get('text_redacted'),
            'words': row.get('words'),
        },
        'remaining': remaining,
    })


@bp.post('/call-analysis/translation-check/<uuid:call_id>')
@require_auth(roles=R_TRANSLATION)
@guarded
def translation_check_submit(call_id):
    cid = str(call_id)
    body = request.get_json(silent=True) or {}
    match = body.get('match')
    if not isinstance(match, bool):
        return api_json(error='match: ожидается true/false', code=422)
    # note — «где не совпало»: раньше молча терялась, теперь хранится (0009)
    if not store.mark_translation_checked(cid, match, note=body.get('note')):
        return api_json(error='Транскрипт не найден', code=404)
    store.log_access(current_user_id(), cid, 'translation_check')
    return ok({'call_id': cid, 'match': match, 'translation_verified': bool(match)})
