"""LLM-адаптер поверх OpenRouter (dev spec §6.2, §10.4).

Заказчик даёт ключ OPENROUTER — НЕ Anthropic напрямую. Один клиент к
https://openrouter.ai/api/v1/chat/completions (Bearer OPENROUTER_API_KEY, обычный
requests). complete_json: response_format=json_object где поддержано + строгий
парс со strip ```-fences; ретрай 3x exp(2→10s); invalid JSON → fallback-модель с
добавкой «return valid JSON only». Плюс translate() и summarize() (перевод/сжатие).

Turnkey: конструктор без ключа ок; вызов без ключа → ConfigError с понятным текстом.
Модель НЕ зашита — приходит аргументом из Config (primary/fallback).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from call_analyzer.config import ConfigError

logger = logging.getLogger("call_analyzer.llm")

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_RETRY_DELAYS = (2, 4, 8)  # exp-бэкофф, потолок 10с (dev spec §10.4)
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class LLMError(RuntimeError):
    """Сбой LLM после ретраев/fallback (dev spec §7 → llm_failed)."""


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = _FENCE_RE.sub("", t)
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


class OpenRouterClient:
    """Единый клиент OpenRouter. Держит только ключ и таймаут — модель приходит в вызов."""

    def __init__(self, api_key: str | None = None, timeout: float = 90.0) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.timeout = timeout
        # метаданные последнего вызова (токены/модель) — пайплайн пишет их в аудит
        self.last_meta: dict = {}

    # ── низкий уровень ────────────────────────────────────────────────────────────
    def _requests(self):
        try:
            import requests  # noqa: PLC0415 — ленивый импорт (тесты мокают клиент целиком)
        except ImportError as e:  # pragma: no cover
            raise LLMError("пакет 'requests' не установлен — OpenRouter недоступен") from e
        return requests

    def _headers(self) -> dict:
        if not self._api_key:
            raise ConfigError("OPENROUTER_API_KEY не задан — LLM-вызовы недоступны")
        h = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        # необязательные атрибуты OpenRouter (рейтинг приложения) — если заданы
        if os.environ.get("OPENROUTER_REFERER"):
            h["HTTP-Referer"] = os.environ["OPENROUTER_REFERER"]
        if os.environ.get("OPENROUTER_TITLE"):
            h["X-Title"] = os.environ["OPENROUTER_TITLE"]
        return h

    def _chat(self, *, system: str, user: str, model: str, temperature: float,
              json_mode: bool) -> str:
        """Один HTTP-вызов → content-строка. Сеть/HTTP-ошибки → LLMError."""
        requests = self._requests()
        body: dict = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = requests.post(_ENDPOINT, headers=self._headers(), json=body, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except ConfigError:
            raise
        except Exception as e:  # noqa: BLE001 — сеть/HTTP/JSON транспорта
            raise LLMError(f"OpenRouter HTTP-ошибка ({model}): {e}") from e
        usage = data.get("usage", {}) or {}
        self.last_meta = {"model": model, "tokens": usage.get("total_tokens")}
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"OpenRouter: неожиданная форма ответа: {e}") from e

    # ── высокий уровень ───────────────────────────────────────────────────────────
    def complete_json(self, system: str, user: str, model: str, temperature: float = 0.1,
                      fallback_model: str | None = None) -> dict:
        """Вернуть распарсенный JSON (dev spec §6.2). Ретрай 3x, затем fallback (§10.4)."""
        last_err: Exception | None = None
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                raw = self._chat(system=system, user=user, model=model,
                                 temperature=temperature, json_mode=True)
                return self._parse(raw)
            except ConfigError:
                raise
            except (LLMError, ValueError) as e:
                last_err = e
                if attempt < len(_RETRY_DELAYS):
                    time.sleep(_RETRY_DELAYS[attempt])
        # primary исчерпан → fallback-модель с явной командой вернуть JSON (§10.4)
        if fallback_model:
            logger.warning("primary %s не дал валидный JSON (%s) → fallback %s",
                           model, last_err, fallback_model)
            try:
                raw = self._chat(system=system + "\nReturn valid JSON only.",
                                 user=user, model=fallback_model,
                                 temperature=temperature, json_mode=True)
                return self._parse(raw)
            except ConfigError:
                raise
            except (LLMError, ValueError) as e:
                last_err = e
        raise LLMError(f"LLM не вернул валидный JSON после ретраев и fallback: {last_err}")

    def translate(self, text: str, target_lang: str) -> str:
        """Перевод транскрипта on-demand (интерфейс §5). Возвращает строку, не JSON."""
        from call_analyzer.prompts import TRANSLATE_SYSTEM  # noqa: PLC0415
        lang = {"ru": "Russian", "en": "English"}.get(target_lang, target_lang)
        return self._chat(system=TRANSLATE_SYSTEM.format(target_lang=lang),
                          user=text, model=os.environ.get("OPENROUTER_TRANSLATE_MODEL",
                                                           "google/gemini-3-flash"),
                          temperature=0.0, json_mode=False)

    def summarize(self, text: str, model: str) -> str:
        """Сжать середину длинного транскрипта дешёвой моделью (dev spec §10.8)."""
        from call_analyzer.prompts import COMPRESS_SYSTEM  # noqa: PLC0415
        return self._chat(system=COMPRESS_SYSTEM, user=text, model=model,
                          temperature=0.1, json_mode=False)

    @staticmethod
    def _parse(raw: str) -> dict:
        try:
            obj = json.loads(_strip_fences(raw))
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"невалидный JSON от LLM: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError("ожидался JSON-объект верхнего уровня")
        return obj


def get_llm() -> OpenRouterClient:
    """Единый конструктор клиента (ключ из env). turnkey — без ключа не падает."""
    return OpenRouterClient()
