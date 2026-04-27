"""Route-level tests for org key admin endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.db import get_session
from app.gateway.identity.routers import admin as admin_router_module


class _StubSession:
    """Minimal AsyncSession stub for org-key endpoint tests."""

    def __init__(self) -> None:
        self.committed = False

    async def execute(self, stmt, params=None):  # noqa: D401
        sql = str(getattr(stmt, "text", stmt))
        # Guard against asyncpg bind parser conflict on ':param::jsonb'.
        assert "::jsonb" not in sql
        row = {
            "id": 101,
            "name": params["name"],
            "prefix": params["prefix"],
            "no_expiry": params["no_expiry"],
            "expires_at": params["expires_at"],
            "auto_rotate_at": params["auto_rotate_at"],
            "last_used_at": None,
            "revoked_at": None,
            "created_at": params["now"],
        }
        result = MagicMock()
        mappings = MagicMock()
        mappings.one.return_value = row
        result.mappings.return_value = mappings
        return result

    async def commit(self) -> None:
        self.committed = True


@pytest.fixture
def org_keys_app():
    """Build a minimal app mounting admin router with stub identity/session."""
    app = FastAPI()
    app.include_router(admin_router_module.router)
    current = {
        "identity": Identity(
            token_type="jwt",
            user_id=1,
            email="owner@example.com",
            tenant_id=5,
            workspace_ids=(1,),
            permissions=frozenset({"token:create", "token:read", "token:revoke"}),
            roles={"platform": [], "tenant": ["tenant_owner"], "workspaces": {}},
            session_id="sess-owner",
        ),
        "session": _StubSession(),
    }

    @app.middleware("http")
    async def inject_identity(request, call_next):
        request.state.identity = current["identity"]
        return await call_next(request)

    async def _override_session() -> AsyncIterator[_StubSession]:
        yield current["session"]

    app.dependency_overrides[get_session] = _override_session
    return app, current


def test_create_org_key_uses_safe_jsonb_cast(org_keys_app):
    """POST /api/admin/org-keys should avoid ':param::jsonb' SQL syntax."""
    app, holder = org_keys_app
    with TestClient(app) as c:
        r = c.post(
            "/api/admin/org-keys",
            json={"name": "prod-ingest", "no_expiry": True, "allowed_skills": []},
        )

    assert r.status_code == 201, r.text
    assert r.json()["name"] == "prod-ingest"
    assert holder["session"].committed is True
