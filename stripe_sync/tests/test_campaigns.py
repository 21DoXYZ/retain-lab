"""Чистая логика раннера кампаний: планирование шагов, выходы, рендер писем."""

from datetime import datetime, timedelta

from stripe_sync.campaign_tick import due_steps, exit_status, next_step_time
from stripe_sync.saas_senders import render

STEPS = [{"delay_h": 0, "action": "email"},
         {"delay_h": 0, "action": "offer"},
         {"delay_h": 24, "action": "email"},
         {"delay_h": 72, "action": "email"}]
T0 = datetime(2026, 8, 5, 12, 0, 0)


def test_due_steps_batches_zero_delay_and_stops_at_future():
    # одновременные шаги уходят вместе, разные ступени - по одной за тик
    assert due_steps(STEPS, T0, 0, T0) == [0, 1]
    assert due_steps(STEPS, T0, 0, T0 + timedelta(hours=25)) == [0, 1]
    assert due_steps(STEPS, T0, 2, T0 + timedelta(hours=25)) == [2]
    assert due_steps(STEPS, T0, 2, T0 + timedelta(hours=23)) == []
    assert due_steps(STEPS, T0, 4, T0 + timedelta(hours=100)) == []


def test_next_step_time_tracks_pending_step():
    assert next_step_time(STEPS, T0, 2) == T0 + timedelta(hours=24)
    assert next_step_time(STEPS, T0, 4) == T0   # шагов не осталось


def test_exit_status_priority_stage_change_over_done():
    assert exit_status("DUNNING", "DUNNING", 2, 4) is None
    assert exit_status("MONITOR", "DUNNING", 2, 4) == "exited"
    assert exit_status("DUNNING", "DUNNING", 4, 4) == "done"
    # смена стадии важнее конца шагов: цель достигнута -> exited, не done
    assert exit_status("MONITOR", "DUNNING", 4, 4) == "exited"


def test_render_known_and_unknown_placeholders():
    out = render("Update card: {{card_update_url}} ({{mystery}})",
                 {"card_update_url": "https://b.example/p"})
    assert out == "Update card: https://b.example/p ({{mystery}})"


def test_tenant_identity_overrides_env(tmp_path, monkeypatch):
    """Отправитель = бренд тенанта: tenants.json важнее платформенного env."""
    import json
    from stripe_sync import saas_senders as sn
    from stripe_sync.saas_senders import EmailConfig, MessagingConfig, tenant_configs

    f = tmp_path / "tenants.json"
    f.write_text(json.dumps({"hubcontent": {
        "email_from": "Hub Content <care@mail.hubcontent.com>",
        "sms_sender": "HubContent", "telegram_bot_token": "tt"}}))
    monkeypatch.setattr(sn, "TENANTS_FILE", str(f))

    e, m = tenant_configs(
        "hubcontent",
        EmailConfig(email_from="platform@retivo.digital"),
        MessagingConfig(sms_sender="Retivo", viber_sender="Retivo"))
    assert e.email_from == "Hub Content <care@mail.hubcontent.com>"
    assert m.sms_sender == "HubContent"
    assert m.viber_sender == "Retivo"          # не задан у тенанта - фолбэк env
    assert m.telegram_bot_token == "tt"

    e2, m2 = tenant_configs("unknown", EmailConfig(email_from="p@x"), MessagingConfig())
    assert e2.email_from == "p@x"


def test_inapp_row_renders_and_expires():
    from datetime import timedelta
    from stripe_sync.campaign_tick import INAPP_COLUMNS, inapp_row

    camp = {"campaign_id": "K3_payment_recovery", "entry_stage": "DUNNING"}
    step = {"action": "inapp", "subject": "Payment issue",
            "body": "Update your card: {{card_update_url}}",
            "cta_label": "Update card", "cta_url": "{{card_update_url}}",
            "ttl_days": 7}
    row = inapp_row("hub", camp, step, 0, "id-1", "u_1", T0,
                    {"card_update_url": "https://b.example/p"})
    assert len(row) == len(INAPP_COLUMNS)
    d = dict(zip(INAPP_COLUMNS, row))
    assert d["message_id"] == "K3_payment_recovery:0:id-1"
    assert d["client_user_id"] == "u_1"
    assert d["body"] == "Update your card: https://b.example/p"
    assert d["cta_url"] == "https://b.example/p"
    assert d["entry_stage"] == "DUNNING"
    assert d["expires_at"] == T0 + timedelta(days=7)


