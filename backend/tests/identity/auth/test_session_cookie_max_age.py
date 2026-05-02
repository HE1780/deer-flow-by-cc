# backend/tests/identity/auth/test_session_cookie_max_age.py
"""Regression: cookie max_age must equal refresh_ttl_sec, not access_ttl_sec.

Prior bug: _set_session_cookie used access_ttl_sec for max_age, causing the
browser to drop the cookie ~15 min after login. The next request hit
/api/auth/refresh with no cookie → 401 "no session" → frontend modal.
Cookie lifetime must outlive its token so refresh can read sid out of an
expired-but-still-decodable JWT.

See: docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.gateway.identity.auth.passwords import hash_password
from app.gateway.identity.models.user import User


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://t",
        follow_redirects=False,
    )


async def _seed_password_user(app_handle, email: str, password: str) -> int:
    """Insert a User row with a valid password_hash so /api/auth/login succeeds."""
    async with app_handle.runtime.session_maker() as db:
        existing = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name="cookie-test",
            status=1,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    # Membership in default tenant is auto-provisioned by the login path
    # (auto_provision=True on the test runtime), so no extra setup needed.
    return user.id


@pytest.mark.asyncio
async def test_login_cookie_max_age_matches_refresh_ttl(app_handle):
    """Set-Cookie Max-Age must equal refresh_ttl_sec, not access_ttl_sec."""
    email = f"cookie-{uuid.uuid4().hex[:8]}@example.com"
    password = "ChangeMe!2026"
    await _seed_password_user(app_handle, email, password)

    async with _client(app_handle.app) as c:
        r = await c.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
    assert r.status_code == 200, r.text

    set_cookie = r.headers.get("set-cookie", "")
    assert "deerflow_session=" in set_cookie

    refresh_ttl = app_handle.runtime.refresh_ttl_sec
    access_ttl = app_handle.runtime.access_ttl_sec
    assert refresh_ttl != access_ttl, (
        "test runtime must distinguish the two TTLs to be meaningful; "
        f"got refresh={refresh_ttl} access={access_ttl}"
    )

    # Positive assertion: cookie lifetime tracks the Redis session TTL.
    assert f"Max-Age={refresh_ttl}" in set_cookie, set_cookie
    # Negative assertion: defends against re-coupling to access TTL.
    assert f"Max-Age={access_ttl}" not in set_cookie, set_cookie


@pytest.mark.asyncio
async def test_switch_tenant_cookie_max_age_matches_refresh_ttl(app_handle):
    """/api/me/switch-tenant must reuse _set_session_cookie (not its own copy)."""
    # The test app_handle from auth/conftest.py only mounts auth_router. We
    # need me_router for this test, so build a parallel app handle here.
    from fastapi import FastAPI

    from app.gateway.identity.routers import me as me_router_module

    app2 = FastAPI()
    # Re-use the same middleware + runtime as app_handle so the test stays
    # self-contained and doesn't have to re-seed RSA keys, Redis, etc.
    for mw in app_handle.app.user_middleware:
        app2.user_middleware.append(mw)
    app2.include_router(me_router_module.router)

    # Seed a user with membership in two tenants. The auto-provision flag on
    # the runtime makes the first login auto-create one tenant; we add a
    # second one manually so switch-tenant has somewhere to switch to.
    email = f"switch-{uuid.uuid4().hex[:8]}@example.com"
    password = "ChangeMe!2026"
    user_id = await _seed_password_user(app_handle, email, password)

    from app.gateway.identity.models.tenant import Tenant
    from app.gateway.identity.models.user import Membership
    async with app_handle.runtime.session_maker() as db:
        # The login below will auto-provision tenant #1 + membership.
        # Pre-create tenant #2 + membership so switch-tenant can target it.
        t2 = Tenant(slug=f"t2-{uuid.uuid4().hex[:6]}", name="T2")
        db.add(t2)
        await db.flush()
        db.add(Membership(user_id=user_id, tenant_id=t2.id, status=1))
        await db.commit()
        target_tenant_id = t2.id

    # Log in to get a session cookie.
    async with _client(app_handle.app) as c:
        login = await c.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
    assert login.status_code == 200, login.text
    cookie_header = login.headers["set-cookie"]
    # Extract just the deerflow_session=VALUE; pair for the next request.
    session_cookie = cookie_header.split(";", 1)[0]

    # Switch tenant on the second app — passes the cookie manually.
    async with _client(app2) as c:
        r = await c.post(
            "/api/me/switch-tenant",
            json={"tenant_id": target_tenant_id},
            headers={"cookie": session_cookie},
        )
    assert r.status_code == 200, r.text

    set_cookie = r.headers.get("set-cookie", "")
    assert "deerflow_session=" in set_cookie

    refresh_ttl = app_handle.runtime.refresh_ttl_sec
    access_ttl = app_handle.runtime.access_ttl_sec
    assert f"Max-Age={refresh_ttl}" in set_cookie, set_cookie
    assert f"Max-Age={access_ttl}" not in set_cookie, set_cookie
