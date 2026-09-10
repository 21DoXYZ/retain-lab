"""Методология текстов как код (METHODOLOGY.md §8) - движок v2.

Валидатор письма/in-app: посыл, конкретика, один CTA, человеческий голос.
Гоняется по ЛЮБОМУ тексту касания - сгенерированному моделью (ai_compose
отбрасывает невалидные шаги) и написанному руками (экран кампаний флажит,
auto_improve не запускает).

v2 (2026-09-10) - перенос выстраданных правил из других проектов владельца:
  • contract-hunter (validate.py + banned_phrases.txt): бан-лист ИИ-клише,
    маркетинг-слова, «машинный ритм» (длина предложений, одинаковые зачины,
    тире-пунктуация), цифры только из подтверждённого источника,
    анти-повтор между касаниями (фоллоуап не пересказывает первое письмо);
  • retivo-tg voice.ts: КАЖДАЯ пойманная при ревью ошибка зашивается СЮДА
    НАВСЕГДА (см. блок CAUGHT_MISTAKES), а не флагается разово.

Флаги - коды с параметрами, не готовые фразы: их читают UI, логи и тесты.
Уровни: fatal (текст не должен уйти) / warn (уйдёт, но владельцу показываем).
"""

from __future__ import annotations

import re

MAX_WORDS = 130
MIN_WORDS = 12

# ── Голос: ИИ-клише и маркетинг-слова (из contract-hunter, дважды браковано
# владельцем как «видно что писал ИИ»; правила живут в коде, не в промпте -
# промпт версии теряет, валидатор нет) ────────────────────────────────────────
_AI_CLICHES = (
    "i hope this finds you well", "i hope this email finds you well",
    "i hope you're doing well", "i came across", "reaching out because",
    "just wanted to reach out", "i wanted to reach out", "touch base",
    "circle back", "quick question", "caught my eye", "your focus on",
    "sounds like", "spot on", "as an ai", "let me know if this resonates",
    "looking forward to hearing from you", "at your earliest convenience",
    "to whom it may concern", "in today's fast-paced", "perfect fit for",
    "game-changer", "game changer", "cutting-edge", "best-in-class",
)
_MARKETING_WORDS = (
    "streamline", "seamless", "seamlessly", "leverage", "empower", "unlock",
    "elevate", "supercharge", "revolutionize", "delve", "synergy",
    "robust", "effortless", "turbocharge",
)

# Крик и спам-триггеры. Восклицание - не «энергия», а девальвация: письмо,
# которому нужен «!», не имеет посыла. CAPS и hurry-лексика дополнительно
# бьют по доставляемости.
_SHOUT_WORDS = re.compile(
    r"\b(hurry|act now|last chance|don'?t miss|limited time|urgent|"
    r"don'?t wait|final hours)\b", re.I)
_CAPS_WORD = re.compile(r"\b[A-Z]{4,}\b")
_LINK = re.compile(r"(\{\{\w*url\w*\}\}|https?://\S+)")
_URL_STRIP = re.compile(r"https?://\S+|\{\{[\w .-]+\}\}")
_SENTENCE_SPLIT = re.compile(r"[.!?]+\s")
_NUMBER = re.compile(r"\d[\d,.]*%?")

# Цифры, которым источник не нужен: счёт по пальцам, типовые окна времени.
# Всё остальное в письме обязано приходить из профиля тенанта или из
# плейсхолдера - выдуманная цифра хуже её отсутствия (урок contract-hunter).
_FREE_NUMBERS = {"1", "2", "3", "4", "5", "7", "10", "14", "15", "20", "24",
                 "30", "48", "60", "90", "100"}

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

# ── CAUGHT_MISTAKES: вечные правила из пойманных ошибок ─────────────────────
# Дисциплина (retivo-tg): поймал ошибку в тексте руками - добавь regex сюда
# с датой и одной строкой «почему». Правило не удаляется никогда.
_CAUGHT_MISTAKES: tuple[tuple[str, re.Pattern], ...] = (
    # 2026-09-10: рендерер сам ставит тихую отписку; слово в теле дублирует
    # её и тащит письмо в Promotions
    ("unsubscribe_in_body", re.compile(r"\bunsubscribe\b", re.I)),
    # 2026-09-10: em/en dash в видимом тексте запрещены во всех проектах
    # владельца (validate_steps чинит молча, но автор должен УЗНАТЬ)
    ("em_dash", re.compile(r"[–—]")),
)


def _words(text: str) -> int:
    return len(re.findall(r"[\w'-]+", text or ""))


def _sentences(text: str) -> list[str]:
    body = _URL_STRIP.sub("", text or "")
    return [s.strip() for s in _SENTENCE_SPLIT.split(body) if len(s.split()) > 2]


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