def test_inapp_row_defaults():
    from stripe_sync.campaign_tick import INAPP_COLUMNS, inapp_row

    camp = {"campaign_id": "K2", "entry_stage": "CONVERT"}
    d = dict(zip(INAPP_COLUMNS,
                 inapp_row("hub", camp, {"action": "inapp", "body": "hi"},
                           2, "id-9", "u_9", T0, {"app_url": "https://a.pp"})))
    assert d["cta_label"] == "Open" and d["cta_url"] == "https://a.pp"
    assert d["title"] == ""


def test_resolve_autopilot_override_wins():
    from stripe_sync.campaign_tick import resolve_autopilot

    assert resolve_autopilot({"autopilot": False}, {}) is False
    assert resolve_autopilot({"autopilot": True}, {}) is True
    # рантайм-рубильник из tenants.json важнее захардкоженного в конфиге
    assert resolve_autopilot({"autopilot": False}, {"autopilot": True}) is True
    assert resolve_autopilot({"autopilot": True}, {"autopilot": False}) is False
    assert resolve_autopilot({}, {}) is False


# ── Каналы: устойчивость отправки ────────────────────────────────────────────

def test_phone_with_spaces_does_not_crash_the_run():
    """Клиенты хранят телефоны как попало. Раньше int('+38 063...') кидал
    ValueError прямо в тик - и НИКТО из юзеров тенанта не получал касаний."""
    from stripe_sync.saas_senders import MessagingConfig, send_sms, send_viber
    cfg = MessagingConfig(dry_run=True)
    for raw in ("+38 (063) 111-22-33", "380 63 111 22 33", "+380-63-111-22-33"):
        assert send_sms(raw, "hi", cfg) == (True, "dry_run")
    for bad in ("not-a-phone", "", "12345", "+++"):
        assert send_sms(bad, "hi", cfg) == (False, "invalid_phone")
        assert send_viber(bad, "hi", cfg) == (False, "invalid_phone")


def test_us_numbers_get_no_sms():
    """TCPA: SMS на номер +1 без письменного согласия - иски $500-1500 за штуку.
    Правило было только в документации, теперь в коде."""
    from stripe_sync.saas_senders import MessagingConfig, is_us_number, send_sms
    cfg = MessagingConfig(dry_run=True)
    assert is_us_number("14155550134")
    assert not is_us_number("380631112233")
    assert send_sms("+1 415 555 0134", "hi", cfg) == (False, "us_sms_blocked")
    # виберу TCPA не писан - это OTT-мессенджер, не SMS
    from stripe_sync.saas_senders import send_viber
    assert send_viber("+1 415 555 0134", "hi", cfg) == (True, "dry_run")


def test_transient_vs_permanent_failures():
    """Повторяем только то, что имеет смысл повторить."""
    from stripe_sync.saas_senders import transient_failure
    for d in ("http_500", "http_503", "http_429", "URLError", "timeout",
              "RemoteDisconnected"):
        assert transient_failure(d), d
    for d in ("http_401", "http_404", "http_422", "invalid_phone",
              "us_sms_blocked", "telegram_not_configured", "unknown_channel:fax",
              "dry_run", ""):
        assert not transient_failure(d), d


def test_unknown_channel_is_not_retried_forever():
    from stripe_sync.saas_senders import (EmailConfig, MessagingConfig,
                                          route_message, transient_failure)
    ok, detail = route_message("fax", "1", "s", "b", EmailConfig(), MessagingConfig())
    assert not ok and detail.startswith("unknown_channel")
    assert not transient_failure(detail)


# ── Прогон тика на подставном ClickHouse: проверяем, что касание не теряется ──

class _Res:
    def __init__(self, rows):
        self.result_rows = rows


class FakeCH:
    """Минимальный клиент: отвечает по фрагменту запроса, копит вставки."""

    def __init__(self, stages, retry_rows=0, touches=None):
        self.stages, self.retry_rows = stages, retry_rows
        # [identity, касаний за сутки, за неделю] - частотный предохранитель
        self.touches = touches or []
        self.inserts = []

    def query(self, sql, parameters=None):
        if "user_actions" in sql:
            return _Res(self.stages)
        if "email_suppressions_current" in sql:
            return _Res([])
        if "contacts_current" in sql:
            return _Res([])
        if "campaign_enrollments_current" in sql:
            return _Res([])
        if "campaign_send_log" in sql and "GROUP BY identity_id" in sql:
            return _Res(self.touches)
        if "campaign_send_log" in sql:
            return _Res([[self.retry_rows]])
        raise AssertionError("неожиданный запрос: " + sql[:80])

    def insert(self, table, rows, column_names=None):
        self.inserts.append((table, rows, column_names))

    def logged(self):
        out = []
        for table, rows, cols in self.inserts:
            if table.endswith("campaign_send_log"):
                out.append(dict(zip(cols, rows[0])))
        return out

    def saved(self):
        out = []
        for table, rows, cols in self.inserts:
            if table.endswith("campaign_enrollments"):
                out.append(dict(zip(cols, rows[0])))
        return out


