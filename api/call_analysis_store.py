"""api/call_analysis_store.py — слой доступа к данным Call Analyzer (Postgres).

Здесь живёт ВЕСЬ SQL модуля «Анализ звонков»: схема ``analyzer`` (звонки,
транскрипты, аудиты, сверка, карточки, скрипт, настройки, журнал доступа) плюс
чтение из схемы ``crm`` (назначения, журнал звонилки, пользователи/отделы).
Спеки: call_analyzer_dev_spec.md §4 + call_analyzer_interface_spec_FINAL.md §12.

Почему отдельный модуль (а не в api/call_analysis.py):
  • «много маленьких файлов»: ручки (RBAC + форма ответа) отделены от SQL;
  • браузер сюда не ходит — схема ``analyzer`` НЕ экспонируется через PostgREST
    (миграция 0007), доступ только через Flask с ролевым гейтом.

Правила слоя:
  • psycopg (v3), подключение ленивое (импорт внутри connect) — модуль грузится
    даже без установленного драйвера, авто-регистрация пакета api не падает;
  • ВСЕ запросы параметризованы (%(name)s) — защита от инъекций;
  • функции возвращают простые dict/list (dict_row), без Flask-объектов;
  • подсчёт баллов сюда НЕ лезет — арифметика только в call_analyzer.scoring.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Iterable

logger = logging.getLogger('api.call_analysis_store')

# 9 канонических критериев рубрики (§8). Импорт из единого источника — не дублируем.
from call_analyzer.scoring import CRITERIA  # noqa: E402

CASINO_ID = 'default'                       # мультиказино пока не задействовано (0007)
CHECK_LEVELS = ('verbatim', 'meaning', 'none')
IMPORTANCE = ('critical', 'normal', 'minor')


class AnalyzerStoreError(RuntimeError):
    """Ошибка доступа к данным анализатора (нет DSN / драйвера / сбой запроса)."""


# ════════════════════════════════════════════════════════════════════════════
# Подключение
# ════════════════════════════════════════════════════════════════════════════
def _dsn() -> str:
    dsn = os.environ.get('SUPABASE_DB_URL', '').strip()
    if not dsn:
        raise AnalyzerStoreError('SUPABASE_DB_URL не задан — база анализатора недоступна')
    return dsn


def connect():
    """Ленивое psycopg-подключение с dict_row (строки — как dict).

    Контекст-менеджер psycopg коммитит транзакцию на выходе из ``with``.
    Импорт psycopg изолирован, чтобы отсутствие драйвера не ломало загрузку пакета.
    """
    try:
        import psycopg                       # noqa: PLC0415
        from psycopg.rows import dict_row     # noqa: PLC0415
    except ImportError as e:                  # pragma: no cover
        raise AnalyzerStoreError(
            "Драйвер 'psycopg' (v3) не установлен — чтение анализатора недоступно "
            "(pip install 'psycopg[binary]')."
        ) from e
    return psycopg.connect(_dsn(), row_factory=dict_row)


def _json(value: Any):
    """Обёртка значения для параметра jsonb-колонки (psycopg Json-адаптер)."""
    from psycopg.types.json import Json       # noqa: PLC0415
    return Json(value)


def _op_filter(alias: str, op_ids: list[str] | None, params: dict) -> str:
    """Фрагмент WHERE для ограничения по операторам (dept-scope / свои).

    ``op_ids is None`` → без ограничения (видно всех). Пустой список → никого
    (оператор без области видимости не получает чужих строк — fail-closed).
    """
    if op_ids is None:
        return ''
    params['op_ids'] = list(op_ids)
    return f' AND {alias}.operator_id = ANY(%(op_ids)s)'


# ════════════════════════════════════════════════════════════════════════════
# Настройки казино + состояние вердикта (§7, §10.13)
# ════════════════════════════════════════════════════════════════════════════
def get_settings(casino_id: str = CASINO_ID) -> dict:
    """Строка analyzer.settings (вердикт/пороги/config). Всегда есть (засеяна 0007)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT casino_id, verdict_unlocked, verdict_unlocked_by, verdict_unlocked_at, "
            "random_sample_per_day, min_review_time_s, config "
            "FROM analyzer.settings WHERE casino_id = %(cid)s",
            {'cid': casino_id})
        row = cur.fetchone()
    if row is None:
        # На случай незасеянной базы — безопасные дефолты (вердикт заблокирован).
        return {'casino_id': casino_id, 'verdict_unlocked': False,
                'random_sample_per_day': 2, 'min_review_time_s': 20, 'config': {}}
    return row


def config_int(settings: dict, key: str, default: int) -> int:
    """Целочисленный параметр из settings.config с фолбэком (пороги действий)."""
    cfg = settings.get('config') or {}
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def get_weights(settings: dict) -> dict[str, int]:
    """Боевые веса рубрики: settings.config.weights → иначе DEFAULT_WEIGHTS (scoring)."""
    from call_analyzer.scoring import DEFAULT_WEIGHTS   # noqa: PLC0415
    cfg = settings.get('config') or {}
    weights = cfg.get('weights')
    if isinstance(weights, dict) and weights:
        # оставляем только валидные критерии с числовыми весами
        clean = {k: int(v) for k, v in weights.items()
                 if k in CRITERIA and isinstance(v, (int, float))}
        if clean:
            return clean
    return dict(DEFAULT_WEIGHTS)


def update_settings(casino_id: str, random_sample_per_day: int | None,
                    min_review_time_s: int | None) -> dict:
    """Точечное обновление порогов/выборки (§10.13). Меняет только переданные поля."""
    sets, params = [], {'cid': casino_id}
    if random_sample_per_day is not None:
        sets.append('random_sample_per_day = %(rs)s')
        params['rs'] = int(random_sample_per_day)
    if min_review_time_s is not None:
        sets.append('min_review_time_s = %(mr)s')
        params['mr'] = int(min_review_time_s)
    if not sets:
        return get_settings(casino_id)
    sets.append('updated_at = now()')
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE analyzer.settings SET {', '.join(sets)} WHERE casino_id = %(cid)s",
            params)
    return get_settings(casino_id)


def unlock_verdict(casino_id: str, user_id: str | None) -> dict:
    """Разблокировать вердикт (§10.13): verdict_unlocked=true + кто/когда."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE analyzer.settings SET verdict_unlocked = true, "
            "verdict_unlocked_by = %(uid)s, verdict_unlocked_at = now(), updated_at = now() "
            "WHERE casino_id = %(cid)s",
            {'uid': user_id, 'cid': casino_id})
    return get_settings(casino_id)


# ════════════════════════════════════════════════════════════════════════════
# Область видимости (отдел главы / владение звонком)
# ════════════════════════════════════════════════════════════════════════════
def user_department(user_id: str | None) -> str | None:
    if not user_id:
        return None
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT department FROM crm.crm_users WHERE id = %(uid)s", {'uid': user_id})
        row = cur.fetchone()
    return row['department'] if row else None


def dept_operator_ids(user_id: str | None) -> list[str]:
    """UUID операторов ОТДЕЛА главы (head_department видит только свой отдел, §4).

    Пустой список, если отдел не задан — глава без отдела не видит чужих операторов.
    """
    dept = user_department(user_id)
    if not dept:
        return []
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM crm.crm_users "
            "WHERE department = %(dept)s AND department IS NOT NULL",
            {'dept': dept})
        rows = cur.fetchall()
    return [str(r['id']) for r in rows]


# ════════════════════════════════════════════════════════════════════════════
# Один звонок: базовые поля + аудит + транскрипт + сверка + сигнал + карточка
# ════════════════════════════════════════════════════════════════════════════
def get_call(call_id: str) -> dict | None:
    """Базовая строка analyzer.calls (для доступа/стрима/карточки)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT call_id, crm_call_id, casino_id, operator_id, casino_player_id, "
            "source, channels, audio_ref, started_at, ended_at, duration_s, snr, "
            "player_speech_ms, status, recommended_offer_id, flags "
            "FROM analyzer.calls WHERE call_id = %(id)s",
            {'id': call_id})
        return cur.fetchone()


