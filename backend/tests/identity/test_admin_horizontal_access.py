"""Cross-tenant and cross-role denial matrix for the A2 admin read routes.

Templated from backend/tests/identity/rbac/test_horizontal_access.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.bootstrap import PREDEFINED_ROLE_PERMISSIONS
from app.gateway.identity.db import get_session
from app.gateway.identity.routers import admin as admin_router_module


def _identity(role_key: str, *, tenant_id: int, workspace_ids: tuple[int, ...] = (1,)) -> Identity:
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
        roles={"platform": platform_roles, "tenant": tenant_roles, "workspaces": workspace_role_map},
        session_id=f"sess-{role_key}",
    )


@pytest.fixture
def app_with_admin():
    app = FastAPI()
    app.include_router(admin_router_module.router)
    current: dict = {"identity": Identity.anonymous()}

    @app.middleware("http")
    async def inject_identity(request, call_next):
        request.state.identity = current["identity"]
        return await call_next(request)

    async def _noop_session() -> AsyncIterator[object]:
        # Horizontal-access tests assert 401/403 BEFORE the handler ever needs
        # a session. If a test reaches the handler, _NoSession.execute raises,
        # which surfaces the mis-configuration rather than silently passing.
        class _NoSession:
            async def execute(self, stmt):
                raise AssertionError("handler should have been blocked before hitting the DB")

        yield _NoSession()

    app.dependency_overrides[get_session] = _noop_session
    return app, current


DENIALS = [
    # role,          method, path,                                        expected
    ("member", "GET", "/api/admin/tenants", 403),
    ("tenant_owner", "GET", "/api/admin/tenants", 403),
    ("viewer", "GET", "/api/tenants/1/users", 403),
    ("member", "GET", "/api/tenants/1/users", 403),
    ("tenant_owner", "GET", "/api/tenants/99/users", 403),  # cross-tenant
    ("member", "GET", "/api/tenants/1/workspaces", 403),
    ("tenant_owner", "GET", "/api/tenants/99/workspaces", 403),  # cross-tenant
    ("member", "GET", "/api/tenants/1/workspaces/1/members", 403),
    ("tenant_owner", "GET", "/api/tenants/99/workspaces/1/members", 403),
    ("member", "GET", "/api/tenants/1/tokens", 403),
    ("tenant_owner", "GET", "/api/tenants/99/tokens", 403),
]


@pytest.mark.parametrize("role,method,path,expected", DENIALS)
def test_horizontal_denial(app_with_admin, role, method, path, expected):
    app, holder = app_with_admin
    holder["identity"] = _identity(role, tenant_id=1, workspace_ids=(1,))
    with TestClient(app) as c:
        r = c.request(method, path)
    assert r.status_code == expected, f"{role} {method} {path}: expected {expected}, got {r.status_code}"


def test_anonymous_gets_401_everywhere(app_with_admin):
    app, _ = app_with_admin
    for path in [
        "/api/admin/tenants",
        "/api/admin/tenants/1",
        "/api/tenants/1/users",
        "/api/tenants/1/users/1",
        "/api/tenants/1/workspaces",
        "/api/tenants/1/workspaces/1/members",
        "/api/tenants/1/tokens",
    ]:
        with TestClient(app) as c:
            r = c.get(path)
        assert r.status_code == 401, f"GET {path} returned {r.status_code}"
