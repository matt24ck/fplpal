"""Daily chat spend cap: the all-users token ceiling on /chat."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from api import chat


def _usage(**kw) -> SimpleNamespace:
    base = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_cap_zero_blocks_before_any_spend(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("CHAT_DAILY_TOKEN_CAP", "0")
    from api.app import app

    r = TestClient(app).post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 429
    assert "midnight UTC" in r.json()["detail"]


def test_cap_reached_blocks(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("CHAT_DAILY_TOKEN_CAP", "1000")
    monkeypatch.setattr(chat, "_daily_tokens", {chat._today(): 1000})
    from api.app import app

    r = TestClient(app).post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 429


def test_unset_cap_means_no_ceiling(monkeypatch):
    monkeypatch.delenv("CHAT_DAILY_TOKEN_CAP", raising=False)
    monkeypatch.setattr(chat, "_daily_tokens", {chat._today(): 10**9})
    assert chat.daily_cap() is None
    assert not chat.budget_spent()


def test_unparseable_cap_fails_closed(monkeypatch):
    monkeypatch.setenv("CHAT_DAILY_TOKEN_CAP", "loads")
    monkeypatch.setattr(chat, "_daily_tokens", {})
    assert chat.daily_cap() == 0
    assert chat.budget_spent()


def test_ledger_counts_all_token_kinds_and_resets_daily(monkeypatch):
    monkeypatch.setattr(chat, "_daily_tokens", {})
    monkeypatch.setattr(chat, "_today", lambda: "2026-08-22")
    chat.record_usage(
        _usage(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=10,
            cache_read_input_tokens=40,
        )
    )
    chat.record_usage(_usage(output_tokens=5))
    assert chat.tokens_spent_today() == 205

    monkeypatch.setattr(chat, "_today", lambda: "2026-08-23")  # midnight UTC
    assert chat.tokens_spent_today() == 0
    chat.record_usage(_usage(input_tokens=7))
    assert chat.tokens_spent_today() == 7
    assert list(chat._daily_tokens) == ["2026-08-23"]  # yesterday pruned
