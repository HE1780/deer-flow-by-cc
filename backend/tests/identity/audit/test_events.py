"""Tests for AuditEvent dataclass + action taxonomy."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from app.gateway.identity.audit.events import (
    KEY_CRITICAL_ACTIONS,
    KNOWN_ACTIONS,
    WRITE_METHODS,
    AuditEvent,
    is_critical_action,
)


def test_audit_event_is_frozen():
    ev = AuditEvent(action="user.login.success", result="success")
    with pytest.raises(FrozenInstanceError):
        ev.action = "user.login.failure"  # type: ignore[misc]


def test_audit_event_defaults():
    ev = AuditEvent(action="user.login.success", result="success")
    assert ev.tenant_id is None
    assert ev.user_id is None
    assert ev.metadata == {}
    # default timestamp is tz-aware UTC
    assert ev.created_at.tzinfo is UTC


def test_audit_event_keeps_explicit_timestamp():
    ts = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    ev = AuditEvent(action="user.logout", result="success", created_at=ts)
    assert ev.created_at == ts


def test_critical_actions_are_subset_of_known_actions():
    missing = KEY_CRITICAL_ACTIONS - KNOWN_ACTIONS
    assert not missing, f"KEY_CRITICAL_ACTIONS not in KNOWN_ACTIONS: {missing}"


def test_is_critical_action_enumerated():
    assert is_critical_action("user.login.success") is True
    assert is_critical_action("authz.tool.denied") is True
    # non-critical enumerated action
    assert is_critical_action("thread.created") is False


def test_is_critical_action_http_writes():
    # Every write method promotes even unknown actions to critical.
    for m in WRITE_METHODS:
        assert is_critical_action("random.action.name", http_method=m) is True


def test_is_critical_action_http_reads_not_critical():
    # Non-enumerated read action → not critical.
    assert is_critical_action("some.read.action", http_method="GET") is False
    # Enumerated critical action on GET still critical (list wins).
    assert is_critical_action("user.login.success", http_method="GET") is True


def test_llm_error_silenced_known_and_critical():
    """LLM-error silencing must surface in audit so silent failures don't hide."""
    assert "llm.error.silenced" in KNOWN_ACTIONS
    assert "llm.error.silenced" in KEY_CRITICAL_ACTIONS
    assert is_critical_action("llm.error.silenced") is True
