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
