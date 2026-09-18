"""Replenishment Autopilot v1: чистая логика без ClickHouse - создание планов,
дубль-защита, дозревание с lead_days, частотные лимиты, EWMA только на
подтверждённых циклах, optout, выключенный конфиг, подписанный reorder-код."""

from datetime import date, datetime, timedelta

from stripe_sync.replenishment import (advance_plans,
                                       apply_vertical_campaign_defaults,
                                       build_plans, due_on, ewma_update,
                                       extension_days_for, parse_items,
                                       parse_source_items, plan_id_for,
                                       predicted_for, reorder_url,
                                       replenishment_config, run, select_due,
                                       sku_medians)
from stripe_sync.wa_templates import (parse_reorder_code, parse_reply_intent,
                                      reorder_code)

T0 = datetime(2026, 8, 1, 10, 0, 0)


def _plan(pid="p1", identity="id1", sku="food-2kg", ref="o1", status="ACTIVE",
          started=T0, predicted=30, ext=0):
    return {"plan_id": pid, "identity_id": identity, "sku": sku,
            "order_ref": ref, "status": status, "started_at": started,
            "predicted_days": predicted, "extension_days": ext,
            "finished_at": None, "finish_reason": ""}


def _order(identity="id1", ref="o1", ts=T0, skus=("food-2kg",)):
    return {"identity_id": identity, "order_ref": ref, "ts": ts,
            "items": [{"sku": s, "qty": 1, "name": ""} for s in skus]}


# ── конфиг тенанта ───────────────────────────────────────────────────────────

def test_config_defaults_disabled():
    cfg = replenishment_config({})
    assert cfg == {"enabled": False, "lead_days": 4,
                   "reorder_url_template": "", "max_per_customer_week": 2,
                   "plan_source_events": ["order_confirmed"],
                   "vertical": "ecom"}


def test_config_overrides_and_garbage():
    cfg = replenishment_config({"replenishment": {
        "enabled": True, "lead_days": "7", "max_per_customer_week": "мусор",
        "reorder_url_template": "https://shop.example/r?sku={sku}&c={code}"}})
    assert cfg["enabled"] is True
    assert cfg["lead_days"] == 7
    assert cfg["max_per_customer_week"] == 2      # мусор -> дефолт, не падение
    assert cfg["reorder_url_template"].startswith("https://shop.example")


def test_disabled_config_is_total_noop():
    # client=None: любое обращение к базе уронило бы тест - его не происходит
    assert run(None, "t1", replenishment_config({})) == {"skipped": "disabled"}


# ── вертикаль service: конфиг ────────────────────────────────────────────────

def test_config_vertical_default_ecom_and_garbage():
    assert replenishment_config({})["vertical"] == "ecom"
    assert replenishment_config(
        {"replenishment": {"vertical": " Service "}})["vertical"] == "service"
    # неизвестная вертикаль не роняет джоб и не включает чужое поведение
    assert replenishment_config(
        {"replenishment": {"vertical": "spa"}})["vertical"] == "ecom"


def test_config_plan_source_events_default_and_override():
    assert replenishment_config({})["plan_source_events"] == ["order_confirmed"]
    cfg = replenishment_config({"replenishment": {
        "plan_source_events": ["visit_completed", "order_confirmed",
                               "visit_completed", "", None]}})
    # дедуп с сохранением порядка, мусор молча выброшен
    assert cfg["plan_source_events"] == ["visit_completed", "order_confirmed"]
    # мусор целиком -> дефолт, не падение и не пустой список
    for garbage in ("visit_completed", [], [""], {"a": 1}, 7):
        cfg = replenishment_config(
            {"replenishment": {"plan_source_events": garbage}})
        assert cfg["plan_source_events"] == ["order_confirmed"]


def test_config_defaults_lists_not_shared_between_tenants():
    replenishment_config({})["plan_source_events"].append("hacked")
    assert replenishment_config({})["plan_source_events"] == ["order_confirmed"]


# ── создание планов ──────────────────────────────────────────────────────────