def latest_audit(call_id: str) -> dict | None:
    """Последний аудит звонка (по created_at)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT audit_id, prompt_version, rubric_version, script_version, model_used, "
            "overall_score_100, pass_fail, dimensions, objections, compliance, offer_outcome, "
            "coaching_narrative, highlights, improvement_areas, needs_human, "
            "human_reviewed, human_override_score, human_reviewer_id, human_notes, created_at "
            "FROM analyzer.call_audits WHERE call_id = %(id)s "
            "ORDER BY created_at DESC LIMIT 1",
            {'id': call_id})
        return cur.fetchone()


def get_transcript(call_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT transcript_id, asr_provider, language, text_redacted, words, "
            "diarization_conf, translation_ru, translation_en, translation_verified, created_at "
            "FROM analyzer.transcripts WHERE call_id = %(id)s",
            {'id': call_id})
        return cur.fetchone()


def call_reviews(call_id: str) -> list[dict]:
    """История сверки по звонку (подтверждения/правки) — для карточки (§10.4)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT r.review_id, r.reviewer_id, r.kind, r.scores, r.reason, "
            "r.review_time_s, r.counted, r.was_random_sample, r.created_at, "
            "u.full_name AS reviewer_name "
            "FROM analyzer.audit_reviews r "
            "JOIN analyzer.call_audits a ON a.audit_id = r.audit_id "
            "LEFT JOIN crm.crm_users u ON u.id = r.reviewer_id "
            "WHERE a.call_id = %(id)s ORDER BY r.created_at DESC",
            {'id': call_id})
        return cur.fetchall()


def offer_signal(call_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT recommended_offer_id, offer_presented, player_response, "
            "alt_offer_worked, refusal_reason, callback_scheduled "
            "FROM analyzer.offer_signals WHERE call_id = %(id)s",
            {'id': call_id})
        return cur.fetchone()


def call_card(call_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT card_id, operator_id, tips, approved_by, approved_at, delivered_at, "
            "op_response, op_dispute_reason, responded_at "
            "FROM analyzer.coaching_cards WHERE call_id = %(id)s "
            "ORDER BY created_at DESC LIMIT 1",
            {'id': call_id})
        return cur.fetchone()


def log_access(actor_id: str | None, call_id: str | None, action: str) -> None:
    """Иммутабельная запись доступа (§4.1). Best-effort: сбой не роняет операцию."""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO analyzer.access_log (actor_id, call_id, action) "
                "VALUES (%(a)s, %(c)s, %(act)s)",
                {'a': actor_id, 'c': call_id, 'act': action})
    except Exception as e:                    # noqa: BLE001
        logger.warning('access_log write failed (%s %s): %s', action, call_id, e)


# ════════════════════════════════════════════════════════════════════════════
# Сверка: вставка подтверждения/правки, применение override (§7, §10.4)
# ════════════════════════════════════════════════════════════════════════════
def find_review(audit_id: str, reviewer_id: str | None, kind: str) -> dict | None:
    """Уже есть подтверждение этого ревьюера по этому аудиту? (идемпотентность confirm)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT review_id FROM analyzer.audit_reviews "
            "WHERE audit_id = %(aid)s AND reviewer_id = %(rid)s AND kind = %(kind)s "
            "ORDER BY created_at DESC LIMIT 1",
            {'aid': audit_id, 'rid': reviewer_id, 'kind': kind})
        return cur.fetchone()


def insert_review(audit_id: str, reviewer_id: str | None, kind: str,
                  scores: dict | None, reason: str | None, review_time_s: int,
                  counted: bool, was_random_sample: bool) -> str:
    """Точка данных сверки (§7). counted=false → в статистику согласия не идёт."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO analyzer.audit_reviews "
            "(audit_id, reviewer_id, kind, scores, reason, review_time_s, counted, was_random_sample) "
            "VALUES (%(aid)s, %(rid)s, %(kind)s, %(scores)s, %(reason)s, %(t)s, %(c)s, %(rand)s) "
            "RETURNING review_id",
            {'aid': audit_id, 'rid': reviewer_id, 'kind': kind,
             'scores': _json(scores) if scores is not None else None,
             'reason': reason, 't': review_time_s, 'c': counted, 'rand': was_random_sample})
        return str(cur.fetchone()['review_id'])


