"""Контрактные тесты шва SimbaGo -> Revenue Autopilot (сторона приёмника).

ИСТОЧНИК ИСТИНЫ — golden-файлы отправителя:
    simbagoapp/backend/apps/ra_events/golden/*.json
tests/golden_simbago/ здесь — их ТОЧНАЯ КОПИЯ (кросс-репозиторные пути в
тестах запрещены). Меняется формат у отправителя — сначала обновляется его
golden (apps/ra_events/tests_contract.py заставит), затем синхронно копия
здесь, и эти тесты покажут, переваривает ли платформа новый формат.

Прогоняется реальный код платформы:
  1. ingest/app.py :: /ingest/saas/events — валидация, auth, привязка токена
     к тенанту, нормализация (source, email, ts), что уходит в Kafka;
  2. stripe_sync/stitch.py :: build_identities — доходят ли client_user_id /
     email_hash до склейки (R2/R4);
  3. stripe_sync/replenishment.py :: parse_items/build_plans — рождается ли
     план потребления из order_confirmed.meta.items.

Kafka-producer подменён фейком (чистые функции, без брокера и без CH).

ЗАФИКСИРОВАННЫЕ РАСХОЖДЕНИЯ КОНТРАКТА (тесты закрепляют ФАКТИЧЕСКОЕ
поведение, чтобы починка была осознанной, а не случайной):
  D1. ingest_saas со СНИППЕТ-токена удаляет открытый email (e.pop("email")) —
      публичный токен, адресу верить нельзя. email_norm в identity не
      заполняется, активационные письма неоплатившим бьются в no_contact.
      Склейка живёт: email_hash проходит. Лечится переходом simbago на
      серверный токен (SERVER_TOKENS_FILE, tests/test_ingest_server_token.py).
  D2. ingest_saas со сниппет-токена перезаписывает source="snippet" —
      source="api" SimbaGo теряется (на серверном токене source=api уцелел бы).
  D3. ЗАКРЫТО НА ОТПРАВИТЕЛЕ: SimbaGo шлёт meta компактной JSON-СТРОКОЙ
      (json.dumps(separators=(",", ":"), ensure_ascii=False)) — схема
      saas_events (String) и гео/UA-обогащение шлюза совместимы. В golden
      meta лежит распакованным объектом ради читаемости; golden() здесь
      сериализует его обратно, как это делает отправитель.
  D4. ЗАКРЫТО НА ОТПРАВИТЕЛЕ: meta несёт order_ref (= order_number /
      external_order_id) РЯДОМ с order_id — replenishment читает order_ref
      напрямую, без фолбэка на event_id.
  D5. ЗАКРЫТО НА ОТПРАВИТЕЛЕ: items несут name (product_snapshot.name;
      для mp_order — best effort из raw-строки площадки) — {{product}}
      в replenishment_due больше не деградирует до SKU.
"""
import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / "golden_simbago"

sys.path.insert(0, str(ROOT))
from stripe_sync.replenishment import (  # noqa: E402
    build_plans, parse_items, parse_source_items, plan_id_for,
)
from stripe_sync.stitch import EventKey, build_identities  # noqa: E402


# ── фейковый Kafka-producer и импорт шлюза ───────────────────────────────────

class FakeProducer:
    def __init__(self, _conf):
        self.messages = []

    def produce(self, topic, key=None, value=None, on_delivery=None):
        self.messages.append({"topic": topic, "key": key, "value": value})
        if on_delivery is not None:
            on_delivery(None, None)

    def flush(self, _timeout=None):
        return 0


