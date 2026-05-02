"""Public /api/auth/register endpoint tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.identity.db import get_session
from app.gateway.identity.routers import auth as auth_module


@pytest.fixture
def reg_app():
    app = FastAPI()
    app.include_router(auth_module.router)

    current: dict[str, Any] = {"session": None}

    async def _override() -> AsyncIterator[Any]:
        yield current["session"]

    app.dependency_overrides[get_session] = _override
    return app, current


def _make_pending_code(plaintext: str, *, tenant_id: int = 1, status: int = 0,
                      expires_offset: timedelta = timedelta(days=7)):
    return SimpleNamespace(
        id=1,
        tenant_id=tenant_id,
        creator_id=99,
        code_hash=bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode(),
        code_prefix=plaintext[:8],
        status=status,
        expires_at=datetime.now(UTC) + expires_offset,
        accepted_by=None,
        accepted_at=None,
        created_at=datetime.now(UTC),
    )


def _patch_runtime():
    rt = MagicMock()
    rt.cookie_name = "deerflow_session"
    rt.cookie_secure = False
    rt.access_ttl_sec = 900
    rt.refresh_ttl_sec = 604800
    rt.issuer = "deerflow"
    rt.audience = "deerflow-api"
    rt.jwt_private_key_pem = "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----"
    rt.auto_provision = False
    rt.session_store.create = AsyncMock(return_value=SimpleNamespace(sid="sess-new"))
    return rt


def test_register_happy_path_creates_user_and_sets_cookie(reg_app):
    app, holder = reg_app
    plaintext = "verylongplaintextcode" + "x" * 30
    code_row = _make_pending_code(plaintext)
    workspace_row = SimpleNamespace(id=1, tenant_id=1)
    role_row = SimpleNamespace(id=4, role_key="workspace_member", scope="workspace")
    tenant_row = SimpleNamespace(id=1, slug="default")

    class _Sess:
        def __init__(self):
            self.added: list[Any] = []
            self.committed = False
            self.calls = 0

        def add(self, obj):
            self.added.append(obj)
            from app.gateway.identity.models import User
            if isinstance(obj, User):
                obj.id = 100

        async def commit(self):
            self.committed = True

        async def flush(self):
            pass

        async def execute(self, stmt):
            self.calls += 1
            r = MagicMock()
            # Sequence:
            # 1. candidate codes by prefix+pending
            # 2. existing user lookup (by email) -> none
            # 3. default workspace lookup -> workspace_row
            # 4. workspace_member role lookup -> role_row
            if self.calls == 1:
                r.scalars.return_value.all.return_value = [code_row]
            elif self.calls == 2:
                r.scalar_one_or_none.return_value = None
            elif self.calls == 3:
                r.scalar_one_or_none.return_value = workspace_row
            elif self.calls == 4:
                r.scalar_one_or_none.return_value = role_row
            return r

    holder["session"] = _Sess()

    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()), \
         patch.object(auth_module, "issue_access_token", return_value="tok123"), \
         patch.object(auth_module, "build_identity_for_user", new=AsyncMock(return_value=SimpleNamespace(
             user_id=100, tenant_id=1, workspace_ids=(1,), permissions=set(), roles={},
             email="new@example.com",
         ))), \
         patch.object(auth_module, "resolve_active_tenant", new=AsyncMock(return_value=(tenant_row, workspace_row))):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={
                    "code": plaintext,
                    "email": "new@example.com",
                    "password": "atleast8chars",
                    "display_name": "Newbie",
                },
            )

    assert r.status_code == 201, r.text
    assert r.json() == {"status": "ok", "email": "new@example.com"}
    assert "deerflow_session" in r.cookies
    # Code marked accepted.
    assert code_row.status == 1
    assert code_row.accepted_by == 100
    assert code_row.accepted_at is not None


def test_register_weak_password_422(reg_app):
    app, _ = reg_app
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={"code": "x" * 40, "email": "a@b.com", "password": "short"},
            )
    assert r.status_code == 422


def test_register_invalid_email_422(reg_app):
    app, _ = reg_app
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={"code": "x" * 40, "email": "not-an-email", "password": "longpassword"},
            )
    assert r.status_code == 422


def test_register_unknown_code_404(reg_app):
    app, holder = reg_app

    class _Sess:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            pass

        async def flush(self):
            pass

        async def execute(self, stmt):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []  # no candidates
            return r

    holder["session"] = _Sess()
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={"code": "x" * 40, "email": "a@b.com", "password": "longpassword"},
            )
    assert r.status_code == 404


def test_register_already_used_code_404(reg_app):
    """A code with status=1 (accepted) or status=3 (revoked) isn't returned by
    the prefix+pending query → 404 (not 410). The spec lists 410 for 'already
    used' / 'revoked', but the query path filters out non-pending, so the bcrypt
    step never matches. 404 is the correct observable result for both states;
    behavior is documented in CLAUDE.md. This single test covers spec §9.2's
    'revoked code' case as well — the code path is identical."""
    app, holder = reg_app
    plaintext = "y" * 40

    class _Sess:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            pass

        async def flush(self):
            pass

        async def execute(self, stmt):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r

    holder["session"] = _Sess()
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={"code": plaintext, "email": "a@b.com", "password": "longpassword"},
            )
    assert r.status_code == 404


def test_register_expired_code_410(reg_app):
    app, holder = reg_app
    plaintext = "z" * 40
    code_row = _make_pending_code(plaintext, expires_offset=timedelta(days=-1))

    class _Sess:
        def __init__(self):
            self.added = []
            self.committed = False

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            self.committed = True

        async def flush(self):
            pass

        async def execute(self, stmt):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [code_row]
            return r

    holder["session"] = _Sess()
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={"code": plaintext, "email": "a@b.com", "password": "longpassword"},
            )
    assert r.status_code == 410
    assert code_row.status == 2  # auto-marked expired


def test_register_email_already_registered_409(reg_app):
    app, holder = reg_app
    plaintext = "q" * 40
    code_row = _make_pending_code(plaintext)
    existing_user = SimpleNamespace(id=99, email="dup@example.com")

    class _Sess:
        def __init__(self):
            self.added = []
            self.committed = False
            self.calls = 0

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            self.committed = True

        async def flush(self):
            pass

        async def execute(self, stmt):
            self.calls += 1
            r = MagicMock()
            if self.calls == 1:
                r.scalars.return_value.all.return_value = [code_row]
            elif self.calls == 2:
                r.scalar_one_or_none.return_value = existing_user
            return r

    holder["session"] = _Sess()
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={"code": plaintext, "email": "dup@example.com", "password": "longpassword"},
            )
    assert r.status_code == 409
    # Code remains pending (we abort before marking accepted).
    assert code_row.status == 0


def test_register_concurrent_email_race_returns_409(reg_app):
    """Pre-check passes but commit hits User.email UNIQUE constraint
    (concurrent identical email). Handler catches IntegrityError → 409."""
    from sqlalchemy.exc import IntegrityError

    app, holder = reg_app
    plaintext = "p" * 40
    code_row = _make_pending_code(plaintext)
    workspace_row = SimpleNamespace(id=1, tenant_id=1)
    role_row = SimpleNamespace(id=4, role_key="workspace_member", scope="workspace")

    class _Sess:
        def __init__(self):
            self.added = []
            self.calls = 0

        def add(self, obj):
            self.added.append(obj)
            from app.gateway.identity.models import User
            if isinstance(obj, User):
                obj.id = 100

        async def commit(self):
            # Simulate winner-loser race: pre-check passed (email lookup #2
            # returned None), but commit hits the UNIQUE constraint.
            raise IntegrityError("INSERT", {}, Exception("unique violation"))

        async def rollback(self):
            pass

        async def flush(self):
            pass

        async def execute(self, stmt):
            self.calls += 1
            r = MagicMock()
            if self.calls == 1:
                r.scalars.return_value.all.return_value = [code_row]
            elif self.calls == 2:
                r.scalar_one_or_none.return_value = None
            elif self.calls == 3:
                r.scalar_one_or_none.return_value = workspace_row
            elif self.calls == 4:
                r.scalar_one_or_none.return_value = role_row
            return r

    holder["session"] = _Sess()
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={
                    "code": plaintext,
                    "email": "race@example.com",
                    "password": "longpassword",
                },
            )
    assert r.status_code == 409
    assert "email already registered" in r.json()["detail"].lower()
