#!/usr/bin/env python3
"""HTTP-шлюз приёма событий казино -> Kafka (casino.events).

Казино шлёт обычный POST с JSON события (или массивом событий) на /ingest/events.
Шлюз валидирует, кладёт в Kafka (durable-буфер) и отвечает 200 ТОЛЬКО после
подтверждённой доставки в Kafka (at-least-once). Дальше: ClickHouse -> live_events.

Авторизация: заголовок  Authorization: Bearer <INGEST_TOKEN>
"""
import os
from datetime import datetime, timedelta, timezone
import json
import urllib.parse
import urllib.request
import hmac
import ipaddress
from flask import Flask, request, jsonify
from confluent_kafka import Producer

# fail-closed: в проде (INGEST_REQUIRE_AUTH=1) приём без токенов запрещён
REQUIRE_AUTH = os.environ.get('INGEST_REQUIRE_AUTH', '').strip().lower() in ('1', 'true', 'yes', 'on')

BROKER    = os.environ.get("KAFKA_BROKER", "redpanda:9092")
TOPIC     = os.environ.get("KAFKA_TOPIC", "casino.events")
TOKENS_FILE = os.environ.get("TOKENS_FILE", "/secrets/tokens.json")
# фолбэк, если файла нет: INGEST_TOKEN (через запятую)
ENV_TOKENS  = {t.strip() for t in os.environ.get("INGEST_TOKEN", "").split(",") if t.strip()}
SASL_USER = os.environ.get("SASL_USER", "")

IPS_FILE = os.environ.get("IPS_FILE", "/secrets/allowed_ips.json")

_tok_cache = {"mtime": 0, "map": {}}
_ips_cache = {"mtime": -1, "nets": None}   # nets=None -> allow all (файла нет/пуст)


def _allowed_nets():
    """Список разрешённых сетей из allowed_ips.json (перечитывается при изменении).
    None = разрешить всем (список пуст/файл отсутствует)."""
    try:
        mt = os.path.getmtime(IPS_FILE)
        if mt != _ips_cache["mtime"]:
            with open(IPS_FILE) as fh:
                entries = json.load(fh)
            nets = []
            for e in entries:
                e = str(e).strip()
                if e:
                    nets.append(ipaddress.ip_network(e, strict=False))
            _ips_cache["nets"] = nets or None
            _ips_cache["mtime"] = mt
        return _ips_cache["nets"]
    except Exception:
        return _ips_cache.get("nets")


def _ip_allowed():
    nets = _allowed_nets()
    if not nets:
        return True   # список пуст -> пускаем всех
    # реальный IP клиента ставит Caddy в X-Real-Client-IP (клиент подделать не может)
    raw = request.headers.get("X-Real-Client-IP", request.remote_addr or "")
    try:
        ip = ipaddress.ip_address(raw.split(",")[0].strip())
    except Exception:
        return False
    return any(ip in n for n in nets)

def _token_map():
    """{токен: tenant_id} из tokens.json. КЛЮЧ ФАЙЛА = ID ТЕНАНТА: так токен
    привязан к своему рабочему пространству, и чужой токен не может писать
    события за другого клиента (см. _tenant_allowed)."""
    try:
        mt = os.path.getmtime(TOKENS_FILE)
        if mt != _tok_cache["mtime"]:
            with open(TOKENS_FILE) as fh:
                data = json.load(fh)
            _tok_cache["map"] = {str(v): str(k) for k, v in data.items() if v}
            _tok_cache["mtime"] = mt
        return _tok_cache.get("map") or {}
    except Exception:
        return _tok_cache.get("map") or {}


def _valid_tokens():
    """Актуальные токены (значения). Фолбэк - ENV_TOKENS (dev/казино)."""
    return set(_token_map()) or ENV_TOKENS


def _token_tenant():
    """Тенант предъявленного токена; '' - токен из env-фолбэка (любой тенант)."""
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "):
        return ""
    return _token_map().get(h[7:], "")
SASL_PASS = os.environ.get("SASL_PASS", "")
MAX_BATCH = int(os.environ.get("MAX_BATCH", "1000"))

REQUIRED = {"event_id", "event_type", "casino_player_id", "ts"}

# SaaS-контур (Revenue Autopilot): свой топик и свой контракт (saas_schema.sql).
SAAS_TOPIC = os.environ.get("SAAS_KAFKA_TOPIC", "saas.events")
REQUIRED_SAAS = {"event_id", "tenant_id", "event_type", "ts"}

from event_time import sane_ts  # noqa: E402
# Сниппет ra.js постит с сайта тенанта (кросс-домен) — браузеру нужен CORS.
# Токен «публичного класса» (как ключи аналитик), поэтому echo-origin допустим;
# сузить до доменов тенантов: SAAS_CORS_ORIGINS="https://app.x.com,https://y.io".
SAAS_CORS_ORIGINS = [o.strip() for o in
                     os.environ.get("SAAS_CORS_ORIGINS", "*").split(",") if o.strip()]