@pytest.fixture(scope="module")
def ingest(tmp_path_factory):
    """ingest/app.py с фейковым producer'ом и токеном тенанта simbago."""
    secrets = tmp_path_factory.mktemp("secrets")
    tokens = secrets / "tokens.json"
    tokens.write_text(json.dumps({"simbago": "test-token"}))
    server_tokens = secrets / "server_tokens.json"
    server_tokens.write_text(json.dumps({"simbago": "server-token"}))
    os.environ["TOKENS_FILE"] = str(tokens)
    os.environ["SERVER_TOKENS_FILE"] = str(server_tokens)
    os.environ["INGEST_REQUIRE_AUTH"] = "1"
    os.environ.pop("INGEST_TOKEN", None)

    fake = types.ModuleType("confluent_kafka")
    fake.Producer = FakeProducer
    sys.modules["confluent_kafka"] = fake
    sys.path.insert(0, str(ROOT / "ingest"))
    try:
        spec = importlib.util.spec_from_file_location(
            "ra_ingest_app", ROOT / "ingest" / "app.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(ROOT / "ingest"))
    mod.app.config["TESTING"] = True
    return mod


@pytest.fixture()
def client(ingest):
    ingest.producer.messages.clear()
    return ingest.app.test_client()


def _now_ms() -> str:
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def golden(name: str, ts: str = "", user_id: str = "42") -> dict:
    """Golden-payload с подставленной динамикой (как его пришлёт simbago).

    meta в golden-файле — объект (читаемость); по проводу simbago шлёт его
    компактной JSON-строкой (D3) — сериализуем так же, как отправитель."""
    text = (GOLDEN / f"{name}.json").read_text(encoding="utf-8")
    text = text.replace("<USER_ID>", user_id)
    payload = json.loads(text)
    payload["ts"] = ts or _now_ms()
    if isinstance(payload.get("meta"), (dict, list)):
        payload["meta"] = json.dumps(
            payload["meta"], separators=(",", ":"), ensure_ascii=False)
    return payload


ALL_GOLDEN = ["signup", "order_confirmed", "value_moment", "invoice_paid",
              "order_cancelled", "order_confirmed_guest", "mp_order",
              "mp_order_empty_items", "visit_completed"]

AUTH = {"Authorization": "Bearer test-token"}


def post(client, payload):
    return client.post("/ingest/saas/events", json=payload, headers=AUTH)


def landed(ingest) -> dict:
    assert len(ingest.producer.messages) == 1
    msg = ingest.producer.messages[0]
    assert msg["topic"] == "saas.events"
    return json.loads(msg["value"])


# ── 1. шлюз принимает каждый тип события ─────────────────────────────────────

@pytest.mark.parametrize("name", ALL_GOLDEN)
def test_every_golden_event_accepted(client, ingest, name):
    ts = _now_ms()
    resp = post(client, golden(name, ts=ts))
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "accepted": 1}
    e = landed(ingest)
    # обязательные поля контракта приёмника
    assert {"event_id", "tenant_id", "event_type", "ts"} <= set(e)
    assert e["tenant_id"] == "simbago"
    # ts с миллисекундами проходит sane_ts без искажений
    assert e["ts"] == ts
    # ключ партиционирования — client_user_id
    assert ingest.producer.messages[0]["key"] == e["client_user_id"]


