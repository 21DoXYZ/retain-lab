"""api/reports.py — JSON-домен «Конструктор отчётов» (W5-T2).

Headless-обёртка над компилятором api/report_builder.py: принимает spec (метрики ×
разрезы × фильтры × период), собирает ОДИН ClickHouse-запрос и отдаёт таблицу +
тоталы + meta. Формулы/условия успешных операций не переписаны — они в реестре
report_fields.py (зеркало player_board.py:116-124). Экспорт CSV/XLSX — те же
паттерны, что у бордовых выгрузок (BOM+';' и openpyxl).

Эндпоинты (под /api/v1):
  POST /reports/run          {spec} → {columns, rows, totals, meta}
  GET  /reports/fields               → оба реестра (METRICS/DIMENSIONS) для UI
  POST /reports/export.csv   {spec} → text/csv (UTF-8 BOM, ';')
  POST /reports/export.xlsx  {spec} → xlsx (openpyxl)

Роли — аналитики + денежные руководители (ANALYSTS+finance, сверено с nav.ts):
  super_admin, head_retention, director, analyst, marketing_manager, finance.
"""
from __future__ import annotations

import io
import os
import time
import uuid
from decimal import Decimal

from flask import Blueprint, request, Response

from .core import (require_auth, api_json, current_user_id, current_role,
                   _auth_off)
from .report_builder import (build_report_query, report_uses_state_at,
                             result_columns, SpecError)
from .report_fields import describe_fields, is_derived, compute_derived
from . import reports_store
import player_board as pb   # pb.q — исполнитель CH-запросов, единый клиент борда

bp = Blueprint('api_reports', __name__, url_prefix='/api/v1')

# ── роли: ANALYSTS + finance (см. nav.ts:58-64 ANALYSTS; деньги видят finance) ──
REPORT_ROLES = ['super_admin', 'head_retention', 'director',
                'analyst', 'marketing_manager', 'finance']

# Кто может делать отчёт «официальным» (каноническим отчётом компании). Уже, чем
# REPORT_ROLES: рядовой аналитик/маркетолог/финансист официальность не ставит.
OFFICIAL_ROLES = frozenset({'director', 'head_retention', 'super_admin'})


# ── валюта отчёта (П6: суммы в USD/TRY) ──
# В данных нет по-транзакционного курса (money.exchange_rate = NULL), поэтому USD —
# по ФИКСИРОВАННОМУ курсу из конфига. Конвертируем POST-AGG только money-колонки;
# отношения (pct) безразмерны и не масштабируются.
try:
    USD_TRY_RATE = float(os.environ.get('REPORT_USD_TRY_RATE', '34') or 34)
except (TypeError, ValueError):
    USD_TRY_RATE = 34.0


def _currency(spec: dict) -> str:
    c = str((spec or {}).get('currency') or 'TRY').upper()
    return c if c in ('TRY', 'USD') else 'TRY'


def _apply_currency(rows: list[dict], columns: list[dict], currency: str) -> None:
    """Масштабирует money-колонки в USD по фиксированному курсу (мутирует rows)."""
    if currency != 'USD' or USD_TRY_RATE <= 0:
        return
    money_keys = [c['key'] for c in columns if c.get('type') == 'money']
    for row in rows:
        for k in money_keys:
            v = row.get(k)
            # ClickHouse отдаёт суммы как Decimal — учитываем и его
            if isinstance(v, (int, float, Decimal)):
                row[k] = round(float(v) / USD_TRY_RATE, 2)


def _spec_error(e: Exception, code: int = 422) -> Response:
    """Ответ об ошибке спеки: рус. текст + (для SpecError) error_code/error_params
    → фронт переводит по reports.err.<code> с фолбэком на текст."""
    extra = None
    if isinstance(e, SpecError):
        extra = {'error_code': e.code, 'error_params': e.params}
    return api_json(error=str(e), code=code, extra=extra)


def _spec_from_request() -> dict:
    """spec может прийти как {spec:{...}} или напрямую телом запроса."""
    body = request.get_json(silent=True) or {}
    if isinstance(body, dict) and isinstance(body.get('spec'), dict):
        return body['spec']
    return body if isinstance(body, dict) else {}


def _history_from():
    """Первая дата снапшотов состояний — UI предупреждает, если период раньше.
    Пусто (None) — если таблицы/данных нет (тогда историческая корректность
    начинается позже)."""
    try:
        r = pb.q("SELECT min(snap_date) FROM player_state_daily FINAL")[1]
        v = r[0][0] if r else None
        # ClickHouse может вернуть «нулевую» дату при пустой таблице
        if v is None or str(v).startswith('1970'):
            return None
        return v
    except Exception:
        return None