def test_build_plans_only_eligible_sku_and_known_cycle():
    orders = [_order(skus=("food-2kg", "toy", "shampoo"))]
    plans = build_plans("t1", orders, {"food-2kg", "shampoo"}, {}, {},
                        {"food-2kg": 30}, set(), set(), set())
    # toy не отслеживается; shampoo eligible, но цикла никто не знает - не гадаем
    assert [p["sku"] for p in plans] == ["food-2kg"]
    assert plans[0]["status"] == "ACTIVE"
    assert plans[0]["predicted_days"] == 30
    assert plans[0]["extension_days"] == 0


def test_build_plans_second_order_same_pair_queued():
    orders = [_order(ref="o1", ts=T0),
              _order(ref="o2", ts=T0 + timedelta(days=3))]
    plans = build_plans("t1", orders, {"food-2kg"}, {}, {}, {"food-2kg": 30},
                        set(), set(), set())
    assert [p["status"] for p in plans] == ["ACTIVE", "QUEUED"]


def test_build_plans_duplicate_order_ref_skipped():
    pid = plan_id_for("t1", "id1", "food-2kg", "o1")
    plans = build_plans("t1", [_order(ref="o1")], {"food-2kg"}, {}, {},
                        {"food-2kg": 30}, set(), {pid}, set())
    assert plans == []                    # повтор события заказа - дубль


def test_build_plans_optout_pair_never_planned():
    plans = build_plans("t1", [_order()], {"food-2kg"}, {}, {},
                        {"food-2kg": 30}, set(), set(), {("id1", "food-2kg")})
    assert plans == []


def test_predicted_ladder_baseline_median_default():
    baselines = {("id1", "s"): (26.4, 3)}
    medians = {"s": 33.0}
    defaults = {"s": 45}
    assert predicted_for("id1", "s", baselines, medians, defaults) == 26
    assert predicted_for("id2", "s", baselines, medians, defaults) == 33
    assert predicted_for("id2", "s", {}, {}, defaults) == 45
    assert predicted_for("id2", "s", {}, {}, {}) == 0


def test_sku_medians_from_pair_baselines():
    baselines = {("a", "s"): (20.0, 1), ("b", "s"): (30.0, 2),
                 ("c", "s"): (40.0, 1), ("a", "z"): (0.0, 0)}
    med = sku_medians(baselines)
    assert med == {"s": 30.0}             # нулевой базлайн в медиану не входит


def test_parse_items_tolerates_garbage():
    assert parse_items("не json") == []
    assert parse_items('{"items": [{"qty": 2}, "x", {"sku": " a ", "name": "Dog food"}]}') \
        == [{"sku": "a", "qty": 1, "name": "Dog food"}]


# ── дозревание с lead_days и частотные лимиты ────────────────────────────────

def test_due_on_respects_lead_days_and_extension():
    plan = _plan(started=datetime(2026, 8, 1), predicted=33, ext=7)
    assert due_on(plan, 4) == date(2026, 9, 6)   # 1.08 + 33 + 7 - 4


def test_select_due_matures_with_lead_days():
    today = date(2026, 8, 30)
    ripe = _plan(pid="p1", started=datetime(2026, 8, 1), predicted=33)   # due 30.08
    green = _plan(pid="p2", identity="id2", started=datetime(2026, 8, 2),
                  predicted=33)                                          # due 31.08
    finished = _plan(pid="p3", identity="id3", status="FINISHED",
                     started=datetime(2026, 7, 1), predicted=10)
    out = select_due([ripe, green, finished], today, 4, {}, {}, 2)
    assert [p["plan_id"] for p in out] == ["p1"]


def test_select_due_plan_cooldown_7d():
    today = date(2026, 8, 30)
    plan = _plan(started=datetime(2026, 8, 1), predicted=20)   # давно дозрел
    assert select_due([plan], today, 4, {"p1": date(2026, 8, 25)}, {}, 2) == []
    out = select_due([plan], today, 4, {"p1": date(2026, 8, 23)}, {}, 2)
    assert [p["plan_id"] for p in out] == ["p1"]