def _live_tick(monkeypatch, tmp_path, sender, retry_rows=0, users=None,
               touches=None):
    """Тик с боевым (не dry-run) режимом и подменённой отправкой."""
    import campaign_tick as ct
    import overrides as ov_mod
    import saas_senders as sn
    # пути читаются в МОМЕНТ ИМПОРТА, env после этого уже не влияет
    monkeypatch.setattr(ov_mod, "OVERRIDES_FILE", str(tmp_path / "ov.json"))
    monkeypatch.setattr(sn, "TENANTS_FILE", str(tmp_path / "tenants.json"))
    (tmp_path / "tenants.json").write_text('{"probe": {"autopilot": true}}')
    monkeypatch.setenv("SIGNALS_DRY_RUN", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_probe")
    monkeypatch.setenv("EMAIL_FROM", "Probe <care@probe.test>")
    monkeypatch.setattr(ct, "route_message", sender)
    users = users or [["id1", "DUNNING", "user1@probe.test", "u1"]]
    client = FakeCH(users, retry_rows=retry_rows, touches=touches)
    return client, ct.tick(client, "probe")


def test_provider_outage_does_not_burn_the_touch(monkeypatch, tmp_path):
    """503 у провайдера: шаг помечен retry и НЕ сдвинут - следующий тик повторит.
    Раньше письмо о несписании исчезало навсегда из-за минутного сбоя."""
    client, _ = _live_tick(monkeypatch, tmp_path,
                           lambda *a, **k: (False, "http_503"))
    logs = [r for r in client.logged() if r["action"] == "email"]
    assert logs and logs[0]["status"] == "retry" and logs[0]["reason"] == "http_503"
    # шаг НЕ сдвинулся: сохранённый индекс указывает на несделанное касание
    assert client.saved()[-1]["step_idx"] == logs[0]["step_idx"]


def test_retries_are_bounded(monkeypatch, tmp_path):
    """После MAX_SEND_RETRIES перестаём долбиться и идём дальше по цепочке."""
    import campaign_tick as ct
    client, _ = _live_tick(monkeypatch, tmp_path,
                           lambda *a, **k: (False, "http_503"),
                           retry_rows=ct.MAX_SEND_RETRIES)
    logs = [r for r in client.logged() if r["action"] == "email"]
    assert logs and logs[0]["status"] == "rejected"
    assert client.saved()[-1]["step_idx"] > logs[0]["step_idx"]


def test_one_broken_contact_does_not_stop_the_others(monkeypatch, tmp_path):
    """Исключение на одном юзере больше не валит весь прогон тенанта."""
    def boom(channel, address, *a, **k):
        if address.startswith("bad"):
            raise ValueError("invalid literal for int()")
        return True, "msg_ok"

    client, stats = _live_tick(
        monkeypatch, tmp_path, boom,
        users=[["id1", "DUNNING", "bad@probe.test", "u1"],
               ["id2", "DUNNING", "good@probe.test", "u2"]])
    logs = [r for r in client.logged() if r["action"] == "email"]
    by_status = {r["identity_id"]: r["status"] for r in logs}
    assert by_status["id1"] == "rejected"
    assert by_status["id2"] == "sent"
    assert stats["enrolled"] == 2


def test_backlog_does_not_fire_the_whole_chain_at_once():
    """Раннер стоял трое суток. Человек не должен получить четыре письма за
    минуту: отдаём только группу шагов с одинаковой задержкой."""
    from stripe_sync.campaign_tick import due_steps
    steps = [{"delay_h": 0}, {"delay_h": 0}, {"delay_h": 24}, {"delay_h": 72}]
    late = T0 + timedelta(hours=100)
    assert due_steps(steps, T0, 0, late) == [0, 1]     # только «мгновенная» пара
    assert due_steps(steps, T0, 2, late) == [2]        # дальше по одному
    assert due_steps(steps, T0, 3, late) == [3]


def test_delay_between_touches_survives_downtime():
    """Между 2-м и 3-м касанием задумано двое суток - после простоя пауза
    обязана сохраниться, а не схлопнуться в ноль."""
    from stripe_sync.campaign_tick import next_step_time
    steps = [{"delay_h": 0}, {"delay_h": 24}, {"delay_h": 72}]
    late = T0 + timedelta(hours=100)          # шаг 1 ушёл с опозданием
    nxt = next_step_time(steps, T0, 2, late)
    assert nxt == late + timedelta(hours=48)  # 72 - 24 = двое суток от факта
    # без опоздания расписание прежнее
    assert next_step_time(steps, T0, 2, T0 + timedelta(hours=24)) == T0 + timedelta(hours=72)


def test_sms_length_respects_the_alphabet():
    """Кириллица в SMS - 70 знаков на сегмент, латиница 160. Не режешь сам -
    оператор порежет и возьмёт деньги за каждую часть."""
    from stripe_sync.saas_senders import fit_sms
    ru = "Платёж не прошёл, обновите карту в личном кабинете " * 6
    en = "Payment failed, please update your card in the billing portal " * 6
    assert len(fit_sms(ru)) <= 140 and fit_sms(ru).endswith("…")
    assert len(fit_sms(en)) <= 320 and fit_sms(en).endswith("…")
    assert fit_sms("Коротко") == "Коротко"        # короткое не трогаем


# ── Частота и форма цепочек: сверено с публичными бенчмарками ────────────────

def test_frequency_cap_is_a_rule_about_the_person_not_the_campaign():
    """Причина отписок №1 - количество писем, а не их текст.

    Отдельная цепочка не видит соседей, поэтому лимит стоит НАД кампаниями.
    """
    from campaign_tick import frequency_block
    assert frequency_block("K1_activation", 0, 0) == ""
    assert frequency_block("K1_activation", 1, 1) == "freq_cap_day"
    assert frequency_block("K1_activation", 0, 3) == "freq_cap_week"


def test_dunning_ignores_the_frequency_cap():
    """Сломанная оплата - не рассылка. Молчать про неё ради частоты нельзя."""
    from campaign_tick import frequency_block
    assert frequency_block("K3_payment_recovery", 5, 20) == ""


def test_frequency_cap_holds_the_touch_instead_of_burning_it(monkeypatch, tmp_path):
    """Придержанный шаг обязан созреть снова, а не пропасть.

    Иначе соседняя кампания молча съедала бы касание навсегда.
    """
    import campaign_tick as ct
    sent = []
    client, _ = _live_tick(monkeypatch, tmp_path,
                           lambda *a, **k: (sent.append(a) or (True, "id")),
                           users=[["id1", "ACTIVATE", "u@probe.test", "u1"]],
                           touches=[["id1", 1, 1]])
    assert not sent                                  # письмо не ушло
    logged = client.logged()
    assert logged and logged[0]["reason"] == "freq_cap_day"
    saved = client.saved()
    assert not saved or saved[0]["step_idx"] == 0    # шаг не сдвинут


def _chain(campaign_id):
    import json
    from campaign_tick import CAMPAIGNS_PATH
    conf = json.loads(CAMPAIGNS_PATH.read_text())["_default"]
    camp = next(c for c in conf["campaigns"] if c["campaign_id"] == campaign_id)
    days, total = [], 0.0
    for s in camp["steps"]:
        total += float(s.get("delay_h", 0)) / 24.0
        days.append(round(total, 1))
    return camp, days


def test_dunning_runs_for_weeks_because_late_touches_still_recover():
    """Нулевой день возвращает ~13% платежей, но и тридцатый ещё ~4%.

    Цепочка на три дня дарила эти проценты никому.
    """
    camp, days = _chain("K3_payment_recovery")
    assert days[-1] >= 14, "дуннинг обрывается раньше двух недель"
    emails = [s for s in camp["steps"] if s["action"] == "email"]
    assert len(emails) >= 4, "меньше четырёх писем - ниже бенчмарка"


def test_winback_waits_before_the_first_word_and_pays_late():
    """Первое касание на 14-й день даёт больше возвратов, чем письмо вдогонку.

    А глубина скидки решает меньше, чем момент: деньги предлагаем последними,
    иначе возвращаются те, кто уйдёт снова, как только скидка кончится.
    """
    camp, days = _chain("K6_winback")
    assert days[0] >= 14, "пишем вдогонку, не дав человеку соскучиться"
    actions = [s["action"] for s in camp["steps"]]
    assert actions[0] != "offer", "винбэк начинается с денег"
    assert days[actions.index("offer")] >= 30, "подарок раньше 30-го дня"
    assert days[-1] >= 60


def test_no_chain_opens_with_a_gift():
    """Верх лестницы уступок: сначала слово, деньги потом.

    Подарок первым шагом - это плата раньше, чем мы вообще попросили.
    """
    import json
    from campaign_tick import CAMPAIGNS_PATH
    for camp in json.loads(CAMPAIGNS_PATH.read_text())["_default"]["campaigns"]:
        assert camp["steps"][0]["action"] != "offer", camp["campaign_id"]
