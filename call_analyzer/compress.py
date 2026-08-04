"""Компрессия длинного транскрипта перед скорингом (dev spec §10.8).

Если грубая оценка токенов > порога: дословно оставляем первые/последние 5 реплик
и реплики с маркером возражения/оффера, середину — сжимаем дешёвой (fallback)
моделью. Иначе — passthrough. Токены считаем грубо: len/3.5 (dev spec §8 указывает
именно грубый счёт, без токенайзера-зависимости).
"""
from __future__ import annotations

from typing import Callable

TOKENS_PER_CHAR = 1 / 3.5
DEFAULT_MAX_TOKENS = 6000
_KEEP_EDGE = 5  # первых/последних реплик дословно

# Маркеры «важной» реплики (возражение/оффер) — турецкие + общие (dev spec §10.8).
_KEYWORDS = (
    "param yok", "zaman", "kaybett", "bonus", "teklif", "freespin",
    "bedava", "depozito", "güvenmiyor", "geri ara", "indirim",
)


def estimate_tokens(text: str) -> int:
    """Грубая оценка токенов: len/3.5 (dev spec §8)."""
    return int(len(text) * TOKENS_PER_CHAR)


def _is_flagged(line: str) -> bool:
    low = line.lower()
    return any(k in low for k in _KEYWORDS)


def compress_transcript(lines: list[str], *, summarizer: Callable[[str], str] | None = None,
                        max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """Вернуть транскрипт для скоринга: passthrough или сжатый (dev spec §10.8).

    lines — реплики "[mm:ss] ROLE: text". summarizer(middle_text)->str сжимает
    середину (обычно fallback-модель). Без summarizer середина заменяется меткой —
    детерминированно и без сети (для тестов и офлайна).
    """
    full = "\n".join(lines)
    if estimate_tokens(full) <= max_tokens or len(lines) <= 2 * _KEEP_EDGE:
        return full

    head = lines[:_KEEP_EDGE]
    tail = lines[-_KEEP_EDGE:]
    middle = lines[_KEEP_EDGE:-_KEEP_EDGE]

    kept_flagged = [ln for ln in middle if _is_flagged(ln)]
    plain_middle = [ln for ln in middle if not _is_flagged(ln)]

    if plain_middle:
        middle_text = "\n".join(plain_middle)
        summary = summarizer(middle_text) if summarizer else "[... orta bölüm kısaltıldı ...]"
    else:
        summary = ""

    parts = head + kept_flagged
    if summary:
        parts.append(summary)
    parts += tail
    return "\n".join(p for p in parts if p)
