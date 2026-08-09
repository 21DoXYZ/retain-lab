"""Методология текстов как код (METHODOLOGY.md §8).

Валидатор конверсионного письма: посыл, конкретика, один CTA, запреты.
Гоняется по ЛЮБОМУ тексту касания - сгенерированному моделью (ai_compose
отбрасывает невалидные шаги) и написанному руками (экран кампаний флажит).

Флаги - коды с параметрами, не готовые фразы: их читают UI, логи и тесты.
Уровни: fatal (текст не должен уйти) / warn (уйдёт, но владельцу показываем).
"""

from __future__ import annotations

import re

MAX_WORDS = 130
MIN_WORDS = 12

# Крик и спам-триггеры. Восклицание - не «энергия», а девальвация: письмо,
# которому нужен «!», не имеет посыла. CAPS и hurry-лексика дополнительно
# бьют по доставляемости.
_SHOUT_WORDS = re.compile(
    r"\b(hurry|act now|last chance|don'?t miss|limited time|urgent|"
    r"don'?t wait|final hours)\b", re.I)
_CAPS_WORD = re.compile(r"\b[A-Z]{4,}\b")
_LINK = re.compile(r"(\{\{\w*url\w*\}\}|https?://\S+)")

# Обещания-способности: их можно давать только если профиль подтверждает.
# ПРЕДЛОЖЕНИЕ паузы («you can pause», «pause your plan») - обещание фичи;
# ОПИСАНИЕ последствия («your subscription pauses if...») - честный факт
# биллинга, он разрешён всегда.
_PAUSE_PROMISE = re.compile(
    r"\b(you can pause|pause (your|my|the) (plan|subscription|billing)|"
    r"pause instead|pause it for)\b", re.I)
_TRIAL_EXTEND_PROMISE = re.compile(
    r"\b(extend(ed)?\s+(your\s+)?trial|extra\s+(trial\s+)?days|"
    r"trial\s+(got\s+)?extended)\b", re.I)
_LEAVER_TALK = re.compile(
    r"\b(since you (left|canceled|cancelled)|you canceled|you cancelled|"
    r"welcome back)\b", re.I)


def _words(text: str) -> int:
    return len(re.findall(r"[\w'-]+", text or ""))


def profile_terms(profile: dict) -> list[str]:
    """Термины продукта, хотя бы один обязан быть в теле письма: без единого
    факта продукта письмо - генерик, а генерик не конвертит."""
    out = []
    for key in ("product_name", "value_unit"):
        v = str(profile.get(key) or "").strip()
        if len(v) >= 3:
            out.append(v.lower())
    aha = str(profile.get("aha_moment") or "")
    out += [w.lower() for w in re.findall(r"[A-Za-z]{5,}", aha)][:6]
    return out


def review_step(subject: str, body: str, campaign_id: str, step_role: str,
                profile: dict) -> list[dict]:
    """Флаги одного текста. step_role: 'inapp' | 'email'."""
    flags: list[dict] = []
    text = f"{subject or ''}\n{body or ''}"
    can_pause = bool(profile.get("can_pause"))
    executors = set(profile.get("executors") or ())

    # ── fatal: текст не должен уйти ──
    links = _LINK.findall(body or "")
    # Письмо-вопрос («ответь одной строкой») легально без ссылки: ответ и
    # есть действие, кнопка тут только отвлекала бы.
    asks_reply = re.search(r"\breply\b", body or "", re.I)
    if step_role == "email" and not links and not asks_reply:
        flags.append({"code": "no_action_link", "level": "fatal"})
    if len(set(links)) > 1:
        flags.append({"code": "many_actions", "level": "fatal",
                      "links": len(set(links))})
    if not can_pause and _PAUSE_PROMISE.search(text):
        flags.append({"code": "promises_pause_without_capability",
                      "level": "fatal"})
    if "trial_extend" not in executors and _TRIAL_EXTEND_PROMISE.search(text):
        flags.append({"code": "promises_trial_extension_without_capability",
                      "level": "fatal"})
    if campaign_id != "K6_winback" and _LEAVER_TALK.search(text):
        flags.append({"code": "talks_to_leaver", "level": "fatal"})
    if "!" in (subject or "") or (body or "").count("!") > 0:
        flags.append({"code": "shouting_exclamation", "level": "fatal"})
    if _SHOUT_WORDS.search(text):
        flags.append({"code": "hype_words", "level": "fatal"})

    # ── warn: уйдёт, но владельцу показываем ──
    if _CAPS_WORD.search(subject or ""):
        flags.append({"code": "caps_in_subject", "level": "warn"})
    n = _words(body)
    if step_role == "email" and n > MAX_WORDS:
        flags.append({"code": "too_long", "level": "warn", "words": n})
    if step_role == "email" and n < MIN_WORDS:
        flags.append({"code": "too_short", "level": "warn", "words": n})
    terms = profile_terms(profile)
    low = (body or "").lower()
    # единственное/множественное число - один и тот же термин
    hit = any(t in low or t.rstrip("s") in low for t in terms)
    if terms and not hit:
        flags.append({"code": "no_product_specificity", "level": "warn"})
    return flags


def fatal(flags: list[dict]) -> bool:
    return any(f["level"] == "fatal" for f in flags)
