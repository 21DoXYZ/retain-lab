"""Ingest API (FastAPI) — dev spec §5 + перевод on-demand (интерфейс §5).

Внутренний сервис: наружу НЕ публикуется (только docker-сеть). Аутентификация —
сервис-токен ANALYZER_SERVICE_TOKEN в заголовке Authorization: Bearer <token>.

Эндпоинты:
  POST /v1/calls/ingest    — создать analyzer.calls + поставить задачу в очередь → 202
  POST /internal/translate — синхронный перевод text_redacted (Flask-портал дёргает)
  GET  /healthz            — живость

Тяжёлые зависимости (celery) импортируются лениво внутри обработчиков, чтобы модуль
парсился/грузился без брокера.
"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from call_analyzer import db

app = FastAPI(title="Call Analyzer Ingest", docs_url=None, redoc_url=None)


# ── аутентификация сервис-токеном (dev spec §5) ───────────────────────────────────
def require_service_token(authorization: str = Header(default="")) -> None:
    expected = os.environ.get("ANALYZER_SERVICE_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="ANALYZER_SERVICE_TOKEN не задан на сервере")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    # constant-time сравнение — обычный != утекает длину совпавшего префикса по таймингу
    import hmac  # noqa: PLC0415
    if not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="неверный сервис-токен")


# ── схемы запросов ────────────────────────────────────────────────────────────────
class IngestRequest(BaseModel):
    casino_id: str = "default"
    operator_id: str
    casino_player_id: int
    crm_call_id: str | None = None
    source: str = "tegsoft"
    channels: int = Field(default=1, ge=1, le=2)
    audio_ref: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: int | None = None
    recommended_offer_id: str | None = None


class TranslateRequest(BaseModel):
    call_id: str
    lang: str = Field(pattern="^(ru|en)$")


# ── эндпоинты ─────────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/calls/ingest", status_code=status.HTTP_202_ACCEPTED,
          dependencies=[Depends(require_service_token)])
def ingest(req: IngestRequest) -> dict:
    """Создать звонок и поставить в очередь (dev spec §5). 202 или 400."""
    try:
        call_id = db.create_call({
            "crm_call_id": req.crm_call_id, "casino_id": req.casino_id,
            "operator_id": req.operator_id, "casino_player_id": req.casino_player_id,
            "source": req.source, "channels": req.channels, "audio_ref": req.audio_ref,
            "started_at": req.started_at, "ended_at": req.ended_at,
            "duration_s": req.duration_s, "recommended_offer_id": req.recommended_offer_id,
        })
    except Exception as e:  # noqa: BLE001 — битый ввод → 400, звонок не создаём (§7)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"ingest failed: {e}") from e

    from call_analyzer.worker import analyze_call  # noqa: PLC0415 — ленивый celery-импорт
    analyze_call.delay(call_id)
    return {"call_id": call_id, "status": "received"}


@app.post("/internal/translate", dependencies=[Depends(require_service_token)])
def translate(req: TranslateRequest) -> dict:
    """Синхронный перевод text_redacted в ru|en с кэшем (интерфейс §5, §10.11)."""
    tr = db.get_transcript(req.call_id)
    if not tr:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="транскрипт не найден")
    cached = tr.get(f"translation_{req.lang}")
    if cached:
        return {"text": cached, "cached": True}

    from call_analyzer.llm import get_llm  # noqa: PLC0415
    try:
        text = get_llm().translate(tr["text_redacted"], req.lang)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"перевод не удался: {e}") from e
    db.set_translation(req.call_id, req.lang, text)
    return {"text": text, "cached": False}