def apply_override(audit_id: str, call_id: str, human_score: int | None,
                   reviewer_id: str | None, notes: str | None) -> None:
    """Записать человеческое решение в call_audits + перевести звонок в completed (§10.4).

    История правок НЕ здесь (она в audit_reviews) — тут только «последнее решение».
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE analyzer.call_audits SET human_reviewed = true, "
            "human_override_score = %(score)s, human_reviewer_id = %(rid)s, human_notes = %(notes)s "
            "WHERE audit_id = %(aid)s",
            {'score': human_score, 'rid': reviewer_id, 'notes': notes, 'aid': audit_id})
        cur.execute(
            "UPDATE analyzer.calls SET status = 'completed', updated_at = now() "
            "WHERE call_id = %(cid)s AND status = 'needs_review'",
            {'cid': call_id})


# ════════════════════════════════════════════════════════════════════════════
# Обзор (§10.1) и общие агрегаты по звонкам/аудитам
# ════════════════════════════════════════════════════════════════════════════
def completed_audits(op_ids: list[str] | None, dt_from: datetime, dt_to: datetime) -> list[dict]:
    """Последний аудит каждого звонка за период (для агрегатов обзора/сводки/отчётов).

    Один звонок = один последний аудит (DISTINCT ON по created_at DESC).
    """
    params = {'f': dt_from, 't': dt_to}
    clause = _op_filter('c', op_ids, params)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (a.call_id) a.call_id, c.operator_id, "
            "a.overall_score_100 AS score, a.pass_fail, a.dimensions, a.compliance, "
            "a.offer_outcome, a.human_override_score, c.duration_s, c.flags, c.status, "
            "COALESCE(c.started_at, c.created_at) AS at "
            "FROM analyzer.calls c JOIN analyzer.call_audits a ON a.call_id = c.call_id "
            "WHERE COALESCE(c.started_at, c.created_at) >= %(f)s "
            "  AND COALESCE(c.started_at, c.created_at) < %(t)s" + clause + " "
            "ORDER BY a.call_id, a.created_at DESC",
            params)
        return cur.fetchall()


def call_status_counts(op_ids: list[str] | None, dt_from: datetime, dt_to: datetime) -> list[dict]:
    """Счётчики звонков по статусам на оператора за период (дозвоны/разобрано/очереди)."""
    params = {'f': dt_from, 't': dt_to}
    clause = _op_filter('c', op_ids, params)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.operator_id, count(*) AS total, "
            "count(*) FILTER (WHERE c.status = 'completed') AS analyzed, "
            "count(*) FILTER (WHERE c.status = 'needs_review') AS needs_review, "
            "count(*) FILTER (WHERE c.status = 'manual_review') AS manual_review, "
            "count(*) FILTER (WHERE c.status IN ('asr_failed','llm_failed','error')) AS failed "
            "FROM analyzer.calls c "
            "WHERE COALESCE(c.started_at, c.created_at) >= %(f)s "
            "  AND COALESCE(c.started_at, c.created_at) < %(t)s" + clause + " "
            "GROUP BY c.operator_id",
            params)
        return cur.fetchall()


def operator_names(op_ids: Iterable[str] | None = None) -> dict[str, str]:
    """{uuid: full_name} для подписи операторов в таблицах."""
    with connect() as conn, conn.cursor() as cur:
        if op_ids is None:
            cur.execute("SELECT id, full_name FROM crm.crm_users WHERE role IN "
                        "('operator','vip_manager')")
        else:
            ids = list(op_ids)
            if not ids:
                return {}
            cur.execute("SELECT id, full_name FROM crm.crm_users WHERE id = ANY(%(ids)s)",
                        {'ids': ids})
        return {str(r['id']): r['full_name'] for r in cur.fetchall()}


def review_rows(casino_id: str, dt_from: datetime | None = None,
                dt_to: datetime | None = None) -> list[dict]:
    """Сверочные записи + модельные баллы/критерии аудита (для согласия и дельт, §10.13).

    Возвращаем и counted=false тоже — фильтрацию по зачёту делает вызывающий,
    чтобы одна выборка обслуживала и «проверено», и «согласие».
    """
    params: dict = {'cid': casino_id}
    period = ''
    if dt_from is not None and dt_to is not None:
        period = " AND r.created_at >= %(f)s AND r.created_at < %(t)s"
        params['f'], params['t'] = dt_from, dt_to
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT r.review_id, r.kind, r.scores, r.counted, r.was_random_sample, "
            "a.call_id, a.overall_score_100 AS model_score, a.dimensions AS model_dims "
            "FROM analyzer.audit_reviews r "
            "JOIN analyzer.call_audits a ON a.audit_id = r.audit_id "
            "JOIN analyzer.calls c ON c.call_id = a.call_id "
            "WHERE c.casino_id = %(cid)s" + period,
            params)
        return cur.fetchall()


def translation_verified_count(casino_id: str) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM analyzer.transcripts t "
            "JOIN analyzer.calls c ON c.call_id = t.call_id "
            "WHERE c.casino_id = %(cid)s AND t.translation_verified = true",
            {'cid': casino_id})
        return int(cur.fetchone()['n'])


def cards_pending_approve(op_ids: list[str] | None) -> int:
    """Карточки, ждущие апрува руководителя (approved_at IS NULL)."""
    params: dict = {}
    clause = _op_filter('coaching_cards', op_ids, params) if op_ids is not None else ''
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM analyzer.coaching_cards "
            "WHERE approved_at IS NULL" + clause, params)
        return int(cur.fetchone()['n'])


def cards_disputed(op_ids: list[str] | None) -> list[dict]:
    """Оспоренные оператором карточки (op_response='disputed') — в очередь руководителю."""
    params: dict = {}
    clause = _op_filter('cc', op_ids, params)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT cc.card_id, cc.call_id, cc.operator_id, cc.op_dispute_reason, "
            "cc.responded_at, u.full_name AS operator_name "
            "FROM analyzer.coaching_cards cc "
            "LEFT JOIN crm.crm_users u ON u.id = cc.operator_id "
            "WHERE cc.op_response = 'disputed'" + clause + " "
            "ORDER BY cc.responded_at DESC NULLS LAST",
            params)
        return cur.fetchall()


def never_called_counts(op_ids: list[str] | None, overdue_days: int) -> list[dict]:
    """«Не набирали»: игрок назначен, 0 звонков (crm.calls), срок вышел — на оператора.

    Порога-дедлайна в схеме нет: «срок вышел» = назначение старше overdue_days
    без единого звонка (эвристика, порог настраивается в settings.config).
    """
    params = {'days': overdue_days}
    clause = _op_filter('a', op_ids, params)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT a.operator_id, count(*) AS n FROM crm.player_assignments a "
            "WHERE a.created_at < now() - make_interval(days => %(days)s) "
            "  AND NOT EXISTS (SELECT 1 FROM crm.calls k "
            "                  WHERE k.casino_player_id = a.casino_player_id "
            "                    AND k.operator_id = a.operator_id)" + clause + " "
            "GROUP BY a.operator_id",
            params)
        return cur.fetchall()


# ════════════════════════════════════════════════════════════════════════════
# Очередь проверки (§10.2)
# ════════════════════════════════════════════════════════════════════════════
def queue_calls(op_ids: list[str] | None) -> list[dict]:
    """Звонки, требующие внимания: needs_review/manual_review/asr_failed/llm_failed
    + любой звонок с флагами подлинности/случайной проверкой (§10.2, §11.4)."""
    params: dict = {}
    clause = _op_filter('c', op_ids, params)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.call_id, c.operator_id, c.casino_player_id, c.status, c.flags, "
            "c.duration_s, COALESCE(c.started_at, c.created_at) AS at, "
            "a.overall_score_100 AS score, a.pass_fail, a.needs_human, "
            "u.full_name AS operator_name "
            "FROM analyzer.calls c "
            "LEFT JOIN LATERAL (SELECT overall_score_100, pass_fail, needs_human "
            "                   FROM analyzer.call_audits WHERE call_id = c.call_id "
            "                   ORDER BY created_at DESC LIMIT 1) a ON true "
            "LEFT JOIN crm.crm_users u ON u.id = c.operator_id "
            "WHERE (c.status IN ('needs_review','manual_review','asr_failed','llm_failed') "
            "       OR jsonb_array_length(c.flags) > 0)" + clause + " "
            "ORDER BY at DESC",
            params)
        return cur.fetchall()


# ════════════════════════════════════════════════════════════════════════════
# Отчёт по оператору (§10.5)
# ════════════════════════════════════════════════════════════════════════════
def operator_weekly_scores(op_id: str, dt_from: datetime, dt_to: datetime) -> list[dict]:
    """Средний балл оператора по неделям (для графика перелома, §10.5)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT date_trunc('week', COALESCE(c.started_at, c.created_at)) AS week, "
            "round(avg(a.overall_score_100))::int AS avg_score, count(*) AS n "
            "FROM analyzer.calls c JOIN analyzer.call_audits a ON a.call_id = c.call_id "
            "WHERE c.operator_id = %(op)s AND a.overall_score_100 IS NOT NULL "
            "  AND COALESCE(c.started_at, c.created_at) >= %(f)s "
            "  AND COALESCE(c.started_at, c.created_at) < %(t)s "
            "GROUP BY week ORDER BY week",
            {'op': op_id, 'f': dt_from, 't': dt_to})
        return cur.fetchall()


def operator_worst_calls(op_id: str, dt_from: datetime, dt_to: datetime,
                         limit: int = 5) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (a.call_id) a.call_id, a.overall_score_100 AS score, "
            "a.offer_outcome, c.duration_s, COALESCE(c.started_at, c.created_at) AS at "
            "FROM analyzer.calls c JOIN analyzer.call_audits a ON a.call_id = c.call_id "
            "WHERE c.operator_id = %(op)s AND a.overall_score_100 IS NOT NULL "
            "  AND COALESCE(c.started_at, c.created_at) >= %(f)s "
            "  AND COALESCE(c.started_at, c.created_at) < %(t)s "
            "ORDER BY a.call_id, a.created_at DESC",
            {'op': op_id, 'f': dt_from, 't': dt_to})
        rows = cur.fetchall()
    rows.sort(key=lambda r: (r['score'] if r['score'] is not None else 999))
    return rows[:limit]


def script_activations(casino_id: str, dt_from: datetime, dt_to: datetime) -> list[dict]:
    """Даты ввода версий скрипта в бой (обязательная отметка на графике, §10.5)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT version, activated_at FROM analyzer.script_versions "
            "WHERE casino_id = %(cid)s AND activated_at IS NOT NULL "
            "  AND activated_at >= %(f)s AND activated_at < %(t)s "
            "ORDER BY activated_at",
            {'cid': casino_id, 'f': dt_from, 't': dt_to})
        return cur.fetchall()


# ════════════════════════════════════════════════════════════════════════════
# Мои звонки / коуч-карточки (§10.10)
# ════════════════════════════════════════════════════════════════════════════
def operator_cards(op_id: str, only_approved: bool) -> list[dict]:
    """Карточки оператора. only_approved → лишь approved_at IS NOT NULL (вердикт заблокирован)."""
    approved = ' AND cc.approved_at IS NOT NULL' if only_approved else ''
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT cc.card_id, cc.call_id, cc.tips, cc.approved_at, cc.delivered_at, "
            "cc.op_response, cc.op_dispute_reason, cc.responded_at, cc.created_at, "
            "c.casino_player_id, c.duration_s "
            "FROM analyzer.coaching_cards cc "
            "JOIN analyzer.calls c ON c.call_id = cc.call_id "
            "WHERE cc.operator_id = %(op)s" + approved + " "
            "ORDER BY cc.created_at DESC",
            {'op': op_id})
        return cur.fetchall()


def operator_recent_calls(op_id: str, include_scores: bool, limit: int = 20) -> list[dict]:
    """«Son aramalar»: последние звонки оператора; баллы — только при разблок. вердикте."""
    score_col = ("(SELECT overall_score_100 FROM analyzer.call_audits "
                 "WHERE call_id = c.call_id ORDER BY created_at DESC LIMIT 1)"
                 if include_scores else "NULL")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT c.call_id, c.casino_player_id, c.duration_s, "
            f"COALESCE(c.started_at, c.created_at) AS at, {score_col} AS score "
            "FROM analyzer.calls c WHERE c.operator_id = %(op)s "
            "ORDER BY at DESC LIMIT %(lim)s",
            {'op': op_id, 'lim': limit})
        return cur.fetchall()


def get_card_for_operator(card_id: str, op_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT card_id, operator_id, approved_at, delivered_at, op_response "
            "FROM analyzer.coaching_cards WHERE card_id = %(id)s AND operator_id = %(op)s",
            {'id': card_id, 'op': op_id})
        return cur.fetchone()


def mark_card_delivered(card_id: str) -> None:
    """Пометить первое прочтение оператором (delivered_at) — замыкает фидбек-луп (§10.10)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE analyzer.coaching_cards SET delivered_at = now() "
            "WHERE card_id = %(id)s AND delivered_at IS NULL",
            {'id': card_id})