def _run(spec: dict):
    """Компиляция + исполнение основного запроса. → (columns, rows, meta, err_resp).
    err_resp != None — вернуть его сразу (ошибка валидации/исполнения)."""
    try:
        sql, params = build_report_query(spec)
    except ValueError as e:
        return None, None, None, _spec_error(e)

    columns = result_columns(spec)
    t0 = time.time()
    try:
        qr = pb._client().query(sql, parameters=params)
    except Exception as e:                       # noqa: BLE001
        pb.app.logger.error('reports run failed: %s\nSQL: %s', e, sql)
        return None, None, None, api_json(
            error='Не удалось выполнить отчёт (проверьте параметры или упростите разрезы)',
            code=500, extra={'error_code': 'exec_failed', 'error_params': {}})
    took_ms = int((time.time() - t0) * 1000)
    col_names = qr.column_names
    rows = [dict(zip(col_names, r)) for r in qr.result_rows]

    # производные колонки (отношения base-метрик) — post-agg по каждой строке.
    # ВАЖНО: считаем ДО валютного масштабирования — pct-отношения безразмерны,
    # а money-числитель/знаменатель ещё в TRY (иначе двойной пересчёт).
    derived_keys = [m for m in (spec.get('metrics') or []) if is_derived(m)]
    if derived_keys:
        for row in rows:
            compute_derived(row, derived_keys)
    _apply_currency(rows, columns, _currency(spec))

    scanned = None
    try:
        scanned = int(qr.summary.get('read_rows'))
    except Exception:                            # noqa: BLE001
        scanned = None

    cur = _currency(spec)
    meta = {'took_ms': took_ms, 'result_rows': len(rows),
            'rows_scanned': scanned, 'history_from': _history_from(),
            'uses_state_at': report_uses_state_at(spec),
            'currency': cur,
            'usd_rate': USD_TRY_RATE if cur == 'USD' else None}
    return columns, rows, meta, None


def _totals(spec: dict) -> dict:
    """Та же выборка БЕЗ разрезов (отдельный запрос) — строка итогов."""
    tspec = {**spec, 'dims': []}
    try:
        sql, params = build_report_query(tspec)
        qr = pb._client().query(sql, parameters=params)
    except Exception:                            # noqa: BLE001
        return {}
    if not qr.result_rows:
        return {}
    totals = dict(zip(qr.column_names, qr.result_rows[0]))
    derived_keys = [m for m in (spec.get('metrics') or []) if is_derived(m)]
    if derived_keys:
        compute_derived(totals, derived_keys)
    _apply_currency([totals], result_columns(spec), _currency(spec))
    return totals


# ════════════════════════════════════════════════════════════════════════════
# POST /reports/run
# ════════════════════════════════════════════════════════════════════════════
@bp.post('/reports/run')
@require_auth(roles=REPORT_ROLES)
def reports_run():
    """Собрать сводный отчёт: {columns, rows, totals, meta}. Историческая
    корректность сегментов (state_at) — через снапшот на дату события."""
    spec = _spec_from_request()
    columns, rows, meta, err = _run(spec)
    if err is not None:
        return err
    return api_json({'columns': columns, 'rows': rows,
                     'totals': _totals(spec), 'meta': meta})


# ════════════════════════════════════════════════════════════════════════════
# GET /reports/fields — оба реестра для UI
# ════════════════════════════════════════════════════════════════════════════
@bp.get('/reports/fields')
@require_auth(roles=REPORT_ROLES)
def reports_fields():
    """Каталог доступных метрик и разрезов (для панели сборки отчёта)."""
    return api_json(describe_fields())


# ════════════════════════════════════════════════════════════════════════════
# Экспорт
# ════════════════════════════════════════════════════════════════════════════
def _cell(v) -> str:
    if v is None:
        return ''
    return str(v)


def _export_filename(spec: dict, ext: str) -> str:
    p = spec.get('period') or {}
    return f"report_{p.get('from', 'all')}_{p.get('to', 'all')}.{ext}"


def _labels_from_request() -> dict:
    """Локализованные заголовки колонок {key: label} из тела запроса (фронт —
    источник правды по i18n). Пусто → используются бэкенд-label (рус.)."""
    body = request.get_json(silent=True) or {}
    lbl = body.get('labels') if isinstance(body, dict) else None
    return lbl if isinstance(lbl, dict) else {}


def _header_labels(columns: list[dict]) -> list[str]:
    """Заголовки колонок: локализованные с фронта, иначе бэкенд-label."""
    labels = _labels_from_request()
    return [str(labels.get(c['key'], c['label'])) for c in columns]


