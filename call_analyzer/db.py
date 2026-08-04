"""Доступ к Postgres (схема analyzer + чтение crm.calls) — dev spec §4.

Подключение как в tegsoft/store.py: psycopg (v3), env SUPABASE_DB_URL, ленивый
импорт драйвера (отсутствие psycopg не ломает загрузку модулей). conn_factory
инжектируется в тестах. Смена статуса — ТОЛЬКО через state.check_transition.

jsonb-поля (words/flags/dimensions/…) сериализуем json.dumps на запись; на чтение
psycopg3 отдаёт их уже разобранными (list/dict).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from call_analyzer import state

logger = logging.getLogger("call_analyzer.db")


class DbError(RuntimeError):
    """Ошибка доступа к Postgres анализатора."""


def _dsn() -> str:
    dsn = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not dsn:
        raise DbError("SUPABASE_DB_URL не задан — некуда писать analyzer.*")
    return dsn


def _connect():
    """Ленивое psycopg (v3). Изолируем импорт как в tegsoft/store.py."""
    try:
        import psycopg  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise DbError("Драйвер 'psycopg' (v3) не установлен (pip install 'psycopg[binary]').") from e
    return psycopg.connect(_dsn())


def _j(value: Any) -> str:
    """Сериализация для jsonb-плейсхолдера."""
    return json.dumps(value if value is not None else [])


def resolve_script_version(operator_id: str | None, casino_id: str = "default",
                           *, conn_factory=_connect) -> int | None:
    """Активная версия скрипта для оператора звонка (A/B — 0010).

    Оператор в группе → активный скрипт ГРУППЫ; нет группы / у неё нет
    активного → скрипт казино по умолчанию (group_id IS NULL). Пишется в
    audit.script_version, чтобы звонок сравнивался в статистике под своей
    версией/вариантом. NULL → скрипта нет (оценка «без скрипта»).
    """
    with conn_factory() as conn, conn.cursor() as cur:
        gid, gref = None, None
        if operator_id:
            cur.execute("SELECT m.group_id, g.script_ref FROM analyzer.script_group_members m "
                        "JOIN analyzer.script_groups g ON g.group_id = m.group_id "
                        "WHERE m.operator_id = %(op)s", {"op": operator_id})
            row = cur.fetchone()
            if row:
                gid, gref = row[0], row[1]
        # 0011: скрипт, назначенный группе → скрипт казино по умолчанию
        cur.execute("SELECT script_ref FROM analyzer.casino_default_script "
                    "WHERE casino_id = %(cid)s", {"cid": casino_id})
        row = cur.fetchone()
        default_ref = row[0] if row else None
        for ref in [r for r in (gref, default_ref) if r]:
            cur.execute("SELECT version FROM analyzer.script_versions "
                        "WHERE script_ref = %(r)s AND status = 'active' LIMIT 1", {"r": ref})
            row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
        # легаси (до 0011): активный поток группы, потом — казино-дефолт (group_id IS NULL)
        for filt in ([("group_id = %(g)s", {"g": gid})] if gid else []) + \
                    [("group_id IS NULL", {})]:
            where, extra = filt
            cur.execute(
                "SELECT version FROM analyzer.script_versions "
                "WHERE casino_id = %(cid)s AND status = 'active' AND script_ref IS NULL AND " + where
                + " ORDER BY version DESC LIMIT 1",
                {"cid": casino_id, **extra})
            row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
        return None


# ── settings (dev spec §12) ──────────────────────────────────────────────────────
def get_settings(casino_id: str = "default", *, conn_factory=_connect) -> dict | None:
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT config, random_sample_per_day, min_review_time_s, verdict_unlocked
               FROM analyzer.settings WHERE casino_id = %(cid)s""",
            {"cid": casino_id},
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "config": row[0] or {},
        "random_sample_per_day": row[1],
        "min_review_time_s": row[2],
        "verdict_unlocked": row[3],
    }


# ── analyzer.calls ───────────────────────────────────────────────────────────────
_CALL_COLS = (
    "crm_call_id", "casino_id", "operator_id", "casino_player_id", "source",
    "channels", "audio_ref", "started_at", "ended_at", "duration_s",
    "recommended_offer_id",
)