def respond_card(card_id: str, op_id: str, response: str, reason: str | None) -> bool:
    """Ответ оператора на карточку (acknowledged|disputed). True, если карточка найдена."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE analyzer.coaching_cards SET op_response = %(resp)s, "
            "op_dispute_reason = %(reason)s, responded_at = now() "
            "WHERE card_id = %(id)s AND operator_id = %(op)s RETURNING card_id",
            {'resp': response, 'reason': reason, 'id': card_id, 'op': op_id})
        return cur.fetchone() is not None


def get_card(card_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT cc.card_id, cc.operator_id, cc.approved_at "
            "FROM analyzer.coaching_cards cc WHERE cc.card_id = %(id)s",
            {'id': card_id})
        return cur.fetchone()


def card_operator_dept(card_id: str) -> str | None:
    """Отдел оператора карточки — для dept-scope апрува главой отдела."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT u.department FROM analyzer.coaching_cards cc "
            "JOIN crm.crm_users u ON u.id = cc.operator_id WHERE cc.card_id = %(id)s",
            {'id': card_id})
        row = cur.fetchone()
    return row['department'] if row else None


def approve_card(card_id: str, approver_id: str | None) -> bool:
    """Руководитель апрувит карточку (approved_by/approved_at). True, если найдена."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE analyzer.coaching_cards SET approved_by = %(who)s, approved_at = now() "
            "WHERE card_id = %(id)s AND approved_at IS NULL RETURNING card_id",
            {'who': approver_id, 'id': card_id})
        return cur.fetchone() is not None


# ════════════════════════════════════════════════════════════════════════════
# Покрытие обзвона (§10.7) и сводка владельцу (§10.12) — из CRM/звонилки
# ════════════════════════════════════════════════════════════════════════════
def coverage(op_ids: list[str] | None, dt_from: datetime, dt_to: datetime,
             overdue_days: int) -> list[dict]:
    """Покрытие на оператора: назначено / попытки / дозвоны / разговоры / не набирали / на проверке.

    Разговор = crm.calls.result задан ИЛИ у связанного analyzer.call player_speech_ms>0.
    Учёт идёт по факту звонков (crm.calls), а не по выгрузке базы (§10.7).
    """
    params = {'f': dt_from, 't': dt_to, 'days': overdue_days}
    ac = _op_filter('a', op_ids, params)      # назначения
    kc = _op_filter('k', op_ids, params)      # звонки
    cc = _op_filter('c', op_ids, params)      # анализатор
    with connect() as conn, conn.cursor() as cur:
        # назначено + не набирали, на оператора
        cur.execute(
            "SELECT a.operator_id, count(*) AS assigned, "
            "count(*) FILTER (WHERE a.created_at < now() - make_interval(days => %(days)s) "
            "  AND NOT EXISTS (SELECT 1 FROM crm.calls k2 "
            "     WHERE k2.casino_player_id = a.casino_player_id "
            "       AND k2.operator_id = a.operator_id)) AS never_called "
            "FROM crm.player_assignments a WHERE true" + ac + " GROUP BY a.operator_id",
            params)
        assigned = {str(r['operator_id']): r for r in cur.fetchall()}

        # попытки / дозвоны / разговоры за период, на оператора
        cur.execute(
            "SELECT k.operator_id, count(*) AS attempts, "
            "count(*) FILTER (WHERE k.outcome = 'answered') AS connected, "
            "count(*) FILTER (WHERE k.result IS NOT NULL OR EXISTS ("
            "   SELECT 1 FROM analyzer.calls ac WHERE ac.crm_call_id = k.id "
            "     AND ac.player_speech_ms > 0)) AS talks "
            "FROM crm.calls k WHERE k.started_at >= %(f)s AND k.started_at < %(t)s" + kc + " "
            "GROUP BY k.operator_id",
            params)
        calls = {str(r['operator_id']): r for r in cur.fetchall()}

        # на проверке (analyzer needs_review) за период, на оператора
        cur.execute(
            "SELECT c.operator_id, count(*) AS in_review FROM analyzer.calls c "
            "WHERE c.status = 'needs_review' "
            "  AND COALESCE(c.started_at, c.created_at) >= %(f)s "
            "  AND COALESCE(c.started_at, c.created_at) < %(t)s" + cc + " "
            "GROUP BY c.operator_id",
            params)
        review = {str(r['operator_id']): r for r in cur.fetchall()}

    ops = set(assigned) | set(calls) | set(review)
    out = []
    for op in ops:
        a = assigned.get(op, {})
        k = calls.get(op, {})
        out.append({
            'operator_id': op,
            'assigned': int(a.get('assigned') or 0),
            'never_called': int(a.get('never_called') or 0),
            'attempts': int(k.get('attempts') or 0),
            'connected': int(k.get('connected') or 0),
            'talks': int(k.get('talks') or 0),
            'in_review': int(review.get(op, {}).get('in_review') or 0),
        })
    return out


def dialing_facts(dt_from: datetime, dt_to: datetime) -> dict:
    """Факты обзвона за период для сводки владельцу (§10.12): база/попытки/дозвоны/разговоры/не набирали.

    Приходят из звонилки (crm.calls) и назначений (crm.player_assignments), от модели
    и сверки НЕ зависят — поэтому владелец видит их и при заблокированном вердикте.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT casino_player_id) AS assigned FROM crm.player_assignments")
        assigned = int(cur.fetchone()['assigned'])
        cur.execute(
            "SELECT count(*) AS attempts, "
            "count(*) FILTER (WHERE outcome = 'answered') AS connected, "
            "count(*) FILTER (WHERE result IS NOT NULL OR EXISTS ("
            "  SELECT 1 FROM analyzer.calls ac WHERE ac.crm_call_id = crm.calls.id "
            "    AND ac.player_speech_ms > 0)) AS talks "
            "FROM crm.calls WHERE started_at >= %(f)s AND started_at < %(t)s",
            {'f': dt_from, 't': dt_to})
        r = cur.fetchone()
        cur.execute(
            "SELECT count(*) AS never_called FROM crm.player_assignments a "
            "WHERE NOT EXISTS (SELECT 1 FROM crm.calls k "
            "  WHERE k.casino_player_id = a.casino_player_id AND k.operator_id = a.operator_id)")
        never = int(cur.fetchone()['never_called'])
    return {'assigned': assigned, 'attempts': int(r['attempts']),
            'connected': int(r['connected']), 'talks': int(r['talks']),
            'never_called': never}


# ════════════════════════════════════════════════════════════════════════════
# Что работает (§10.6) — ранжирование по принятым офферам, приёмы по шагам
# ════════════════════════════════════════════════════════════════════════════
def offer_acceptance(dt_from: datetime, dt_to: datetime) -> list[dict]:
    """На оператора: предложено офферов / принято (offer_signals) за период (§10.6)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.operator_id, count(*) FILTER (WHERE s.offer_presented) AS presented, "
            "count(*) FILTER (WHERE s.player_response = 'accepted') AS accepted, "
            "count(*) AS signals "
            "FROM analyzer.offer_signals s JOIN analyzer.calls c ON c.call_id = s.call_id "
            "WHERE COALESCE(c.started_at, c.created_at) >= %(f)s "
            "  AND COALESCE(c.started_at, c.created_at) < %(t)s "
            "GROUP BY c.operator_id",
            {'f': dt_from, 't': dt_to})
        return cur.fetchall()


def step_audits(dt_from: datetime, dt_to: datetime) -> list[dict]:
    """Последний аудит каждого звонка за период + транскрипт (для приёмов по шагам, §10.6).

    Тяжеловат по объёму, но выборка ограничена периодом; агрегирование — в ручке.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (a.call_id) a.call_id, c.operator_id, a.dimensions, "
            "a.offer_outcome, t.words, t.language, t.translation_ru, t.translation_en "
            "FROM analyzer.calls c JOIN analyzer.call_audits a ON a.call_id = c.call_id "
            "LEFT JOIN analyzer.transcripts t ON t.call_id = c.call_id "
            "WHERE COALESCE(c.started_at, c.created_at) >= %(f)s "
            "  AND COALESCE(c.started_at, c.created_at) < %(t)s "
            "ORDER BY a.call_id, a.created_at DESC",
            {'f': dt_from, 't': dt_to})
        return cur.fetchall()


