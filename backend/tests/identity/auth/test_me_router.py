"""Tests for /api/me/* routes (tokens, sessions, switch-tenant, patch)."""

from __future__ import annotations

import asyncio
import uuid
from urllib.parse import parse_qs, urlparse

import bcrypt
import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from alembic import command
from app.gateway.identity.auth.config import OIDCProviderConfig
from app.gateway.identity.auth.lockout import LoginLockout
from app.gateway.identity.auth.oidc import OIDCClient
from app.gateway.identity.auth.runtime import AuthRuntime, clear_runtime, set_runtime
from app.gateway.identity.auth.session import SessionStore
from app.gateway.identity.bootstrap import bootstrap
from app.gateway.identity.middlewares.identity import IdentityMiddleware
from app.gateway.identity.routers import auth as auth_router_module
from app.gateway.identity.routers import me as me_router_module


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


@pytest_asyncio.fixture
async def app_handle(mock_idp, redis_client, fresh_db_seeded):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    prefix = f"test-{uuid.uuid4().hex[:8]}"
    session_store = SessionStore(redis_client, refresh_ttl_sec=3600, key_prefix=prefix)
    lockout = LoginLockout(redis_client, max_attempts=99, window_sec=60, block_sec=60, key_prefix=prefix)
    oidc_cfg = OIDCProviderConfig(
        name="mock",
        issuer=mock_idp.base_url,
        client_id="test-client",
        client_secret="test-secret",
        scopes=["openid", "profile", "email"],
    )
    oidc = OIDCClient(oidc_cfg, redis_client=redis_client, state_ttl_sec=60, key_prefix=prefix)
    runtime = AuthRuntime(
        jwt_private_key_pem=priv_pem,
        jwt_public_key_pem=pub_pem,
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
        auto_provision=True,
    )
    set_runtime(runtime)
    app = FastAPI()
    app.add_middleware(
        IdentityMiddleware,
        public_key_pem=pub_pem,
        session_store=session_store,
        session_maker=fresh_db_seeded,
        issuer="deerflow",
        audience="deerflow-api",
        cookie_name="deerflow_session",
    )
    app.include_router(auth_router_module.router)
    app.include_router(me_router_module.router)
    yield type("H", (), {"app": app, "runtime": runtime, "idp": mock_idp, "prefix": prefix})()
    clear_runtime()
    async for k in redis_client.scan_iter(f"{prefix}:*"):
        await redis_client.delete(k)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", follow_redirects=False)


async def _login(handle, *, email: str, subject: str) -> httpx.AsyncClient:
    handle.idp.idp.set_user(email=email, subject=subject)
    c = _client(handle.app)
    r = await c.get("/api/auth/oidc/mock/login")
    async with httpx.AsyncClient(follow_redirects=False) as ext:
        r2 = await ext.get(r.headers["location"])
    qs = parse_qs(urlparse(r2.headers["location"]).query)
    r3 = await c.get(f"/api/auth/oidc/mock/callback?code={qs['code'][0]}&state={qs['state'][0]}")
    cookie = r3.cookies.get("deerflow_session")
    c.cookies.set("deerflow_session", cookie)
    return c


@pytest.mark.asyncio
async def test_me_requires_auth(app_handle):
    async with _client(app_handle.app) as c:
        r = await c.get("/api/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_profile(app_handle):
    c = await _login(app_handle, email="alice@example.com", subject="alice-sub")
    try:
        r = await c.get("/api/me")
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == "alice@example.com"
        assert body["active_tenant_id"] is not None
        assert len(body["tenants"]) >= 1
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_create_and_list_tokens(app_handle):
    c = await _login(app_handle, email="bob@example.com", subject="bob-sub")
    try:
        create = await c.post("/api/me/tokens", json={"name": "ci", "scopes": ["thread:read"]})
        assert create.status_code == 200
        plaintext = create.json()["plaintext"]
        assert plaintext.startswith("dft_")
        lst = await c.get("/api/me/tokens")
        assert lst.status_code == 200
        items = lst.json()
        assert len(items) == 1
        assert items[0]["name"] == "ci"
        # Plaintext must not leak in list.
        assert "plaintext" not in items[0]
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_cannot_revoke_another_users_token(app_handle):
    c1 = await _login(app_handle, email="x@example.com", subject="x-sub")
    c2 = await _login(app_handle, email="y@example.com", subject="y-sub")
    try:
        r = await c1.post("/api/me/tokens", json={"name": "x", "scopes": []})
        token_id = r.json()["id"]
        # c2 tries to revoke c1's token.
        r2 = await c2.delete(f"/api/me/tokens/{token_id}")
        assert r2.status_code == 403
    finally:
        await c1.aclose()
        await c2.aclose()


@pytest.mark.asyncio
async def test_revoke_own_token(app_handle):
    c = await _login(app_handle, email="z@example.com", subject="z-sub")
    try:
        r = await c.post("/api/me/tokens", json={"name": "mine", "scopes": []})
        tid = r.json()["id"]
        r2 = await c.delete(f"/api/me/tokens/{tid}")
        assert r2.status_code == 200
        r3 = await c.get("/api/me/tokens")
        assert all(item["id"] != tid for item in r3.json())
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_list_and_revoke_session(app_handle):
    c = await _login(app_handle, email="s@example.com", subject="s-sub")
    try:
        r = await c.get("/api/me/sessions")
        assert r.status_code == 200
        sessions = r.json()
        assert len(sessions) == 1
        sid = sessions[0]["sid"]
        r2 = await c.delete(f"/api/me/sessions/{sid}")
        assert r2.status_code == 200
        # Subsequent /me with the same cookie fails (session revoked).
        r3 = await c.get("/api/me")
        assert r3.status_code == 401
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_patch_me_updates_display_name(app_handle):
    c = await _login(app_handle, email="p@example.com", subject="p-sub")
    try:
        r = await c.patch("/api/me", json={"display_name": "Pat"})
        assert r.status_code == 200
        assert r.json()["display_name"] == "Pat"
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_switch_tenant_forbidden_for_non_member(app_handle):
    c = await _login(app_handle, email="q@example.com", subject="q-sub")
    try:
        r = await c.post("/api/me/switch-tenant", json={"tenant_id": 99999})
        assert r.status_code == 403
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_change_password_updates_hash_and_allows_password_login(app_handle):
    email = "pwd-change@example.com"
    old_password = "OldPass!2026"
    new_password = "NewPass!2026"
    c = await _login(app_handle, email=email, subject="pwd-change-sub")
    try:
        # Seed an old password hash for this user.
        async with app_handle.runtime.session_maker() as db:
            from app.gateway.identity.models.user import User

            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one()
            user.password_hash = bcrypt.hashpw(
                old_password.encode(), bcrypt.gensalt()
            ).decode()
            await db.commit()

        bad = await c.post(
            "/api/me/password",
            json={"old_password": "WrongPass!2026", "new_password": new_password},
        )
        assert bad.status_code == 401

        ok = await c.post(
            "/api/me/password",
            json={"old_password": old_password, "new_password": new_password},
        )
        assert ok.status_code == 200

        # Clear session, then password-login with the new password.
        await c.post("/api/auth/logout")
        login = await c.post(
            "/api/auth/login",
            json={"email": email, "password": new_password},
        )
        assert login.status_code == 200
    finally:
        await c.aclose()