def test_select_due_identity_weekly_cap():
    today = date(2026, 8, 30)
    plans = [_plan(pid=f"p{i}", sku=f"sku{i}", ref=f"o{i}",
                   started=datetime(2026, 8, 1), predicted=20)
             for i in range(3)]
    out = select_due(plans, today, 4, {}, {}, 2)
    assert len(out) == 2                  # не больше 2/нед на клиента
    out = select_due(plans, today, 4, {}, {"id1": 2}, 2)
    assert out == []                      # неделя уже выбрана прошлыми пушами


# ── EWMA: только подтверждённые циклы ────────────────────────────────────────

def test_ewma_first_cycle_and_blend():
    assert ewma_update(0.0, 0, 30) == (30.0, 1)
    assert ewma_update(30.0, 1, 40) == (33.0, 2)   # 0.7*30 + 0.3*40


def test_advance_reorder_closes_without_learning():
    plan = _plan()
    reorder_ts = T0 + timedelta(days=28)
    updates, bases = advance_plans(
        [plan], {("id1", "food-2kg"): [(T0, "o1"), (reorder_ts, "o2")]},
        {}, {}, {}, set(), {}, T0 + timedelta(days=29))
    assert updates[0]["status"] == "FINISHED"
    assert updates[0]["finish_reason"] == "REORDERED"
    assert updates[0]["finished_at"] == reorder_ts
    assert bases == []                    # реордер цикл закрывает, но НЕ учит


def test_advance_confirm_closes_and_learns_ewma():
    plan = _plan()
    confirm_ts = T0 + timedelta(days=26)
    updates, bases = advance_plans(
        [plan], {}, {"p1": [confirm_ts]}, {}, {}, set(),
        {("id1", "food-2kg"): (30.0, 1)}, T0 + timedelta(days=27))
    assert updates[0]["finish_reason"] == "USER_CONFIRMED"
    assert bases == [{"identity_id": "id1", "sku": "food-2kg",
                      "baseline_days": 28.8,        # 0.7*30 + 0.3*26
                      "last_cycle_days": 26.0, "cycles_count": 2}]


def test_advance_confirm_before_started_ignored():
    plan = _plan()
    updates, bases = advance_plans(
        [plan], {}, {"p1": [T0 - timedelta(days=1)]}, {}, {}, set(), {},
        T0 + timedelta(days=1))
    assert updates == [] and bases == []


def test_advance_still_have_extends_idempotently():
    plan = _plan()
    still = {("id1", "food-2kg"): [T0 + timedelta(days=20)]}
    updates, _ = advance_plans([plan], {}, {}, {}, still, set(), {},
                               T0 + timedelta(days=21))
    assert updates[0]["extension_days"] == 7
    assert updates[0]["status"] == "ACTIVE"
    # повторный прогон по тем же событиям ничего не меняет (не +7 ещё раз)
    plan2 = {**plan, "extension_days": 7}
    updates2, _ = advance_plans([plan2], {}, {}, {}, still, set(), {},
                                T0 + timedelta(days=22))
    assert updates2 == []
    assert extension_days_for(plan2, still) == 7


def test_advance_optout_cancels_active_and_queued():
    active = _plan(pid="p1")
    queued = _plan(pid="p2", ref="o2", status="QUEUED")
    updates, bases = advance_plans(
        [active, queued], {}, {}, {}, {}, {("id1", "food-2kg")}, {}, T0)
    assert sorted((u["plan_id"], u["finish_reason"]) for u in updates) \
        == [("p1", "CANCELLED"), ("p2", "CANCELLED")]
    assert bases == []


def test_advance_reorder_promotes_queued():
    active = _plan(pid="p1")
    queued = _plan(pid="p2", ref="o2", status="QUEUED",
                   started=T0 + timedelta(days=1))
    reorder_ts = T0 + timedelta(days=25)
    updates, _ = advance_plans(
        [active, queued],
        {("id1", "food-2kg"): [(reorder_ts, "o3")]}, {}, {}, {}, set(), {},
        T0 + timedelta(days=26))
    by_id = {u["plan_id"]: u for u in updates}
    assert by_id["p1"]["status"] == "FINISHED"
    assert by_id["p2"]["status"] == "ACTIVE"
    assert by_id["p2"]["started_at"] == reorder_ts   # запасной пакет начат тогда


# ── вертикаль service: визиты вместо заказов ─────────────────────────────────

