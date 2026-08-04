"""Пайплайн разбора звонка (dev spec §2) — синхронный оркестратор.

process_call() прогоняет шаги 0–8 последовательно, меняя статус через машину
состояний. Сбой ОДНОГО звонка не роняет очередь (dev spec §7): каждый шаг
обёрнут, ошибка уводит звонок в верный терминальный статус и возвращает управление.

Оркестратор чист и инъектируем (asr/llm/cfg/conn_factory/ch_client) — Celery-обёртка
в worker.py просто вызывает его. Так же его дёргает тест на Mock ASR + Mock LLM.

Шаги: audio_qc → asr → diarize → redact → score → validate → offer_signal →
coaching card → запись Postgres/ClickHouse. Идемпотентность аудита — upsert по
(call_id, prompt_version, model_used) в db.upsert_audit.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from call_analyzer import authenticity, clickhouse, db, pii, prompts, roles, scoring, state, validate
from call_analyzer.compress import compress_transcript
from call_analyzer.config import Config, load_config
from call_analyzer.state import CallStatus, TransitionError

logger = logging.getLogger("call_analyzer.pipeline")

_ASR_RETRY_DELAYS = (2, 4, 8)  # dev spec §7: ASR fail — ретрай 3x exp(2→10s)


def _set_status(call_id: str, target: CallStatus, kw: dict) -> None:
    """Идемпотентный forward-переход (dev spec §2). Повтор process_call на уже
    обработанном звонке не должен падать на строгой машине: если звонок УЖЕ на
    целевом статусе или дальше по happy-path — тихо пропускаем."""
    try:
        db.update_status(call_id, target, **kw)
    except TransitionError:
        cur = db.get_call(call_id, **kw)
        cur_status = cur["status"] if cur else None
        if cur_status is not None and state.rank(cur_status) >= state.rank(target):
            logger.info("повтор: %s уже на/после %s — переход пропущен", cur_status, target.value)
            return
        raise


def _fail_status(call_id: str, target: CallStatus, kw: dict) -> None:
    """Best-effort терминальный сбой (§7): не роняем, если звонок уже терминален."""
    try:
        db.update_status(call_id, target, **kw)
    except TransitionError:
        logger.warning("статус %s не выставлен для %s (уже терминально)", target.value, call_id)


@dataclass
class PipelineResult:
    call_id: str
    status: str
    overall_score_100: int | None = None
    pass_fail: str | None = None
    audit_id: str | None = None
    error: str | None = None


# ── сборка транскрипта из размеченных слов ────────────────────────────────────────
def build_turns(words: list[dict]) -> list[dict]:
    """Склеить подряд идущие слова одной роли в реплики [{role,start,end,text}]."""
    turns: list[dict] = []
    for w in words:
        role = w.get("role", roles.AGENT)
        text = (w.get("w") or "").strip()
        if turns and turns[-1]["role"] == role:
            turns[-1]["text"] = (turns[-1]["text"] + " " + text).strip()
            turns[-1]["end"] = w.get("end", turns[-1]["end"])
        else:
            turns.append({"role": role, "start": w.get("start", 0.0),
                          "end": w.get("end", 0.0), "text": text})
    return turns


def format_lines(turns: list[dict]) -> list[str]:
    """Реплики → строки "[mm:ss] ROLE: text" (вход скоринга, dev spec §10.2)."""
    return [f"[{prompts.format_ts(t['start'])}] {t['role']}: {t['text']}" for t in turns]


def player_speech_ms(words: list[dict]) -> int:
    """Суммарная длительность речи игрока (для флагов §11.4)."""
    total = 0.0
    for w in words:
        if w.get("role") == roles.PLAYER:
            start, end = w.get("start"), w.get("end")
            if start is not None and end is not None and end > start:
                total += (end - start)
    return int(total * 1000)


def _snr(audio_ref: str | None) -> float | None:
    """Оценка SNR (librosa опционален). Нет librosa / не локальный файл → None (skip).

    VAD (Silero) НЕ тащим — заглушка с интерфейсом: боевая сборка отсекает hold/IVR.
    """
    if not audio_ref:
        return None
    try:
        import os  # noqa: PLC0415
        if not os.path.exists(audio_ref):
            return None
        import librosa  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        y, _sr = librosa.load(audio_ref, sr=16000, mono=True)
        rms = float(np.sqrt(np.mean(y ** 2))) if y.size else 0.0
        noise = float(np.percentile(np.abs(y), 10)) if y.size else 1e-9
        return 20.0 * float(np.log10((rms + 1e-9) / (noise + 1e-9)))
    except Exception as e:  # noqa: BLE001 — QC не должен ронять пайплайн
        logger.info("SNR не посчитан (%s) — шаг пропущен", e)
        return None


class AudioFetchError(Exception):
    """Запись недоступна у провайдера звонилки (сеть/сессия/нет файла)."""


def _noop() -> None:
    """Пустой cleanup для путей, которые не мы создавали."""


def _fetch_audio(call: dict) -> tuple[str | None, "callable"]:
    """Разрешить audio_ref в локальный путь + функция уборки.

    audio_ref из discover-таска — это crm.calls.recording_ref, т.е. КЛЮЧ записи
    на стороне Tegsoft, а не файл: скачиваем стримом во временный файл через
    tegsoft-адаптер (тот же путь, каким плеер карточки слушает запись).
    Локальный путь (тесты/ingest с файлом) и http-URL проходят как есть.
    """
    ref = call.get("audio_ref")
    if not ref:
        return None, _noop
    import os  # noqa: PLC0415
    if os.path.exists(ref):
        return ref, _noop
    if ref.startswith(("http://", "https://")):
        return ref, _noop                     # ASR-адаптер умеет URL напрямую
    if (call.get("source") or "tegsoft") != "tegsoft":
        raise AudioFetchError(f"неизвестный источник аудио: {call.get('source')!r}")
    import tempfile  # noqa: PLC0415
    tmp = tempfile.NamedTemporaryFile(prefix="ca_audio_", suffix=".mp3", delete=False)
    try:
        from tegsoft import get_provider  # noqa: PLC0415 — только при реальном звонке
        with tmp:
            for chunk in get_provider().stream_recording(ref):
                tmp.write(chunk)
        path = tmp.name
    except Exception as e:  # noqa: BLE001 — сеть/сессия/провайдер → понятная ошибка
        # недокачанный файл НЕ оставляем: сырое аудио не персистим даже при сбое (§11)
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise AudioFetchError(str(e)) from e

    def _cleanup() -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    return path, _cleanup


def _retry_asr(asr, audio_ref: str, language: str, channels: int) -> dict:
    """ASR с ретраем 3x exp (dev spec §7). Исчерпание → пробрасываем последнюю ошибку."""
    from call_analyzer.asr import ASRError  # noqa: PLC0415
    last: Exception | None = None
    for attempt in range(len(_ASR_RETRY_DELAYS) + 1):
        try:
            return asr.transcribe(audio_ref, language=language, channels=channels)
        except ASRError as e:
            last = e
            if attempt < len(_ASR_RETRY_DELAYS):
                time.sleep(_ASR_RETRY_DELAYS[attempt])
    raise last if last else RuntimeError("ASR failed")


# ── LLM-подшаги ───────────────────────────────────────────────────────────────────
def _score_llm(llm, cfg: Config, *, call: dict, transcript_text: str) -> tuple[dict, dict]:
    """Скоринг (dev spec §10.1-10.3, §8). Возвращает (валидный аудит, meta llm)."""
    user = prompts.build_scoring_user(
        call_id=call["call_id"], duration_s=call.get("duration_s"),
        operator_id=str(call.get("operator_id")),
        recommended_offer_id=call.get("recommended_offer_id"),
        transcript_lines=transcript_text, rubric_block=cfg.rubric_block,
    )
    system = prompts.SCORING_SYSTEM.format(output_lang=cfg.output_lang)
    raw = llm.complete_json(system, user, cfg.primary_model, temperature=0.1,
                            fallback_model=cfg.fallback_model)
    try:
        audit = validate.validate_audit(raw)  # §8: ровно 9 dims, score 1..5, enum'ы
    except validate.ValidationError as first_err:
        # JSON распарсился, но схема битая (8 критериев, левый enum…) — примари
        # «уверенно ошибся», ретраи в complete_json это не ловят. По §10.4 такой
        # провал тоже уходит на fallback-модель с ужесточённой инструкцией.
        raw = llm.complete_json(
            system, user + "\n\nReturn valid JSON exactly per the schema. "
            "All 9 dimensions required.", cfg.fallback_model, temperature=0.1)
        try:
            audit = validate.validate_audit(raw)
        except validate.ValidationError as e:
            raise e from first_err          # оба не смогли → llm_failed выше
    meta = getattr(llm, "last_meta", {}) or {}
    return audit, meta


def _offer_signal(llm, cfg: Config, *, call: dict, transcript_text: str) -> dict | None:
    """Экстракция оффер-сигнала (dev spec §10.5). best-effort."""
    try:
        user = prompts.SIGNAL_USER.format(
            player_id=call.get("casino_player_id"),
            recommended_offer_id=call.get("recommended_offer_id") or "NONE",
            transcript_lines=transcript_text)
        return llm.complete_json(prompts.SIGNAL_SYSTEM, user, cfg.primary_model,
                                 temperature=0.1, fallback_model=cfg.fallback_model)
    except Exception as e:  # noqa: BLE001
        logger.warning("offer_signal не извлечён для %s: %s", call["call_id"], e)
        return None


def _coaching_card(llm, cfg: Config, *, audit: dict) -> dict | None:
    """Коуч-карточка НА ТУРЕЦКОМ (dev spec §10.6). best-effort."""
    try:
        user = prompts.COACHING_USER.format(audit_json=json.dumps(audit, ensure_ascii=False))
        return llm.complete_json(prompts.COACHING_SYSTEM, user, cfg.primary_model,
                                 temperature=0.2, fallback_model=cfg.fallback_model)
    except Exception as e:  # noqa: BLE001
        logger.warning("coaching card не собрана: %s", e)
        return None


# ── главный оркестратор ───────────────────────────────────────────────────────────
def process_call(call_id: str, *, conn_factory=None, asr=None, llm=None,
                 cfg: Config | None = None, ch_client=None) -> PipelineResult:
    """Прогнать звонок по шагам §2. Возвращает PipelineResult (не бросает на сбоях звонка)."""
    from call_analyzer.asr import get_asr, ASRError  # noqa: PLC0415
    from call_analyzer.llm import get_llm, LLMError  # noqa: PLC0415
    from call_analyzer.pii import RedactError  # noqa: PLC0415
    from call_analyzer.validate import ValidationError  # noqa: PLC0415

    cf = conn_factory
    kw = {"conn_factory": cf} if cf else {}
    cfg = cfg or load_config(cf)
    asr = asr or get_asr(cfg.asr_provider)
    llm = llm or get_llm()
    t0 = time.time()

    call = db.get_call(call_id, **kw)
    if not call:
        return PipelineResult(call_id, "error", error="звонок не найден")

    # ── шаг 0: аудио — качаем запись у провайдера звонилки (crm recording_ref) ──
    cleanup = _noop
    try:
        audio_path, cleanup = _fetch_audio(call)
    except AudioFetchError as e:
        _fail_status(call_id, CallStatus.ASR_FAILED, kw)
        logger.error("аудио недоступно для %s: %s", call_id, e)
        return PipelineResult(call_id, CallStatus.ASR_FAILED.value,
                              error=f"аудио недоступно: {e}")

    try:
        # ── шаг 1: Audio QC (received → audio_checked; SNR < min → manual_review) ──
        _set_status(call_id, CallStatus.AUDIO_CHECKED, kw)
        snr = _snr(audio_path)
        if snr is not None:
            db.update_call_fields(call_id, snr=snr, **kw)
            if snr < cfg.snr_min:
                _set_status(call_id, CallStatus.MANUAL_REVIEW, kw)
                return PipelineResult(call_id, CallStatus.MANUAL_REVIEW.value)

        # ── шаг 2: ASR (retry 3x) ────────────────────────────────────────────────
        try:
            # вход всегда турецкий (dev spec §1); output_lang — язык рассуждений, не ASR
            asr_result = _retry_asr(asr, audio_path or "", "tr", call.get("channels", 1))
        except ASRError as e:
            _fail_status(call_id, CallStatus.ASR_FAILED, kw)
            logger.error("ASR failed для %s: %s", call_id, e)
            return PipelineResult(call_id, CallStatus.ASR_FAILED.value, error=str(e))
        _set_status(call_id, CallStatus.TRANSCRIBED, kw)

        # ── шаг 3: Диаризация (роли §6.3) ────────────────────────────────────────
        diar = roles.assign_roles(
            asr_result.get("words", []), channels=call.get("channels", 1),
            diar_conf_min=cfg.diar_conf_min, operator_channel=cfg.operator_channel,
            audio_path=audio_path)
        _set_status(call_id, CallStatus.DIARIZED, kw)
        if diar.low_diar_conf:
            db.add_flag(call_id, "low_diar_conf", **kw)  # dev spec §7

        # ── шаг 4: Redact (fail → транскрипт НЕ хранить, §7) ─────────────────────
        turns = build_turns(diar.words)
        try:
            red_lines = [pii.redact(ln, language="tr") for ln in format_lines(turns)]
            red_words = pii.redact_words(diar.words, language="tr")
        except RedactError as e:
            _fail_status(call_id, CallStatus.ERROR, kw)
            logger.error("redact failed для %s — транскрипт не сохранён: %s", call_id, e)
            return PipelineResult(call_id, CallStatus.ERROR.value, error=f"redact: {e}")
        text_redacted = "\n".join(red_lines)
        db.upsert_transcript(call_id, asr_provider=asr_result.get("provider", asr.name if hasattr(asr, "name") else "?"),
                             language="tr", text_redacted=text_redacted, words=red_words,
                             diarization_conf=diar.diarization_conf, **kw)
        _set_status(call_id, CallStatus.REDACTED, kw)

        # ── флаги подлинности §11.4 (нужна отметка оператора из crm.calls) ───────
        p_ms = player_speech_ms(diar.words)
        db.update_call_fields(call_id, player_speech_ms=p_ms, **kw)
        crm_outcome = db.get_crm_outcome(call.get("crm_call_id"), **kw)
        for f in authenticity.compute_flags(duration_s=call.get("duration_s"),
                                            player_speech_ms=p_ms, crm_outcome=crm_outcome,
                                            too_short_s=cfg.too_short_s):
            db.add_flag(call_id, f, **kw)

        # ── шаг 5-6: Score + компрессия + валидация + подсчёт кодом ──────────────
        scoring_text = compress_transcript(
            red_lines, summarizer=lambda t: llm.summarize(t, cfg.fallback_model))
        try:
            audit, meta = _score_llm(llm, cfg, call=call, transcript_text=scoring_text)
        except (LLMError, ValidationError) as e:
            _fail_status(call_id, CallStatus.LLM_FAILED, kw)
            logger.error("scoring failed для %s: %s", call_id, e)
            return PipelineResult(call_id, CallStatus.LLM_FAILED.value, error=str(e))
        _set_status(call_id, CallStatus.SCORED, kw)

        dims = audit["dimensions"]
        overall = scoring.overall_score(dims, cfg.weights)
        needs_human = scoring.audit_needs_human(dims, audit.get("needs_human", False))
        verdict = scoring.pass_fail(overall, needs_human, cfg.pass_threshold, cfg.review_low)

        # скрипт оператора этого звонка (A/B, 0010): под какую версию его судить
        try:
            script_version = db.resolve_script_version(
                str(call.get("operator_id")) if call.get("operator_id") else None, **kw)
        except Exception as e:  # noqa: BLE001 — резолв не должен ронять оценку
            logger.warning("resolve script для %s не удался: %s", call_id, e)
            script_version = None

        audit_row = {
            "call_id": call_id, "prompt_version": cfg.prompt_version,
            "rubric_version": cfg.rubric_version, "script_version": script_version,
            "model_used": meta.get("model", cfg.primary_model),
            "overall_score_100": overall, "pass_fail": verdict,
            "dimensions": dims, "objections": audit.get("objections", []),
            "offer_outcome": audit.get("offer_outcome"),
            "coaching_narrative": audit.get("coaching_narrative"),
            "highlights": audit.get("highlights", []),
            "improvement_areas": audit.get("improvement_areas", []),
            "needs_human": needs_human, "llm_tokens": meta.get("tokens"),
            "processing_ms": int((time.time() - t0) * 1000),
        }
        audit_id = db.upsert_audit(audit_row, **kw)  # идемпотентно (dev spec §2)

        # ── шаг 8a: ClickHouse (best-effort, dev spec §4.2) ─────────────────────
        clickhouse.write_audit_flat({
            **audit_row, "operator_id": call.get("operator_id"),
            "casino_id": call.get("casino_id", "default"),
            "duration_s": call.get("duration_s"),
            "audit_json": json.dumps(audit, ensure_ascii=False),
        }, client=ch_client)

        # ── шаг 7: оффер-сигнал (§10.5) ─────────────────────────────────────────
        sig = _offer_signal(llm, cfg, call=call, transcript_text=scoring_text)
        if sig:
            db.upsert_offer_signal({
                "call_id": call_id, "casino_player_id": call.get("casino_player_id"),
                "recommended_offer_id": sig.get("recommended_offer_id") or call.get("recommended_offer_id"),
                "offer_presented": bool(sig.get("offer_presented", False)),
                "player_response": sig.get("player_response"),
                "alt_offer_worked": sig.get("alt_offer_worked"),
                "refusal_reason": sig.get("refusal_reason"),
                "callback_scheduled": sig.get("callback_scheduled"),
            }, **kw)

        # ── шаг 8b: коуч-карточка (§10.6, TR) ───────────────────────────────────
        card = _coaching_card(llm, cfg, audit=audit)
        if card and card.get("tips"):
            db.insert_coaching_card({
                "call_id": call_id, "operator_id": call.get("operator_id"),
                "tips": card["tips"],
            }, **kw)

        # ── финал: scored → needs_review | completed ────────────────────────────
        final = CallStatus.NEEDS_REVIEW if needs_human else CallStatus.COMPLETED
        _set_status(call_id, final, kw)
        return PipelineResult(call_id, final.value, overall_score_100=overall,
                              pass_fail=verdict, audit_id=audit_id)

    except Exception as e:  # noqa: BLE001 — любой неожиданный сбой = error, очередь жива
        logger.exception("process_call неожиданно упал для %s", call_id)
        _fail_status(call_id, CallStatus.ERROR, kw)
        return PipelineResult(call_id, CallStatus.ERROR.value, error=str(e))
    finally:
        cleanup()   # временный файл записи (сырое аудио не персистим, dev spec §11)