# ════════════════════════════════════════════════════════════════════════════
# Скрипт (§10.8/§10.9) — версии, черновик, ввод в бой, прогон на прошлых
# ════════════════════════════════════════════════════════════════════════════
# _grp() — фрагмент WHERE «эта группа ИЛИ казино-дефолт»: group_id IS NULL
# сравнивается через IS, а не =, поэтому обрабатываем отдельно.
def _grp_where(group_id: str | None, params: dict) -> str:
    if group_id is None:
        return ' AND group_id IS NULL'
    params['gid'] = group_id
    return ' AND group_id = %(gid)s'


def _resolve_ref(cur, casino_id: str, script_ref: str | None) -> str | None:
    """script_ref как есть, либо дефолт казино (0011). None → скриптов ещё нет."""
    if script_ref:
        return script_ref
    cur.execute("SELECT script_ref FROM analyzer.casino_default_script WHERE casino_id = %(cid)s",
                {'cid': casino_id})
    row = cur.fetchone()
    return str(row['script_ref']) if row else None


_SV_COLS = ("script_id, version, status, blocks, group_id, script_ref, "
            "activated_at, created_by, created_at")


def active_script(casino_id: str, script_ref: str | None = None) -> dict | None:
    """Активная версия скрипта (script_ref=None → скрипт казино по умолчанию)."""
    with connect() as conn, conn.cursor() as cur:
        ref = _resolve_ref(cur, casino_id, script_ref)
        if ref is None:   # легаси до 0011: дефолтный поток group_id IS NULL
            cur.execute(f"SELECT {_SV_COLS} FROM analyzer.script_versions "
                        "WHERE casino_id = %(cid)s AND status = 'active' AND group_id IS NULL "
                        "ORDER BY version DESC LIMIT 1", {'cid': casino_id})
            return cur.fetchone()
        cur.execute(f"SELECT {_SV_COLS} FROM analyzer.script_versions "
                    "WHERE script_ref = %(r)s AND status = 'active' LIMIT 1", {'r': ref})
        return cur.fetchone()


def active_script_by_version(casino_id: str, version: int) -> dict | None:
    """Активный скрипт по номеру версии (оператору — та версия, что резолвнулась
    для него по группе; §10.9, только чтение)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT script_id, version, status, blocks, group_id, activated_at, created_at "
            "FROM analyzer.script_versions WHERE casino_id = %(cid)s AND version = %(v)s "
            "AND status = 'active' LIMIT 1",
            {'cid': casino_id, 'v': version})
        return cur.fetchone()


def draft_script(casino_id: str, script_ref: str | None = None) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        ref = _resolve_ref(cur, casino_id, script_ref)
        if ref is None:   # легаси до 0011
            cur.execute(f"SELECT {_SV_COLS} FROM analyzer.script_versions "
                        "WHERE casino_id = %(cid)s AND status = 'draft' AND group_id IS NULL "
                        "ORDER BY created_at DESC LIMIT 1", {'cid': casino_id})
            return cur.fetchone()
        cur.execute(f"SELECT {_SV_COLS} FROM analyzer.script_versions "
                    "WHERE script_ref = %(r)s AND status = 'draft' "
                    "ORDER BY created_at DESC LIMIT 1", {'r': ref})
        return cur.fetchone()


def save_draft(casino_id: str, blocks: list, user_id: str | None,
               script_ref: str | None = None) -> str:
    """Сохранить черновик (§10.8). Один черновик на СКРИПТ: старый draft удаляем.
    script_ref=None → дефолт казино; если скриптов ещё нет вообще — создаём
    «Основной» и назначаем дефолтом (плавный переход со старой модели)."""
    with connect() as conn, conn.cursor() as cur:
        ref = _resolve_ref(cur, casino_id, script_ref)
        if ref is None:
            cur.execute("INSERT INTO analyzer.scripts (casino_id, name, created_by) "
                        "VALUES (%(cid)s, 'Основной', %(uid)s) "
                        "ON CONFLICT (casino_id, name) DO UPDATE SET name = EXCLUDED.name "
                        "RETURNING script_ref", {'cid': casino_id, 'uid': user_id})
            ref = str(cur.fetchone()['script_ref'])
            cur.execute("INSERT INTO analyzer.casino_default_script (casino_id, script_ref) "
                        "VALUES (%(cid)s, %(r)s) ON CONFLICT (casino_id) DO NOTHING",
                        {'cid': casino_id, 'r': ref})
        cur.execute("DELETE FROM analyzer.script_versions "
                    "WHERE script_ref = %(r)s AND status = 'draft'", {'r': ref})
        cur.execute(
            "INSERT INTO analyzer.script_versions "
            "(casino_id, version, status, blocks, script_ref, created_by) "
            "VALUES (%(cid)s, NULL, 'draft', %(blocks)s, %(r)s, %(uid)s) RETURNING script_id",
            {'cid': casino_id, 'blocks': _json(blocks), 'r': ref, 'uid': user_id})
        return str(cur.fetchone()['script_id'])


def activate_draft(casino_id: str, script_ref: str | None = None) -> int | None:
    """Ввести черновик скрипта в бой (§10.8): version=max+1 (глобально по казино —
    номера уникальны, скрипт их различает), status=active, старую активную ЭТОГО
    скрипта → archived. Возвращает новый номер версии; None, если черновика нет."""
    with connect() as conn, conn.cursor() as cur:
        ref = _resolve_ref(cur, casino_id, script_ref)
        if ref is None:
            return None
        cur.execute("SELECT script_id FROM analyzer.script_versions "
                    "WHERE script_ref = %(r)s AND status = 'draft' "
                    "ORDER BY created_at DESC LIMIT 1", {'r': ref})
        draft = cur.fetchone()
        if not draft:
            return None
        cur.execute("SELECT COALESCE(MAX(version), 0) AS mx FROM analyzer.script_versions "
                    "WHERE casino_id = %(cid)s", {'cid': casino_id})
        new_version = int(cur.fetchone()['mx']) + 1
        cur.execute("UPDATE analyzer.script_versions SET status = 'archived' "
                    "WHERE script_ref = %(r)s AND status = 'active'", {'r': ref})
        cur.execute(
            "UPDATE analyzer.script_versions SET status = 'active', version = %(v)s, "
            "activated_at = now() WHERE script_id = %(sid)s",
            {'v': new_version, 'sid': draft['script_id']})
        return new_version


# ── Реестр именованных скриптов (0011) ───────────────────────────────────────
def list_scripts(casino_id: str) -> list[dict]:
    """Все именованные скрипты: активная версия, черновик, дефолт, кому назначен."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT s.script_ref, s.name, s.created_at,
                      (SELECT version FROM analyzer.script_versions v
                       WHERE v.script_ref = s.script_ref AND v.status = 'active') AS active_version,
                      EXISTS (SELECT 1 FROM analyzer.script_versions v
                              WHERE v.script_ref = s.script_ref AND v.status = 'draft') AS has_draft,
                      (d.script_ref IS NOT NULL) AS is_default,
                      ARRAY(SELECT g.name FROM analyzer.script_groups g
                            WHERE g.script_ref = s.script_ref ORDER BY g.name) AS groups
               FROM analyzer.scripts s
               LEFT JOIN analyzer.casino_default_script d
                      ON d.casino_id = s.casino_id AND d.script_ref = s.script_ref
               WHERE s.casino_id = %(cid)s AND NOT s.archived ORDER BY s.created_at""",
            {'cid': casino_id})
        return [dict(r) for r in cur.fetchall()]


def create_script(casino_id: str, name: str, user_id: str | None) -> str | None:
    """Создать именованный скрипт. None = имя занято. Первый скрипт казино
    автоматически становится дефолтом (иначе резолв операторов пустой)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO analyzer.scripts (casino_id, name, created_by) "
                    "VALUES (%(cid)s, %(name)s, %(uid)s) "
                    "ON CONFLICT (casino_id, name) DO NOTHING RETURNING script_ref",
                    {'cid': casino_id, 'name': name.strip()[:120], 'uid': user_id})
        row = cur.fetchone()
        if not row:
            return None
        ref = str(row['script_ref'])
        cur.execute("INSERT INTO analyzer.casino_default_script (casino_id, script_ref) "
                    "VALUES (%(cid)s, %(r)s) ON CONFLICT (casino_id) DO NOTHING",
                    {'cid': casino_id, 'r': ref})
        return ref


