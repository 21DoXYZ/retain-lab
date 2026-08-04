"""Подсчёт итогового балла и вердикта — ЕДИНСТВЕННАЯ реализация (dev spec §9).

Балл считает КОД, не LLM — и при первичной оценке (пайплайн), и при правке
руководителем (Flask api/call_analysis.py). Оба импортируют ЭТОТ модуль:
вторая реализация формулы запрещена, расхождение баллов = сломанная сверка.

Правило needs_human: критерии, которые модель не смогла оценить уверенно,
исключаются из суммы, веса остальных ренормируются на 100. Выключенные
скриптом критерии (§8 интерфейса) исключаются тем же механизмом до вызова.
"""
from __future__ import annotations

# Веса рубрики v1 (dev spec §9, сумма = 100). Боевые веса приходят из
# analyzer.settings.config.weights; это — дефолт, если конфиг пуст.
DEFAULT_WEIGHTS: dict[str, int] = {
    'open_identify': 5,
    'rapport': 10,
    'discovery': 15,
    'offer_presented': 15,
    'offer_value': 15,
    'objection_handling': 20,
    'alt_offer': 5,
    'next_step': 10,
    'tone': 5,
}

CRITERIA = tuple(DEFAULT_WEIGHTS)          # канонический словарь из 9 критериев
PASS_THRESHOLD_DEFAULT = 70
REVIEW_LOW_DEFAULT = 50


def overall_score(dimensions: list[dict], weights: dict[str, int] | None = None) -> int | None:
    """overall_score_100 по dev spec §9.

    dimensions: [{"name": str, "score": 1..5, "needs_human": bool, ...}].
    Критерий с needs_human=true (или отсутствующий в weights — выключен скриптом)
    исключается; веса включённых ренормируются на 100.
    Все исключены → None (pass_fail = NEEDS_REVIEW).
    """
    w = weights or DEFAULT_WEIGHTS
    included = [d for d in dimensions
                if not d.get('needs_human') and d.get('name') in w]
    total_w = sum(w[d['name']] for d in included)
    if not total_w:
        return None
    raw = sum(d['score'] / 5 * w[d['name']] for d in included)
    return round(raw / total_w * 100)


def pass_fail(score: int | None, needs_human: bool,
              pass_threshold: int = PASS_THRESHOLD_DEFAULT,
              review_low: int = REVIEW_LOW_DEFAULT) -> str:
    """PASS | NEEDS_REVIEW | FAIL (dev spec §9). needs_human всегда побеждает."""
    if needs_human or score is None:
        return 'NEEDS_REVIEW'
    if score >= pass_threshold:
        return 'PASS'
    if score >= review_low:
        return 'NEEDS_REVIEW'
    return 'FAIL'


def audit_needs_human(dimensions: list[dict], llm_needs_human: bool) -> bool:
    """needs_human аудита = хотя бы один критерий ИЛИ флаг верхнего уровня LLM."""
    return bool(llm_needs_human or any(d.get('needs_human') for d in dimensions))


def recompute_after_override(model_dimensions: list[dict],
                             human_scores: dict[str, int],
                             weights: dict[str, int] | None = None) -> int | None:
    """Пересчёт итога после правки руководителя (интерфейс §10.4).

    Человек правит ПО КРИТЕРИЯМ; его балл заменяет модельный, включая критерии,
    которые модель пометила needs_human (человек их оценил → они в подсчёте).
    Не тронутые человеком needs_human-критерии остаются исключёнными.
    """
    merged: list[dict] = []
    for d in model_dimensions:
        name = d.get('name')
        if name in human_scores:
            merged.append({'name': name, 'score': human_scores[name], 'needs_human': False})
        else:
            merged.append(d)
    return overall_score(merged, weights)
