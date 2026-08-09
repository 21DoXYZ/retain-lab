"""Единый контракт LLM: инвариант контекста §9 + резолв провайдера."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llm_stage as ls  # noqa: E402


def test_call_refuses_without_business_context(monkeypatch):
    """§9: генерик-промпт запрещён архитектурно - вызов без контекста падает
    ДО обращения к сети (MissingContext), а не молча уходит генериком."""
    monkeypatch.setattr(ls, "resolve_provider", lambda env=None: ("anthropic", "k"))
    called = {"n": 0}
    monkeypatch.setattr(ls, "_call_anthropic",
                        lambda *a: called.__setitem__("n", called["n"] + 1) or "{}")
    try:
        ls.call("system", "no context here, write now")
        assert False, "должно было выбросить MissingContext"
    except ls.MissingContext:
        pass
    assert called["n"] == 0                      # сеть не тронута


def test_call_passes_with_context(monkeypatch):
    monkeypatch.setattr(ls, "resolve_provider", lambda env=None: ("anthropic", "k"))
    monkeypatch.setattr(ls, "_call_anthropic", lambda *a: '{"ok": 1}')
    body = "=== BUSINESS CONTEXT ===\nclaimed...\nProduce now."
    text, note = ls.call("system", body)
    assert note == "" and text == '{"ok": 1}'


def test_allow_no_context_bypasses_guard(monkeypatch):
    """Классификатор отмен: профиль опционален - явное исключение."""
    monkeypatch.setattr(ls, "resolve_provider", lambda env=None: ("openai", "k"))
    monkeypatch.setattr(ls, "_call_openai", lambda *a: "{}")
    text, note = ls.call("system", "classify these", allow_no_context=True)
    assert note == ""


def test_no_provider_is_configured_note(monkeypatch):
    monkeypatch.setattr(ls, "resolve_provider", lambda env=None: ("", ""))
    text, note = ls.call("s", "x", allow_no_context=True)
    assert note == "ai_not_configured" and text == ""


def test_http_error_becomes_note(monkeypatch):
    import urllib.error
    monkeypatch.setattr(ls, "resolve_provider", lambda env=None: ("anthropic", "k"))
    def boom(*a):
        raise urllib.error.HTTPError("u", 429, "rate", {}, None)
    monkeypatch.setattr(ls, "_call_anthropic", boom)
    text, note = ls.call("s", "x", allow_no_context=True)
    assert note == "ai_http_429"


def test_provider_priority():
    assert ls.resolve_provider({"ANTHROPIC_API_KEY": "a"}) == ("anthropic", "a")
    assert ls.resolve_provider({"OPENAI_API_KEY": "o"}) == ("openai", "o")
    assert ls.resolve_provider({}) == ("", "")


def test_record_run_survives_no_client():
    ls.record_run(None, "t", "offers", "ok", kept=3)   # не должно падать