def script_by_ref(casino_id: str, script_ref: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT script_ref, name FROM analyzer.scripts "
                    "WHERE casino_id = %(cid)s AND script_ref = %(r)s",
                    {'cid': casino_id, 'r': script_ref})
        row = cur.fetchone()
        return {'script_ref': str(row['script_ref']), 'name': row['name']} if row else None


def default_script_ref(casino_id: str) -> str | None:
    with connect() as conn, conn.cursor() as cur:
        return _resolve_ref(cur, casino_id, None)


def set_default_script(casino_id: str, script_ref: str) -> None:
    """Назначить скрипт казино по умолчанию (кто не в группах — получает его)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO analyzer.casino_default_script (casino_id, script_ref) "
                    "VALUES (%(cid)s, %(r)s) "
                    "ON CONFLICT (casino_id) DO UPDATE SET script_ref = EXCLUDED.script_ref, "
                    "updated_at = now()", {'cid': casino_id, 'r': script_ref})


def assign_group_script(group_id: str, script_ref: str | None) -> None:
    """«Какой скрипт идёт этой группе»: NULL → группа наследует дефолт казино."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE analyzer.script_groups SET script_ref = %(r)s "
                    "WHERE group_id = %(g)s", {'r': script_ref, 'g': group_id})


def group_script_ref(group_id: str) -> str | None:
    """Скрипт, назначенный группе (легаси-маппинг group_id→script_ref в API)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT script_ref FROM analyzer.script_groups WHERE group_id = %(g)s",
                    {'g': group_id})
        row = cur.fetchone()
        return str(row['script_ref']) if row and row['script_ref'] else None


def rename_script(casino_id: str, script_ref: str, name: str) -> bool:
    """Переименовать скрипт. False = имя занято (уникальность по казино)."""
    with connect() as conn, conn.cursor() as cur:
        try:
            cur.execute("UPDATE analyzer.scripts SET name = %(n)s "
                        "WHERE casino_id = %(cid)s AND script_ref = %(r)s",
                        {'n': name.strip()[:120], 'cid': casino_id, 'r': script_ref})
            return cur.rowcount > 0
        except Exception:   # UniqueViolation — имя занято
            conn.rollback()
            return False


def duplicate_script(casino_id: str, script_ref: str, name: str,
                     user_id: str | None) -> str | None:
    """«Создать на основе»: новый скрипт + копия блоков (черновик, если есть,
    иначе активная версия) его ЧЕРНОВИКОМ. None = имя занято/исходник не найден."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT blocks FROM analyzer.script_versions "
                    "WHERE script_ref = %(r)s AND status IN ('draft', 'active') "
                    "ORDER BY status = 'draft' DESC, created_at DESC LIMIT 1", {'r': script_ref})
        src = cur.fetchone()
        cur.execute("INSERT INTO analyzer.scripts (casino_id, name, created_by) "
                    "VALUES (%(cid)s, %(n)s, %(uid)s) "
                    "ON CONFLICT (casino_id, name) DO NOTHING RETURNING script_ref",
                    {'cid': casino_id, 'n': name.strip()[:120], 'uid': user_id})
        row = cur.fetchone()
        if not row:
            return None
        new_ref = str(row['script_ref'])
        if src and src['blocks']:
            cur.execute(
                "INSERT INTO analyzer.script_versions "
                "(casino_id, version, status, blocks, script_ref, created_by) "
                "VALUES (%(cid)s, NULL, 'draft', %(b)s, %(r)s, %(uid)s)",
                {'cid': casino_id, 'b': _json(src['blocks']), 'r': new_ref, 'uid': user_id})
        return new_ref


def archive_script(casino_id: str, script_ref: str) -> str | None:
    """Архив (не удаление — версии остаются в статистике). Возвращает код ошибки:
    'default' — скрипт назначен дефолтом казино; 'assigned' — назначен группе;
    'not_found'; None = заархивирован."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM analyzer.casino_default_script "
                    "WHERE casino_id = %(cid)s AND script_ref = %(r)s",
                    {'cid': casino_id, 'r': script_ref})
        if cur.fetchone():
            return 'default'
        cur.execute("SELECT 1 FROM analyzer.script_groups WHERE script_ref = %(r)s LIMIT 1",
                    {'r': script_ref})
        if cur.fetchone():
            return 'assigned'
        cur.execute("UPDATE analyzer.scripts SET archived = true "
                    "WHERE casino_id = %(cid)s AND script_ref = %(r)s AND NOT archived",
                    {'cid': casino_id, 'r': script_ref})
        return None if cur.rowcount else 'not_found'



# ── A/B-группы: CRUD + резолв «оператор → активный скрипт» ────────────────────
def resolve_script_version(casino_id: str, operator_id: str | None) -> int | None:
    """Активная версия скрипта для оператора звонка (для audit.script_version).

    0011: оператор в группе → скрипт, НАЗНАЧЕННЫЙ группе (script_ref); у группы
    нет назначения / оператор без группы → скрипт казино по умолчанию
    (casino_default_script). Легаси-фолбэк (до бэкфилла) — старый путь по
    group_id. Это же делает A/B работающим: звонок падает под версию СВОЕЙ группы.
    """
    with connect() as conn, conn.cursor() as cur:
        gid, gref = None, None
        if operator_id:
            cur.execute("SELECT m.group_id, g.script_ref FROM analyzer.script_group_members m "
                        "JOIN analyzer.script_groups g ON g.group_id = m.group_id "
                        "WHERE m.operator_id = %(op)s", {'op': operator_id})
            row = cur.fetchone()
            if row:
                gid = row['group_id']
                gref = str(row['script_ref']) if row['script_ref'] else None
        # новая модель: скрипт группы → дефолт казино
        for ref in filter(None, [gref, _resolve_ref(cur, casino_id, None)]):
            cur.execute("SELECT version FROM analyzer.script_versions "
                        "WHERE script_ref = %(r)s AND status = 'active' LIMIT 1", {'r': ref})
            row = cur.fetchone()
            if row and row['version'] is not None:
                return int(row['version'])
        # легаси до 0011: активная версия потока группы → потока казино (group_id IS NULL)
        for g in ([gid, None] if gid else [None]):
            params = {'cid': casino_id}
            cur.execute("SELECT version FROM analyzer.script_versions "
                        "WHERE casino_id = %(cid)s AND status = 'active' AND script_ref IS NULL"
                        + _grp_where(str(g) if g else None, params)
                        + " ORDER BY version DESC LIMIT 1", params)
            row = cur.fetchone()
            if row and row['version'] is not None:
                return int(row['version'])
        return None


def create_script_group(casino_id: str, name: str, user_id: str | None) -> str:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO analyzer.script_groups (casino_id, name, created_by) "
                    "VALUES (%(cid)s, %(name)s, %(uid)s) RETURNING group_id",
                    {'cid': casino_id, 'name': name.strip()[:120], 'uid': user_id})
        return str(cur.fetchone()['group_id'])


def delete_script_group(group_id: str) -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM analyzer.script_groups WHERE group_id = %(g)s RETURNING group_id",
                    {'g': group_id})
        return cur.fetchone() is not None


def list_script_groups(casino_id: str) -> list[dict]:
    """Группы + число операторов + активная версия скрипта каждой."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT g.group_id, g.name, g.created_at, g.script_ref,
                      sc.name AS script_name,
                      COUNT(DISTINCT m.operator_id) AS members,
                      (SELECT version FROM analyzer.script_versions v
                       WHERE v.script_ref = COALESCE(g.script_ref, d.script_ref)
                         AND v.status = 'active' LIMIT 1) AS active_version
               FROM analyzer.script_groups g
               LEFT JOIN analyzer.scripts sc ON sc.script_ref = g.script_ref
               LEFT JOIN analyzer.casino_default_script d ON d.casino_id = g.casino_id
               LEFT JOIN analyzer.script_group_members m ON m.group_id = g.group_id
               WHERE g.casino_id = %(cid)s
               GROUP BY g.group_id, g.name, g.created_at, g.script_ref, sc.name, d.script_ref
               ORDER BY g.created_at""",
            {'cid': casino_id})
        return [{**dict(r), 'script_ref': str(r['script_ref']) if r['script_ref'] else None}
                for r in cur.fetchall()]


def group_members(group_id: str) -> list[dict]:
    """Операторы группы с именами (crm.crm_users)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT m.operator_id, u.full_name, u.department::text AS department
               FROM analyzer.script_group_members m
               LEFT JOIN crm.crm_users u ON u.id = m.operator_id
               WHERE m.group_id = %(g)s ORDER BY u.full_name""",
            {'g': group_id})
        return [dict(r) for r in cur.fetchall()]


def ungrouped_operators(casino_id: str) -> list[dict]:
    """Операторы (роли operator/vip_manager), НЕ состоящие ни в одной группе —
    кандидаты на назначение. casino_id пока один (мультиказино не задействовано)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT u.id AS operator_id, u.full_name, u.department::text AS department
               FROM crm.crm_users u
               WHERE u.role IN ('operator','vip_manager') AND u.is_active
                 AND u.id NOT IN (SELECT operator_id FROM analyzer.script_group_members)
               ORDER BY u.full_name""")
        return [{'operator_id': str(r['operator_id']), 'name': r['full_name'],
                 'department': r['department']} for r in cur.fetchall()]


def set_operator_group(operator_id: str, group_id: str | None) -> None:
    """Назначить оператора в группу (оператор в одной группе — PK на operator_id).
    group_id=None → убрать из групп."""
    with connect() as conn, conn.cursor() as cur:
        if group_id is None:
            cur.execute("DELETE FROM analyzer.script_group_members WHERE operator_id = %(op)s",
                        {'op': operator_id})
        else:
            cur.execute(
                "INSERT INTO analyzer.script_group_members (operator_id, group_id) "
                "VALUES (%(op)s, %(g)s) "
                "ON CONFLICT (operator_id) DO UPDATE SET group_id = EXCLUDED.group_id, added_at = now()",
                {'op': operator_id, 'g': group_id})


def last_completed_dimensions(casino_id: str, limit: int = 20) -> list[dict]:
    """Последние N разобранных звонков: dimensions + текущий балл — для прогона черновика (§10.8).

    Эфемерный пересчёт делает ручка (в базу не пишет).
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (a.call_id) a.call_id, a.dimensions, "
            "a.overall_score_100 AS current_score, COALESCE(c.started_at, c.created_at) AS at "
            "FROM analyzer.calls c JOIN analyzer.call_audits a ON a.call_id = c.call_id "
            "WHERE c.casino_id = %(cid)s AND c.status = 'completed' "
            "ORDER BY a.call_id, a.created_at DESC",
            {'cid': casino_id})
        rows = cur.fetchall()
    rows.sort(key=lambda r: (r['at'] is None, r['at']), reverse=True)
    return rows[:limit]


