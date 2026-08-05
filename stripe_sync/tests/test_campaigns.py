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
    assert due_steps(STEPS, T0, 0, T0) == [0, 1]
    assert due_steps(STEPS, T0, 0, T0 + timedelta(hours=25)) == [0, 1, 2]
    assert due_steps(STEPS, T0, 2, T0 + timedelta(hours=23)) == []
    assert due_steps(STEPS, T0, 0, T0 + timedelta(hours=100)) == [0, 1, 2, 3]
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
