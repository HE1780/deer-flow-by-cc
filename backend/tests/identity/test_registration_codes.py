"""Route-level tests for admin registration-code endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.bootstrap import PREDEFINED_ROLE_PERMISSIONS
from app.gateway.identity.db import get_session
from app.gateway.identity.routers import admin_writes as admin_writes_module


def _identity_for_role(role_key: str, *, tenant_id: int) -> Identity:
    perms: set[str] = set()
    tenant_roles: list[str] = []
    for (key, scope), tags in PREDEFINED_ROLE_PERMISSIONS.items():
        if key == role_key and scope == "tenant":
            tenant_roles.append(key)
            perms.update(tags)
    return Identity(
        token_type="jwt",
        user_id=1,
        email=f"{role_key}@ex.com",
        tenant_id=tenant_id,
        workspace_ids=(1,),
        permissions=frozenset(perms),
        roles={"platform": [], "tenant": tenant_roles, "workspaces": {}},
        session_id=f"sess-{role_key}",
    )


class _StubSession:
    def __init__(self):
        self.added: list[Any] = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass

    async def execute(self, stmt):
        return MagicMock()


@pytest.fixture
def codes_app():
    app = FastAPI()
    app.include_router(admin_writes_module.router)
    current = {"identity": Identity.anonymous(), "session": _StubSession()}

    @app.middleware("http")
    async def inject(request, call_next):
        request.state.identity = current["identity"]
        return await call_next(request)

    async def _override() -> AsyncIterator[_StubSession]:
        yield current["session"]

    app.dependency_overrides[get_session] = _override
    return app, current


def test_create_code_returns_plaintext_once(codes_app):
    from app.gateway.identity.models import RegistrationCode

    app, holder = codes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=1)

    class _S(_StubSession):
        def add(self, obj):
            super().add(obj)
            if isinstance(obj, RegistrationCode):
                obj.id = 42
                obj.created_at = datetime(2026, 4, 29, tzinfo=UTC)

    holder["session"] = _S()
    with TestClient(app) as c:
        r = c.post("/api/tenants/1/registration-codes", json={})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "code" in body and len(body["code"]) >= 32
    assert body["code_prefix"] == body["code"][:8]
    assert body["tenant_id"] == 1
    assert body["id"] == 42


def test_create_code_forbidden_for_member(codes_app):
    app, holder = codes_app
    holder["identity"] = _identity_for_role("member", tenant_id=1)
    with TestClient(app) as c:
        r = c.post("/api/tenants/1/registration-codes", json={})
    assert r.status_code == 403