# ════════════════════════════════════════════════════════════════════════════
# Проверка перевода (§10.11)
# ════════════════════════════════════════════════════════════════════════════
def next_unverified_translation(casino_id: str) -> dict | None:
    """Следующий звонок с непроверенным переводом: транскрипт TR + audio_ref (§10.11)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.call_id, c.audio_ref, c.duration_s, c.casino_player_id, "
            "t.text_redacted, t.words, t.language "
            "FROM analyzer.transcripts t JOIN analyzer.calls c ON c.call_id = t.call_id "
            "WHERE c.casino_id = %(cid)s AND t.translation_checked_at IS NULL "
            "ORDER BY c.created_at LIMIT 1",
            {'cid': casino_id})
        return cur.fetchone()


def unverified_translation_count(casino_id: str) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM analyzer.transcripts t "
            "JOIN analyzer.calls c ON c.call_id = t.call_id "
            "WHERE c.casino_id = %(cid)s AND t.translation_checked_at IS NULL",
            {'cid': casino_id})
        return int(cur.fetchone()['n'])


def mark_translation_checked(call_id: str, match: bool, note: str | None = None) -> bool:
    """Отметить проверку перевода (§10.11). checked_at ставится ВСЕГДА (иначе
    «не совпало» блокировало очередь навсегда), verified = вердикт, note
    рецензента сохраняется. True, если транскрипт найден."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE analyzer.transcripts SET translation_verified = %(m)s, "
            "translation_checked_at = now(), translation_note = %(note)s "
            "WHERE call_id = %(id)s RETURNING transcript_id",
            {'m': bool(match), 'id': call_id, 'note': (note or '').strip()[:1000] or None})
        return cur.fetchone() is not None


def save_translation(call_id: str, lang: str, text: str) -> None:
    """Кэшировать перевод, вернувшийся от пайплайна (страховка, если он не записал сам)."""
    col = 'translation_ru' if lang == 'ru' else 'translation_en'
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE analyzer.transcripts SET {col} = %(text)s WHERE call_id = %(id)s",
            {'text': text, 'id': call_id})


# ── статистика версий скрипта («какие скрипты работают») ─────────────────────
def script_version_stats(casino_id: str) -> tuple[list[dict], list[tuple]]:
    """Версии скрипта с бизнес-исходами звонков по каждой.

    Сравнивать версии по БАЛЛУ нельзя (линейки разные — спека §10.5/§10.8),
    поэтому агрегируем ЧЕСТНЫЕ исходы: прозвучал ли оффер и принял ли игрок
    (analyzer.offer_signals). Вторым значением возвращаем (version,
    casino_player_id, started_at) разобранных звонков — по ним API доклеивает
    «депозит ≤7 дней после звонка» из ClickHouse (money-данные не в Postgres).
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT sv.version, sv.status, sv.activated_at, sv.group_id, g.name AS group_name,
                      sc.name AS script_name,
                      COUNT(DISTINCT a.call_id)                                            AS analyzed,
                      COUNT(DISTINCT s.call_id) FILTER (WHERE s.offer_presented)           AS presented,
                      COUNT(DISTINCT s.call_id) FILTER (WHERE s.player_response='accepted') AS accepted,
                      ROUND(AVG(COALESCE(a.human_override_score, a.overall_score_100)))     AS avg_score
               FROM analyzer.script_versions sv
               LEFT JOIN analyzer.script_groups g ON g.group_id = sv.group_id
               LEFT JOIN analyzer.scripts sc ON sc.script_ref = sv.script_ref
               LEFT JOIN analyzer.call_audits a ON a.script_version = sv.version
               LEFT JOIN analyzer.offer_signals s ON s.call_id = a.call_id
               WHERE sv.casino_id = %(cid)s AND sv.version IS NOT NULL
               GROUP BY sv.version, sv.status, sv.activated_at, sv.group_id, g.name, sc.name
               ORDER BY sv.version""",
            {'cid': casino_id})
        stats = cur.fetchall()
        # звонки для атрибуции депозитов (кап — против раздувания CH-запроса)
        cur.execute(
            """SELECT a.script_version, c.casino_player_id, c.started_at
               FROM analyzer.call_audits a
               JOIN analyzer.calls c ON c.call_id = a.call_id
               WHERE a.script_version IS NOT NULL AND c.started_at IS NOT NULL
               ORDER BY c.started_at DESC LIMIT 5000""")
        calls = [(r['script_version'], r['casino_player_id'], r['started_at']) for r in cur.fetchall()]
    return list(stats), calls