def _saas_cors(resp):
    origin = request.headers.get("Origin", "")
    allow = ("*" in SAAS_CORS_ORIGINS and "*") or (origin if origin in SAAS_CORS_ORIGINS else "")
    if allow:
        resp.headers["Access-Control-Allow-Origin"] = allow if allow != "*" else (origin or "*")
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Vary"] = "Origin"
    return resp

producer = Producer({
    "bootstrap.servers": BROKER,
    "security.protocol": "SASL_PLAINTEXT",   # внутренний listener Redpanda (доверенная docker-сеть)
    "sasl.mechanism": "SCRAM-SHA-256",
    "sasl.username": SASL_USER,
    "sasl.password": SASL_PASS,
    "enable.idempotence": True,
    "acks": "all",
    "retries": 1_000_000,
    "linger.ms": 20,
    "compression.type": "lz4",
    "client.id": "http-ingest",
})

app = Flask(__name__)


def _auth_ok():
    toks = _valid_tokens()
    if not toks:
        return not REQUIRE_AUTH   # нет токенов: локально — открыто; в проде (REQUIRE_AUTH) — отказ
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "):
        return False
    got = h[7:]
    return any(hmac.compare_digest(got, t) for t in toks)   # timing-safe


@app.post("/ingest/events")
def ingest():
    if not _ip_allowed():
        return jsonify(error="forbidden (ip not allowed)"), 403
    try:
        body = request.get_json(force=True)
    except Exception:
        body = None
    if not _auth_ok():
        # Ключ не подошёл. Запоминаем факт: на сайте клиента мог остаться старый
        # код после перевыпуска токена, и без этой отметки он видит только
        # «событий нет» и ищет ошибку у себя.
        _record_reject(body, "unknown_token")
        return jsonify(error="unauthorized"), 401
    if body is None:
        return jsonify(error="invalid json"), 400

    events = body if isinstance(body, list) else [body]
    if not events:
        return jsonify(error="empty payload"), 400

    # DEBUG_FIELDS=1 — разово логируем поля события (диагностика новых полей от казино:
    # game_name у игровых; transaction_id / description / is_manual у денежных)
    if os.environ.get("DEBUG_FIELDS") == "1":
        for _e in events:
            if not isinstance(_e, dict):
                continue
            et = _e.get("event_type")
            if et in ("bet", "win", "session_start"):
                print(f"[debug] game {et}: поля {sorted(_e.keys())} · "
                      f"game_name={_e.get('game_name')!r}", flush=True)
                break
            if et in ("deposit", "withdrawal", "bonus") or (et or "").startswith("manual_"):
                print(f"[debug] money {et}: поля {sorted(_e.keys())} · "
                      f"transaction_id={_e.get('transaction_id')!r} "
                      f"description={_e.get('description')!r} is_manual={_e.get('is_manual')!r}", flush=True)
                break
    if len(events) > MAX_BATCH:
        return jsonify(error=f"batch too large (max {MAX_BATCH})"), 413

    # валидация обязательных полей
    for i, e in enumerate(events):
        if not isinstance(e, dict) or not REQUIRED.issubset(e):
            return jsonify(error="missing required fields", index=i,
                           required=sorted(REQUIRED)), 400

    errs = []
    def _cb(err, _msg):
        if err is not None:
            errs.append(str(err))

    for e in events:
        producer.produce(TOPIC, key=str(e["casino_player_id"]),
                         value=json.dumps(e), on_delivery=_cb)
    producer.flush(10)

    if errs:   # хоть одно событие не доставлено в Kafka -> 503, казино ретраит весь батч
        return jsonify(error="kafka delivery failed", detail=errs[:3]), 503
    return jsonify(status="ok", accepted=len(events)), 200


@app.after_request
def _saas_cors_after(resp):
    if request.path == "/ingest/saas/events":
        return _saas_cors(resp)
    return resp


@app.route("/ingest/saas/events", methods=["OPTIONS"])
def ingest_saas_preflight():
    return "", 204


CH_URL = "http://{}:{}/".format(os.environ.get("CH_HOST", "clickhouse"),
                                os.environ.get("CH_PORT", "8123"))


