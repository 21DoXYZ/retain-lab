"""ASR-адаптер (dev spec §6.1).

Protocol ASRProvider + две реализации:
  • GladiaAdapter    — боевой Gladia v2 (upload → transcription, diarization=true,
                       language=tr). Ключ GLADIA_API_KEY. Без ключа — ConfigError.
                       ПИСАНО ПО ДОКАМ, вживую не проверено (доступов нет) — UNVERIFIED.
  • MockASRAdapter   — детерминированный, читает фикстуру call_analyzer/fixtures/*.json.
                       Работает БЕЗ ключей и сети (разработка/тесты/CI).

Выбор — env ASR_PROVIDER (gladia|mock), дефолт mock (turnkey без ключей).
ASRResult (dict): {"words":[{w,start,end,channel|None,speaker|None,conf}], "provider":str}.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

from call_analyzer.config import ConfigError

logger = logging.getLogger("call_analyzer.asr")

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class ASRError(RuntimeError):
    """Ошибка распознавания (после ретраев → status asr_failed, dev spec §7)."""


@runtime_checkable
class ASRProvider(Protocol):
    def transcribe(self, audio_path: str, language: str = "tr", channels: int = 1) -> dict:
        ...


# ── Mock (без ключей/сети) ────────────────────────────────────────────────────────
class MockASRAdapter:
    """Детерминированный ASR из фикстуры. `name` для журналирования провайдера."""

    name = "mock"

    def __init__(self, fixture: str | None = None) -> None:
        # выбор фикстуры: аргумент → env ASR_FIXTURE → дефолт
        self._fixture = fixture or os.environ.get("ASR_FIXTURE", "retention_call_1")

    def _load(self, name: str) -> dict:
        path = _FIXTURES_DIR / f"{name}.json"
        if not path.exists():
            raise ASRError(f"фикстура ASR не найдена: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def transcribe(self, audio_path: str, language: str = "tr", channels: int = 1) -> dict:
        data = self._load(self._fixture)
        return {"words": data.get("words", []), "provider": data.get("provider", "mock")}


# ── Gladia (боевой, UNVERIFIED) ───────────────────────────────────────────────────
class GladiaAdapter:
    """Клиент Gladia Solaria v2 (REST). Диаризация встроена (dev spec §1, §6.1).

    Секрет GLADIA_API_KEY живёт только здесь. Без него transcribe() кидает
    ConfigError (turnkey: конструктор не падает, падает вызов). Имена полей REST
    вынесены по докам Gladia v2 и помечены UNVERIFIED — сверить на боевом аудио.
    """

    name = "gladia"
    _BASE = "https://api.gladia.io/v2"

    def __init__(self, api_key: str | None = None, timeout: float = 60.0,
                 poll_interval: float = 3.0, max_poll: int = 100) -> None:
        self._api_key = api_key or os.environ.get("GLADIA_API_KEY", "")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_poll = max_poll

    def _requests(self):
        try:
            import requests  # noqa: PLC0415 — ленивый импорт, mock/тесты живут без него
        except ImportError as e:  # pragma: no cover
            raise ASRError("пакет 'requests' не установлен — Gladia недоступен") from e
        return requests

    def _headers(self) -> dict:
        if not self._api_key:
            raise ConfigError("GLADIA_API_KEY не задан — ASR через Gladia недоступен")
        return {"x-gladia-key": self._api_key}

    def transcribe(self, audio_path: str, language: str = "tr", channels: int = 1) -> dict:
        requests = self._requests()
        headers = self._headers()
        # 1) upload аудио
        with open(audio_path, "rb") as f:
            up = requests.post(f"{self._BASE}/upload", headers=headers,
                               files={"audio": f}, timeout=self.timeout)
        up.raise_for_status()
        audio_url = up.json().get("audio_url")  # UNVERIFIED: имя поля ответа
        # 2) запуск транскрипции с диаризацией
        body = {"audio_url": audio_url, "diarization": True,
                "language": language, "detect_language": False}
        tr = requests.post(f"{self._BASE}/transcription", headers=headers,
                           json=body, timeout=self.timeout)
        tr.raise_for_status()
        result_url = tr.json().get("result_url")  # UNVERIFIED
        # 3) поллинг результата
        for _ in range(self.max_poll):
            r = requests.get(result_url, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            payload = r.json()
            if payload.get("status") == "done":
                return {"words": self._to_words(payload), "provider": self.name}
            if payload.get("status") == "error":
                raise ASRError(f"Gladia вернул ошибку: {payload.get('error')}")
            time.sleep(self.poll_interval)
        raise ASRError("Gladia: превышено время ожидания результата")

    @staticmethod
    def _to_words(payload: dict) -> list[dict]:
        """Разобрать ответ Gladia в контракт ASRResult.words (UNVERIFIED-маппинг)."""
        words: list[dict] = []
        utterances = (payload.get("result", {}).get("transcription", {}).get("utterances", []))
        for u in utterances:
            speaker = u.get("speaker")
            channel = u.get("channel")
            for w in u.get("words", []):
                words.append({"w": w.get("word"), "start": w.get("start"),
                              "end": w.get("end"), "channel": channel,
                              "speaker": speaker, "conf": w.get("confidence")})
        return words


# ── фабрика по env ────────────────────────────────────────────────────────────────
def get_asr(provider: str | None = None) -> ASRProvider:
    """mock|gladia по env ASR_PROVIDER (dev spec §6.1). Дефолт mock — без ключей."""
    name = (provider or os.environ.get("ASR_PROVIDER", "mock")).strip().lower()
    if name == "gladia":
        return GladiaAdapter()
    if name == "mock":
        return MockASRAdapter()
    raise ConfigError(f"неизвестный ASR_PROVIDER: {name!r} (ожидалось gladia|mock)")
