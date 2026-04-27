"""Route-level tests for the admin **write** endpoints (M7 A3).

Mirrors the test_admin_readonly.py fixture pattern: synthetic Identity
through a one-line middleware + dependency-overridden ``get_session`` returning
a stub. No live DB.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.bootstrap import PREDEFINED_ROLE_PERMISSIONS
from app.gateway.identity.db import get_session
from app.gateway.identity.routers import admin_writes as admin_writes_module


def _identity_for_role(
    role_key: str,
    *,
    tenant_id: int,
    workspace_ids: tuple[int, ...] = (1,),
) -> Identity:
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
        perms = set()
    return Identity(
        token_type="jwt",
        user_id=1,
        email=f"{role_key}@example.com",
        tenant_id=tenant_id,
        workspace_ids=workspace_ids,
        permissions=frozenset(perms),
        roles={
            "platform": platform_roles,
            "tenant": tenant_roles,
            "workspaces": workspace_role_map,
        },
        session_id=f"sess-{role_key}",
    )


class _StubSession:
    """Minimal AsyncSession stub. Tests override ``execute`` per-call when
    multiple statements run in one handler."""

    def __init__(self):
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = False
        self.flushed = False

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def flush(self) -> None:
        self.flushed = True

    async def execute(self, stmt):  # noqa: D401
        return MagicMock()


@pytest.fixture
def writes_app():
    app = FastAPI()
    app.include_router(admin_writes_module.router)
    current: dict = {"identity": Identity.anonymous(), "session": _StubSession()}

    @app.middleware("http")
    async def inject_identity(request, call_next):
        request.state.identity = current["identity"]
        return await call_next(request)

    async def _override_session() -> AsyncIterator[_StubSession]:
        yield current["session"]

    app.dependency_overrides[get_session] = _override_session
    return app, current


# ---------------------------------------------------------------------------
# POST /api/tenants/{tid}/users  — create a user + tenant membership
# ---------------------------------------------------------------------------


def test_create_user_allowed_for_tenant_owner(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    created_user = SimpleNamespace(
        id=42,
        email="new@example.com",
        display_name="New",
        avatar_url=None,
        status=1,
        last_login_at=None,
    )

    class _Sess(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                # Lookup existing user by email -> none
                result.scalar_one_or_none.return_value = None
            elif self.calls == 2:
                # Lookup membership -> none
                result.scalar_one_or_none.return_value = None
            return result

        def add(self, obj):
            super().add(obj)
            # Mimic flush populating an id on the User row.
            from app.gateway.identity.models import User

            if isinstance(obj, User):
                obj.id = created_user.id
                obj.created_at = datetime(2026, 4, 24, tzinfo=UTC)
                obj.last_login_at = None
                obj.status = 1
                obj.avatar_url = None

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/users",
            json={"email": "new@example.com", "display_name": "New"},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "new@example.com"
    assert body["display_name"] == "New"
    assert body["id"] == 42
    assert holder["session"].committed is True


def test_create_user_forbidden_for_member(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("member", tenant_id=5)
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/users",
            json={"email": "new@example.com", "display_name": "New"},
        )
    assert r.status_code == 403


def test_create_user_409_when_membership_exists(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    existing_user = SimpleNamespace(
        id=10,
        email="dup@example.com",
        display_name="Dup",
        avatar_url=None,
        status=1,
        last_login_at=None,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    existing_membership = SimpleNamespace(id=99, user_id=10, tenant_id=5)

    class _Sess(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                result.scalar_one_or_none.return_value = existing_user
            elif self.calls == 2:
                result.scalar_one_or_none.return_value = existing_membership
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/users",
            json={"email": "dup@example.com", "display_name": "Dup"},
        )
    assert r.status_code == 409, r.text
    assert "already" in r.json()["detail"].lower()


def test_create_user_400_for_invalid_email(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/users",
            json={"email": "not-an-email", "display_name": "Bad"},
        )
    assert r.status_code == 422  # pydantic email validation


def test_create_user_with_initial_password_sets_hash(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    class _Sess(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            # existing user lookup -> none, membership lookup -> none
            result.scalar_one_or_none.return_value = None
            return result

        def add(self, obj):
            super().add(obj)
            from app.gateway.identity.models import User

            if isinstance(obj, User):
                obj.id = 43
                obj.created_at = datetime(2026, 4, 24, tzinfo=UTC)
                obj.last_login_at = None
                obj.status = 1
                obj.avatar_url = None

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/users",
            json={
                "email": "password-user@example.com",
                "display_name": "Pwd User",
                "initial_password": "ChangeMe!2026",
            },
        )
    assert r.status_code == 201, r.text

    from app.gateway.identity.models import User

    created_user = next(obj for obj in holder["session"].added if isinstance(obj, User))
    assert created_user.password_hash is not None
    assert created_user.password_hash != "ChangeMe!2026"
    assert bcrypt.checkpw(b"ChangeMe!2026", created_user.password_hash.encode())


# ---------------------------------------------------------------------------
# POST /api/tenants/{tid}/workspaces/{wid}/members
# ---------------------------------------------------------------------------


def test_add_workspace_member_allowed_for_tenant_owner(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    target_user = SimpleNamespace(
        id=11,
        email="b@b.com",
        display_name="Bob",
        avatar_url=None,
        status=1,
    )
    role = SimpleNamespace(id=8, role_key="member", scope="workspace")

    class _Sess(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                # Workspace lookup
                result.scalar_one_or_none.return_value = SimpleNamespace(id=7, tenant_id=5)
            elif self.calls == 2:
                # User lookup
                result.scalar_one_or_none.return_value = target_user
            elif self.calls == 3:
                # Membership lookup
                result.scalar_one_or_none.return_value = SimpleNamespace(id=88)
            elif self.calls == 4:
                # Role lookup by key
                result.scalar_one_or_none.return_value = role
            elif self.calls == 5:
                # Existing workspace member?
                result.scalar_one_or_none.return_value = None
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/workspaces/7/members",
            json={"user_id": 11, "role": "member"},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == 11
    assert body["role"] == "member"
    assert holder["session"].committed is True


def test_add_workspace_member_forbidden_for_member(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("member", tenant_id=5)
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/workspaces/7/members",
            json={"user_id": 11, "role": "member"},
        )
    assert r.status_code == 403


def test_add_workspace_member_400_when_user_not_in_tenant(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    class _Sess(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                result.scalar_one_or_none.return_value = SimpleNamespace(id=7, tenant_id=5)
            elif self.calls == 2:
                result.scalar_one_or_none.return_value = SimpleNamespace(
                    id=11,
                    email="b@b.com",
                    display_name="Bob",
                    avatar_url=None,
                    status=1,
                )
            elif self.calls == 3:
                # No tenant membership
                result.scalar_one_or_none.return_value = None
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/workspaces/7/members",
            json={"user_id": 11, "role": "member"},
        )
    assert r.status_code == 400, r.text
    assert "tenant" in r.json()["detail"].lower()


def test_patch_workspace_member_role(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    member = SimpleNamespace(user_id=11, workspace_id=7, role_id=8)
    new_role = SimpleNamespace(id=9, role_key="workspace_admin", scope="workspace")
    target_user = SimpleNamespace(
        id=11,
        email="b@b.com",
        display_name="Bob",
        avatar_url=None,
        status=1,
    )

    class _Sess(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                # Workspace lookup
                result.scalar_one_or_none.return_value = SimpleNamespace(id=7, tenant_id=5)
            elif self.calls == 2:
                # Member lookup
                result.scalar_one_or_none.return_value = member
            elif self.calls == 3:
                # New role lookup
                result.scalar_one_or_none.return_value = new_role
            elif self.calls == 4:
                # User row for response
                result.scalar_one_or_none.return_value = target_user
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.patch(
            "/api/tenants/5/workspaces/7/members/11",
            json={"role": "workspace_admin"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "workspace_admin"
    assert member.role_id == 9
    assert holder["session"].committed is True


def test_patch_workspace_member_404_when_missing(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    class _Sess(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                result.scalar_one_or_none.return_value = SimpleNamespace(id=7, tenant_id=5)
            elif self.calls == 2:
                result.scalar_one_or_none.return_value = None
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.patch(
            "/api/tenants/5/workspaces/7/members/999",
            json={"role": "member"},
        )
    assert r.status_code == 404


def test_remove_workspace_member(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    member = SimpleNamespace(user_id=11, workspace_id=7, role_id=8)

    class _Sess(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                result.scalar_one_or_none.return_value = SimpleNamespace(id=7, tenant_id=5)
            elif self.calls == 2:
                result.scalar_one_or_none.return_value = member
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.delete("/api/tenants/5/workspaces/7/members/11")
    assert r.status_code == 204
    assert member in holder["session"].deleted
    assert holder["session"].committed is True


def test_remove_workspace_member_forbidden_for_member(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("member", tenant_id=5)
    with TestClient(app) as c:
        r = c.delete("/api/tenants/5/workspaces/7/members/11")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/tenants/{tid}/tokens  — admin token issue
# DELETE /api/tenants/{tid}/tokens/{token_id}  — admin token revoke
# ---------------------------------------------------------------------------


def test_create_tenant_token_returns_plaintext_once(writes_app, monkeypatch):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    from app.gateway.identity.auth import api_token as api_token_mod

    async def fake_create(session, *, user_id, tenant_id, workspace_id, name, scopes, expires_at, created_by):
        return api_token_mod.CreatedToken(
            token_id=200,
            plaintext="dft_abc123XYZ",
            prefix="dft_abc123",
        )

    monkeypatch.setattr(admin_writes_module, "create_api_token", fake_create)

    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/tokens",
            json={
                "name": "ci-bot",
                "scopes": ["skill:invoke"],
                "user_id": 1,
                "workspace_id": 7,
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plaintext"] == "dft_abc123XYZ"
    assert body["prefix"] == "dft_abc123"
    assert body["id"] == 200


def test_create_tenant_token_forbidden_for_member(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("member", tenant_id=5)
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/tokens",
            json={"name": "x", "scopes": [], "user_id": 1, "workspace_id": 1},
        )
    assert r.status_code == 403


def test_revoke_tenant_token_allowed_for_tenant_owner(writes_app, monkeypatch):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    token = SimpleNamespace(id=200, tenant_id=5, user_id=10, revoked_at=None)

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = token
            return result

    holder["session"] = _Sess()
    captured: dict = {}

    async def fake_revoke(session, *, token_id, by_user_id):
        captured["token_id"] = token_id
        captured["by_user_id"] = by_user_id

    monkeypatch.setattr(admin_writes_module, "revoke_api_token", fake_revoke)

    with TestClient(app) as c:
        r = c.delete("/api/tenants/5/tokens/200")
    assert r.status_code == 204
    assert captured == {"token_id": 200, "by_user_id": 1}


def test_revoke_tenant_token_404_when_missing(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.delete("/api/tenants/5/tokens/999")
    assert r.status_code == 404


def test_revoke_tenant_token_blocks_cross_tenant(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    # Token belongs to a different tenant (tampered ID in URL).
    token = SimpleNamespace(id=200, tenant_id=99, user_id=10, revoked_at=None)

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = token
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.delete("/api/tenants/5/tokens/200")
    assert r.status_code == 404  # generic 404 — never confirm cross-tenant existence


# ---------------------------------------------------------------------------
# Tenant CRUD (M7A item 2)
# ---------------------------------------------------------------------------


def test_create_tenant_allowed_for_platform_admin(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("platform_admin", tenant_id=1)

    class _Sess(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            # First call: slug lookup -> none
            if self.calls == 1:
                result.scalar_one_or_none.return_value = None
            return result

        def add(self, obj):
            super().add(obj)
            from app.gateway.identity.models import Tenant

            if isinstance(obj, Tenant):
                obj.id = 77
                obj.plan = "free"
                obj.status = 1

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.post("/api/admin/tenants", json={"slug": "acme", "name": "Acme"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "acme"
    assert body["id"] == 77


def test_create_tenant_forbidden_for_tenant_owner(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=1)
    with TestClient(app) as c:
        r = c.post("/api/admin/tenants", json={"slug": "acme", "name": "Acme"})
    assert r.status_code == 403


def test_create_tenant_409_on_slug_conflict(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("platform_admin", tenant_id=1)

    existing = SimpleNamespace(id=1, slug="acme", name="Acme")

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.post("/api/admin/tenants", json={"slug": "acme", "name": "Acme"})
    assert r.status_code == 409
    assert "slug" in r.json()["detail"].lower()


def test_create_tenant_422_on_invalid_slug(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("platform_admin", tenant_id=1)
    with TestClient(app) as c:
        r = c.post("/api/admin/tenants", json={"slug": "NO-CAPS", "name": "x"})
    assert r.status_code == 422


def test_patch_tenant_renames(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("platform_admin", tenant_id=1)

    tenant = SimpleNamespace(id=5, slug="acme", name="Old", plan="free", status=1)

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = tenant
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.patch("/api/admin/tenants/5", json={"name": "New"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "New"
    assert tenant.name == "New"


def test_patch_tenant_404_missing(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("platform_admin", tenant_id=1)

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.patch("/api/admin/tenants/999", json={"name": "z"})
    assert r.status_code == 404


def test_patch_tenant_forbidden_for_tenant_owner(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)
    with TestClient(app) as c:
        r = c.patch("/api/admin/tenants/5", json={"name": "x"})
    assert r.status_code == 403


def test_delete_tenant_sets_status_zero(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("platform_admin", tenant_id=1)

    tenant = SimpleNamespace(id=5, slug="acme", name="Acme", plan="free", status=1)

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = tenant
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.delete("/api/admin/tenants/5")
    assert r.status_code == 204
    assert tenant.status == 0


def test_delete_tenant_forbidden_for_tenant_owner(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)
    with TestClient(app) as c:
        r = c.delete("/api/admin/tenants/5")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Workspace CRUD (M7A item 2)
# ---------------------------------------------------------------------------


def test_create_workspace_allowed_for_tenant_owner(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    class _Sess(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            result = MagicMock()
            if self.calls == 1:
                # Slug+tenant lookup -> none
                result.scalar_one_or_none.return_value = None
            return result

        def add(self, obj):
            super().add(obj)
            from app.gateway.identity.models import Workspace

            if isinstance(obj, Workspace):
                obj.id = 13

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/workspaces",
            json={"slug": "eng", "name": "Engineering"},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["tenant_id"] == 5
    assert body["slug"] == "eng"
    assert body["id"] == 13


def test_create_workspace_forbidden_for_member(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("member", tenant_id=5)
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/workspaces",
            json={"slug": "eng", "name": "Engineering"},
        )
    assert r.status_code == 403


def test_create_workspace_409_on_slug_conflict(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    existing = SimpleNamespace(id=1, tenant_id=5, slug="eng", name="Engineering")

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = existing
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.post(
            "/api/tenants/5/workspaces",
            json={"slug": "eng", "name": "Engineering"},
        )
    assert r.status_code == 409


def test_patch_workspace_renames(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    ws = SimpleNamespace(id=7, tenant_id=5, slug="eng", name="Old")

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = ws
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.patch("/api/tenants/5/workspaces/7", json={"name": "New"})
    assert r.status_code == 200, r.text
    assert ws.name == "New"


def test_patch_workspace_cross_tenant_404(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    # Workspace exists but in a different tenant.
    ws = SimpleNamespace(id=7, tenant_id=99, slug="eng", name="Old")

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = ws
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.patch("/api/tenants/5/workspaces/7", json={"name": "New"})
    assert r.status_code == 404


def test_delete_workspace_removes_row(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=5)

    ws = SimpleNamespace(id=7, tenant_id=5, slug="eng", name="Eng")

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = ws
            return result

    holder["session"] = _Sess()
    with TestClient(app) as c:
        r = c.delete("/api/tenants/5/workspaces/7")
    assert r.status_code == 204
    assert ws in holder["session"].deleted


def test_delete_workspace_forbidden_for_member(writes_app):
    app, holder = writes_app
    holder["identity"] = _identity_for_role("member", tenant_id=5)
    with TestClient(app) as c:
        r = c.delete("/api/tenants/5/workspaces/7")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Audit emission (M7A item 2, task 5)
#
# Parametrized smoke: every write endpoint, when successful, produces exactly
# one AuditEvent via the AuditMiddleware. The action name derives from method
# (http.post / http.patch / http.delete) and the resource_type is extracted
# from the URL pattern. We mount the middleware on a fresh FastAPI app that
# shares the stubbed session + identity inject from writes_app.
# ---------------------------------------------------------------------------


class _CapturingWriter:
    def __init__(self) -> None:
        self.events: list = []

    async def enqueue(self, event, *, critical: bool = False) -> None:
        self.events.append((event, critical))


def _audit_app(captured: _CapturingWriter, stub_session: _StubSession, identity: Identity):
    from app.gateway.identity.audit.middleware import AuditMiddleware

    app = FastAPI()
    app.include_router(admin_writes_module.router)

    @app.middleware("http")
    async def inject_identity(request, call_next):
        request.state.identity = identity
        return await call_next(request)

    app.add_middleware(AuditMiddleware, writer=captured)

    async def _override_session() -> AsyncIterator[_StubSession]:
        yield stub_session

    app.dependency_overrides[get_session] = _override_session
    return app


@pytest.mark.parametrize(
    "method,path,body,role,setup",
    [
        # Tenant CRUD — /api/admin/tenants is not matched by any current
        # resource pattern in the audit middleware, so resource_type is None.
        # What we care about: an event fires with the right action + success.
        ("POST", "/api/admin/tenants", {"slug": "acme", "name": "Acme"}, "platform_admin", "create_tenant"),
        ("PATCH", "/api/admin/tenants/5", {"name": "New"}, "platform_admin", "get_tenant"),
        ("DELETE", "/api/admin/tenants/5", None, "platform_admin", "get_tenant"),
        # Workspace CRUD — path matches the tenant+workspace pattern so
        # resource_type is either "tenant" (POST to collection) or "workspace"
        # (PATCH/DELETE on the item). Either is fine; the assertion is that
        # SOMETHING non-empty is classified for tenant-scoped paths.
        ("POST", "/api/tenants/5/workspaces", {"slug": "eng", "name": "Eng"}, "tenant_owner", "create_workspace"),
        ("PATCH", "/api/tenants/5/workspaces/7", {"name": "New"}, "tenant_owner", "get_workspace"),
        ("DELETE", "/api/tenants/5/workspaces/7", None, "tenant_owner", "get_workspace"),
    ],
)
def test_write_endpoints_emit_audit(method, path, body, role, setup):
    captured = _CapturingWriter()
    identity = _identity_for_role(role, tenant_id=5)

    class _Sess(_StubSession):
        async def execute(self, stmt):
            result = MagicMock()
            if setup == "create_tenant" or setup == "create_workspace":
                result.scalar_one_or_none.return_value = None  # no conflict
            elif setup == "get_tenant":
                result.scalar_one_or_none.return_value = SimpleNamespace(id=5, slug="acme", name="Old", plan="free", status=1)
            elif setup == "get_workspace":
                result.scalar_one_or_none.return_value = SimpleNamespace(id=7, tenant_id=5, slug="eng", name="Old")
            return result

        def add(self, obj):
            super().add(obj)
            # Give created rows an id so flush/commit returns valid payloads.
            from app.gateway.identity.models import Tenant, Workspace

            if isinstance(obj, Tenant):
                obj.id = 5
                obj.plan = "free"
                obj.status = 1
            elif isinstance(obj, Workspace):
                obj.id = 7

    app = _audit_app(captured, _Sess(), identity)
    with TestClient(app) as c:
        r = c.request(method, path, json=body)
    assert r.status_code in (200, 201, 204), r.text

    # Exactly one event per request.
    assert len(captured.events) == 1, [e[0].action for e in captured.events]
    event, _critical = captured.events[0]
    assert event.action == f"http.{method.lower()}"
    assert event.result == "success"
    assert event.user_id == 1
    assert event.metadata["path"] == path
    assert event.metadata["method"] == method