def _record_reject(body, reason: str) -> None:
    """След отбитого события: кто стучался, с каким ключом и откуда.

    Пишем напрямую в ClickHouse (одна строка, без зависимостей и без своего
    топика). Диагностика НЕ ИМЕЕТ ПРАВА мешать приёму - любая ошибка гасится.
    """
    try:
        first = body[0] if isinstance(body, list) and body else body
        claim = str((first or {}).get("tenant_id") or "")[:64]
        auth = request.headers.get("Authorization", "")
        row = {
            "tenant_id": claim,
            "origin": (request.headers.get("Origin")
                       or request.headers.get("Referer") or "")[:200],
            "token_prefix": auth.replace("Bearer ", "").strip()[:8],
            "reason": reason,
        }
        req = urllib.request.Request(
            CH_URL + "?" + urllib.parse.urlencode({
                "database": os.environ.get("CH_DB", "retention"),
                "query": "INSERT INTO ingest_rejects (tenant_id, origin, "
                         "token_prefix, reason) FORMAT JSONEachRow",
                "user": os.environ.get("CH_USER", "default"),
                "password": os.environ.get("CH_PASSWORD", ""),
            }),
            data=json.dumps(row).encode(), method="POST")
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:  # noqa: BLE001
        pass


@app.post("/ingest/saas/events")
def ingest_saas():
    """События продукта (сниппет/API) → топик saas.events. Auth/лимиты — как /ingest/events."""
    if not _ip_allowed():
        return jsonify(error="forbidden (ip not allowed)"), 403
    try:
        body = request.get_json(force=True)
    except Exception:
        body = None
    if not _auth_ok():
        # Ключ не подошёл. Запоминаем факт: на сайте клиента мог остаться старый
        # код после перевыпуска токена, и без этой отметки он видит только
        # «событий нет» и ищет ошибку у себя.
        _record_reject(body, "unknown_token")
        return jsonify(error="unauthorized"), 401
    if body is None:
        return jsonify(error="invalid json"), 400

    events = body if isinstance(body, list) else [body]
    if not events:
        return jsonify(error="empty payload"), 400
    if len(events) > MAX_BATCH:
        return jsonify(error=f"batch too large (max {MAX_BATCH})"), 413

    for i, e in enumerate(events):
        if not isinstance(e, dict) or not REQUIRED_SAAS.issubset(e):
            return jsonify(error="missing required fields", index=i,
                           required=sorted(REQUIRED_SAAS)), 400

    # Токен привязан к тенанту: событие за чужое пространство не принимаем.
    own = _token_tenant()
    if own:
        for i, e in enumerate(events):
            if str(e.get("tenant_id")) != own:
                return jsonify(error="tenant mismatch: token belongs to another workspace",
                               index=i), 403

    errs = []
    def _cb(err, _msg):
        if err is not None:
            errs.append(str(err))

    now_utc = datetime.now(tz=timezone.utc)
    for e in events:
        e.setdefault("source", "snippet")
        e["ts"] = sane_ts(e.get("ts"), now_utc)
        key = e.get("client_user_id") or e.get("stripe_customer_id") or e["tenant_id"]
        producer.produce(SAAS_TOPIC, key=str(key), value=json.dumps(e), on_delivery=_cb)
    producer.flush(10)

    if errs:
        return jsonify(error="kafka delivery failed", detail=errs[:3]), 503
    return jsonify(status="ok", accepted=len(events)), 200


# ── Telegram-вебхук ботов тенантов (Phase 4 каналы) ──────────────────────────
# Секрет ставится при подключении бота (POST /saas/channels/telegram в борде,
# setWebhook secret_token) и хранится в tenants.json. Fail-closed: нет секрета
# у тенанта или не совпал заголовок -> 403.
from tg_events import update_to_event  # noqa: E402

TENANTS_FILE = os.environ.get("TENANTS_FILE", "/secrets/tenants.json")
_tenants_cache = {"mtime": 0, "data": {}}


def _tenant_conf(tenant_id):
    try:
        mt = os.path.getmtime(TENANTS_FILE)
        if mt != _tenants_cache["mtime"]:
            with open(TENANTS_FILE) as fh:
                _tenants_cache["data"] = json.load(fh) or {}
            _tenants_cache["mtime"] = mt
    except Exception:
        pass
    return _tenants_cache["data"].get(tenant_id, {}) or {}


@app.post("/ingest/saas/tg/<tenant_id>")
def ingest_tg(tenant_id):
    secret = str(_tenant_conf(tenant_id).get("telegram_webhook_secret", ""))
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secret or not hmac.compare_digest(got, secret):
        return jsonify(error="forbidden"), 403

    upd = request.get_json(silent=True) or {}
    ev = update_to_event(tenant_id, upd)
    if ev is None:
        return jsonify(status="ignored"), 200   # не-подписочные апдейты не интересны

    errs = []
    producer.produce(SAAS_TOPIC, key=str(ev.get("client_user_id") or tenant_id),
                     value=json.dumps(ev),
                     on_delivery=lambda err, _m: errs.append(str(err)) if err else None)
    producer.flush(10)
    if errs:   # Telegram ретраит любые не-2xx - доставка гарантируется
        return jsonify(error="kafka delivery failed"), 503
    return jsonify(status="ok"), 200


@app.get("/ingest/health")
def health():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, threaded=True)
