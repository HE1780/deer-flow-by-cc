# backend/tests/identity/test_gateway_authn_baseline.py
"""Tests for the gateway auth baseline.

Verifies that ``require_authenticated_global`` (when ``ENABLE_IDENTITY=true``)
returns 401 for legacy /api/* routes when the caller is anonymous, while
genuinely public endpoints (auth flows, health, metrics) stay reachable.

The legacy gateway routers don't need a real database — we only care about
the auth dep firing first. We build a minimal app that mounts the routers
and stubs identity via the same Starlette middleware pattern used in
test_artifacts_authz.py.

See: docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.identity.settings import get_identity_settings


@dataclass
class FakeIdentity:
    tenant_id: int | None = 1
    workspace_ids: tuple[int, ...] = (1,)
    is_authenticated: bool = True


def _inject_identity(app: FastAPI, identity: FakeIdentity | None) -> None:
    class _Inject(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.identity = identity
            return await call_next(request)

    app.add_middleware(_Inject)


def _build_protected_app(identity: FakeIdentity | None) -> FastAPI:
    """Mounts a representative legacy router with the global dep."""
    from fastapi import Depends
    from app.gateway.auth_baseline import require_authenticated_global
    import app.gateway.routers.models as models_router

    app = FastAPI()
    app.include_router(
        models_router.router,
        dependencies=[Depends(require_authenticated_global)],
    )
    _inject_identity(app, identity)
    return app


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("ENABLE_IDENTITY", "true")
    get_identity_settings.cache_clear()
    yield
    get_identity_settings.cache_clear()


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setenv("ENABLE_IDENTITY", "false")
    get_identity_settings.cache_clear()
    yield
    get_identity_settings.cache_clear()


# ---------------------------------------------------------------------------
# Flag ON — anonymous caller is rejected
# ---------------------------------------------------------------------------


def test_anonymous_caller_gets_401_on_protected_route(flag_on):
    app = _build_protected_app(identity=None)
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 401, r.text
    assert "authentication required" in r.text.lower()


def test_anonymous_identity_gets_401_on_protected_route(flag_on):
    """is_authenticated=False is the same as no identity."""
    app = _build_protected_app(identity=FakeIdentity(is_authenticated=False))
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 401, r.text


def test_authenticated_caller_passes_auth_check(flag_on):
    """Authenticated caller passes auth — handler may still 4xx/5xx for
    unrelated reasons but it must not be 401-from-baseline."""
    app = _build_protected_app(identity=FakeIdentity())
    with TestClient(app) as client:
        r = client.get("/api/models")
    # The handler may return 200 with model list, or some other status if
    # config/env isn't set up — but it must NOT be 401 (that would mean the
    # auth dep didn't pass through).
    assert r.status_code != 401, r.text


# ---------------------------------------------------------------------------
# Flag OFF — dep is a no-op
# ---------------------------------------------------------------------------


def test_baseline_no_op_when_identity_disabled(flag_off):
    """ENABLE_IDENTITY=false must let anonymous callers through."""
    app = _build_protected_app(identity=None)
    with TestClient(app) as client:
        r = client.get("/api/models")
    # Same "must not be 401-from-baseline" assertion — but here even with
    # identity=None the dep should early-return.
    assert r.status_code != 401, r.text


# ---------------------------------------------------------------------------
# Allowlist behavior (unit-style — exercise the dep directly)
# ---------------------------------------------------------------------------


def test_allowlisted_path_passes_with_no_identity(flag_on):
    """A path under PUBLIC_PREFIXES must skip the auth check entirely."""
    from app.gateway.auth_baseline import PUBLIC_PREFIXES

    # Sanity: the spec's allowlist must include the auth flow.
    assert any(p.startswith("/api/auth/login") for p in PUBLIC_PREFIXES)
    assert any(p == "/health" or p.startswith("/health") for p in PUBLIC_PREFIXES)
    assert any(p == "/metrics" or p.startswith("/metrics") for p in PUBLIC_PREFIXES)
    # And must NOT include channels (per the spec correction in the plan
    # header — /api/channels is admin-console API, not platform webhook).
    assert not any("/api/channels" in p for p in PUBLIC_PREFIXES)


def test_dep_directly_returns_for_allowlisted_path(flag_on):
    """Unit-style: feed a request whose path is on the allowlist; dep returns
    without raising even when identity is anonymous."""
    from app.gateway.auth_baseline import require_authenticated_global

    class _Req:
        class _State:
            identity = None
        url = type("U", (), {"path": "/api/auth/login"})()
        state = _State()

    # Should not raise.
    require_authenticated_global(_Req())


def test_dep_directly_raises_for_protected_path_anonymous(flag_on):
    """Unit-style: feed a request whose path is NOT on the allowlist with no
    identity; dep raises 401."""
    from fastapi import HTTPException
    from app.gateway.auth_baseline import require_authenticated_global

    class _Req:
        class _State:
            identity = None
        url = type("U", (), {"path": "/api/models"})()
        state = _State()

    with pytest.raises(HTTPException) as excinfo:
        require_authenticated_global(_Req())
    assert excinfo.value.status_code == 401


# ---------------------------------------------------------------------------
# Real app smoke — confirms the dep was attached at every legacy router
# ---------------------------------------------------------------------------


def _build_real_app_anonymous():
    """Build a thin FastAPI clone that shares the real gateway's route table.

    We cannot call ``_inject_identity`` (i.e. ``app.add_middleware``) on the
    real gateway ``app`` singleton after it has been started by a previous
    TestClient call — Starlette raises ``RuntimeError: Cannot add middleware
    after an application has started``.

    Instead we create a *fresh* FastAPI application and copy the real app's
    ``routes`` list into it.  The clone inherits every router registration
    (including the ``dependencies=[Depends(require_authenticated_global)]``
    attached at ``include_router`` time) but starts with a clean
    ``middleware_stack``, so ``add_middleware`` works.
    """
    import importlib

    app_mod = importlib.import_module("app.gateway.app")
    real_app = app_mod.app

    # Fresh app — no lifespan, no middleware yet.
    clone = FastAPI()
    # Share the route objects (router registrations incl. deps live on each
    # Route object, not on the app itself), but copy the list so any later
    # mutation in real_app.router.routes does not leak into the clone (and
    # vice versa). ``app.routes`` is a read-only property; the underlying
    # mutable list lives on ``app.router.routes``.
    clone.router.routes = list(real_app.router.routes)

    _inject_identity(clone, identity=None)
    return clone


# One representative path per legacy router. Auth must fire before any
# business validation, so invalid ids are fine — we never reach the handler.
LEGACY_ROUTES = [
    ("GET", "/api/models"),
    ("GET", "/api/mcp/config"),
    ("GET", "/api/memory"),
    ("GET", "/api/skills"),
    ("GET", "/api/threads/abc/artifacts/x.txt"),
    ("GET", "/api/threads/abc/uploads/list"),
    ("POST", "/api/threads/search"),         # threads
    ("GET", "/api/threads/abc/skills"),       # thread_skills
    ("GET", "/api/agents"),
    ("POST", "/api/threads/abc/suggestions"),
    ("GET", "/api/channels/"),
    ("POST", "/api/assistants/search"),
    ("GET", "/api/threads/abc/runs"),         # thread_runs
    ("POST", "/api/runs/wait"),               # runs
]


@pytest.mark.parametrize("method,path", LEGACY_ROUTES)
def test_real_app_legacy_route_returns_401_for_anonymous(
    flag_on, method, path,
):
    app = _build_real_app_anonymous()
    # raise_server_exceptions=False: the dep fires *before* the handler, so a
    # 401 from the dep is a proper HTTP response, not an exception.  Setting
    # this flag prevents unrelated handler failures (e.g. missing DB) from
    # masking the auth check result.
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.request(method, path)
    assert r.status_code == 401, (
        f"{method} {path} returned {r.status_code}; expected 401. "
        "Did you forget to attach require_authenticated_global to this "
        "router's include_router call?"
    )


PUBLIC_ROUTES = [
    ("GET", "/health"),
    ("GET", "/api/auth/providers"),
    # /api/auth/login and /api/auth/refresh exist but require POST body —
    # we hit them with empty body and accept any non-401 (validation errors
    # are fine, what matters is the auth dep didn't raise).
]


@pytest.mark.parametrize("method,path", PUBLIC_ROUTES)
def test_real_app_public_route_does_not_401(flag_on, method, path):
    app = _build_real_app_anonymous()
    # raise_server_exceptions=False: we only care that the auth baseline dep
    # did not inject a 401; handler errors (e.g. missing auth runtime) are
    # acceptable here.
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.request(method, path)
    assert r.status_code != 401, (
        f"{method} {path} returned 401 but is on the public allowlist"
    )
