"""Tests for the artifacts router tenant/workspace authz guard (M4 task 7).

These tests are deliberately light-weight: they build a minimal FastAPI
app around ``artifacts_router.router``, stub identity via a Starlette
middleware, and exercise the full resolve-and-guard path against a real
``tmp_path`` filesystem laid out in the tenant-stratified layout.

They do **not** touch Postgres or Redis — the goal is to exercise the
``_extract_scope`` / ``assert_within_tenant_root`` wiring, not the M2/M3
identity stack. Full-stack coverage lives in the identity-container tests
under ``tests/identity/auth/``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

import app.gateway.routers.artifacts as artifacts_router
from app.gateway.identity.settings import get_identity_settings
from deerflow.config import paths as paths_mod


@dataclass
class FakeIdentity:
    """Minimal stand-in for the production ``Identity`` dataclass.

    Exposes the attributes ``_extract_scope`` reads: ``tenant_id``,
    ``workspace_ids`` (plural, tuple) and ``is_authenticated``.
    """

    tenant_id: int | None
    workspace_ids: tuple[int, ...]
    is_authenticated: bool = True


def _inject_identity_middleware(app: FastAPI, identity: FakeIdentity | None):
    class _Inject(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.identity = identity
            return await call_next(request)

    app.add_middleware(_Inject)


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point DEER_FLOW_HOME at tmp_path and reset the Paths singleton."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_mod, "_paths", None)
    yield tmp_path
    monkeypatch.setattr(paths_mod, "_paths", None)


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setenv("ENABLE_IDENTITY", "false")
    get_identity_settings.cache_clear()
    yield
    get_identity_settings.cache_clear()


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("ENABLE_IDENTITY", "true")
    get_identity_settings.cache_clear()
    yield
    get_identity_settings.cache_clear()


def _make_app(identity: FakeIdentity | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(artifacts_router.router)
    _inject_identity_middleware(app, identity)
    return app


# ---------------------------------------------------------------------------
# Flag OFF — regression: legacy layout works exactly as before.
# ---------------------------------------------------------------------------


def test_flag_off_legacy_layout_returns_200(isolated_home, flag_off):
    paths = paths_mod.get_paths()
    paths.ensure_thread_dirs_for("t1")
    outputs = isolated_home / "threads" / "t1" / "user-data" / "outputs"
    (outputs / "hello.txt").write_text("legacy", encoding="utf-8")

    app = _make_app(identity=FakeIdentity(tenant_id=5, workspace_ids=(7,)))
    # Even with a fake identity attached, flag_off must keep the legacy path.
    with TestClient(app) as client:
        r = client.get("/api/threads/t1/artifacts/mnt/user-data/outputs/hello.txt")
    assert r.status_code == 200, r.text
    assert r.text == "legacy"


# ---------------------------------------------------------------------------
# Flag ON — same-tenant happy path.
# ---------------------------------------------------------------------------


def test_flag_on_same_tenant_returns_200(isolated_home, flag_on):
    paths = paths_mod.get_paths()
    paths.ensure_thread_dirs_for("t1", tenant_id=5, workspace_id=7)
    outputs = isolated_home / "tenants" / "5" / "workspaces" / "7" / "threads" / "t1" / "user-data" / "outputs"
    (outputs / "report.txt").write_text("scoped", encoding="utf-8")

    app = _make_app(identity=FakeIdentity(tenant_id=5, workspace_ids=(7,)))
    with TestClient(app) as client:
        r = client.get("/api/threads/t1/artifacts/mnt/user-data/outputs/report.txt")
    assert r.status_code == 200, r.text
    assert r.text == "scoped"


# ---------------------------------------------------------------------------
# Flag ON — cross-tenant denial.
# ---------------------------------------------------------------------------


def test_flag_on_cross_tenant_traversal_returns_403(isolated_home, flag_on):
    """A caller in tenant 5 cannot escape into tenant 99 via ``../`` segments.

    We call ``get_artifact`` directly rather than through the HTTP client —
    Starlette's URL path normalisation consumes ``../`` before dispatching,
    which would mask the application-level guard that we actually want to
    assert here.
    """
    import asyncio

    paths = paths_mod.get_paths()
    paths.ensure_thread_dirs_for("t1", tenant_id=5, workspace_id=7)
    paths.ensure_thread_dirs_for("t1", tenant_id=99, workspace_id=1)
    other_outputs = isolated_home / "tenants" / "99" / "workspaces" / "1" / "threads" / "t1" / "user-data" / "outputs"
    (other_outputs / "secret.txt").write_text("tenant-99-secret", encoding="utf-8")

    identity = FakeIdentity(tenant_id=5, workspace_ids=(7,))
    request = _fake_request_with_identity(identity)
    traversal_path = "mnt/user-data/outputs/../../../../../../tenants/99/workspaces/1/threads/t1/user-data/outputs/secret.txt"
    with pytest.raises(Exception) as excinfo:
        asyncio.run(artifacts_router.get_artifact("t1", traversal_path, request))
    # Either the path resolver trips on the traversal (HTTPException 403),
    # or ``assert_within_tenant_root`` trips on the resolved path (also 403).
    exc = excinfo.value
    status = getattr(exc, "status_code", None)
    assert status == 403, f"expected 403, got {exc!r}"
    detail = getattr(exc, "detail", "") or ""
    # Body must not leak cross-tenant ids / paths — lock in the exact
    # generic message so future refactors can't weaken the contract.
    assert str(detail) == "Access denied"


def test_flag_on_path_traversal_returns_403(isolated_home, flag_on):
    """Basic ``../`` escape inside the user-data prefix is rejected."""
    paths = paths_mod.get_paths()
    paths.ensure_thread_dirs_for("t1", tenant_id=5, workspace_id=7)

    app = _make_app(identity=FakeIdentity(tenant_id=5, workspace_ids=(7,)))
    with TestClient(app) as client:
        r = client.get("/api/threads/t1/artifacts/mnt/user-data/outputs/../../../etc/passwd")
    # Either 403 (traversal detected) or 400 (invalid path) — both are safe.
    # The path resolver raises "Access denied: path traversal detected", which
    # the gateway maps to 403.
    assert r.status_code in (400, 403), r.text


# ---------------------------------------------------------------------------
# Flag ON but anonymous — falls back to legacy behaviour.
# ---------------------------------------------------------------------------


def test_flag_on_anonymous_uses_legacy(isolated_home, flag_on):
    paths = paths_mod.get_paths()
    paths.ensure_thread_dirs_for("t1")
    outputs = isolated_home / "threads" / "t1" / "user-data" / "outputs"
    (outputs / "hello.txt").write_text("legacy", encoding="utf-8")

    anon = FakeIdentity(tenant_id=None, workspace_ids=(), is_authenticated=False)
    app = _make_app(identity=anon)
    with TestClient(app) as client:
        r = client.get("/api/threads/t1/artifacts/mnt/user-data/outputs/hello.txt")
    assert r.status_code == 200, r.text
    assert r.text == "legacy"


# ---------------------------------------------------------------------------
# _extract_scope unit behaviours.
# ---------------------------------------------------------------------------


def _fake_request_with_identity(identity) -> Request:
    """Construct a minimal Starlette Request carrying *identity* in state."""
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    req = Request(scope)
    req.state.identity = identity
    return req


def test_extract_scope_rejects_non_positive_ids(flag_on):
    bad = FakeIdentity(tenant_id=0, workspace_ids=(7,))
    req = _fake_request_with_identity(bad)
    assert artifacts_router._extract_scope(req) == (None, None)


def test_extract_scope_rejects_bool_ids(flag_on):
    # bool is subclass of int — must be rejected explicitly.
    bad = FakeIdentity(tenant_id=True, workspace_ids=(True,))  # type: ignore[arg-type]
    req = _fake_request_with_identity(bad)
    assert artifacts_router._extract_scope(req) == (None, None)


def test_extract_scope_handles_dict_shape(flag_on):
    req = _fake_request_with_identity({"tenant_id": 5, "workspace_id": 7})
    assert artifacts_router._extract_scope(req) == (5, 7)


def test_extract_scope_flag_off(flag_off):
    good = FakeIdentity(tenant_id=5, workspace_ids=(7,))
    req = _fake_request_with_identity(good)
    # Flag off → always (None, None) even with a populated identity.
    assert artifacts_router._extract_scope(req) == (None, None)


def test_extract_scope_uses_first_workspace_id(flag_on):
    good = FakeIdentity(tenant_id=5, workspace_ids=(7, 8, 9))
    req = _fake_request_with_identity(good)
    assert artifacts_router._extract_scope(req) == (5, 7)


def test_extract_scope_tenant_without_workspace_falls_back(flag_on):
    """Tenant id present but workspace_ids is empty → falls back to (None, None)."""
    bad = FakeIdentity(tenant_id=5, workspace_ids=())
    req = _fake_request_with_identity(bad)
    assert artifacts_router._extract_scope(req) == (None, None)
