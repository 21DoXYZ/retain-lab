"""Юнит-тесты проверок и отправителей цепочек (chains/checks.py, chains/senders.py).

Все проверки — чистые функции: CH-запросы замоканы `query`-callable (возвращает
result_rows-подобный список кортежей). Минимум по тесту на каждую проверку +
рендер шаблонов и запрос fatigue. БЕЗ БД и сети (DRY_RUN у отправителей).
"""
from __future__ import annotations

import pytest

from chains import checks as C
from chains import senders as S


# ── query-мок ─────────────────────────────────────────────────────────────────
def make_query(value):
    """Возвращает query(sql, params) -> [(value,)] и запоминает последний вызов."""
    calls = []

    def query(sql, params):
        calls.append((sql, params))
        return [(value,)]
    query.calls = calls
    return query


# ── consent (send_message) ────────────────────────────────────────────────────
def test_consent_ok():
    ok, reason = C.check_consent(
        {'marketing_consent': 't', 'opt_out': 'f', 'do_not_contact': '', 'self_excluded': 'f'})
    assert ok and reason == ''


@pytest.mark.parametrize('player,expect', [
    ({'marketing_consent': 't', 'self_excluded': 't'}, 'self_excluded'),
    ({'marketing_consent': 't', 'do_not_contact': '1'}, 'do_not_contact'),
    ({'marketing_consent': 't', 'opt_out': 'yes'}, 'opted_out'),
])
def test_consent_blocks(player, expect):
    """Явные запреты режут всегда, независимо от CHAINS_CONSENT_MODE."""
    ok, reason = C.check_consent(player)
    assert not ok and reason == expect


def test_consent_unknown_info_mode(monkeypatch):
    """Пустое согласие (казино не шлёт opt-in): режим info (дефолт) — отправка
    идёт с информационной пометкой (решение владельца 18.07)."""
    monkeypatch.setattr(C, 'CONSENT_MODE', 'info')
    ok, reason = C.check_consent({'marketing_consent': ''})
    assert ok and reason == 'consent_unknown'


def test_consent_unknown_enforce_mode(monkeypatch):
    """Режим enforce (для прода, когда появится opt_in_changed) — fail-closed."""
    monkeypatch.setattr(C, 'CONSENT_MODE', 'enforce')
    ok, reason = C.check_consent({'marketing_consent': ''})
    assert not ok and reason == 'no_marketing_consent'


def test_not_restricted():
    assert C.check_not_restricted({'self_excluded': 'f'}) == (True, '')
    assert C.check_not_restricted({'self_excluded': 't'}) == (False, 'self_excluded')


# ── канал доступен ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize('channel,player,expect', [
    ('casino_webhook', {}, (True, '')),                     # контакты у казино
    ('email', {'email': 'a@b.c'}, (True, '')),
    ('email', {'email': ''}, (False, 'no_email')),
    ('telegram', {'telegram_id': '123'}, (True, '')),
    ('telegram', {'telegram_id': '0'}, (False, 'no_telegram')),
    ('telegram', {'telegram_id': ''}, (False, 'no_telegram')),
    ('sms', {}, (False, 'unknown_channel')),
])
def test_channel(channel, player, expect):
    assert C.check_channel(channel, player) == expect


# ── языковая версия шаблона ─────────────────────────────────────────────────────
def test_template_language_direct_and_fallback():
    tpl = {'texts': {'ru': 'привет', 'tr': 'merhaba'}}
    assert C.check_template_language(tpl, 'tr') == (True, '')      # прямое совпадение
    assert C.check_template_language(tpl, 'en') == (True, '')      # фолбэк tr
    assert C.check_template_language({'texts': {'ru': 'x'}}, 'en') == (True, '')  # фолбэк ru


@pytest.mark.parametrize('tpl,expect', [
    (None, 'no_template'),
    ({'texts': {}}, 'no_template_text'),
    ({'texts': {'de': 'hallo'}}, 'no_template_text'),
    ({'texts': 'broken'}, 'bad_template'),
])
def test_template_language_missing(tpl, expect):
    ok, reason = C.check_template_language(tpl, 'en')
    assert not ok and reason == expect


