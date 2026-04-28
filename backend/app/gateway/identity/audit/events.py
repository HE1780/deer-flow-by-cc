"""AuditEvent dataclass + well-known action taxonomy (spec §9.2).

``AuditEvent`` is the one shape that flows through the whole M6 pipeline:
Middleware → BatchWriter → Postgres row. It is intentionally frozen so a
queued event can never be mutated mid-flight (redaction runs *before*
enqueue, never after).

``KNOWN_ACTIONS`` is advisory — the writer accepts any string so producers
outside this list (e.g. future LangGraph events) still land. ``KEY_CRITICAL_ACTIONS``
drives the ``critical=True`` enqueue path where the writer falls back to
synchronous write + on-disk JSONL instead of dropping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

Result = Literal["success", "failure"]


# Resource-type constants used by middleware/producers. Free-form strings
# are allowed; these simply give call sites a canonical vocabulary.
RESOURCE_TENANT = "tenant"
RESOURCE_USER = "user"
RESOURCE_WORKSPACE = "workspace"
RESOURCE_THREAD = "thread"
RESOURCE_SKILL = "skill"
RESOURCE_TOOL = "tool"
RESOURCE_API_TOKEN = "api_token"
RESOURCE_ROLE = "role"
RESOURCE_AUDIT = "audit"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Immutable audit event ready for insert.

    Mirrors ``identity.audit_logs`` columns 1:1. ``metadata`` is the only
    free-form field and must already be redacted (see ``redact.py``).
    """

    action: str
    result: Result
    tenant_id: int | None = None
    user_id: int | None = None
    workspace_id: int | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    error_code: str | None = None
    duration_ms: int | None = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# Set of canonical action strings. Producers outside this list are still
# accepted — writing a fresh action does not require editing this file.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        # --- identity / session lifecycle ---
        "user.login.success",
        "user.login.failure",
        "user.logout",
        "user.switch_tenant",
        "user.disabled",
        "user.deleted",
        "api_token.created",
        "api_token.revoked",
        "api_token.used",
        "session.created",
        "session.revoked",
        "session.expired",
        # --- authorisation decisions ---
        "authz.api.denied",
        "authz.tool.denied",
        "authz.path.denied",
        # --- role grants ---
        "role.assigned",
        "role.revoked",
        # --- thread / skill / tool work ---
        "thread.created",
        "thread.deleted",
        "skill.invoked",
        "skill.installed",
        "skill.published",
        "skill.removed",
        "skill.review.approved",
        "skill.review.rejected",
        "tool.called",
        "tool.denied",
        "tool.failed",
        # --- knowledge / workflows ---
        "knowledge.queried",
        "knowledge.written",
        "workflow.started",
        "workflow.completed",
        "workflow.failed",
        # --- org API key lifecycle ---
        "org_key.created",
        "org_key.revoked",
        "org_key.auto_rotated",
        # --- platform-side migration / retention ---
        "system.migration.item.moved",
        "system.migration.completed",
        "system.retention.archived",
        # --- audit plane's own operations ---
        "audit.exported",
        # --- LLM error observability ---
        "llm.error.silenced",
    }
)


# Subset that must never be silently dropped. The batch writer routes these
# through the fallback path when Postgres is unavailable.
KEY_CRITICAL_ACTIONS: frozenset[str] = frozenset(
    {
        "user.login.success",
        "user.login.failure",
        "api_token.used",
        "authz.api.denied",
        "authz.tool.denied",
        "authz.path.denied",
        "role.assigned",
        "role.revoked",
        "llm.error.silenced",
    }
)

# HTTP methods treated as writes — every write goes critical regardless
# of whether its action string is in KEY_CRITICAL_ACTIONS.
WRITE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_critical_action(action: str, *, http_method: str | None = None) -> bool:
    """Return True if this event must survive PG outage via fallback.

    The rule mirrors spec §9.9: critical = the action is explicitly
    enumerated, or it corresponds to an HTTP write on a data-modifying
    route.
    """

    if action in KEY_CRITICAL_ACTIONS:
        return True
    if http_method is not None and http_method.upper() in WRITE_METHODS:
        return True
    return False
