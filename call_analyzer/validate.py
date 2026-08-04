"""Валидатор JSON-вывода скоринга (dev spec §8).

strip ```-fences → json.loads → ровно 9 dimensions с валидными name → каждый
score ∈ 1..5 → offer_outcome и objections[].type в enum. Провал → ValidationError,
пайплайн уходит в ретрай/fallback (dev spec §7). overall_score_100/pass_fail тут
НЕ считаются — это делает scoring.py по валидному объекту.
"""
from __future__ import annotations

import json
import re

from call_analyzer.scoring import CRITERIA  # 9 канонических критериев (импорт, не правка)

# Разрешённые enum'ы (dev spec §8).
OFFER_OUTCOMES: frozenset[str] = frozenset(
    {"accepted", "refused", "countered", "no_offer", "unclear"}
)
OBJECTION_TYPES: frozenset[str] = frozenset(
    {"no_money", "no_time", "lost_before", "distrust", "other"}
)
_VALID_NAMES: frozenset[str] = frozenset(CRITERIA)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class ValidationError(ValueError):
    """LLM вернула структурно неверный JSON (dev spec §8)."""


def strip_fences(text: str) -> str:
    """Снять markdown-ограждения ```json ... ``` вокруг ответа модели."""
    t = text.strip()
    if t.startswith("```"):
        t = _FENCE_RE.sub("", t)
        # хвостовой ``` мог остаться, если модель закрыла с новой строки
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def parse_json(text: str) -> dict:
    """strip fences → json.loads. Не-JSON → ValidationError (dev spec §8)."""
    try:
        obj = json.loads(strip_fences(text))
    except (json.JSONDecodeError, TypeError) as e:
        raise ValidationError(f"невалидный JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ValidationError("ожидался JSON-объект верхнего уровня")
    return obj


def validate_audit(payload: dict | str) -> dict:
    """Проверить объект аудита по схеме §8. Возвращает нормализованный dict.

    payload — уже распарсенный dict или сырой текст модели.
    """
    obj = parse_json(payload) if isinstance(payload, str) else payload
    if not isinstance(obj, dict):
        raise ValidationError("аудит должен быть объектом")

    dims = obj.get("dimensions")
    if not isinstance(dims, list) or len(dims) != 9:
        raise ValidationError(f"ожидалось ровно 9 dimensions, получено {len(dims) if isinstance(dims, list) else 'не-список'}")

    seen: set[str] = set()
    for d in dims:
        if not isinstance(d, dict):
            raise ValidationError("dimension должен быть объектом")
        name = d.get("name")
        if name not in _VALID_NAMES:
            raise ValidationError(f"неизвестный критерий: {name!r}")
        if name in seen:
            raise ValidationError(f"дублируется критерий: {name!r}")
        seen.add(name)
        score = d.get("score")
        if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 5):
            raise ValidationError(f"score критерия {name!r} должен быть int 1..5, получено {score!r}")
        if not isinstance(d.get("needs_human", False), bool):
            raise ValidationError(f"needs_human критерия {name!r} должен быть bool")

    if seen != _VALID_NAMES:
        missing = _VALID_NAMES - seen
        raise ValidationError(f"не все критерии присутствуют, нет: {sorted(missing)}")

    outcome = obj.get("offer_outcome")
    if outcome not in OFFER_OUTCOMES:
        raise ValidationError(f"offer_outcome вне enum: {outcome!r}")

    objections = obj.get("objections", [])
    if not isinstance(objections, list):
        raise ValidationError("objections должен быть списком")
    for o in objections:
        if not isinstance(o, dict) or o.get("type") not in OBJECTION_TYPES:
            raise ValidationError(f"objection.type вне enum: {o!r}")

    if not isinstance(obj.get("needs_human", False), bool):
        raise ValidationError("needs_human верхнего уровня должен быть bool")

    return obj