def test_parse_source_items_visit_service_meta():
    # visit_completed несёт service вместо items -> sku=услуга, qty=1
    assert parse_source_items('{"service": " grooming-full ", '
                              '"service_name": "Full grooming"}') \
        == [{"sku": "grooming-full", "qty": 1, "name": "Full grooming"}]
    assert parse_source_items('{"service": "vet-checkup"}') \
        == [{"sku": "vet-checkup", "qty": 1, "name": ""}]
    # items-путь главнее и не изменился ни на йоту
    both = '{"items": [{"sku": "a"}], "service": "grooming-full"}'
    assert parse_source_items(both) == parse_items(both)
    assert parse_source_items("не json") == []
    assert parse_source_items('{"service": ""}') == []


def test_visit_completed_builds_plan_with_service_sku():
    # заказ-объект тот же, что даёт _load_orders из visit_completed
    visits = [_order(ref="v1", skus=("grooming-full",))]
    plans = build_plans("t1", visits, {"grooming-full"}, {}, {},
                        {"grooming-full": 45}, set(), set(), set())
    assert [p["sku"] for p in plans] == ["grooming-full"]
    assert plans[0]["status"] == "ACTIVE"
    assert plans[0]["predicted_days"] == 45


def test_service_predicted_ladder_same_as_ecom():
    """У сервиса нет «упаковки»: базлайн пары (EWMA на интервалах между
    визитами) -> медиана по услуге -> default_days. Лестница predicted_for уже
    работает так - тест фиксирует контракт, правка не требовалась."""
    baselines = {("id1", "grooming-full"): (42.0, 3)}
    medians = {"grooming-full": 35.0}
    defaults = {"grooming-full": 45}
    assert predicted_for("id1", "grooming-full", baselines, medians,
                         defaults) == 42
    assert predicted_for("new", "grooming-full", baselines, medians,
                         defaults) == 35
    assert predicted_for("new", "grooming-full", {}, {}, defaults) == 45
    assert predicted_for("new", "grooming-full", {}, {}, {}) == 0


def test_service_second_visit_closes_and_learns_interval():
    """service: следующий визит пары закрывает цикл REORDERED И учит EWMA
    фактическим интервалом (визит - достоверный факт, подтверждение клиента
    не нужно) - в отличие от ecom, где REORDERED не учит."""
    plan = _plan(sku="grooming-full", predicted=45)
    visit2_ts = T0 + timedelta(days=35)
    updates, bases = advance_plans(
        [plan], {("id1", "grooming-full"): [(T0, "v1"), (visit2_ts, "v2")]},
        {}, {}, {}, set(), {("id1", "grooming-full"): (45.0, 1)},
        T0 + timedelta(days=36), vertical="service")
    assert updates[0]["status"] == "FINISHED"
    assert updates[0]["finish_reason"] == "REORDERED"
    assert updates[0]["finished_at"] == visit2_ts
    assert bases == [{"identity_id": "id1", "sku": "grooming-full",
                      "baseline_days": 42.0,        # 0.7*45 + 0.3*35
                      "last_cycle_days": 35.0, "cycles_count": 2}]


def test_service_confirm_still_learns_too():
    plan = _plan(sku="grooming-full")
    updates, bases = advance_plans(
        [plan], {}, {"p1": [T0 + timedelta(days=30)]}, {}, {}, set(), {},
        T0 + timedelta(days=31), vertical="service")
    assert updates[0]["finish_reason"] == "USER_CONFIRMED"
    assert bases[0]["cycles_count"] == 1


def test_ecom_reorder_still_does_not_learn_regression():
    """Регрессия: дефолтная вертикаль (без аргумента И с explicit ecom)
    ведёт себя как раньше - REORDERED закрывает, но EWMA не двигает."""
    plan = _plan()
    orders = {("id1", "food-2kg"): [(T0, "o1"), (T0 + timedelta(days=28), "o2")]}
    for kwargs in ({}, {"vertical": "ecom"}):
        updates, bases = advance_plans(
            [dict(plan)], orders, {}, {}, {}, set(), {},
            T0 + timedelta(days=29), **kwargs)
        assert updates[0]["finish_reason"] == "REORDERED"
        assert bases == []