# ── «когда звонить»: рекомендации + фиксация ─────────────────────────────────
def last_call_and_attempts(pid: int) -> dict:
    """Последний звонок игроку + попытки за сегодня (для retry-правила)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT outcome::text, started_at FROM crm.calls
               WHERE casino_player_id = %(pid)s ORDER BY started_at DESC LIMIT 1""",
            {'pid': pid})
        last = cur.fetchone()
        cur.execute(
            """SELECT count(*) FROM crm.calls
               WHERE casino_player_id = %(pid)s AND started_at >= date_trunc('day', now())""",
            {'pid': pid})
        today = cur.fetchone()['count']
    return {'last_outcome': last['outcome'] if last else None,
            'last_at': last['started_at'] if last else None,
            'attempts_today': int(today or 0)}


def answer_rate_by_hour() -> list[dict]:
    """Глобальная статистика дозвона по часам (Istanbul): основа рекомендаций
    и обучающие данные — по мере роста журнала звонков точность растёт сама."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT extract(hour FROM started_at AT TIME ZONE 'Europe/Istanbul')::int AS h,
                      count(*) AS total,
                      count(*) FILTER (WHERE outcome = 'answered') AS answered
               FROM crm.calls GROUP BY h ORDER BY h""")
        return [{'hour': r['h'], 'total': int(r['total']),
                 'answered': int(r['answered']),
                 'rate': round(r['answered'] / r['total'] * 100) if r['total'] else None}
                for r in cur.fetchall()]


def log_recommendation(pid: int, operator_id: str | None, kind: str, slot,
                       basis: str, context: dict) -> str:
    """Фиксация выданной рекомендации (дедуп: та же kind+слот за сегодня → reuse)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT rec_id FROM analyzer.call_recommendations
               WHERE casino_player_id = %(pid)s AND kind = %(kind)s AND slot = %(slot)s
                 AND created_at >= date_trunc('day', now()) LIMIT 1""",
            {'pid': pid, 'kind': kind, 'slot': slot})
        row = cur.fetchone()
        if row:
            return str(row['rec_id'])
        cur.execute(
            """INSERT INTO analyzer.call_recommendations
               (casino_player_id, operator_id, kind, slot, basis, context)
               VALUES (%(pid)s, %(op)s, %(kind)s, %(slot)s, %(basis)s, %(ctx)s)
               RETURNING rec_id""",
            {'pid': pid, 'op': operator_id, 'kind': kind, 'slot': slot,
             'basis': basis, 'ctx': json.dumps(context, ensure_ascii=False, default=str)})
        return str(cur.fetchone()['rec_id'])


def accept_recommendation(rec_id: str, schedule_id: str | None,
                          restrict_operator: str | None = None) -> bool:
    """restrict_operator задан (оператор) → принять можно только свою
    рекомендацию (или ничью, выданную до привязки к оператору)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE analyzer.call_recommendations
               SET accepted_at = now(), schedule_id = %(sid)s
               WHERE rec_id = %(rid)s
                 AND (%(op)s::uuid IS NULL OR operator_id IS NULL OR operator_id = %(op)s::uuid)
               RETURNING rec_id""",
            {'rid': rec_id, 'sid': schedule_id, 'op': restrict_operator})
        return cur.fetchone() is not None


# ── покрытие: перезвоны + дриллдаун по оператору («кому дозвонился, кому нет») ──
def coverage_operator_detail(operator_id: str) -> list[dict]:
    """Игроки оператора: попытки, последний исход, следующий запланированный звонок."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """WITH lastc AS (
                 SELECT DISTINCT ON (casino_player_id) casino_player_id,
                        outcome::text AS last_outcome, started_at AS last_at
                 FROM crm.calls WHERE operator_id = %(op)s
                 ORDER BY casino_player_id, started_at DESC),
               cnt AS (
                 SELECT casino_player_id, count(*) AS attempts,
                        count(*) FILTER (WHERE outcome='answered') AS answered
                 FROM crm.calls WHERE operator_id = %(op)s GROUP BY casino_player_id),
               nexts AS (
                 SELECT casino_player_id, min(scheduled_at) AS next_at
                 FROM crm.scheduled_calls
                 WHERE operator_id = %(op)s AND status = 'planned' AND scheduled_at >= now()
                 GROUP BY casino_player_id)
               SELECT a.casino_player_id,
                      COALESCE(c.attempts, 0)  AS attempts,
                      COALESCE(c.answered, 0)  AS answered,
                      l.last_outcome, l.last_at, n.next_at
               FROM crm.player_assignments a
               LEFT JOIN cnt  c ON c.casino_player_id = a.casino_player_id
               LEFT JOIN lastc l ON l.casino_player_id = a.casino_player_id
               LEFT JOIN nexts n ON n.casino_player_id = a.casino_player_id
               WHERE a.operator_id = %(op)s
               ORDER BY (c.attempts IS NULL) DESC, l.last_at DESC NULLS LAST
               LIMIT 300""",
            {'op': operator_id})
        return [dict(r) for r in cur.fetchall()]


def coverage_scheduled_counts() -> dict[str, int]:
    """Сколько перезвонов назначено (pending, в будущем) — по операторам."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT operator_id, count(*) AS n FROM crm.scheduled_calls
               WHERE status = 'planned' AND scheduled_at >= now()
               GROUP BY operator_id""")
        return {str(r['operator_id']): int(r['n']) for r in cur.fetchall()}


# ── доп. содержание сводки и вердикта (запрос владельца продукта) ─────────────
def weekly_dialing_facts(weeks: int = 6) -> list[dict]:
    """Факты обзвона ПО НЕДЕЛЯМ (сводка §10.12): владелец видит динамику, а не
    только «эта неделя vs прошлая». Только данные звонилки — от модели не зависят."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT date_trunc('week', started_at)::date AS week,
                      count(*) AS attempts,
                      count(*) FILTER (WHERE outcome = 'answered') AS connected,
                      count(*) FILTER (WHERE result IS NOT NULL) AS talks
               FROM crm.calls
               WHERE started_at >= date_trunc('week', now()) - make_interval(weeks => %(w)s)
               GROUP BY 1 ORDER BY 1""",
            {'w': int(weeks)})
        return [{'week': r['week'].isoformat(), 'attempts': int(r['attempts']),
                 'connected': int(r['connected']), 'talks': int(r['talks'])}
                for r in cur.fetchall()]


def scheduled_upcoming_count() -> int:
    """Назначено перезвонов на будущее (факт CRM — планирование, не модель)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM crm.scheduled_calls "
                    "WHERE status = 'planned' AND scheduled_at >= now()")
        return int(cur.fetchone()['n'])


def recent_disagreements(limit: int = 10) -> list[dict]:
    """Последние правки руководителя С ПРИЧИНАМИ (вердикт §10.13): где и почему
    человек не согласился с моделью — прямая наводка на починку промпта."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT r.created_at, r.reason, r.review_time_s, r.counted,
                      a.call_id, a.overall_score_100 AS model_score,
                      a.human_override_score AS human_score,
                      u.full_name AS reviewer_name
               FROM analyzer.audit_reviews r
               JOIN analyzer.call_audits a ON a.audit_id = r.audit_id
               LEFT JOIN crm.crm_users u ON u.id = r.reviewer_id
               WHERE r.kind = 'override'
               ORDER BY r.created_at DESC LIMIT %(lim)s""",
            {'lim': int(limit)})
        return [{'at': r['created_at'].isoformat(), 'reason': r['reason'],
                 'counted': r['counted'], 'call_id': str(r['call_id']),
                 'model_score': r['model_score'], 'human_score': r['human_score'],
                 'reviewer': r['reviewer_name']} for r in cur.fetchall()]


def agreement_weekly(weeks: int = 6) -> list[dict]:
    """Согласие модели с человеком ПО НЕДЕЛЯМ (вердикт §10.13): видно, сходится
    ли модель со временем — а не только среднее за всю историю."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT date_trunc('week', created_at)::date AS week,
                      count(*) FILTER (WHERE counted) AS checked,
                      count(*) FILTER (WHERE counted AND kind = 'confirm') AS agreed
               FROM analyzer.audit_reviews
               WHERE created_at >= date_trunc('week', now()) - make_interval(weeks => %(w)s)
               GROUP BY 1 ORDER BY 1""",
            {'w': int(weeks)})
        out = []
        for r in cur.fetchall():
            checked = int(r['checked'])
            out.append({'week': r['week'].isoformat(), 'checked': checked,
                        'agreement': round(int(r['agreed']) / checked * 100) if checked else None})
        return out
