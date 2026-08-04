"""Промпты и шаблоны LLM (dev spec §10).

Статичные строки: system + рубрика кэшируются на стороне провайдера (prompt
caching). Здесь только текст и сборка — никаких сетевых вызовов и зависимостей,
модуль обязан импортироваться где угодно (его тянут config.py и pipeline.py).

Язык рассуждений модели — {output_lang} (ru/en). Вход всегда турецкий транскрипт
строками вида "[mm:ss] AGENT: ..." / "[mm:ss] PLAYER: ...".
"""
from __future__ import annotations

# ── Рубрика v1 (dev spec §10.3). Дефолт конфига; боевая приходит из settings.config.
RUBRIC_V1_BLOCK = """Score each dimension 1-5 (1=poor, 3=meets standard, 5=exceptional).
- open_identify: greeted, named the brand, friendly opener
- rapport: built contact, addressed the player by name
- discovery: asked >=1 question about inactivity reason / player need
- offer_presented: stated the recommended offer.
    If recommended_offer_id == NONE, score=3 and needs_human=true (cannot verify)
- offer_value: explained the offer's value, not just "there is a bonus"
- objection_handling: addressed the player's objection (no money / no time / lost before)
- alt_offer: if the offer was refused, proposed an alternative
- next_step: fixed a concrete next step / callback date
- tone (subjective): not pushy, did not interrupt. needs_human=true if confidence<0.7"""

# ── System-промпт скоринга (dev spec §10.1). {output_lang} подставляется. ──────────
SCORING_SYSTEM = """You are an expert QA auditor for an iGaming RETENTION call center.
Input: a diarized Turkish transcript of an OUTBOUND call where an OPERATOR
calls a lapsing PLAYER to bring them back with a recommended bonus offer.
Score the OPERATOR against the rubric. Judge ONLY what the transcript supports.
Do NOT infer intent. Cite exact timestamps as evidence. Be fair and specific.
For a subjective dimension, if your confidence < 0.7, set that dimension's needs_human=true.
Return ONLY valid JSON per the schema. No preamble, no markdown fences.
Write all reasoning fields in {output_lang}."""

# ── User-шаблон скоринга (dev spec §10.2) ─────────────────────────────────────────
SCORING_USER = """## Call
call_id: {call_id} | duration_s: {duration_s} | operator_id: {operator_id}
recommended_offer_id: {recommended_offer_id}

## Transcript (diarized, Turkish; lines "[mm:ss] AGENT: ..." / "[mm:ss] PLAYER: ...")
{transcript_lines}

## Rubric
{rubric_block}

## Return JSON per schema. All 9 dimensions required.
Schema keys: prompt_version, model_used, dimensions[{{name,score,justification,evidence_ts,needs_human}}],
objections[{{type,handled,reason}}], offer_outcome, needs_human, coaching_narrative,
highlights[], improvement_areas[]."""

# ── Экстракция оффер-сигнала (dev spec §10.5) ─────────────────────────────────────
SIGNAL_SYSTEM = """From transcript + operator note (if any) output ONLY valid JSON:
{"player_id": str, "recommended_offer_id": str|null, "offer_presented": bool,
 "player_response": "accepted|refused|countered|deferred",
 "alt_offer_worked": bool|null,
 "refusal_reason": "no_money|no_time|distrust|competitor|other"|null,
 "callback_scheduled": "ISO-8601"|null}
Only fields grounded in the transcript. No guessing. No markdown fences."""

SIGNAL_USER = """## Call
player_id: {player_id} | recommended_offer_id: {recommended_offer_id}

## Transcript
{transcript_lines}

Return ONLY the JSON object."""

# ── Коуч-карточка (dev spec §10.6). СОВЕТЫ НА ТУРЕЦКОМ — язык оператора. ──────────
COACHING_SYSTEM = """Given the audit JSON, write 2-3 specific coaching tips.
Reference exact timestamps ("skipped the offer at 01:12"). Concrete, not generic.
Encouraging tone. Max 60 words total. Write the tips in TURKISH (operator's language).
Return ONLY {"tips":[{"ts":"mm:ss","text":"..."}]}. No markdown fences."""

COACHING_USER = """## Audit
{audit_json}

Return ONLY the JSON with Turkish tips."""

# ── Компрессия середины длинного транскрипта (dev spec §10.8) ─────────────────────
COMPRESS_SYSTEM = """Summarize this middle section of a Turkish retention-call transcript
in 3-5 short Turkish sentences. Keep any objection or offer moment. No fences, plain text."""

# ── Перевод транскрипта on-demand (интерфейс §5) ──────────────────────────────────
TRANSLATE_SYSTEM = """You are a professional translator. Translate the Turkish call
transcript into {target_lang}. Preserve the line structure and the "[mm:ss] ROLE:"
prefixes exactly. Translate only the spoken text. Return plain text, no commentary."""


def format_ts(seconds: float) -> str:
    """Секунды → "mm:ss" (таймкоды в промпте и подсветке доказательств)."""
    s = max(0, int(round(seconds)))
    return f"{s // 60:02d}:{s % 60:02d}"


def build_scoring_user(*, call_id: str, duration_s: int | None, operator_id: str,
                       recommended_offer_id: str | None, transcript_lines: str,
                       rubric_block: str) -> str:
    """Собрать user-промпт скоринга (dev spec §10.2). NONE вместо пустого оффера."""
    return SCORING_USER.format(
        call_id=call_id,
        duration_s=duration_s if duration_s is not None else "?",
        operator_id=operator_id,
        recommended_offer_id=recommended_offer_id or "NONE",
        transcript_lines=transcript_lines,
        rubric_block=rubric_block,
    )
