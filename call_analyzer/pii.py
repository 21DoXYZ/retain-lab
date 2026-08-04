"""Редакция персональных данных ДО хранения (dev spec §11).

Regex-паттерны турецких PII + необязательный слой Presidio (NER PERSON/LOCATION).
Presidio импортируется опционально: установлен — добавляет распознавание имён и
адресов; нет — работает только regex. Так пайплайн живёт и без тяжёлой зависимости.

Redact fail → RedactError. Пайплайн ловит её и НЕ сохраняет транскрипт (§7):
сырую речь с номерами/картами не персистим ни при каких обстоятельствах.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("call_analyzer.pii")


class RedactError(RuntimeError):
    """Не удалось отредактировать текст → транскрипт хранить нельзя (dev spec §7)."""


# ── Regex-паттерны (dev spec §11) ─────────────────────────────────────────────────
# Порядок применения важен: карта (16 цифр) → телефон → TC kimlik (11 цифр) → email.
# Иначе телефонный шаблон `0\d{10}` откусит часть 16-значной карты.
_CARD_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
# Телефон TR: 5XXXXXXXXX / 05XXXXXXXXX / +90XXXXXXXXXX / 0XXXXXXXXXX.
# Границы через lookaround по цифрам, а не \b: иначе `\b` перед `+` (не-словом)
# не срабатывает и +90… не редактируется (dev spec §11 — паттерн тот же, якорь надёжнее).
# ВАЖНО: ASR отдаёт номера ГРУППАМИ («0555 123 45 67») — между группами цифр
# допускаем пробел/дефис, иначе сырой номер уезжает в хранилище (провал DoD §17.3).
_SEP = r"[\s-]?"
_PHONE_RE = re.compile(
    r"(?<!\d)(?:"
    r"\+?90" + _SEP + r"5\d{2}" + _SEP + r"\d{3}" + _SEP + r"\d{2}" + _SEP + r"\d{2}"   # +90 5xx xxx xx xx
    r"|0?5\d{2}" + _SEP + r"\d{3}" + _SEP + r"\d{2}" + _SEP + r"\d{2}"                  # (0)5xx xxx xx xx
    r"|0\d{3}" + _SEP + r"\d{3}" + _SEP + r"\d{2}" + _SEP + r"\d{2}"                    # 0xxx xxx xx xx (стационар)
    r")(?!\d)")
_TC_RE = re.compile(r"\b\d{11}\b")  # TC kimlik — 11 цифр
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# (паттерн, замена) — применяются строго в этом порядке.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (_CARD_RE, "[CARD]"),
    (_PHONE_RE, "[PHONE]"),
    (_TC_RE, "[TC]"),
    (_EMAIL_RE, "[EMAIL]"),
)


def redact_regex(text: str) -> str:
    """Только regex-редакция (dev spec §11). Детерминирована, без зависимостей."""
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text


def _presidio_redact(text: str, language: str) -> str | None:
    """NER-слой Presidio (PERSON/LOCATION). None — если Presidio не установлен.

    Полностью опционален: отсутствие пакета не ошибка, просто regex-only режим.
    """
    try:
        from presidio_analyzer import AnalyzerEngine  # noqa: PLC0415
        from presidio_anonymizer import AnonymizerEngine  # noqa: PLC0415
    except ImportError:
        return None
    analyzer = AnalyzerEngine()
    results = analyzer.analyze(text=text, language=language,
                               entities=["PERSON", "LOCATION"])
    if not results:
        return text
    anonymizer = AnonymizerEngine()
    return anonymizer.anonymize(text=text, analyzer_results=results).text


def redact(text: str, *, language: str = "tr", use_presidio: bool = True) -> str:
    """Полная редакция: regex всегда + Presidio, если доступен и включён.

    Бросает RedactError при любом сбое — вызывающий обязан НЕ хранить транскрипт.
    """
    if text is None:
        raise RedactError("нечего редактировать: text is None")
    try:
        redacted = redact_regex(text)
        if use_presidio:
            ner = _presidio_redact(redacted, language)
            if ner is not None:
                redacted = redact_regex(ner)  # regex поверх NER — на всякий случай
        return redacted
    except RedactError:
        raise
    except Exception as e:  # noqa: BLE001 — любой сбой редакции = не хранить
        raise RedactError(f"редакция PII не удалась: {e}") from e


def redact_words(words: list[dict], *, language: str = "tr") -> list[dict]:
    """Редакция пословного списка (analyzer.transcripts.words).

    Каждый токен `w` прогоняется через regex: одиночные email/длинные числа не
    должны утекать и в пословном представлении. Presidio по словам не гоняем —
    он контекстный, по токенам бесполезен. Роли/таймкоды не трогаем.
    """
    out: list[dict] = []
    for w in words:
        token = w.get("w", "")
        out.append({**w, "w": redact_regex(token) if isinstance(token, str) else token})
    return out
