"""Regression test: admin_stub.py must not shadow real handlers in admin_writes.

When both routers are mounted in the same FastAPI app (mirroring the order
in `app/gateway/app.py`), a `POST /api/admin/tenants` and `POST
/api/tenants/{tid}/workspaces` request must reach the real handler in
`admin_writes`, not the stub. FastAPI dispatches in registration order, so
a stub that declares the same path silently turns the create endpoint into
a no-op (the original bug fixed in this commit).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.bootstrap import PREDEFINED_ROLE_PERMISSIONS
from app.gateway.identity.db import get_session
from app.gateway.identity.routers import admin_stub as admin_stub_module
from app.gateway.identity.routers import admin_writes as admin_writes_module


def _platform_admin_identity() -> Identity:
    perms: set[str] = set()
    for (key, scope), tags in PREDEFINED_ROLE_PERMISSIONS.items():
        if key == "platform_admin":
            perms.update(tags)
    return Identity(
        token_type="jwt",
        user_id=1,
        email="admin@example.com",
        tenant_id=None,
        workspace_ids=(),
        permissions=frozenset(perms),
        roles={"platform": ["platform_admin"], "tenant": [], "workspaces": {}},
        session_id="sess",
    )


class _StubSession:
    def __init__(self) -> None:
        self.added: list = []
        self.committed = False
        self.flushed = False

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def flush(self) -> None:
        self.flushed = True

    async def execute(self, stmt):  # noqa: D401
        return MagicMock()


@pytest.fixture
def real_order_app():
    """Mount stub then writes — same order as `app/gateway/app.py`."""
    app = FastAPI()
    app.include_router(admin_stub_module.router)
    app.include_router(admin_writes_module.router)

    holder: dict = {
        "identity": _platform_admin_identity(),
        "session": _StubSession(),
    }

    @app.middleware("http")
    async def inject_identity(request, call_next):
        request.state.identity = holder["identity"]
        return await call_next(request)

    async def _override_session() -> AsyncIterator[_StubSession]:
        yield holder["session"]

    app.dependency_overrides[get_session] = _override_session
    return app, holder


def test_create_tenant_reaches_real_handler(real_order_app):
    app, holder = real_order_app

    class _Sess(_StubSession):
        async def execute(self, stmt):
            # No existing tenant with this slug.
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        def add(self, obj) -> None:
            super().add(obj)
            from app.gateway.identity.models import Tenant

            if isinstance(obj, Tenant):
                obj.id = 99
                obj.plan = "free"
                obj.status = 1

    holder["session"] = _Sess()

    with TestClient(app) as c:
        resp = c.post("/api/admin/tenants", json={"slug": "acme", "name": "Acme Inc"})

    # Real handler returns the full TenantOut shape (id/slug/name/plan/status).
    # The stub used to return ``{"tenant_id": 2}`` — the absence of "tenant_id"
    # and presence of "slug"/"name" proves the shadow is gone.
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "acme"
    assert body["name"] == "Acme Inc"
    assert body["id"] == 99
    assert "tenant_id" not in body


def test_create_workspace_reaches_real_handler(real_order_app):
    app, holder = real_order_app

    class _Sess(_StubSession):
        async def execute(self, stmt):
            # No existing workspace with this (tid, slug).
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        def add(self, obj) -> None:
            super().add(obj)
            from app.gateway.identity.models import Workspace

            if isinstance(obj, Workspace):
                obj.id = 42
                obj.tenant_id = 5

    holder["session"] = _Sess()

    with TestClient(app) as c:
        resp = c.post(
            "/api/tenants/5/workspaces",
            json={"slug": "team-1", "name": "Team One"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Stub used to return ``{"tid": 5, "workspace_id": 2}``.
    assert body.get("slug") == "team-1"
    assert body.get("name") == "Team One"
    assert "workspace_id" not in body
