"""Машина состояний пайплайна (dev spec §3).

ЕДИНСТВЕННАЯ точка смены статуса. Любое обновление analyzer.calls.status идёт
через check_transition() — запрещённый переход падает исключением, а не тихо
пишет мусор в БД. Значения enum совпадают с analyzer.call_status (миграция 0007).
"""
from __future__ import annotations

from enum import Enum


class CallStatus(str, Enum):
    """analyzer.call_status. str-Enum: .value годится напрямую для psycopg."""
    RECEIVED = "received"
    AUDIO_CHECKED = "audio_checked"
    MANUAL_REVIEW = "manual_review"
    TRANSCRIBED = "transcribed"
    DIARIZED = "diarized"
    REDACTED = "redacted"
    SCORED = "scored"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    ASR_FAILED = "asr_failed"
    LLM_FAILED = "llm_failed"
    ERROR = "error"


class TransitionError(RuntimeError):
    """Запрещённый переход состояния (dev spec §3)."""


# Терминальные сбои: достижимы из ЛЮБОГО нетерминального состояния (правило `* → …`).
TERMINAL_FAILURES: frozenset[CallStatus] = frozenset(
    {CallStatus.ASR_FAILED, CallStatus.LLM_FAILED, CallStatus.ERROR}
)

# Терминальные состояния — выхода нет.
TERMINAL: frozenset[CallStatus] = TERMINAL_FAILURES | {CallStatus.COMPLETED}

# Разрешённые «прямые» переходы happy-path и ветвлений (dev spec §3).
# Терминальные сбои сюда НЕ включены — они обрабатываются отдельным правилом `*`.
_ALLOWED: dict[CallStatus, frozenset[CallStatus]] = {
    CallStatus.RECEIVED: frozenset({CallStatus.AUDIO_CHECKED}),
    CallStatus.AUDIO_CHECKED: frozenset({CallStatus.TRANSCRIBED, CallStatus.MANUAL_REVIEW}),
    CallStatus.MANUAL_REVIEW: frozenset({CallStatus.TRANSCRIBED}),
    CallStatus.TRANSCRIBED: frozenset({CallStatus.DIARIZED}),
    CallStatus.DIARIZED: frozenset({CallStatus.REDACTED}),
    CallStatus.REDACTED: frozenset({CallStatus.SCORED}),
    CallStatus.SCORED: frozenset({CallStatus.COMPLETED, CallStatus.NEEDS_REVIEW}),
    CallStatus.NEEDS_REVIEW: frozenset({CallStatus.COMPLETED}),
    CallStatus.COMPLETED: frozenset(),
    CallStatus.ASR_FAILED: frozenset(),
    CallStatus.LLM_FAILED: frozenset(),
    CallStatus.ERROR: frozenset(),
}


# Порядковый ранг happy-path (для идемпотентного повтора пайплайна, dev spec §2):
# повтор process_call не должен падать на строгой машине — «назад/на месте» = no-op.
_ORDER: dict[CallStatus, int] = {
    CallStatus.RECEIVED: 0,
    CallStatus.AUDIO_CHECKED: 1,
    CallStatus.MANUAL_REVIEW: 1,
    CallStatus.TRANSCRIBED: 2,
    CallStatus.DIARIZED: 3,
    CallStatus.REDACTED: 4,
    CallStatus.SCORED: 5,
    CallStatus.NEEDS_REVIEW: 6,
    CallStatus.COMPLETED: 7,
}


def rank(status: CallStatus | str) -> int:
    """Ранг статуса на happy-path. Терминальные сбои → -1 (вне линии)."""
    return _ORDER.get(_coerce(status), -1)


def _coerce(status: CallStatus | str) -> CallStatus:
    return status if isinstance(status, CallStatus) else CallStatus(status)


def is_allowed(src: CallStatus | str, dst: CallStatus | str) -> bool:
    """True, если переход src→dst разрешён (dev spec §3)."""
    src, dst = _coerce(src), _coerce(dst)
    if src in TERMINAL:
        return False  # из терминального состояния уйти нельзя
    if dst in TERMINAL_FAILURES:
        return True   # `* → asr_failed | llm_failed | error`
    return dst in _ALLOWED.get(src, frozenset())


def check_transition(src: CallStatus | str, dst: CallStatus | str) -> CallStatus:
    """Проверить переход; вернуть целевой статус или бросить TransitionError."""
    src_c, dst_c = _coerce(src), _coerce(dst)
    if not is_allowed(src_c, dst_c):
        raise TransitionError(f"недопустимый переход статуса: {src_c.value} → {dst_c.value}")
    return dst_c
