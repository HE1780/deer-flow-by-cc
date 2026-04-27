"""End-to-end tests for /api/auth/* routes.

We stand up a minimal FastAPI app: IdentityMiddleware + auth router with
the full AuthRuntime (real OIDC client pointing at the mock IdP, real
SessionStore on Redis, real JWT keys, real Postgres DB).
"""

from __future__ import annotations

import asyncio
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from alembic import command
from app.gateway.identity.auth.config import OIDCProviderConfig
from app.gateway.identity.auth.lockout import LoginLockout
from app.gateway.identity.auth.oidc import OIDCClient
from app.gateway.identity.auth.runtime import AuthRuntime, clear_runtime, set_runtime
from app.gateway.identity.auth.session import SessionStore
from app.gateway.identity.bootstrap import bootstrap
from app.gateway.identity.middlewares.identity import IdentityMiddleware
from app.gateway.identity.models import User
from app.gateway.identity.routers import auth as auth_router_module


@pytest_asyncio.fixture
async def fresh_db_seeded(pg_url, monkeypatch):
    monkeypatch.setenv("DEERFLOW_DATABASE_URL", pg_url)
    from app.gateway.identity.settings import get_identity_settings

    get_identity_settings.cache_clear()
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(pg_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await bootstrap(s, bootstrap_admin_email=None)
    try:
        yield maker
    finally:
        await engine.dispose()
        await asyncio.to_thread(command.downgrade, cfg, "base")


@pytest_asyncio.fixture
async def redis_client(redis_url):
    import redis.asyncio as aioredis

    c = aioredis.from_url(redis_url, decode_responses=True)
    yield c
    await c.aclose()


@pytest.fixture
def rsa_keys():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    return (
        priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode(),
    )


@pytest_asyncio.fixture
async def app_handle(
    mock_idp,
    rsa_keys,
    redis_client,
    fresh_db_seeded,
):
    priv, pub = rsa_keys
    prefix = f"test-{uuid.uuid4().hex[:8]}"
    session_store = SessionStore(redis_client, refresh_ttl_sec=3600, key_prefix=prefix)
    lockout = LoginLockout(redis_client, max_attempts=3, window_sec=60, block_sec=60, key_prefix=prefix)
    oidc_cfg = OIDCProviderConfig(
        name="mock",
        issuer=mock_idp.base_url,
        client_id="test-client",
        client_secret="test-secret",
        scopes=["openid", "profile", "email"],
    )
    oidc = OIDCClient(oidc_cfg, redis_client=redis_client, state_ttl_sec=60, key_prefix=prefix)
    runtime = AuthRuntime(
        jwt_private_key_pem=priv,
        jwt_public_key_pem=pub,
        issuer="deerflow",
        audience="deerflow-api",
        access_ttl_sec=900,
        refresh_ttl_sec=3600,
        cookie_name="deerflow_session",
        cookie_secure=False,
        oidc_clients={"mock": oidc},
        session_store=session_store,
        lockout=lockout,
        redis_client=redis_client,
        session_maker=fresh_db_seeded,
        auto_provision=True,  # so OIDC callback succeeds without prior membership
    )
    set_runtime(runtime)

    app = FastAPI()
    app.add_middleware(
        IdentityMiddleware,
        public_key_pem=pub,
        session_store=session_store,
        session_maker=fresh_db_seeded,
        issuer="deerflow",
        audience="deerflow-api",
        cookie_name="deerflow_session",
    )
    app.include_router(auth_router_module.router)

    yield type("H", (), {"app": app, "runtime": runtime, "idp": mock_idp, "prefix": prefix})()

    clear_runtime()
    async for k in redis_client.scan_iter(f"{prefix}:*"):
        await redis_client.delete(k)


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