@bp.post('/reports/export.csv')
@require_auth(roles=REPORT_ROLES)
def reports_export_csv():
    """CSV = тот же запрос, что /reports/run (UTF-8 BOM + ';' — как бордовые выгрузки)."""
    spec = _spec_from_request()
    columns, rows, _meta, err = _run(spec)
    if err is not None:
        return err
    keys = [c['key'] for c in columns]
    header = _header_labels(columns)
    out = ['﻿' + ';'.join(header)]         # BOM — Excel открывает UTF-8 без кракозябр
    for row in rows:
        out.append(';'.join(_cell(row.get(k)) for k in keys))
    return Response('\r\n'.join(out), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition':
                             f'attachment; filename="{_export_filename(spec, "csv")}"'})


@bp.post('/reports/export.xlsx')
@require_auth(roles=REPORT_ROLES)
def reports_export_xlsx():
    """XLSX = тот же запрос, openpyxl-паттерн (образец api/players_analytics.py:804)."""
    from openpyxl import Workbook
    spec = _spec_from_request()
    columns, rows, _meta, err = _run(spec)
    if err is not None:
        return err
    keys = [c['key'] for c in columns]
    wb = Workbook()
    ws = wb.active
    ws.title = 'report'
    ws.append(_header_labels(columns))
    for row in rows:
        ws.append([row.get(k) for k in keys])
    ws.freeze_panes = 'A2'
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        buf.read(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':
                 f'attachment; filename="{_export_filename(spec, "xlsx")}"'})


# ════════════════════════════════════════════════════════════════════════════
# Сохранённые отчёты (W5-T3): личные / общие / по ролям + официальные
# CRUD и duplicate над automation.saved_reports (SQL — api/reports_store.py).
# Доступ (personal/shared/roles) собирает store SQL-ом; ролевой гейт модуля —
# REPORT_ROLES; право ставить is_official — OFFICIAL_ROLES (проверка здесь).
# ════════════════════════════════════════════════════════════════════════════
def _valid_uuid(s) -> bool:
    try:
        uuid.UUID(str(s))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _effective_user_id() -> str | None:
    """UUID текущего пользователя для владения записями.

    JWT-sub — обычно реальный crm_users.id. В dev (API_AUTH_OFF) require_auth кладёт
    sub='dev' (не UUID) → FK owner_id не прошёл бы. ТОЛЬКО в явном dev-режиме
    (_auth_off()) подменяем на первого super_admin из crm_users — для локального
    smoke. В проде фолбэк ВЫКЛЮЧЕН: невалидный sub возвращается как есть, и запись
    честно упадёт/не найдётся, а не запишется под чужого (fail-closed).
    """
    sub = current_user_id()
    if _valid_uuid(sub):
        return str(sub)
    if _auth_off():
        try:
            return reports_store.first_super_admin_id()
        except reports_store.ReportStoreError:
            return sub
    return sub


def _can_edit(row: dict, uid: str | None, role: str | None) -> bool:
    """Редактировать/удалять отчёт может владелец или super_admin (зеркало RLS)."""
    if uid and row.get('owner_id') == str(uid):
        return True
    return role == 'super_admin'


def _validate_spec(spec) -> Response | None:
    """spec валиден? Прогоняем через компилятор билдера (валидация whitelist/
    периода/источников БЕЗ исполнения) → None (ок) или Response(422)."""
    if not isinstance(spec, dict):
        return api_json(error='spec: ожидается объект', code=422,
                        extra={'error_code': 'spec_not_object', 'error_params': {}})
    try:
        build_report_query(spec)               # чистая валидация, к БД не ходит
    except ValueError as e:
        return _spec_error(e)
    return None


def _parse_saved_body(role: str | None, current_official: bool = False):
    """Разбор/валидация тела POST/PUT сохранённого отчёта.
    → (fields, err). fields = {name, spec, visibility, roles, is_official}."""
    body = request.get_json(silent=True) or {}

    name = str(body.get('name') or '').strip()
    if not name:
        return None, api_json(error='name: обязательно непустое имя', code=422)
    name = name[:200]

    spec = body.get('spec')
    err = _validate_spec(spec)
    if err is not None:
        return None, err

    visibility = str(body.get('visibility') or 'personal')
    if visibility not in reports_store.VISIBILITIES:
        return None, api_json(error='visibility: personal | shared | roles', code=422)

    roles = body.get('roles') or []
    if not isinstance(roles, list):
        return None, api_json(error='roles: ожидается список ролей', code=422)
    roles = [str(r) for r in roles]
    bad = [r for r in roles if r not in reports_store.USER_ROLES]
    if bad:
        return None, api_json(error=f'roles: неизвестные роли {bad}', code=422)
    # visibility='roles' с пустым roles допустим — отчёт виден только владельцу
    # (эквивалент personal); намеренно не запрещаем.

    # is_official: менять признак (в любую сторону) может только OFFICIAL_ROLES.
    want = body.get('is_official')
    is_official = bool(current_official) if want is None else bool(want)
    if is_official != current_official and role not in OFFICIAL_ROLES:
        return None, api_json(
            error='менять признак «официальный» может только директор / '
                  'глава ретеншена / супер-админ', code=403)

    return {'name': name, 'spec': spec, 'visibility': visibility,
            'roles': roles, 'is_official': is_official}, None


