"""Единый контракт LLM-стадий: одна граница для ВСЕХ обращений к модели.

Раньше транспорт (resolve_provider/_call_anthropic/_call_openai) жил в
ai_compose, а офферы/тексты/аналитик/классификатор импортировали его вразнобой
и каждый сам решал, что подать и как проверить. Это ровно та «путаница
контекста», из-за которой возможны генерик-ответы и галлюцинации.

Здесь одна дверь. Через неё проходит КАЖДЫЙ вызов модели, и на ней стоят два
инварианта:
  1. Без бизнес-контекста вызова НЕ БУДЕТ (методология §9): генерик-промпт
     запрещён архитектурно, а не пожеланием. call() требует непустой
     context_block; хочешь исключение (классификатор без профиля) - проси явно.
  2. Каждый исход записывается (record_run -> retention.llm_runs): провайдер,
     сколько принято/отбраковано, статус. Галлюцинации и пустые ответы видны
     единообразно, как здоровье любой стадии конвейера.

Парсинг и доменную валидацию (схемы офферов, copy_review, коды-не-проза)
по-прежнему делают вызывающие - у каждого своя. Здесь общий транспорт,
инвариант контекста и наблюдаемость.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
_TIMEOUT = 60
_MAX_TOKENS = 1500

# Маркер обязательного блока бизнес-контекста (business_context.context_block).
# По нему граница узнаёт, что контекст реально подан, а не пустая строка.
CONTEXT_MARKER = "BUSINESS CONTEXT"


class MissingContext(Exception):
    """Вызов без бизнес-контекста - нарушение методологии §9, не баг сети."""


def resolve_provider(env: dict | None = None) -> tuple[str, str]:
    """(provider, api_key). Anthropic приоритетнее, OpenAI - фолбэк.
    ('', '') = AI выключен."""
    e = env if env is not None else os.environ
    a = str(e.get("ANTHROPIC_API_KEY", "") or "").strip()
    if a:
        return "anthropic", a
    o = str(e.get("OPENAI_API_KEY", "") or "").strip()
    if o:
        return "openai", o
    return "", ""


def _call_anthropic(api_key: str, system: str, user: str) -> str:
    payload = json.dumps({
        "model": ANTHROPIC_MODEL, "max_tokens": _MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_URL, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "x-api-key": api_key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
    return "".join(b.get("text", "") for b in data.get("content", []))


def _call_openai(api_key: str, system: str, user: str) -> str:
    payload = json.dumps({
        "model": OPENAI_MODEL, "max_tokens": _MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        OPENAI_URL, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")


def has_context(user_body: str) -> bool:
    """Подан ли реальный бизнес-контекст (а не пустой блок)."""
    return CONTEXT_MARKER in (user_body or "")


def call(system: str, user_body: str, *, allow_no_context: bool = False,
         env: dict | None = None) -> tuple[str, str]:
    """Единственный путь к модели. (text, note).

    note: "" - успех; "ai_not_configured" - провайдера нет; "ai_http_<code>" /
    "ai_<Exc>" - сбой. Текст ответа НЕ парсится и НЕ валидируется здесь -
    это дело вызывающего (у каждого свои схемы).

    Инвариант §9: без бизнес-контекста не звоним. allow_no_context=True -
    осознанное исключение (напр. классификатор отмен, где профиль опционален).
    """
    if not allow_no_context and not has_context(user_body):
        raise MissingContext(
            "LLM-вызов без бизнес-контекста запрещён (методология §9): "
            "подай business_context.context_block")
    provider, api_key = resolve_provider(env)
    if not provider:
        return "", "ai_not_configured"
    fn = _call_anthropic if provider == "anthropic" else _call_openai
    try:
        return fn(api_key, system, user_body), ""
    except urllib.error.HTTPError as exc:
        return "", f"ai_http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return "", f"ai_{type(exc).__name__}"


# ── Наблюдаемость: исход каждой LLM-стадии в retention.llm_runs ──────────────

def record_run(ch, tenant: str, stage: str, status: str,
               kept: int = 0, rejected: int = 0, note: str = "") -> None:
    """Записать исход LLM-стадии. ch=None (нет клиента) - молча пропускаем:
    наблюдаемость не должна ронять генерацию."""
    if ch is None:
        return
    try:
        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        ch.insert(
            "retention.llm_runs",
            [[tenant, stage, status, int(kept), int(rejected),
              str(note)[:200], now]],
            column_names=["tenant_id", "stage", "status", "kept", "rejected",
                          "note", "ts"])
    except Exception:  # noqa: BLE001 - журнал не роняет стадию
        pass