# ── не в игровой сессии ─────────────────────────────────────────────────────────
def test_not_in_session_free():
    q = make_query(0)                                   # старт−энд = 0 → не в сессии
    assert C.check_not_in_session(97, q) == (True, '')
    assert q.calls and q.calls[0][1]['pid'] == 97


def test_not_in_session_busy():
    q = make_query(1)                                   # есть открытая сессия
    assert C.check_not_in_session(97, q) == (False, 'in_session')


# ── fatigue (send_log) ──────────────────────────────────────────────────────────
def test_fatigue_under_limit():
    q = make_query(2)                                   # 2 < 3 — ок
    assert C.check_fatigue(97, q, max_sends=3, window_days=7) == (True, '')
    sql, params = q.calls[0]
    assert params == {'pid': 97, 'd': 7} and 'send_log' in sql


def test_fatigue_at_limit():
    q = make_query(3)                                   # 3 >= 3 — стоп
    assert C.check_fatigue(97, q, max_sends=3, window_days=7) == (False, 'fatigue')


# ── сегмент-предохранитель ──────────────────────────────────────────────────────
def test_safety_segment_member():
    q = make_query(1)
    assert C.check_safety_segment(97, q) == (False, 'safety_restricted')
    assert q.calls[0][1]['s'] == 'safety_restricted'


def test_safety_segment_clear():
    q = make_query(0)
    assert C.check_safety_segment(97, q) == (True, '')


# ── senders: рендер шаблонов ────────────────────────────────────────────────────
def test_pick_text_fallback():
    tpl = {'texts': {'ru': 'Привет {name}', 'tr': 'Merhaba {name}'}}
    assert S.pick_text(tpl, 'tr') == 'Merhaba {name}'
    assert S.pick_text(tpl, 'en') == 'Merhaba {name}'      # фолбэк tr
    assert S.pick_text({'texts': {'ru': 'Р'}}, 'en') == 'Р'  # фолбэк ru
    assert S.pick_text(None, 'ru') == ''


def test_render_substitutes_known_vars_only():
    out = S.render('Бонус {bonus_amount}₺ для {name}', {'bonus_amount': 500})
    assert out == 'Бонус 500₺ для {name}'                  # неизвестный {name} не тронут


# ── senders: каналы в DRY_RUN / без конфигурации ───────────────────────────────
def test_casino_and_bonus_dry_run():
    ctx = S.SenderConfig(dry_run=True)
    ok, reason = S.send('casino_webhook', {'casino_player_id': 97},
                        {'template_id': 't1', 'channel_kind': 'casino_webhook'},
                        {'x': 1}, ctx)
    assert ok and reason == 'dry_run'
    ok, reason = S.send('bonus_grant', {'casino_player_id': 97}, None,
                        {'bonus': 'ml_recommended'}, ctx)
    assert ok and reason == 'dry_run'


def test_email_not_configured():
    ctx = S.SenderConfig(dry_run=True, smtp_host='', smtp_from='')
    ok, reason = S.send('email', {'casino_player_id': 97, 'email': 'a@b.c'},
                        {'texts': {'tr': 'x'}}, {}, ctx)
    assert not ok and reason == 'smtp_not_configured'


def test_telegram_no_token_and_no_id():
    ctx = S.SenderConfig(dry_run=True, tg_token='')
    ok, reason = S.send('telegram', {'casino_player_id': 97, 'telegram_id': '123'},
                        {'texts': {'tr': 'x'}}, {}, ctx)
    assert not ok and reason == 'no_tg_token'
    ctx2 = S.SenderConfig(dry_run=True, tg_token='BOT')
    ok, reason = S.send('telegram', {'casino_player_id': 97, 'telegram_id': '0'},
                        {'texts': {'tr': 'x'}}, {}, ctx2)
    assert not ok and reason == 'no_telegram'


def test_unknown_channel():
    assert S.send('carrier_pigeon', {'casino_player_id': 1}, None, {},
                  S.SenderConfig(dry_run=True)) == (False, 'unknown_channel')