@bp.get('/reports/saved')
@require_auth(roles=REPORT_ROLES)
def reports_saved_list():
    """Сохранённые отчёты, видимые пользователю (личные + общие + по ролям).
    Официальные сверху, затем по свежести. mine — признак «мой отчёт»."""
    uid = _effective_user_id()
    role = current_role()
    try:
        rows = reports_store.list_visible(uid, role)
    except reports_store.ReportStoreError as e:
        pb.app.logger.error('saved reports list failed: %s', e)
        return api_json(error='Не удалось загрузить сохранённые отчёты', code=503)
    return api_json({'rows': rows})


@bp.post('/reports/saved')
@require_auth(roles=REPORT_ROLES)
def reports_saved_create():
    """Сохранить отчёт {name, spec, visibility, roles?, is_official?}. spec — через
    валидатор билдера (422 при невалидном). is_official — только OFFICIAL_ROLES."""
    role = current_role()
    fields, err = _parse_saved_body(role)
    if err is not None:
        return err
    owner = _effective_user_id()
    if not owner:
        return api_json(error='не удалось определить владельца отчёта', code=400)
    try:
        rid = reports_store.create(owner, **fields)
    except reports_store.DuplicateName as e:
        return api_json(error=str(e), code=409)
    except reports_store.ReportStoreError as e:
        pb.app.logger.error('saved report create failed: %s', e)
        return api_json(error='Не удалось сохранить отчёт', code=503)
    return api_json({'report_id': rid}, code=201)


@bp.put('/reports/saved/<uuid:report_id>')
@require_auth(roles=REPORT_ROLES)
def reports_saved_update(report_id):
    """Обновить отчёт (полная замена). Только владелец или super_admin."""
    role = current_role()
    uid = _effective_user_id()
    rid = str(report_id)
    try:
        existing = reports_store.get(rid, uid)
        if existing is None:
            return api_json(error='отчёт не найден', code=404)
        if not _can_edit(existing, uid, role):
            return api_json(error='forbidden: редактировать может только владелец '
                            'или супер-админ', code=403)
        fields, err = _parse_saved_body(
            role, current_official=bool(existing.get('is_official')))
        if err is not None:
            return err
        found = reports_store.update(rid, **fields)
        if not found:
            return api_json(error='отчёт не найден', code=404)
        row = reports_store.get(rid, uid)
    except reports_store.DuplicateName as e:
        return api_json(error=str(e), code=409)
    except reports_store.ReportStoreError as e:
        pb.app.logger.error('saved report update failed: %s', e)
        return api_json(error='Не удалось обновить отчёт', code=503)
    return api_json(row)


@bp.delete('/reports/saved/<uuid:report_id>')
@require_auth(roles=REPORT_ROLES)
def reports_saved_delete(report_id):
    """Удалить отчёт. Только владелец или super_admin."""
    role = current_role()
    uid = _effective_user_id()
    rid = str(report_id)
    try:
        existing = reports_store.get(rid, uid)
        if existing is None:
            return api_json(error='отчёт не найден', code=404)
        if not _can_edit(existing, uid, role):
            return api_json(error='forbidden: удалять может только владелец '
                            'или супер-админ', code=403)
        deleted = reports_store.delete(rid)
    except reports_store.ReportStoreError as e:
        pb.app.logger.error('saved report delete failed: %s', e)
        return api_json(error='Не удалось удалить отчёт', code=503)
    return api_json({'deleted': bool(deleted)})


@bp.post('/reports/saved/<uuid:report_id>/duplicate')
@require_auth(roles=REPORT_ROLES)
def reports_saved_duplicate(report_id):
    """Скопировать видимый отчёт себе: имя + « (копия)», visibility=personal,
    is_official=false. Дублировать можно то, что пользователю видно."""
    role = current_role()
    uid = _effective_user_id()
    rid = str(report_id)
    try:
        existing = reports_store.get(rid, uid)
        if existing is None:
            return api_json(error='отчёт не найден', code=404)
        if not reports_store.is_visible(existing, uid, role):
            return api_json(error='forbidden: нет доступа к этому отчёту', code=403)
        if not uid:
            return api_json(error='не удалось определить владельца копии', code=400)
        new_id = reports_store.duplicate(rid, uid)
    except reports_store.DuplicateName as e:
        return api_json(error=str(e), code=409)
    except reports_store.ReportStoreError as e:
        pb.app.logger.error('saved report duplicate failed: %s', e)
        return api_json(error='Не удалось скопировать отчёт', code=503)
    if new_id is None:
        return api_json(error='отчёт не найден', code=404)
    return api_json({'report_id': new_id}, code=201)
