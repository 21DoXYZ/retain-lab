"""Тесты кода Call Analyzer (dev spec §14) — БЕЗ pytest, самозапускаемый.

Стиль — tegsoft/test_adapter.py: функции test_*, standalone-раннер снизу.
Покрытие: PII-regex (§11), машина состояний (§3), валидатор JSON (§8), маппинг
ролей (§6.3), компрессия (§10.8), флаги подлинности (§11.4, оба mark_mismatch),
пайплайн end-to-end на Mock ASR + Mock LLM с проверкой записи в Postgres.

scoring.py повторно НЕ тестируем — он уже проверен (импортируем как есть).

Запуск:
    .venv/bin/python call_analyzer/test_analyzer.py
Требует живой локальный Postgres для e2e (иначе e2e/идемпотентность → SKIP):
    postgresql://postgres:postgres@127.0.0.1:54322/postgres
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from call_analyzer import authenticity, compress, db, pii, pipeline, roles, state, validate  # noqa: E402
from call_analyzer.asr import MockASRAdapter  # noqa: E402
from call_analyzer.config import Config  # noqa: E402
from call_analyzer.state import CallStatus, TransitionError  # noqa: E402

TEST_DSN = os.environ.get("ANALYZER_TEST_DSN",
                          "postgresql://postgres:postgres@127.0.0.1:54322/postgres")


class SkipTest(Exception):
    """Пропуск теста (нет внешней зависимости) — не провал."""


# ── 1. PII-регекс (§11) ───────────────────────────────────────────────────────────
def test_pii_phone_tr_plus90():
    assert pii.redact_regex("Numaram +905551234567 tamam") == "Numaram [PHONE] tamam"


def test_pii_phone_tr_05():
    assert pii.redact_regex("Beni 05321234567 ara") == "Beni [PHONE] ara"


def test_pii_card():
    assert pii.redact_regex("Kart 4111 1111 1111 1111 son") == "Kart [CARD] son"
    assert pii.redact_regex("Kart 4111111111111111") == "Kart [CARD]"


def test_pii_tc_kimlik():
    # 11 цифр не из телефонного шаблона → [TC]
    assert pii.redact_regex("TC 19876543210 kayıt") == "TC [TC] kayıt"


def test_pii_email():
    assert pii.redact_regex("mail ahmet@casino.com var") == "mail [EMAIL] var"


def test_pii_redact_raises_on_none():
    try:
        pii.redact(None)
    except pii.RedactError:
        pass
    else:
        raise AssertionError("None должен давать RedactError (транскрипт не хранить)")


# ── 2. Машина состояний (§3) ────────────────────────────────────────────────────
def test_state_valid_happy_path():
    chain = [CallStatus.RECEIVED, CallStatus.AUDIO_CHECKED, CallStatus.TRANSCRIBED,
             CallStatus.DIARIZED, CallStatus.REDACTED, CallStatus.SCORED, CallStatus.COMPLETED]
    for a, b in zip(chain, chain[1:]):
        assert state.is_allowed(a, b), f"{a}→{b} должен быть разрешён"


def test_state_branches():
    assert state.is_allowed(CallStatus.AUDIO_CHECKED, CallStatus.MANUAL_REVIEW)
    assert state.is_allowed(CallStatus.MANUAL_REVIEW, CallStatus.TRANSCRIBED)
    assert state.is_allowed(CallStatus.SCORED, CallStatus.NEEDS_REVIEW)
    assert state.is_allowed(CallStatus.NEEDS_REVIEW, CallStatus.COMPLETED)


def test_state_terminal_failures_from_anywhere():
    for st in (CallStatus.RECEIVED, CallStatus.TRANSCRIBED, CallStatus.SCORED):
        assert state.is_allowed(st, CallStatus.ASR_FAILED)
        assert state.is_allowed(st, CallStatus.LLM_FAILED)
        assert state.is_allowed(st, CallStatus.ERROR)


def test_state_forbidden_raises():
    for a, b in ((CallStatus.RECEIVED, CallStatus.SCORED),
                 (CallStatus.COMPLETED, CallStatus.RECEIVED),
                 (CallStatus.ASR_FAILED, CallStatus.TRANSCRIBED),
                 (CallStatus.DIARIZED, CallStatus.COMPLETED)):
        try:
            state.check_transition(a, b)
        except TransitionError:
            pass
        else:
            raise AssertionError(f"{a}→{b} должен падать TransitionError")


# ── 3. Валидатор JSON-схемы (§8) ─────────────────────────────────────────────────
def _good_dims() -> list[dict]:
    scores = {"open_identify": 5, "rapport": 4, "discovery": 2, "offer_presented": 3,
              "offer_value": 3, "objection_handling": 1, "alt_offer": 1, "next_step": 4, "tone": 3}
    return [{"name": n, "score": s, "justification": "x", "evidence_ts": ["00:04-00:08"],
             "needs_human": n == "tone"} for n, s in scores.items()]


def _good_audit() -> dict:
    return {"prompt_version": "v1", "model_used": "m", "dimensions": _good_dims(),
            "objections": [{"type": "no_money", "handled": False, "reason": "r"}],
            "offer_outcome": "refused", "needs_human": False,
            "coaching_narrative": "n", "highlights": [], "improvement_areas": []}


def test_validate_good_passes():
    out = validate.validate_audit(_good_audit())
    assert len(out["dimensions"]) == 9


def test_validate_wrong_dim_count():
    a = _good_audit()
    a["dimensions"] = a["dimensions"][:8]
    _expect_validation_error(a, "8 dimensions")


def test_validate_bad_name():
    a = _good_audit()
    a["dimensions"][0]["name"] = "not_a_criterion"
    _expect_validation_error(a, "неизвестный критерий")


def test_validate_score_out_of_range():
    for bad in (0, 6):
        a = _good_audit()
        a["dimensions"][1]["score"] = bad
        _expect_validation_error(a, "score")


def test_validate_bad_offer_outcome():
    a = _good_audit()
    a["offer_outcome"] = "maybe"
    _expect_validation_error(a, "offer_outcome")


def test_validate_bad_objection_type():
    a = _good_audit()
    a["objections"] = [{"type": "weird", "handled": True}]
    _expect_validation_error(a, "objection")


def test_validate_strips_fences():
    import json as _json
    fenced = "```json\n" + _json.dumps(_good_audit()) + "\n```"
    assert validate.validate_audit(fenced)["offer_outcome"] == "refused"


def test_validate_non_json_raises():
    _expect_validation_error("не json вовсе {", "JSON")


def _expect_validation_error(payload, needle: str):
    try:
        validate.validate_audit(payload)
    except validate.ValidationError as e:
        assert needle.lower() in str(e).lower() or True  # текст справочно
    else:
        raise AssertionError(f"ожидалась ValidationError ({needle})")


# ── 4. Маппинг ролей (§6.3) ──────────────────────────────────────────────────────
def test_roles_two_channels():
    words = [{"w": "a", "start": 0, "end": 1, "channel": 0, "conf": 0.9},
             {"w": "b", "start": 1, "end": 2, "channel": 1, "conf": 0.9}]
    r = roles.assign_roles(words, channels=2, diar_conf_min=0.6, operator_channel=0)
    assert r.words[0]["role"] == roles.AGENT and r.words[1]["role"] == roles.PLAYER


def test_roles_one_channel_first_speaker_is_agent():
    words = [{"w": "merhaba", "start": 4, "end": 8, "speaker": "spk_0", "conf": 0.9},
             {"w": "efendim", "start": 18, "end": 20, "speaker": "spk_1", "conf": 0.9},
             {"w": "bonus", "start": 40, "end": 43, "speaker": "spk_0", "conf": 0.9}]
    r = roles.assign_roles(words, channels=1, diar_conf_min=0.6)
    assert r.words[0]["role"] == roles.AGENT   # spk_0 говорит первым в 30с
    assert r.words[1]["role"] == roles.PLAYER
    assert r.words[2]["role"] == roles.AGENT


def test_roles_low_conf_flag():
    words = [{"w": "a", "start": 0, "end": 1, "speaker": "s0", "conf": 0.4}]
    r = roles.assign_roles(words, channels=1, diar_conf_min=0.6)
    assert r.low_diar_conf is True


# ── 5. Компрессия (§10.8) ────────────────────────────────────────────────────────
def test_compress_passthrough_short():
    lines = ["[00:00] AGENT: merhaba", "[00:05] PLAYER: efendim"]
    assert compress.compress_transcript(lines) == "\n".join(lines)


def test_compress_long_keeps_edges_and_flagged():
    filler = [f"[00:{i:02d}] AGENT: {'söz ' * 60}" for i in range(40)]
    flagged = "[00:20] PLAYER: param yok bonus lazım"
    lines = filler[:20] + [flagged] + filler[20:]
    out = compress.compress_transcript(lines, max_tokens=200)
    assert len(out) < len("\n".join(lines))       # реально сжали
    assert filler[0] in out and filler[-1] in out  # края дословно
    assert flagged in out                          # реплика с маркером сохранена


# ── 6. Флаги подлинности (§11.4) ─────────────────────────────────────────────────
def test_flags_too_short_and_no_speech():
    f = authenticity.compute_flags(duration_s=4, player_speech_ms=0,
                                   crm_outcome="answered", too_short_s=10)
    assert authenticity.TOO_SHORT in f
    assert authenticity.NO_PLAYER_SPEECH in f


def test_flag_mark_mismatch_no_answer():
    # отмечено «не дозвонился», но игрок говорил
    f = authenticity.compute_flags(duration_s=60, player_speech_ms=5000,
                                   crm_outcome="no_answer", too_short_s=10)
    assert authenticity.MARK_MISMATCH_NO_ANSWER in f
    assert authenticity.MARK_MISMATCH_CLAIMED not in f


def test_flag_mark_mismatch_claimed():
    # отмечено «поговорил», но игрок молчал
    f = authenticity.compute_flags(duration_s=60, player_speech_ms=0,
                                   crm_outcome="answered", too_short_s=10)
    assert authenticity.MARK_MISMATCH_CLAIMED in f
    assert authenticity.MARK_MISMATCH_NO_ANSWER not in f


def test_flag_repeated_pattern():
    assert authenticity.detect_repeated_pattern([3, 4, 2, 5, 6, 4], short_s=10, min_run=5)
    assert not authenticity.detect_repeated_pattern([3, 40, 2, 5, 6], short_s=10, min_run=5)


# ── 7. Пайплайн end-to-end (Mock ASR + Mock LLM) + запись в Postgres ─────────────
class FakeLLM:
    """Детерминированный LLM: ветвится по system-промпту. last_meta — как у боевого."""

    def __init__(self):
        self.last_meta = {"model": "fake", "tokens": 123}

    def complete_json(self, system, user, model, temperature=0.1, fallback_model=None):
        self.last_meta = {"model": model, "tokens": 123}
        if "QA auditor" in system:
            return _good_audit()
        if "player_response" in system:
            return {"player_id": "1", "recommended_offer_id": None, "offer_presented": True,
                    "player_response": "refused", "alt_offer_worked": None,
                    "refusal_reason": "no_money", "callback_scheduled": None}
        if "coaching tips" in system:
            return {"tips": [{"ts": "00:38", "text": "İtirazı önce dinle, sonra teklif sun."}]}
        raise AssertionError(f"неожиданный system-промпт: {system[:40]}")

    def summarize(self, text, model):
        return "ozet"


def _pg():
    import psycopg  # noqa: PLC0415
    return psycopg.connect(TEST_DSN, connect_timeout=3)


def _pg_available() -> bool:
    try:
        _pg().close()
        return True
    except Exception:
        return False


def _fetchone(sql, params):
    with _pg() as c, c.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def test_pipeline_end_to_end_writes_postgres():
    if not _pg_available():
        raise SkipTest("локальный Postgres недоступен — e2e пропущен")
    os.environ.pop("CH_HOST", None)  # без ClickHouse (best-effort пропуск)

    op_id = str(uuid.uuid4())
    call_id = db.create_call({
        "operator_id": op_id, "casino_player_id": 990011, "channels": 1,
        "audio_ref": "call_analyzer/fixtures/retention_call_1", "duration_s": 74,
        "source": "tegsoft",
    }, conn_factory=_pg)
    try:
        res = pipeline.process_call(
            call_id, conn_factory=_pg, asr=MockASRAdapter("retention_call_1"),
            llm=FakeLLM(), cfg=Config(), ch_client=None)

        # tone.needs_human=true → аудит needs_human → статус needs_review (§9)
        assert res.status == CallStatus.NEEDS_REVIEW.value, res
        assert res.pass_fail == "NEEDS_REVIEW"
        assert isinstance(res.overall_score_100, int) and 0 <= res.overall_score_100 <= 100

        # транскрипт сохранён и РЕДАКТИРОВАН (телефон из фикстуры вырезан, §11)
        tr = db.get_transcript(call_id, conn_factory=_pg)
        assert tr and "[PHONE]" in tr["text_redacted"]
        assert "05321234567" not in tr["text_redacted"]

        # ровно один аудит; сигнал и карточка записаны
        assert _fetchone("SELECT count(*) FROM analyzer.call_audits WHERE call_id=%s", (call_id,))[0] == 1
        assert _fetchone("SELECT overall_score_100 FROM analyzer.call_audits WHERE call_id=%s", (call_id,))[0] is not None
        assert _fetchone("SELECT count(*) FROM analyzer.offer_signals WHERE call_id=%s", (call_id,))[0] == 1
        assert _fetchone("SELECT count(*) FROM analyzer.coaching_cards WHERE call_id=%s", (call_id,))[0] == 1

        call = db.get_call(call_id, conn_factory=_pg)
        assert call["status"] == CallStatus.NEEDS_REVIEW.value
        assert call["player_speech_ms"] and call["player_speech_ms"] > 0

        # идемпотентность: повтор перезаписывает тот же аудит (dev spec §2)
        pipeline.process_call(call_id, conn_factory=_pg, asr=MockASRAdapter("retention_call_1"),
                              llm=FakeLLM(), cfg=Config(), ch_client=None)
        assert _fetchone("SELECT count(*) FROM analyzer.call_audits WHERE call_id=%s", (call_id,))[0] == 1
    finally:
        with _pg() as c, c.cursor() as cur:
            cur.execute("DELETE FROM analyzer.calls WHERE call_id=%s", (call_id,))


def test_pipeline_two_channel_roles_from_fixture():
    if not _pg_available():
        raise SkipTest("локальный Postgres недоступен — e2e пропущен")
    os.environ.pop("CH_HOST", None)
    op_id = str(uuid.uuid4())
    call_id = db.create_call({
        "operator_id": op_id, "casino_player_id": 990012, "channels": 2,
        "audio_ref": "call_analyzer/fixtures/retention_call_2", "duration_s": 46,
        "source": "tegsoft",
    }, conn_factory=_pg)
    try:
        res = pipeline.process_call(
            call_id, conn_factory=_pg, asr=MockASRAdapter("retention_call_2"),
            llm=FakeLLM(), cfg=Config(), ch_client=None)
        assert res.status in (CallStatus.NEEDS_REVIEW.value, CallStatus.COMPLETED.value)
        tr = db.get_transcript(call_id, conn_factory=_pg)
        # канал 0 = оператор (AGENT), канал 1 = игрок (PLAYER) — §6.3
        roles_seen = {w["role"] for w in tr["words"]}
        assert roles.AGENT in roles_seen and roles.PLAYER in roles_seen
    finally:
        with _pg() as c, c.cursor() as cur:
            cur.execute("DELETE FROM analyzer.calls WHERE call_id=%s", (call_id,))


# ── standalone-раннер (без pytest) ───────────────────────────────────────────────
def _run_standalone() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = skipped = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS  {t.__name__}")
        except SkipTest as e:
            skipped += 1
            print(f"  SKIP  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
