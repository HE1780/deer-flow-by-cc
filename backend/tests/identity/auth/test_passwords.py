"""Tests for app.gateway.identity.auth.passwords."""

from __future__ import annotations

import bcrypt
import pytest

from app.gateway.identity.auth import passwords


class _FakeSettings:
    def __init__(self, cost: int) -> None:
        self.bcrypt_cost = cost


@pytest.fixture
def low_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a low bcrypt cost so tests are fast and the cost is observable."""
    monkeypatch.setattr(
        passwords,
        "get_identity_settings",
        lambda: _FakeSettings(cost=4),
    )


def test_hash_password_uses_configured_cost(low_cost: None) -> None:
    h = passwords.hash_password("hunter2")
    # bcrypt encodes the cost as the second '$'-delimited segment, e.g. "$2b$04$...".
    parts = h.split("$")
    assert parts[1] in {"2a", "2b", "2y"}
    assert parts[2] == "04"


def test_verify_password_round_trip(low_cost: None) -> None:
    h = passwords.hash_password("correct horse battery staple")
    assert passwords.verify_password("correct horse battery staple", h) is True
    assert passwords.verify_password("wrong password", h) is False


def test_verify_password_empty_hash_is_false(low_cost: None) -> None:
    assert passwords.verify_password("anything", "") is False


def test_hash_password_changes_when_cost_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Different configured cost must propagate into the produced hash."""
    monkeypatch.setattr(
        passwords,
        "get_identity_settings",
        lambda: _FakeSettings(cost=4),
    )
    h_low = passwords.hash_password("pw")
    monkeypatch.setattr(
        passwords,
        "get_identity_settings",
        lambda: _FakeSettings(cost=5),
    )
    h_high = passwords.hash_password("pw")
    assert h_low.split("$")[2] == "04"
    assert h_high.split("$")[2] == "05"


def test_verify_password_compatible_with_raw_bcrypt(low_cost: None) -> None:
    """Hashes produced outside the helper still verify (no format drift)."""
    raw = bcrypt.hashpw(b"legacy", bcrypt.gensalt(rounds=4)).decode()
    assert passwords.verify_password("legacy", raw) is True
    assert passwords.verify_password("not it", raw) is False
