"""Shared fixtures for /auth route tests.

Provides:
  - mock_idp      — in-process mock OIDC provider (session-scoped)
  - rsa_keys      — fresh RS256 key pair per test
  - redis_client  — per-test aioredis client
  - fresh_db_seeded — per-test Postgres with migrations applied
  - app_handle    — minimal FastAPI app with IdentityMiddleware + auth router
"""

from __future__ import annotations

import asyncio
import base64
import secrets
import socket
import threading
import time
import uuid

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
import uvicorn
from alembic.config import Config
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from jose import jwt as jose_jwt
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.gateway.identity.auth.config import OIDCProviderConfig
from app.gateway.identity.auth.lockout import LoginLockout
from app.gateway.identity.auth.oidc import OIDCClient
from app.gateway.identity.auth.runtime import AuthRuntime, clear_runtime, set_runtime
from app.gateway.identity.auth.session import SessionStore
from app.gateway.identity.bootstrap import bootstrap
from app.gateway.identity.middlewares.identity import IdentityMiddleware
from app.gateway.identity.routers import auth as auth_router_module
from app.gateway.identity.settings import get_identity_settings


def _b64url_uint(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).decode().rstrip("=")


class _MockIdP:
    def __init__(self) -> None:
        self.priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        self.priv_pem = self.priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        pub_numbers = self.priv.public_key().public_numbers()
        self.kid = "mock-kid"
        self.jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self.kid,
                    "n": _b64url_uint(pub_numbers.n),
                    "e": _b64url_uint(pub_numbers.e),
                }
            ]
        }
        # Code → metadata from /authorize (so /token can verify nonce).
        self.codes: dict[str, dict] = {}
        # Behavior flags tests can flip
        self.email = "user@mock.com"
        self.subject = "mock-sub-123"

    def set_user(self, *, email: str, subject: str = "mock-sub-123") -> None:
        self.email = email
        self.subject = subject


def _build_app(idp: _MockIdP, base_url_ref: list[str]) -> FastAPI:
    app = FastAPI()

    @app.get("/.well-known/openid-configuration")
    def discovery():
        base = base_url_ref[0]
        return {
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "jwks_uri": f"{base}/.well-known/jwks.json",
            "id_token_signing_alg_values_supported": ["RS256"],
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "scopes_supported": ["openid", "profile", "email"],
        }

    @app.get("/.well-known/jwks.json")
    def jwks():
        return idp.jwks

    @app.get("/authorize")
    def authorize(
        client_id: str = Query(...),
        redirect_uri: str = Query(...),
        state: str = Query(...),
        nonce: str | None = Query(default=None),
        response_type: str = Query("code"),
        scope: str = Query("openid"),
        code_challenge: str | None = Query(default=None),
        code_challenge_method: str | None = Query(default=None),
    ):
        code = secrets.token_urlsafe(16)
        idp.codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }
        return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", status_code=302)

    @app.post("/token")
    def token(
        grant_type: str = Form(...),
        code: str = Form(...),
        redirect_uri: str = Form(...),
        client_id: str = Form(...),
        client_secret: str | None = Form(default=None),
        code_verifier: str | None = Form(default=None),
    ):
        meta = idp.codes.pop(code, None)
        if meta is None:
            raise HTTPException(400, "invalid code")
        if meta["client_id"] != client_id:
            raise HTTPException(400, "client mismatch")
        if meta["redirect_uri"] != redirect_uri:
            raise HTTPException(400, "redirect mismatch")
        # Issue an id_token.
        base = base_url_ref[0]
        now = int(time.time())
        claims = {
            "iss": base,
            "sub": idp.subject,
            "aud": client_id,
            "iat": now,
            "exp": now + 300,
            "email": idp.email,
            "name": idp.email.split("@")[0],
        }
        if meta["nonce"]:
            claims["nonce"] = meta["nonce"]
        id_token = jose_jwt.encode(claims, idp.priv_pem, algorithm="RS256", headers={"kid": idp.kid})
        return JSONResponse(
            {
                "access_token": "mock-access-token",
                "token_type": "Bearer",
                "expires_in": 300,
                "id_token": id_token,
            }
        )

    return app


class _ServerThread(threading.Thread):
    def __init__(self, app: FastAPI, port: int) -> None:
        super().__init__(daemon=True)
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(self.config)

    def run(self) -> None:
        self.server.run()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def mock_idp():
    idp = _MockIdP()
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    ref = [base_url]
    app = _build_app(idp, ref)
    thread = _ServerThread(app, port)
    thread.start()
    # Wait for server to be ready.
    for _ in range(50):
        try:
            httpx.get(f"{base_url}/.well-known/openid-configuration", timeout=0.2)
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("mock IdP did not start")
    yield type("IdPHandle", (), {"base_url": base_url, "idp": idp})()
    thread.server.should_exit = True
    thread.join(timeout=2)


# ---------------------------------------------------------------------------
# Per-test auth runtime fixtures (promoted from test_auth_router.py)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fresh_db_seeded(pg_url, monkeypatch):
    monkeypatch.setenv("DEERFLOW_DATABASE_URL", pg_url)
    get_identity_settings.cache_clear()
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
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