def create_call(record: dict, *, conn_factory=_connect) -> str:
    """Создать analyzer.calls (ingest §5 / discover §10). Идемпотентно по crm_call_id.

    Возвращает call_id (uuid). Если звонок с таким crm_call_id уже есть — вернёт его.
    """
    cols = {k: record.get(k) for k in _CALL_COLS}
    cols["flags"] = _j(record.get("flags") or [])
    present = [k for k in _CALL_COLS if cols.get(k) is not None] + ["flags"]
    placeholders = ", ".join(f"%({k})s" for k in present)
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO analyzer.calls ({', '.join(present)})
                VALUES ({placeholders})
                ON CONFLICT (crm_call_id) WHERE crm_call_id IS NOT NULL DO NOTHING
                RETURNING call_id""",
            cols,
        )
        row = cur.fetchone()
        if row:
            return str(row[0])
        # конфликт: звонок уже заведён — вернуть существующий id
        cur.execute(
            "SELECT call_id FROM analyzer.calls WHERE crm_call_id = %(c)s",
            {"c": record.get("crm_call_id")},
        )
        existing = cur.fetchone()
    if not existing:
        raise DbError("create_call: не удалось ни вставить, ни найти звонок")
    return str(existing[0])


def get_call(call_id: str, *, conn_factory=_connect) -> dict | None:
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT call_id, crm_call_id, casino_id, operator_id, casino_player_id,
                      source, channels, audio_ref, started_at, ended_at, duration_s,
                      snr, player_speech_ms, status, recommended_offer_id, flags
               FROM analyzer.calls WHERE call_id = %(id)s""",
            {"id": call_id},
        )
        row = cur.fetchone()
    if not row:
        return None
    keys = ("call_id", "crm_call_id", "casino_id", "operator_id", "casino_player_id",
            "source", "channels", "audio_ref", "started_at", "ended_at", "duration_s",
            "snr", "player_speech_ms", "status", "recommended_offer_id", "flags")
    out = dict(zip(keys, row))
    out["call_id"] = str(out["call_id"])
    return out


def update_status(call_id: str, new_status: state.CallStatus | str, *, conn_factory=_connect) -> str:
    """Сменить статус через машину состояний (dev spec §3). Запрещённый переход → TransitionError."""
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM analyzer.calls WHERE call_id = %(id)s FOR UPDATE",
                    {"id": call_id})
        row = cur.fetchone()
        if not row:
            raise DbError(f"update_status: звонок {call_id} не найден")
        dst = state.check_transition(row[0], new_status)  # бросит TransitionError
        cur.execute(
            "UPDATE analyzer.calls SET status = %(s)s, updated_at = now() WHERE call_id = %(id)s",
            {"s": dst.value, "id": call_id},
        )
    return dst.value


def update_call_fields(call_id: str, *, conn_factory=_connect, **fields) -> None:
    """Обновить скалярные поля analyzer.calls (snr, player_speech_ms, recommended_offer_id…)."""
    if not fields:
        return
    if "flags" in fields:
        fields = {**fields, "flags": _j(fields["flags"])}
    sets = ", ".join(f"{k} = %({k})s" for k in fields)
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE analyzer.calls SET {sets}, updated_at = now() WHERE call_id = %(id)s",
            {**fields, "id": call_id},
        )


# ── analyzer.transcripts ─────────────────────────────────────────────────────────
def upsert_transcript(call_id: str, *, asr_provider: str, language: str,
                      text_redacted: str, words: list, diarization_conf: float | None,
                      conn_factory=_connect) -> str:
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO analyzer.transcripts
                 (call_id, asr_provider, language, text_redacted, words, diarization_conf)
               VALUES (%(call_id)s, %(prov)s, %(lang)s, %(text)s, %(words)s, %(conf)s)
               ON CONFLICT (call_id) DO UPDATE SET
                 asr_provider = EXCLUDED.asr_provider, language = EXCLUDED.language,
                 text_redacted = EXCLUDED.text_redacted, words = EXCLUDED.words,
                 diarization_conf = EXCLUDED.diarization_conf
               RETURNING transcript_id""",
            {"call_id": call_id, "prov": asr_provider, "lang": language,
             "text": text_redacted, "words": _j(words), "conf": diarization_conf},
        )
        return str(cur.fetchone()[0])


def get_transcript(call_id: str, *, conn_factory=_connect) -> dict | None:
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT text_redacted, words, language, translation_ru, translation_en
               FROM analyzer.transcripts WHERE call_id = %(id)s""",
            {"id": call_id},
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"text_redacted": row[0], "words": row[1], "language": row[2],
            "translation_ru": row[3], "translation_en": row[4]}


