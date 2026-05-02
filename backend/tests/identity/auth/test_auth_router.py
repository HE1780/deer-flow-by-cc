"""End-to-end tests for /api/auth/* routes.

We stand up a minimal FastAPI app: IdentityMiddleware + auth router with
the full AuthRuntime (real OIDC client pointing at the mock IdP, real
SessionStore on Redis, real JWT keys, real Postgres DB).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.gateway.identity.models import User


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", follow_redirects=False)


@pytest.mark.asyncio
async def test_login_redirects_to_idp(app_handle):
    async with _client(app_handle.app) as c:
        r = await c.get("/api/auth/oidc/mock/login")
    assert r.status_code == 302
    loc = r.headers["location"]
    assert app_handle.idp.base_url in loc
    assert "state=" in loc
    assert "code_challenge=" in loc


@pytest.mark.asyncio
async def test_login_unknown_provider_404(app_handle):
    async with _client(app_handle.app) as c:
        r = await c.get("/api/auth/oidc/nope/login")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_full_oidc_flow_sets_cookie(app_handle):
    """login → IdP authorize → callback → cookie set."""
    app_handle.idp.idp.set_user(email="alice@example.com", subject="alice-sub")
    async with _client(app_handle.app) as c:
        r = await c.get("/api/auth/oidc/mock/login")
        authorize_url = r.headers["location"]

    # Visit IdP /authorize — it 302s to our callback with ?code=&state=
    async with httpx.AsyncClient(follow_redirects=False) as ext:
        r = await ext.get(authorize_url)
    callback_url = r.headers["location"]
    parsed = urlparse(callback_url)
    qs = parse_qs(parsed.query)

    async with _client(app_handle.app) as c:
        r = await c.get(f"/api/auth/oidc/mock/callback?code={qs['code'][0]}&state={qs['state'][0]}")
    assert r.status_code == 302
    assert "deerflow_session" in r.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_callback_with_tampered_state_redirects_to_login_error(app_handle):
    async with _client(app_handle.app) as c:
        r = await c.get("/api/auth/oidc/mock/callback?code=x&state=bogus")
    assert r.status_code == 302
    assert "error=oidc_callback_failed" in r.headers["location"]


@pytest.mark.asyncio
async def test_refresh_with_valid_session(app_handle):
    """Create a session directly + cookie; refresh returns a new token."""
    app_handle.idp.idp.set_user(email="bob@example.com", subject="bob-sub")
    # Drive full flow to get a real cookie.
    async with _client(app_handle.app) as c:
        r = await c.get("/api/auth/oidc/mock/login")
        authorize_url = r.headers["location"]

    async with httpx.AsyncClient(follow_redirects=False) as ext:
        r = await ext.get(authorize_url)
    cb = urlparse(r.headers["location"])
    qs = parse_qs(cb.query)

    async with _client(app_handle.app) as c:
        r = await c.get(f"/api/auth/oidc/mock/callback?code={qs['code'][0]}&state={qs['state'][0]}")
        cookie = r.cookies.get("deerflow_session")
        assert cookie
        c.cookies.set("deerflow_session", cookie)
        r2 = await c.post("/api/auth/refresh")

    assert r2.status_code == 200
    assert r2.json()["token_type"] == "Bearer"
    assert r2.json()["access_token"]


@pytest.mark.asyncio
async def test_refresh_without_cookie_returns_401(app_handle):
    async with _client(app_handle.app) as c:
        r = await c.post("/api/auth/refresh")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_session(app_handle):
    app_handle.idp.idp.set_user(email="carol@example.com", subject="carol-sub")
    async with _client(app_handle.app) as c:
        r = await c.get("/api/auth/oidc/mock/login")
        authorize_url = r.headers["location"]
    async with httpx.AsyncClient(follow_redirects=False) as ext:
        r = await ext.get(authorize_url)
    qs = parse_qs(urlparse(r.headers["location"]).query)
    async with _client(app_handle.app) as c:
        r = await c.get(f"/api/auth/oidc/mock/callback?code={qs['code'][0]}&state={qs['state'][0]}")
        cookie = r.cookies.get("deerflow_session")
        c.cookies.set("deerflow_session", cookie)
        r2 = await c.post("/api/auth/logout")
        assert r2.status_code == 200
        # Subsequent refresh fails — session revoked.
        r3 = await c.post("/api/auth/refresh")
        assert r3.status_code == 401


@pytest.mark.asyncio
async def test_lockout_after_repeated_callback_failures(app_handle):
    """3 bad callbacks from same IP → 429 on 4th."""
    async with _client(app_handle.app) as c:
        for _ in range(3):
            r = await c.get("/api/auth/oidc/mock/callback?code=x&state=bogus")
            assert r.status_code == 302  # soft-fail redirect
        r = await c.get("/api/auth/oidc/mock/callback?code=x&state=bogus")
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_set_password_supports_bootstrap_token_without_session(
    app_handle, monkeypatch
):
    monkeypatch.setenv("DEERFLOW_BOOTSTRAP_ADMIN_EMAIL", "bootstrap-admin@example.com")
    monkeypatch.setenv("DEERFLOW_BOOTSTRAP_PASSWORD_TOKEN", "bootstrap-secret")
    from app.gateway.identity.settings import get_identity_settings

    get_identity_settings.cache_clear()

    async with app_handle.runtime.session_maker() as db:
        db.add(
            User(
                email="bootstrap-admin@example.com",
                display_name="bootstrap-admin",
                status=1,
            )
        )
        await db.commit()

    async with _client(app_handle.app) as c:
        r = await c.post(
            "/api/auth/set-password",
            json={
                "email": "bootstrap-admin@example.com",
                "password": "ChangeMe!2026",
                "bootstrap_token": "bootstrap-secret",
            },
        )
        assert r.status_code == 200, r.text

        login = await c.post(
            "/api/auth/login",
            json={
                "email": "bootstrap-admin@example.com",
                "password": "ChangeMe!2026",
            },
        )
        assert login.status_code == 200, login.text
