"""api/casino_vocab.py — ВОКАБУЛЯР казино (типы/статусы транзакций) как КОНФИГ.

Единый источник значений для условий «успешной операции». Раньше типы/статусы
были захардкожены в player_board.py:116-124 и продублированы в report_fields.py
под спеку BillionBahis. На другом казино (напр. VivaJack у Лолиты) вокабуляр
статусов/типов отличается → весь борд и конструктор отчётов возвращали 0.

Теперь значения берутся из env (дефолты = текущие BillionBahis, поведение не
меняется). На новом тенанте достаточно выставить переменные окружения, без правки
кода. Модуль НАМЕРЕННО без тяжёлых зависимостей (только os) — его импортируют и
player_board, и чистый report_fields.

Собираем только СПИСКИ значений; SQL-фрагменты строит каждый потребитель сам
(player_board — без префикса, report_fields — с `f.`), через in_list().
"""
from __future__ import annotations

import os


def _csv(name: str, default: list[str]) -> list[str]:
    """Список из env "a,b,c" (пусто/не задано → дефолт). Пробелы обрезаются."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return list(default)
    return [v.strip() for v in raw.split(",") if v.strip()]


# ── money: статусы успеха и типы кэш-операций/бонусов ──
SUCCESS_STATUSES = _csv("CASINO_SUCCESS_STATUSES", ["completed", "approved", "success"])
DEPOSIT_TYPES = _csv("CASINO_DEPOSIT_TYPES", ["deposit"])
WITHDRAWAL_TYPES = _csv("CASINO_WITHDRAWAL_TYPES", ["withdrawal"])
BONUS_TYPES = _csv("CASINO_BONUS_TYPES", ["bonus", "manual_bonus", "freespin"])
BONUS_WAGED_TYPES = _csv("CASINO_BONUS_WAGED_TYPES", ["bonus_conversion"])

# ── game: статус успеха и типы ставок/выигрышей ──
GAME_SUCCESS_STATUSES = _csv("CASINO_GAME_SUCCESS_STATUSES", ["completed"])
BET_TYPES = _csv("CASINO_BET_TYPES", ["bet", "freespins_bet"])
WIN_TYPES = _csv("CASINO_WIN_TYPES", ["win", "freespins_win"])


def in_list(col: str, values: list[str]) -> str:
    """SQL «col IN ('a','b')». Пустой список → «1=0» (ничего не матчит, не падает)."""
    if not values:
        return "1=0"
    quoted = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
    return f"{col} IN ({quoted})"