def _profile_numbers(profile: dict) -> set[str]:
    """Все цифры, которые профиль тенанта разрешает упоминать."""
    blob = " ".join(str(v) for v in (profile or {}).values())
    return {n.rstrip(".,").replace(",", "") for n in _NUMBER.findall(blob)}


def check_numbers(body: str, profile: dict) -> list[str]:
    """Цифры без источника. Разрешены: счёт по пальцам, цифры из профиля,
    цифры внутри URL/плейсхолдеров (уже вырезаны _URL_STRIP)."""
    allowed = _FREE_NUMBERS | _profile_numbers(profile)
    text = _URL_STRIP.sub("", body or "")
    hits = []
    for token in _NUMBER.findall(text):
        cleaned = token.rstrip(".,").replace(",", "")
        if cleaned not in allowed and cleaned.rstrip("%") not in allowed:
            hits.append(token)
    return hits


def check_rhythm(body: str) -> list[dict]:
    """«Машинный ритм» (contract-hunter check_naturalness): длинные
    предложения и одинаковые зачины выдают генерацию с первого взгляда."""
    flags: list[dict] = []
    sentences = _sentences(body)
    if sentences:
        avg = sum(len(s.split()) for s in sentences) / len(sentences)
        if avg > 18:
            flags.append({"code": "sentences_too_long", "level": "warn",
                          "avg_words": round(avg)})
        longest = max(len(s.split()) for s in sentences)
        if longest > 28:
            flags.append({"code": "sentence_over_28_words", "level": "warn",
                          "words": longest})
        starters = [s.split()[0].lower() for s in sentences if s.split()]
        for st in set(starters):
            if starters.count(st) >= 3:
                flags.append({"code": "repeated_sentence_starter",
                              "level": "warn", "word": st})
                break
    # тире как пунктуация (« - ») - машинная привычка; дефис внутри слова
    # (e-commerce) - нормальное человеческое письмо
    if re.search(r"(\s-\s|\s--)", _URL_STRIP.sub("", body or "")):
        flags.append({"code": "dash_punctuation", "level": "warn"})
    return flags


def review_step(subject: str, body: str, campaign_id: str, step_role: str,
                profile: dict) -> list[dict]:
    """Флаги одного текста. step_role: 'inapp' | 'email'."""
    flags: list[dict] = []
    text = f"{subject or ''}\n{body or ''}"
    low = text.lower()
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
    for phrase in _AI_CLICHES:
        if phrase in low:
            flags.append({"code": "ai_cliche", "level": "fatal",
                          "phrase": phrase})
            break
    for w in _MARKETING_WORDS:
        if re.search(rf"\b{w}", low):
            flags.append({"code": "marketing_word", "level": "fatal",
                          "word": w})
            break
    for code, rx in _CAUGHT_MISTAKES:
        if rx.search(text):
            flags.append({"code": code, "level": "fatal"})
    unsourced = check_numbers(body or "", profile)
    if unsourced:
        flags.append({"code": "unsourced_numbers", "level": "fatal",
                      "numbers": unsourced[:5]})

    # ── warn: уйдёт, но владельцу показываем ──
    if _CAPS_WORD.search(subject or ""):
        flags.append({"code": "caps_in_subject", "level": "warn"})
    n = _words(body)
    if step_role == "email" and n > MAX_WORDS:
        flags.append({"code": "too_long", "level": "warn", "words": n})
    if step_role == "email" and n < MIN_WORDS:
        flags.append({"code": "too_short", "level": "warn", "words": n})
    terms = profile_terms(profile)
    lowb = (body or "").lower()
    # единственное/множественное число - один и тот же термин
    hit = any(t in lowb or t.rstrip("s") in lowb for t in terms)
    if terms and not hit:
        flags.append({"code": "no_product_specificity", "level": "warn"})
    flags += check_rhythm(body or "")
    return flags


# ── Последовательность шагов: фоллоуап не пересказывает первое письмо ────────
# Провал любого фоллоуапа - повторить уже прочитанное: читается как шаблон,
# а не человек (contract-hunter check_repetition, порог 6 слов подряд).
_REPEAT_WINDOW = 6


def _shingles(text: str, size: int) -> set[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {" ".join(words[i:i + size])
            for i in range(max(0, len(words) - size + 1))}


def review_sequence(steps: list[dict]) -> list[dict]:
    """Флаги ПО ПАРАМ шагов: шаг, который дословно повторяет предыдущий."""
    flags: list[dict] = []
    prev = ""
    for i, st in enumerate(steps or []):
        body = str(st.get("body") or "")
        if prev:
            shared = _shingles(body, _REPEAT_WINDOW) & _shingles(prev, _REPEAT_WINDOW)
            if shared:
                flags.append({"code": "repeats_previous_step", "level": "fatal",
                              "step": i, "phrases": len(shared)})
        prev = body or prev
    return flags


def fatal(flags: list[dict]) -> bool:
    return any(f["level"] == "fatal" for f in flags)
