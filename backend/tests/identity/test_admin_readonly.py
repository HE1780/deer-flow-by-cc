"""Route-level tests for the admin read router.

We inject a synthetic ``Identity`` via middleware and override ``get_session``
with a stub returning canned rows — no live DB/Redis needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.bootstrap import PREDEFINED_ROLE_PERMISSIONS
from app.gateway.identity.db import get_session
from app.gateway.identity.routers import admin as admin_router_module


def _identity_for_role(role_key: str, *, tenant_id: int, workspace_ids: tuple[int, ...] = (1,)) -> Identity:
    """Build an Identity matching a bootstrap seed role (mirrors rbac/test_horizontal_access.py)."""
    platform_roles: list[str] = []
    tenant_roles: list[str] = []
    workspace_role_map: dict[str, str] = {}
    perms: set[str] = set()
    for (key, scope), tags in PREDEFINED_ROLE_PERMISSIONS.items():
        if key == role_key:
            if scope == "platform":
                platform_roles.append(key)
            elif scope == "tenant":
                tenant_roles.append(key)
                perms.update(tags)
            elif scope == "workspace":
                for wid in workspace_ids:
                    workspace_role_map[str(wid)] = key
                perms.update(tags)
    if role_key == "platform_admin":
        perms = set()  # platform_admin bypasses via is_platform_admin
    return Identity(
        token_type="jwt",
        user_id=1,
        email=f"{role_key}@example.com",
        tenant_id=tenant_id,
        workspace_ids=workspace_ids,
        permissions=frozenset(perms),
        roles={"platform": platform_roles, "tenant": tenant_roles, "workspaces": workspace_role_map},
        session_id=f"sess-{role_key}",
    )


class _StubSession:
    """Minimal AsyncSession stub. Tests set ``.rows`` on the instance and
    assert ``.executed_stmts`` after the call."""

    def __init__(self, rows: list[Any] | None = None, scalar_result: Any = None):
        self.rows = rows or []
        self.scalar_result = scalar_result
        self.executed_stmts: list[Any] = []

    async def execute(self, stmt):  # noqa: D401
        self.executed_stmts.append(stmt)
        result = MagicMock()
        result.scalars.return_value.all.return_value = list(self.rows)
        result.scalar.return_value = self.scalar_result
        result.scalar_one.return_value = self.scalar_result
        return result


@pytest.fixture
def admin_app():
    """FastAPI app mounting the admin router with injected Identity + stub session."""
    app = FastAPI()
    app.include_router(admin_router_module.router)
    current: dict = {"identity": Identity.anonymous(), "session": _StubSession()}

    @app.middleware("http")
    async def inject_identity(request, call_next):
        request.state.identity = current["identity"]
        return await call_next(request)

    async def _override_session() -> AsyncIterator[_StubSession]:
        yield current["session"]

    app.dependency_overrides[get_session] = _override_session
    return app, current


def test_list_tenants_allowed_for_platform_admin(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("platform_admin", tenant_id=1)
    holder["session"] = _StubSession(
        rows=[
            SimpleNamespace(
                id=1,
                slug="acme",
                name="Acme",
                plan="pro",
                status=1,
                created_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
            ),
            SimpleNamespace(
                id=2,
                slug="hooli",
                name="Hooli",
                plan="free",
                status=1,
                created_at=datetime(2026, 4, 2, 12, 0, tzinfo=UTC),
            ),
        ],
        scalar_result=2,
    )
    with TestClient(app) as c:
        r = c.get("/api/admin/tenants")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["slug"] == "acme"
    assert body["items"][0]["name"] == "Acme"
    assert body["items"][0]["plan"] == "pro"
    assert body["items"][0]["status"] == 1
    assert body["items"][0]["created_at"].startswith("2026-04-01")


def test_list_tenants_forbidden_for_tenant_owner(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=1)
    with TestClient(app) as c:
        r = c.get("/api/admin/tenants")
    assert r.status_code == 403


def test_list_tenants_401_when_anonymous(admin_app):
    app, _ = admin_app
    with TestClient(app) as c:
        r = c.get("/api/admin/tenants")
    assert r.status_code == 401


def test_get_tenant_detail_platform_admin(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("platform_admin", tenant_id=1)
    t = SimpleNamespace(
        id=7,
        slug="acme",
        name="Acme",
        plan="pro",
        status=1,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
    )

    class _Multi(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                result.scalar_one_or_none.return_value = t
            elif self.calls == 2:
                result.scalar.return_value = 5  # member_count
            else:
                result.scalar.return_value = 3  # workspace_count
            return result

    holder["session"] = _Multi()
    with TestClient(app) as c:
        r = c.get("/api/admin/tenants/7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == 7
    assert body["slug"] == "acme"
    assert body["member_count"] == 5
    assert body["workspace_count"] == 3


def test_get_tenant_detail_404_when_missing(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("platform_admin", tenant_id=1)

    class _None(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

    holder["session"] = _None()
    with TestClient(app) as c:
        r = c.get("/api/admin/tenants/999")
    assert r.status_code == 404


def test_list_users_allowed_for_tenant_owner(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)
    user_row = SimpleNamespace(
        id=10,
        email="a@b.com",
        display_name="Alice",
        status=1,
        avatar_url=None,
        last_login_at=datetime(2026, 4, 15, tzinfo=UTC),
    )

    class _Users(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:  # users
                result.scalars.return_value.all.return_value = [user_row]
            elif self.calls == 2:  # count
                result.scalar.return_value = 1
            elif self.calls == 3:  # role pairs
                result.all.return_value = [(10, "tenant_owner")]
            return result

    holder["session"] = _Users()
    with TestClient(app) as c:
        r = c.get("/api/tenants/5/users")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "a@b.com"
    assert body["items"][0]["roles"] == ["tenant_owner"]


def test_list_users_forbidden_for_member(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("member", tenant_id=5)
    with TestClient(app) as c:
        r = c.get("/api/tenants/5/users")
    assert r.status_code == 403


def test_get_user_detail_platform_admin(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("platform_admin", tenant_id=5)
    u = SimpleNamespace(
        id=10,
        email="a@b.com",
        display_name="Alice",
        status=1,
        avatar_url=None,
        last_login_at=datetime(2026, 4, 15, tzinfo=UTC),
    )

    class _One(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:  # user scalar_one_or_none
                result.scalar_one_or_none.return_value = u
            else:  # roles
                result.all.return_value = [("tenant_owner",), ("member",)]
            return result

    holder["session"] = _One()
    with TestClient(app) as c:
        r = c.get("/api/tenants/5/users/10")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == 10
    assert set(body["roles"]) == {"tenant_owner", "member"}


def test_list_workspaces_tenant_owner(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)
    ws = SimpleNamespace(
        id=7,
        tenant_id=5,
        slug="main",
        name="Main",
        description=None,
        created_at=datetime(2026, 4, 10, tzinfo=UTC),
    )

    class _WS(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                result.scalars.return_value.all.return_value = [ws]
            elif self.calls == 2:
                result.scalar.return_value = 1  # total
            else:
                result.all.return_value = [(7, 4)]  # (workspace_id, member_count)
            return result

    holder["session"] = _WS()
    with TestClient(app) as c:
        r = c.get("/api/tenants/5/workspaces")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"][0]["slug"] == "main"
    assert body["items"][0]["member_count"] == 4


def test_list_workspace_members(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)
    row = (
        SimpleNamespace(id=11, email="b@b.com", display_name="Bob", status=1, avatar_url=None),
        "workspace_admin",
        datetime(2026, 4, 11, tzinfo=UTC),
    )

    class _MM(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                result.all.return_value = [row]
            else:
                result.scalar.return_value = 1
            return result

    holder["session"] = _MM()
    with TestClient(app) as c:
        r = c.get("/api/tenants/5/workspaces/7/members")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "b@b.com"
    assert body["items"][0]["role"] == "workspace_admin"


def test_list_tenant_tokens(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)
    tok = SimpleNamespace(
        id=100,
        tenant_id=5,
        user_id=10,
        workspace_id=7,
        name="ci-bot",
        prefix="dft_abc123",
        scopes=["skill:invoke"],
        expires_at=None,
        last_used_at=datetime(2026, 4, 20, tzinfo=UTC),
        revoked_at=None,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
    )

    class _Tok(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                result.scalars.return_value.all.return_value = [tok]
            else:
                result.scalar.return_value = 1
            return result

    holder["session"] = _Tok()
    with TestClient(app) as c:
        r = c.get("/api/tenants/5/tokens")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["prefix"] == "dft_abc123"
    assert body["items"][0]["scopes"] == ["skill:invoke"]
    assert body["items"][0]["revoked_at"] is None


def test_list_tenant_tokens_forbidden_for_member(admin_app):
    app, holder = admin_app
    holder["identity"] = _identity_for_role("member", tenant_id=5)
    with TestClient(app) as c:
        r = c.get("/api/tenants/5/tokens")
    assert r.status_code == 403
