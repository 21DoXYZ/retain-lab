"""Stripe webhook → Kafka saas.events (+ снапшоты объектов в stripe_*).

Fail-closed: без STRIPE_WEBHOOK_SECRET подпись проверить нельзя — приём запрещён,
кроме явного dev-режима STRIPE_SIGVERIFY_OFF=1 (моки/локальная отладка).
Повторная доставка события безопасна: event_id детерминирован (stripe:<evt_id>).
"""

from __future__ import annotations

import json
import logging
import os

from confluent_kafka import Producer
from flask import Flask, jsonify, request

from mapper import map_event, snapshot

logging.basicConfig(level=logging.INFO, format="[webhook] %(message)s")
log = logging.getLogger(__name__)

BROKER = os.environ.get("KAFKA_BROKER", "redpanda:9092")
TOPIC = os.environ.get("SAAS_KAFKA_TOPIC", "saas.events")
DEFAULT_TENANT = os.environ.get("TENANT_ID", "").strip()
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
SIGVERIFY_OFF = os.environ.get("STRIPE_SIGVERIFY_OFF", "") == "1"

producer = Producer({
    "bootstrap.servers": BROKER,
    "security.protocol": "SASL_PLAINTEXT",
    "sasl.mechanism": "SCRAM-SHA-256",
    "sasl.username": os.environ.get("SASL_USER", ""),
    "sasl.password": os.environ.get("SASL_PASS", ""),
    "enable.idempotence": True,
    "acks": "all",
    "linger.ms": 20,
    "compression.type": "lz4",
    "client.id": "stripe-webhook",
})

app = Flask(__name__)
_ch_client = None


def _ch():
    """Ленивый ClickHouse-клиент для снапшотов (не роняем приём, если CH прилёг)."""
    global _ch_client
    if _ch_client is None:
        import clickhouse_connect
        _ch_client = clickhouse_connect.get_client(
            host=os.environ.get("CH_HOST", "clickhouse"),
            port=int(os.environ.get("CH_PORT", "8123")),
            username=os.environ.get("CH_USER", "default"),
            password=os.environ.get("CH_PASSWORD", ""),
            database=os.environ.get("CH_DB", "retention"),
        )
    return _ch_client


def _tenant_by_signature(payload: bytes, sig_header: str) -> tuple[str, dict | None]:
    """Определяем пространство ПО ПОДПИСИ, когда в URL его не указали.

    Подпись проверяется секретом конкретного клиента, поэтому совпадение
    однозначно: чужой секрет её не подтвердит. Так работает вебхук, заведённый
    на короткий адрес - клиенту не нужно ничего переделывать в Stripe.
    """
    try:
        from saas_senders import TENANTS_FILE
    except ImportError:
        from stripe_sync.saas_senders import TENANTS_FILE
    try:
        with open(TENANTS_FILE) as fh:
            tenants = json.load(fh)
    except Exception:  # noqa: BLE001
        tenants = {}
    import stripe
    for tenant, conf in (tenants or {}).items():
        secret = str((conf or {}).get("stripe_webhook_secret") or "").strip()
        if not secret:
            continue
        try:
            return tenant, stripe.Webhook.construct_event(payload, sig_header, secret)
        except Exception:  # noqa: BLE001 - не этот клиент, пробуем следующего
            continue
    return "", None


def _tenant_secret(tenant: str) -> str:
    """Подписной секрет вебхука ЭТОГО клиента: он заводит вебхук в СВОЁМ Stripe
    и получает свой whsec_. Платформенный env - фолбэк для нашего аккаунта."""
    try:
        from saas_senders import load_tenant_channels
    except ImportError:
        from stripe_sync.saas_senders import load_tenant_channels
    try:
        own = str((load_tenant_channels(tenant) or {}).get("stripe_webhook_secret") or "")
    except Exception:  # noqa: BLE001 - файла нет/битый: остаётся платформенный
        own = ""
    return own.strip() or WEBHOOK_SECRET


def _verified_event(tenant: str) -> dict | None:
    payload = request.get_data()
    if SIGVERIFY_OFF:
        return json.loads(payload)
    secret = _tenant_secret(tenant)
    if not secret:
        return None
    import stripe
    try:
        return stripe.Webhook.construct_event(
            payload, request.headers.get("Stripe-Signature", ""), secret,
        )
    except Exception as exc:  # подпись/формат — 400, Stripe перепошлёт
        log.warning("signature check failed: %s", exc)
        return None


@app.post("/stripe/webhook")
@app.post("/stripe/webhook/<tenant_id>")
def stripe_webhook(tenant_id: str = ""):
    tenant = tenant_id or DEFAULT_TENANT
    if tenant:
        evt = _verified_event(tenant)
    else:
        # Адрес без хвоста пространства: определяем клиента по подписи.
        tenant, evt = _tenant_by_signature(
            request.get_data(), request.headers.get("Stripe-Signature", ""))
        if evt is not None:
            log.info("tenant by signature: %s", tenant)
    if evt is None:
        return jsonify(error="signature verification failed"), 400

    row = map_event(dict(evt), tenant)
    snap = snapshot(dict(evt), tenant)
    if row is None and snap is None:
        return jsonify(status="ignored", type=evt.get("type", "")), 200

    if row is not None:
        producer.produce(
            TOPIC,
            key=(row["stripe_customer_id"] or row["client_user_id"] or tenant),
            value=json.dumps(row, separators=(",", ":")),
        )
        producer.flush(10)
    if snap is not None:
        table, srow = snap
        try:
            _ch().insert(
                f"retention.{table}",
                [list(srow.values())],
                column_names=list(srow.keys()),
            )
        except Exception as exc:
            # событие уже в шине — снапшот догонит backfill/повторная доставка
            log.warning("snapshot insert failed (%s): %s", table, exc)

    etype = row["event_type"] if row is not None else f"snapshot:{evt.get('type', '')}"
    log.info("accepted %s -> %s", evt.get("type"), etype)
    return jsonify(status="ok", event_type=etype), 200


@app.get("/health")
def health():
    return jsonify(status="ok", sigverify="off" if SIGVERIFY_OFF else "on"), 200