def set_translation(call_id: str, lang: str, text: str, *, conn_factory=_connect) -> None:
    if lang not in ("ru", "en"):
        raise DbError(f"перевод поддержан только ru|en, получено {lang!r}")
    col = f"translation_{lang}"
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE analyzer.transcripts SET {col} = %(t)s WHERE call_id = %(id)s",
            {"t": text, "id": call_id},
        )


# ── analyzer.call_audits (идемпотентность — dev spec §2) ─────────────────────────
def upsert_audit(audit: dict, *, conn_factory=_connect) -> str:
    """Записать аудит. Повтор по (call_id, prompt_version, model_used) перезаписывает."""
    params = {
        "call_id": audit["call_id"],
        "prompt_version": audit["prompt_version"],
        "rubric_version": audit["rubric_version"],
        "script_version": audit.get("script_version"),
        "model_used": audit["model_used"],
        "overall_score_100": audit.get("overall_score_100"),
        "pass_fail": audit["pass_fail"],
        "dimensions": _j(audit.get("dimensions") or []),
        "objections": _j(audit.get("objections") or []),
        "compliance": _j(audit.get("compliance") or []),
        "offer_outcome": audit.get("offer_outcome"),
        "coaching_narrative": audit.get("coaching_narrative"),
        "highlights": _j(audit.get("highlights") or []),
        "improvement_areas": _j(audit.get("improvement_areas") or []),
        "needs_human": audit.get("needs_human", False),
        "llm_tokens": audit.get("llm_tokens"),
        "llm_cost_usd": audit.get("llm_cost_usd"),
        "processing_ms": audit.get("processing_ms"),
    }
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO analyzer.call_audits
                 (call_id, prompt_version, rubric_version, script_version, model_used,
                  overall_score_100, pass_fail, dimensions, objections, compliance,
                  offer_outcome, coaching_narrative, highlights, improvement_areas,
                  needs_human, llm_tokens, llm_cost_usd, processing_ms)
               VALUES
                 (%(call_id)s, %(prompt_version)s, %(rubric_version)s, %(script_version)s,
                  %(model_used)s, %(overall_score_100)s, %(pass_fail)s, %(dimensions)s,
                  %(objections)s, %(compliance)s, %(offer_outcome)s, %(coaching_narrative)s,
                  %(highlights)s, %(improvement_areas)s, %(needs_human)s, %(llm_tokens)s,
                  %(llm_cost_usd)s, %(processing_ms)s)
               ON CONFLICT (call_id, prompt_version, model_used) DO UPDATE SET
                 rubric_version = EXCLUDED.rubric_version,
                 script_version = EXCLUDED.script_version,
                 overall_score_100 = EXCLUDED.overall_score_100,
                 pass_fail = EXCLUDED.pass_fail, dimensions = EXCLUDED.dimensions,
                 objections = EXCLUDED.objections, compliance = EXCLUDED.compliance,
                 offer_outcome = EXCLUDED.offer_outcome,
                 coaching_narrative = EXCLUDED.coaching_narrative,
                 highlights = EXCLUDED.highlights,
                 improvement_areas = EXCLUDED.improvement_areas,
                 needs_human = EXCLUDED.needs_human, llm_tokens = EXCLUDED.llm_tokens,
                 llm_cost_usd = EXCLUDED.llm_cost_usd, processing_ms = EXCLUDED.processing_ms
               RETURNING audit_id""",
            params,
        )
        return str(cur.fetchone()[0])


# ── analyzer.offer_signals (dev spec §10.5) ──────────────────────────────────────
def upsert_offer_signal(signal: dict, *, conn_factory=_connect) -> str:
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO analyzer.offer_signals
                 (call_id, casino_player_id, recommended_offer_id, offer_presented,
                  player_response, alt_offer_worked, refusal_reason, callback_scheduled)
               VALUES (%(call_id)s, %(pid)s, %(offer)s, %(presented)s, %(resp)s,
                       %(alt)s, %(refusal)s, %(callback)s)
               ON CONFLICT (call_id) DO UPDATE SET
                 recommended_offer_id = EXCLUDED.recommended_offer_id,
                 offer_presented = EXCLUDED.offer_presented,
                 player_response = EXCLUDED.player_response,
                 alt_offer_worked = EXCLUDED.alt_offer_worked,
                 refusal_reason = EXCLUDED.refusal_reason,
                 callback_scheduled = EXCLUDED.callback_scheduled
               RETURNING signal_id""",
            {"call_id": signal["call_id"], "pid": signal["casino_player_id"],
             "offer": signal.get("recommended_offer_id"),
             "presented": signal.get("offer_presented", False),
             "resp": signal.get("player_response"),
             "alt": signal.get("alt_offer_worked"),
             "refusal": signal.get("refusal_reason"),
             "callback": signal.get("callback_scheduled")},
        )
        return str(cur.fetchone()[0])