def test_wrong_token_rejected(client):
    resp = client.post("/ingest/saas/events", json=golden("signup"),
                       headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_token_bound_to_tenant(client):
    stray = golden("signup")
    stray["tenant_id"] = "someone_else"
    resp = post(client, stray)
    assert resp.status_code == 403


def test_missing_required_field_rejected(client):
    broken = golden("signup")
    del broken["ts"]
    resp = post(client, broken)
    assert resp.status_code == 400
    assert resp.get_json()["required"] == ["event_id", "event_type",
                                           "tenant_id", "ts"]


def test_invoice_paid_is_not_billing_star(client, ingest):
    """invoice_paid НЕ попадает под запрет billing.* (billing-правда — только
    Stripe-вебхук); сам префикс billing. с этого эндпоинта отбивается."""
    assert post(client, golden("invoice_paid")).status_code == 200
    fake_billing = golden("invoice_paid")
    fake_billing["event_type"] = "billing.invoice_paid"
    assert post(client, fake_billing).status_code == 403


# ── 2. нормализация шлюза: зафиксированные расхождения D1-D3 ────────────────

def test_D1_open_email_is_stripped_even_for_server_events(client, ingest):
    """РАСХОЖДЕНИЕ D1: серверный email SimbaGo не переживает шлюз.
    email_hash при этом проходит — склейка работает, письма нет."""
    payload = golden("signup")
    assert payload["email"] == "cust@example.com"  # simbago его шлёт
    post(client, payload)
    e = landed(ingest)
    assert "email" not in e                        # платформа выбросила
    assert e["email_hash"] == payload["email_hash"]


def test_D2_source_api_rewritten_to_snippet(client, ingest):
    """РАСХОЖДЕНИЕ D2: source='api' отправителя затирается 'snippet'."""
    payload = golden("order_confirmed")
    assert payload["source"] == "api"
    post(client, payload)
    assert landed(ingest)["source"] == "snippet"


def test_D3_closed_meta_travels_as_json_string(client, ingest):
    """D3 ЗАКРЫТО: simbago шлёт meta JSON-строкой — в Kafka она уезжает
    строкой (совместимо со схемой String), содержимое переживает шлюз."""
    sent = golden("order_confirmed")
    assert isinstance(sent["meta"], str)   # контракт отправителя — строка
    post(client, sent)
    e = landed(ingest)
    assert isinstance(e["meta"], str)      # не вложенный объект
    m = json.loads(e["meta"])
    assert m["order_ref"] == "SG-CONTRACT-1"
    assert m["items"] == [{"sku": "BALL-1-V", "qty": 2, "name": "Ball"}]


# ── 3. граничные случаи ts ───────────────────────────────────────────────────

def test_ts_without_milliseconds_accepted_and_normalized(client, ingest):
    post(client, golden("signup", ts="2026-08-20 10:00:00"))
    assert landed(ingest)["ts"] == "2026-08-20 10:00:00.000"


def test_ts_from_future_replaced_with_receipt_time(client, ingest):
    future = (datetime.now(tz=timezone.utc) + timedelta(days=30)
              ).strftime("%Y-%m-%d %H:%M:%S.000")
    post(client, golden("signup", ts=future))
    assert landed(ingest)["ts"] != future


def test_ts_garbage_replaced_with_receipt_time(client, ingest):
    post(client, golden("signup", ts="вчера"))
    e = landed(ingest)
    datetime.strptime(e["ts"], "%Y-%m-%d %H:%M:%S.%f")  # валидный ts приёма


# ── 4. склейка (stitch): R2 по email_hash, R4 по псевдонимам ────────────────

def _event_key(name: str) -> EventKey:
    """EventKey, каким событие ляжет в саму склейку ПОСЛЕ шлюза: email
    вырезан (D1), поэтому email_norm пуст даже у серверных событий."""
    p = golden(name)
    return EventKey(client_user_id=p.get("client_user_id", ""),
                    email_hash=p.get("email_hash", ""),
                    email_norm="",          # D1: открытый email не доехал
                    last_ts=p["ts"])


def test_stitch_registered_user_R2_by_email_hash():
    p = golden("signup")
    idents, unmatched = build_identities("simbago", [], [_event_key("signup")])
    assert unmatched == []
    assert len(idents) == 1
    ident = idents[0]
    assert ident.email_hash == p["email_hash"]
    assert ident.client_user_id == "42"
    assert "42" in ident.client_user_ids
    # D1: адреса нет -> активационное письмо этому юзеру невозможно
    assert ident.email_norm == ""


def test_stitch_guest_R4_identity_by_cuid():
    idents, unmatched = build_identities(
        "simbago", [], [_event_key("order_confirmed_guest")])
    assert unmatched == []
    assert len(idents) == 1
    assert idents[0].client_user_id == "guest:+628123456789"
    assert idents[0].email_hash == ""


def test_stitch_mp_pseudonym_R4_identity():
    idents, _ = build_identities("simbago", [], [_event_key("mp_order")])
    assert len(idents) == 1
    assert idents[0].client_user_id == "mp:shopee_id:987654"


def test_stitch_signup_then_order_same_identity():
    """signup и order_confirmed одного юзера (один email_hash) склеиваются
    в ОДНУ identity."""
    keys = [_event_key("signup"), _event_key("order_confirmed")]
    keys[1].email_hash = keys[0].email_hash  # разные ящики в golden — уравняем
    idents, _ = build_identities("simbago", [], keys)
    assert len(idents) == 1


# ── 5. replenishment: order_confirmed.meta.items -> план ─────────────────────

def _order_from_golden(name: str) -> dict:
    """Как _load_orders собирает заказ из события: items из meta,
    order_ref = meta.order_ref | event_id (D4 закрыт: simbago шлёт
    order_ref, фолбэк на event_id больше не срабатывает)."""
    p = golden(name)
    meta = p["meta"]                       # уже строка — как лежит в CH
    items = parse_items(meta)
    ref = str(json.loads(meta).get("order_ref") or "").strip()
    return {"identity_id": "ident-1", "order_ref": ref or p["event_id"],
            "ts": datetime(2026, 8, 20, 10, 0, 0), "items": items}


def test_replenishment_items_parsed_from_meta():
    items = parse_items(golden("order_confirmed")["meta"])
    # D5 закрыто: name доезжает — {{product}} больше не деградирует до SKU
    assert items == [{"sku": "BALL-1-V", "qty": 2, "name": "Ball"}]


def test_D4_closed_order_ref_read_directly():
    """D4 ЗАКРЫТО: order_ref читается из meta НАПРЯМУЮ, без фолбэка на
    event_id — plan_id теперь детерминирован по номеру заказа."""
    p = golden("order_confirmed")
    assert json.loads(p["meta"])["order_ref"] == "SG-CONTRACT-1"
    order = _order_from_golden("order_confirmed")
    assert order["order_ref"] == "SG-CONTRACT-1"
    assert order["order_ref"] != p["event_id"]  # фолбэк не сработал


def test_replenishment_plan_created_from_order_confirmed():
    order = _order_from_golden("order_confirmed")
    plans = build_plans(
        tenant="simbago", orders=[order], eligible={"BALL-1-V"},
        baselines={}, medians={}, defaults={"BALL-1-V": 30},
        active_pairs=set(), existing_plan_ids=set(), optout_pairs=set())
    assert len(plans) == 1
    plan = plans[0]
    assert plan["sku"] == "BALL-1-V"
    assert plan["status"] == "ACTIVE"
    assert plan["predicted_days"] == 30
    assert plan["plan_id"] == plan_id_for(
        "simbago", "ident-1", "BALL-1-V", order["order_ref"])


def test_replenishment_duplicate_event_same_plan_id():
    """Ретрай Celery/at-least-once: повтор того же события даёт тот же
    plan_id и отсекается дубль-защитой."""
    order = _order_from_golden("order_confirmed")
    first = build_plans("simbago", [order], {"BALL-1-V"}, {}, {},
                        {"BALL-1-V": 30}, set(), set(), set())
    again = build_plans("simbago", [order], {"BALL-1-V"}, {}, {},
                        {"BALL-1-V": 30}, set(),
                        {p["plan_id"] for p in first}, set())
    assert again == []


def test_replenishment_empty_items_no_plan():
    """Граница: mp_order с items: [] — событие принято, identity есть,
    плана нет (и прогон не падает)."""
    assert parse_items(golden("mp_order_empty_items")["meta"]) == []


def test_replenishment_ineligible_sku_no_plan():
    order = _order_from_golden("order_confirmed")
    plans = build_plans("simbago", [order], eligible=set(), baselines={},
                        medians={}, defaults={}, active_pairs=set(),
                        existing_plan_ids=set(), optout_pairs=set())
    assert plans == []


# ── 6. сервисная вертикаль: visit_completed -> план цикла визитов ────────────

def test_visit_completed_accepted_via_server_token(client, ingest):
    """Серверный токен - штатный путь simbago: source='api' уцелел, meta
    доехала строкой с service/service_name/booking_ref."""
    ts = _now_ms()
    resp = client.post("/ingest/saas/events",
                       json=golden("visit_completed", ts=ts),
                       headers={"Authorization": "Bearer server-token"})
    assert resp.status_code == 200
    e = landed(ingest)
    assert e["tenant_id"] == "simbago"
    assert e["source"] == "api"            # серверный токен не затирает source
    assert e["ts"] == ts
    assert ingest.producer.messages[0]["key"] == "guest:+628123456789"
    assert isinstance(e["meta"], str)
    m = json.loads(e["meta"])
    # geo/ua дописывает шлюз (штатное обогащение) - контракт отправителя без них.
    m.pop("geo", None)
    m.pop("ua", None)
    assert m == {"service": "full-grooming", "service_name": "Full Grooming",
                 "booking_ref": "GB-CONTRACT-1"}


def test_visit_completed_meta_normalized_to_items():
    """parse_source_items: {service, service_name} -> [{sku, qty=1, name}] -
    дальше весь ecom-контур (атрибуты, базлайны, K7) без ветвлений."""
    meta = golden("visit_completed")["meta"]
    assert parse_items(meta) == []         # items-пути в сервисном событии нет
    assert parse_source_items(meta) == [
        {"sku": "full-grooming", "qty": 1, "name": "Full Grooming"}]


def test_replenishment_plan_created_from_visit_completed():
    """План цикла визитов из visit_completed: order_ref в meta нет -
    _load_orders падает на детерминированный event_id (дубль-защита жива)."""
    p = golden("visit_completed")
    items = parse_source_items(p["meta"])
    ref = str(json.loads(p["meta"]).get("order_ref") or "").strip() or p["event_id"]
    assert ref == "simbago-visit_completed:GB-CONTRACT-1"
    visit = {"identity_id": "ident-groom", "order_ref": ref,
             "ts": datetime(2026, 9, 1, 10, 0, 0), "items": items}
    plans = build_plans(
        tenant="simbago", orders=[visit], eligible={"full-grooming"},
        baselines={}, medians={}, defaults={"full-grooming": 30},
        active_pairs=set(), existing_plan_ids=set(), optout_pairs=set())
    assert len(plans) == 1
    plan = plans[0]
    assert plan["sku"] == "full-grooming"
    assert plan["status"] == "ACTIVE"
    assert plan["predicted_days"] == 30
    assert plan["plan_id"] == plan_id_for(
        "simbago", "ident-groom", "full-grooming", ref)
    # ретрай того же события -> тот же plan_id, дубль отсечён
    again = build_plans("simbago", [visit], {"full-grooming"}, {}, {},
                        {"full-grooming": 30}, set(),
                        {plan["plan_id"]}, set())
    assert again == []
