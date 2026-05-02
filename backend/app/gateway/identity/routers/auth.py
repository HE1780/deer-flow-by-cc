"""/api/auth/* routes: OIDC login / callback, password login, refresh, logout."""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.identity.auth.identity_factory import (
    build_identity_for_user,
    resolve_active_tenant,
    upsert_oidc_user,
)
from app.gateway.identity.auth.jwt import (
    AccessTokenClaims,
    decode_claims_insecure,
    generate_refresh_token,
    issue_access_token,
)
from app.gateway.identity.auth.oidc import (
    NonceMismatchError,
    StateExpiredError,
    StateMismatchError,
)
from app.gateway.identity.auth.passwords import hash_password, verify_password
from app.gateway.identity.auth.runtime import get_runtime
from app.gateway.identity.db import get_session
from app.gateway.identity.models.registration_code import RegistrationCode
from app.gateway.identity.models.role import Role
from app.gateway.identity.models.tenant import Workspace
from app.gateway.identity.models.user import Membership, User, WorkspaceMember
from app.gateway.identity.validators import EMAIL_RE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["identity"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.get("/oidc/{provider}/login")
async def oidc_login(provider: str, request: Request, next: str | None = None):
    rt = get_runtime()
    client = rt.oidc_clients.get(provider)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown provider: {provider}")
    redirect_uri = str(request.url_for("oidc_callback", provider=provider))
    url = await client.login_redirect(redirect_uri=redirect_uri, next_url=next)
    return RedirectResponse(url, status_code=302)


@router.get("/oidc/{provider}/callback", name="oidc_callback")
async def oidc_callback(provider: str, code: str, state: str, request: Request):
    rt = get_runtime()
    client = rt.oidc_clients.get(provider)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown provider: {provider}")

    # Lockout keyed on IP for the OIDC path (email unknown pre-callback).
    ip = _client_ip(request)
    if ip and await rt.lockout.is_blocked(ip=ip, email="_oidc_"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many failed login attempts")

    redirect_uri = str(request.url.replace(query=""))
    try:
        info = await client.handle_callback(code=code, state=state, redirect_uri=redirect_uri)
    except (StateMismatchError, StateExpiredError, NonceMismatchError) as e:
        if ip:
            await rt.lockout.record_failure(ip=ip, email="_oidc_")
        logger.info("oidc callback failed: %s", e)
        return RedirectResponse("/login?error=oidc_callback_failed", status_code=302)
    except Exception:
        if ip:
            await rt.lockout.record_failure(ip=ip, email="_oidc_")
        logger.exception("oidc callback crashed")
        return RedirectResponse("/login?error=oidc_callback_failed", status_code=302)

    # Upsert + first-login policy.
    async with rt.session_maker() as db:
        user = await upsert_oidc_user(db, info)
        await db.commit()
        tenant, workspace = await resolve_active_tenant(db, user, auto_provision=rt.auto_provision)
        if tenant is None:
            return RedirectResponse("/login?error=no_membership", status_code=302)
        await db.commit()
        identity = await build_identity_for_user(db, user, tenant, workspace)

    # Session + tokens.
    refresh = generate_refresh_token()
    sess = await rt.session_store.create(
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        refresh_token=refresh,
        ip=ip,
        ua=_user_agent(request),
    )

    access_token = _issue_access_for(identity, sess.sid)

    # Successful login clears the lockout counter.
    if ip:
        await rt.lockout.clear(ip=ip, email="_oidc_")

    # Redirect to next_url if we stashed one; else root.
    response = RedirectResponse("/", status_code=302)
    _set_session_cookie(response, access_token)
    return response


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    rt = get_runtime()
    token = _read_current_access_token(request, rt.cookie_name)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no session")
    try:
        raw_claims = decode_claims_insecure(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    sid = raw_claims.get("sid")
    if not sid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")

    sess = await rt.session_store.get(sid)
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")

    # Build a fresh access token with the same claims.
    now = int(time.time())
    claims = AccessTokenClaims(
        sub=str(raw_claims["sub"]),
        email=str(raw_claims.get("email", "")),
        tid=raw_claims.get("tid"),
        wids=list(raw_claims.get("wids", [])),
        permissions=list(raw_claims.get("permissions", [])),
        roles=dict(raw_claims.get("roles", {})),
        sid=sid,
        iat=now,
        exp=now + rt.access_ttl_sec,
        iss=rt.issuer,
        aud=rt.audience,
    )
    new_token = issue_access_token(claims, private_key_pem=rt.jwt_private_key_pem)
    _set_session_cookie(response, new_token)
    return {"access_token": new_token, "token_type": "Bearer", "expires_in": rt.access_ttl_sec}


@router.post("/logout")
async def logout(request: Request, response: Response):
    rt = get_runtime()
    token = _read_current_access_token(request, rt.cookie_name)
    if token:
        try:
            raw = decode_claims_insecure(token)
            sid = raw.get("sid")
            if sid:
                await rt.session_store.revoke(sid)
        except Exception:
            pass
    response.delete_cookie(rt.cookie_name, path="/")
    return {"status": "ok"}


class PasswordLoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
async def password_login(body: PasswordLoginIn, request: Request, response: Response):
    """Email + password login. Only works for users with a password_hash set."""
    rt = get_runtime()
    ip = _client_ip(request)
    email = body.email.strip().lower()

    if ip and await rt.lockout.is_blocked(ip=ip, email=email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many failed login attempts")

    async with rt.session_maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    invalid = user is None or not user.password_hash or user.status != 1
    if not invalid:
        invalid = not verify_password(body.password, user.password_hash)

    if invalid:
        if ip:
            await rt.lockout.record_failure(ip=ip, email=email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")

    async with rt.session_maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        tenant, workspace = await resolve_active_tenant(db, user, auto_provision=rt.auto_provision)
        if tenant is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "no_membership")
        await db.commit()
        identity = await build_identity_for_user(db, user, tenant, workspace)

    refresh = generate_refresh_token()
    sess = await rt.session_store.create(
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        refresh_token=refresh,
        ip=ip,
        ua=_user_agent(request),
    )
    access_token = _issue_access_for(identity, sess.sid)

    if ip:
        await rt.lockout.clear(ip=ip, email=email)

    _set_session_cookie(response, access_token)
    return {"status": "ok"}


class RegisterIn(BaseModel):
    code: str
    email: str
    password: str
    display_name: str | None = None


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    rt = get_runtime()

    # Input validation -----------------------------------------------------
    if len(body.password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "password must be at least 8 characters")
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid email format")

    # Find candidate codes by prefix + pending. -----------------------------
    prefix = body.code[:8]
    candidates = (
        await session.execute(
            select(RegistrationCode).where(
                RegistrationCode.code_prefix == prefix,
                RegistrationCode.status == 0,
            )
        )
    ).scalars().all()

    rc = None
    for cand in candidates:
        if verify_password(body.code, cand.code_hash):
            rc = cand
            break
    if rc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invalid registration code")

    # Status transitions ---------------------------------------------------
    now = datetime.now(UTC)
    if rc.expires_at < now:
        rc.status = 2
        await session.commit()
        raise HTTPException(status.HTTP_410_GONE, "code has expired")

    # Email uniqueness (DB unique acts as the concurrency tiebreaker). -----
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")

    # Default workspace + workspace_member role lookup ---------------------
    ws = (
        await session.execute(
            select(Workspace)
            .where(Workspace.tenant_id == rc.tenant_id)
            .order_by(Workspace.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if ws is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "tenant has no default workspace")

    member_role = (
        await session.execute(
            select(Role).where(Role.role_key == "workspace_member", Role.scope == "workspace")
        )
    ).scalar_one_or_none()
    if member_role is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "workspace_member role not seeded")

    # Create user + membership + workspace member; mark code accepted. -----
    password_hash = hash_password(body.password)
    user = User(
        email=email,
        display_name=body.display_name or email.split("@")[0],
        status=1,
        password_hash=password_hash,
    )
    session.add(user)
    await session.flush()

    session.add(Membership(user_id=user.id, tenant_id=rc.tenant_id, status=1))
    session.add(WorkspaceMember(user_id=user.id, workspace_id=ws.id, role_id=member_role.id))

    rc.status = 1
    rc.accepted_by = user.id
    rc.accepted_at = now

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from None

    # Build identity → session → cookie. -----------------------------------
    tenant, workspace = await resolve_active_tenant(session, user, auto_provision=rt.auto_provision)
    identity = await build_identity_for_user(session, user, tenant, workspace)

    sess = await rt.session_store.create(
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        refresh_token=generate_refresh_token(),
        ip=_client_ip(request),
        ua=_user_agent(request),
    )
    access_token = _issue_access_for(identity, sess.sid)
    _set_session_cookie(response, access_token)
    return {"status": "ok", "email": email}


class SetPasswordIn(BaseModel):
    email: str
    password: str
    bootstrap_token: str | None = None


@router.post("/set-password")
async def set_password(body: SetPasswordIn, request: Request):
    """Set or update a user's password.

    Normal mode requires an authenticated ``platform_admin``.
    Bootstrap mode (no session) is allowed only for the configured bootstrap
    admin email and a matching ``DEERFLOW_BOOTSTRAP_PASSWORD_TOKEN``.
    """
    identity = getattr(request.state, "identity", None)
    email = body.email.strip().lower()
    if len(body.password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "password must be at least 8 characters")

    bootstrap_allowed = await _allow_bootstrap_password_init(identity, email, body.bootstrap_token)
    if not bootstrap_allowed:
        if identity is None or not identity.is_authenticated:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
        if "platform_admin" not in identity.roles.get("platform", []):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "platform_admin required")

    hashed = hash_password(body.password)

    rt = get_runtime()
    async with rt.session_maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {email!r} not found")
        if bootstrap_allowed and user.password_hash:
            raise HTTPException(status.HTTP_409_CONFLICT, "bootstrap password already initialized")
        user.password_hash = hashed
        await db.commit()

    return {"status": "ok"}


@router.get("/providers")
async def list_providers():
    """Return configured OIDC providers for the login page button list."""
    rt = get_runtime()
    return {
        "providers": [
            {
                "id": pid,
                "display_name": getattr(client, "display_name", pid.title()),
                "icon_url": getattr(client, "icon_url", None),
            }
            for pid, client in rt.oidc_clients.items()
        ]
    }


# --- helpers ---


def _issue_access_for(identity, sid: str) -> str:
    rt = get_runtime()
    now = int(time.time())
    claims = AccessTokenClaims(
        sub=str(identity.user_id),
        email=identity.email or "",
        tid=identity.tenant_id,
        wids=list(identity.workspace_ids),
        permissions=sorted(identity.permissions),
        roles=identity.roles,
        sid=sid,
        iat=now,
        exp=now + rt.access_ttl_sec,
        iss=rt.issuer,
        aud=rt.audience,
    )
    return issue_access_token(claims, private_key_pem=rt.jwt_private_key_pem)


def _set_session_cookie(response: Response, access_token: str) -> None:
    """Stamp the access token onto the response as the session cookie.

    Cookie lifetime intentionally tracks the Redis session TTL (refresh
    window), NOT the access-token TTL. Browser-side cookie expiry would
    otherwise force a re-login as soon as the access token rolls over:
    /api/auth/refresh reads sid out of the (possibly-expired-but-still-
    decodable) cookie, so the cookie must outlive its token. Backend
    security is unchanged - every request still re-verifies the JWT
    signature and checks sid in Redis.

    See: docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md
    """
    rt = get_runtime()
    response.set_cookie(
        rt.cookie_name,
        access_token,
        httponly=True,
        secure=rt.cookie_secure,
        samesite="lax",
        max_age=rt.refresh_ttl_sec,
        path="/",
    )


def _read_current_access_token(request: Request, cookie_name: str) -> str | None:
    cookie = request.cookies.get(cookie_name)
    if cookie:
        return cookie
    auth = request.headers.get("Authorization", "")
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and not parts[1].startswith("dft_"):
        return parts[1]
    return None


async def _allow_bootstrap_password_init(identity, email: str, bootstrap_token: str | None) -> bool:
    """Return True when a no-session bootstrap password initialization is allowed."""
    if identity is not None and identity.is_authenticated:
        return False

    from app.gateway.identity.settings import get_identity_settings

    settings = get_identity_settings()
    bootstrap_email = (settings.bootstrap_admin_email or "").strip().lower()
    if not bootstrap_email or email != bootstrap_email:
        return False

    expected_token = os.environ.get("DEERFLOW_BOOTSTRAP_PASSWORD_TOKEN", "").strip()
    if not expected_token or not bootstrap_token or bootstrap_token != expected_token:
        return False

    return True