# ── analyzer.coaching_cards (интерфейс §10.10) ───────────────────────────────────
def insert_coaching_card(card: dict, *, conn_factory=_connect) -> str:
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO analyzer.coaching_cards (call_id, operator_id, tips)
               VALUES (%(call_id)s, %(op)s, %(tips)s) RETURNING card_id""",
            {"call_id": card["call_id"], "op": card["operator_id"], "tips": _j(card.get("tips") or [])},
        )
        return str(cur.fetchone()[0])


# ── discover (dev spec §10: crm.calls → analyzer.calls) ──────────────────────────
def discover_new_crm_calls(*, limit: int = 100, conn_factory=_connect) -> list[dict]:
    """Новые дозвоны из crm.calls (answered + есть запись), которых нет в analyzer.calls."""
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT c.id, c.casino_player_id, c.operator_id, c.duration_sec,
                      c.started_at, c.recording_ref
               FROM crm.calls c
               LEFT JOIN analyzer.calls a ON a.crm_call_id = c.id
               WHERE c.outcome = 'answered' AND c.recording_ref IS NOT NULL
                 AND a.call_id IS NULL
               ORDER BY c.created_at DESC LIMIT %(lim)s""",
            {"lim": limit},
        )
        rows = cur.fetchall()
    return [
        {"crm_call_id": str(r[0]), "casino_player_id": r[1],
         "operator_id": str(r[2]) if r[2] else None, "duration_s": r[3],
         "started_at": r[4], "audio_ref": r[5]}
        for r in rows
    ]


def count_random_reviews_today(casino_id: str = "default", *, conn_factory=_connect) -> int:
    """Сколько звонков уже помечено random_review сегодня (учёт дневного счётчика §10)."""
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM analyzer.calls
               WHERE casino_id = %(cid)s AND created_at::date = now()::date
                 AND flags @> '["random_review"]'::jsonb""",
            {"cid": casino_id},
        )
        return int(cur.fetchone()[0])


def pick_random_sample(*, casino_id: str = "default", n: int, conn_factory=_connect) -> list[str]:
    """Случайные completed-звонки дня без флагов — кандидаты в контрольную выборку (§7)."""
    if n <= 0:
        return []
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT call_id FROM analyzer.calls
               WHERE casino_id = %(cid)s AND status = 'completed'
                 AND created_at::date = now()::date AND flags = '[]'::jsonb
               ORDER BY random() LIMIT %(n)s""",
            {"cid": casino_id, "n": n},
        )
        return [str(r[0]) for r in cur.fetchall()]


def get_crm_outcome(crm_call_id: str | None, *, conn_factory=_connect) -> str | None:
    """Отметка оператора из crm.calls (нужна флагам «не сходится», интерфейс §12)."""
    if not crm_call_id:
        return None
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT outcome FROM crm.calls WHERE id = %(id)s", {"id": crm_call_id})
        row = cur.fetchone()
    return row[0] if row else None


def add_flag(call_id: str, flag: str, *, conn_factory=_connect) -> None:
    """Добавить флаг в analyzer.calls.flags, если его там ещё нет."""
    with conn_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE analyzer.calls
               SET flags = flags || %(f)s::jsonb, updated_at = now()
               WHERE call_id = %(id)s AND NOT (flags @> %(f)s::jsonb)""",
            {"f": json.dumps([flag]), "id": call_id},
        )
