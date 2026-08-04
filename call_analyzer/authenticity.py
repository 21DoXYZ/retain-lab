"""Флаги подлинности звонка (интерфейс §11.4).

Это НЕ обвинение — повод послушать. Слов «обман/накрутка» в интерфейсе нет:
экран говорит, что увидел, вердикт ставит человек. Значения флагов совпадают со
столбцом «Внутри» таблицы §11.4 и пишутся в analyzer.calls.flags (jsonb-массив).

Сверка «отметка не сходится» опирается на crm.calls.outcome (по crm_call_id):
без отметки оператора оба mark_mismatch не работают (§12, ограничения данных).
"""
from __future__ import annotations

# Значения флагов (интерфейс §11.4).
TOO_SHORT = "too_short"
NO_PLAYER_SPEECH = "no_player_speech"
MARK_MISMATCH_NO_ANSWER = "mark_mismatch_no_answer"
MARK_MISMATCH_CLAIMED = "mark_mismatch_claimed"
REPEATED_PATTERN = "repeated_pattern"
RANDOM_REVIEW = "random_review"

# crm.call_outcome: только 'answered' = «дозвонился/поговорил». Прочее = «не дозвонился».
_ANSWERED = "answered"


def compute_flags(*, duration_s: int | None, player_speech_ms: int | None,
                  crm_outcome: str | None, too_short_s: int = 10) -> list[str]:
    """Флаги одного звонка (кроме repeated_pattern — он межзвонковый).

    - too_short: короче порога (дефолт 10с).
    - no_player_speech: player_speech_ms == 0 (игрок молчал).
    - mark_mismatch_no_answer: отмечено «не дозвонился», но игрок говорил.
    - mark_mismatch_claimed: отмечено «поговорил», но игрок молчал.
    """
    flags: list[str] = []

    if duration_s is not None and duration_s < too_short_s:
        flags.append(TOO_SHORT)

    player_silent = player_speech_ms == 0  # только явный ноль, не None
    if player_silent:
        flags.append(NO_PLAYER_SPEECH)

    if crm_outcome is not None:
        answered_mark = crm_outcome == _ANSWERED
        # «не дозвонился» по отметке, но разговор был (игрок реально говорил).
        if not answered_mark and player_speech_ms is not None and player_speech_ms > 0:
            flags.append(MARK_MISMATCH_NO_ANSWER)
        # «поговорил» по отметке, но игрок молчал.
        if answered_mark and player_silent:
            flags.append(MARK_MISMATCH_CLAIMED)

    return flags


def repeated_run_length(durations: list[int | float], *, short_s: int) -> int:
    """Максимальная длина серии подряд идущих коротких звонков (< short_s)."""
    best = run = 0
    for d in durations:
        if d is not None and d < short_s:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def detect_repeated_pattern(durations: list[int | float], *, short_s: int = 10,
                            min_run: int = 5) -> bool:
    """>= min_run коротких звонков подряд у оператора за день (интерфейс §11.4)."""
    return repeated_run_length(durations, short_s=short_s) >= min_run