# ── вертикаль service: дефолтный текст K7 ────────────────────────────────────

CONF = {"campaigns": [
    {"campaign_id": "K7_replenishment",
     "steps": [{"delay_h": 0, "action": "email",
                "subject": "Running low on {{product}}?",
                "body": "Reorder: {{reorder_url}}", "cta_label": "Order again",
                "cta_url": "{{reorder_url}}",
                "channels": ["whatsapp", "email"]}]},
    {"campaign_id": "K1_other",
     "steps": [{"subject": "hi", "body": "there"}]},
]}


def test_vertical_defaults_ecom_is_noop():
    cfg = replenishment_config({})
    assert apply_vertical_campaign_defaults(CONF, cfg) is CONF


def test_vertical_defaults_service_swaps_k7_text_only():
    cfg = replenishment_config({"replenishment": {"vertical": "service"}})
    out = apply_vertical_campaign_defaults(CONF, cfg)
    step = out["campaigns"][0]["steps"][0]
    assert step["subject"] == "Time for your next {{product}}?"
    assert "Book again" in step["body"] and "{{reorder_url}}" in step["body"]
    assert step["cta_label"] == "Book again"
    # структура шага и остальные кампании нетронуты; исходник не мутирован
    assert step["cta_url"] == "{{reorder_url}}"
    assert step["channels"] == ["whatsapp", "email"]
    assert out["campaigns"][1] == CONF["campaigns"][1]
    assert CONF["campaigns"][0]["steps"][0]["subject"] \
        == "Running low on {{product}}?"


# ── подписанный reorder-код и ссылка ─────────────────────────────────────────

def test_reorder_code_roundtrip():
    code = reorder_code("t1", "plan_abc", secret="k")
    assert code.startswith("RB_")
    assert parse_reorder_code("t1", f"клик: {code}", secret="k") == "plan_abc"


def test_reorder_code_rejects_forgery():
    code = reorder_code("t1", "plan_abc", secret="k")
    assert parse_reorder_code("other", code, secret="k") == ""   # чужой тенант
    forged = code[:-1] + ("0" if code[-1] != "0" else "1")
    assert parse_reorder_code("t1", forged, secret="k") == ""
    assert parse_reorder_code("t1", "просто текст", secret="k") == ""
    assert reorder_code("t1", "", secret="k") == ""


def test_reorder_url_template_substitution():
    url = reorder_url("https://shop.example/reorder?sku={sku}&code={code}",
                      "food 2kg", "RB_x_y")
    assert url == "https://shop.example/reorder?sku=food%202kg&code=RB_x_y"
    assert reorder_url("", "s", "c") == ""   # нет чекаута - нет ссылки


# ── распознавание ответа клиента (parse_reply_intent) ────────────────────────

def test_reply_intent_confirmed_only_via_valid_code():
    """confirmed двигает EWMA - только валидный подписанный RB_-код."""
    code = reorder_code("t1", "plan_abc", secret="k")
    assert parse_reply_intent("t1", f"ok {code}", secret="k") == \
        ("confirmed", "plan_abc")
    # подделка/чужой тенант кода не дают
    forged = code[:-1] + ("0" if code[-1] != "0" else "1")
    assert parse_reply_intent("t1", forged, secret="k") == ("", "")
    assert parse_reply_intent("other", code, secret="k") == ("", "")


def test_reply_intent_exact_button_phrases():
    for text in ("still have", "Still Have", "  masih ada ", "Ещё есть",
                 "еще  есть"):
        assert parse_reply_intent("t1", text, secret="k") == ("still_have", "")
    for text in ("stop", "STOP", "berhenti", "Не напоминать",
                 "больше не напоминать"):
        assert parse_reply_intent("t1", text, secret="k") == ("optout", "")


def test_reply_intent_free_text_is_never_classified():
    """Свободный текст - оператору в инбокс, не событию."""
    for text in ("у меня ещё есть корм, спасибо", "please stop calling maybe",
                 "reorder", "beli lagi", "заказать снова", "ok", ""):
        assert parse_reply_intent("t1", text, secret="k") == ("", "")
