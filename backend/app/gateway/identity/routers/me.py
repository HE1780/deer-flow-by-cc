"""/api/me routes: current user, tenant switch, own tokens + sessions."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.gateway.identity.auth.api_token import (
    create_api_token,
    revoke_api_token,
)
from app.gateway.identity.auth.dependencies import require_authenticated
from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.auth.identity_factory import build_identity_for_user
from app.gateway.identity.auth.passwords import hash_password, verify_password
from app.gateway.identity.auth.runtime import get_runtime
from app.gateway.identity.models.tenant import Tenant, Workspace
from app.gateway.identity.models.token import ApiToken
from app.gateway.identity.models.user import Membership, User

router = APIRouter(prefix="/api/me", tags=["identity"])


# --- Schemas ---


class MeResponse(BaseModel):
    user_id: int
    email: str | None
    display_name: str | None
    avatar_url: str | None
    active_tenant_id: int | None
    tenants: list[dict]
    workspaces: list[dict]
    permissions: list[str]
    roles: dict


class SwitchTenantIn(BaseModel):
    tenant_id: int


class TokenListItem(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: list[str]
    workspace_id: int | None
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class CreateTokenIn(BaseModel):
    name: str
    scopes: list[str]
    workspace_id: int | None = None
    expires_at: datetime | None = None


class CreateTokenOut(BaseModel):
    id: int
    plaintext: str
    prefix: str


class SessionListItem(BaseModel):
    sid: str
    created_at: datetime
    ip: str | None
    user_agent: str | None


class PatchMeIn(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


# --- Routes ---


@router.get("", response_model=MeResponse)
async def me(identity: Identity = Depends(require_authenticated)):
    rt = get_runtime()
    async with rt.session_maker() as db:
        user = (await db.execute(select(User).where(User.id == identity.user_id))).scalar_one()
        memberships = (await db.execute(select(Tenant).join(Membership, Membership.tenant_id == Tenant.id).where(Membership.user_id == identity.user_id, Membership.status == 1).order_by(Tenant.slug))).scalars().all()
        workspaces = (await db.execute(select(Workspace).where(Workspace.tenant_id == identity.tenant_id) if identity.tenant_id else select(Workspace).where(False))).scalars().all()

    return MeResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        active_tenant_id=identity.tenant_id,
        tenants=[{"id": t.id, "slug": t.slug, "name": t.name} for t in memberships],
        workspaces=[{"id": w.id, "slug": w.slug, "name": w.name} for w in workspaces],
        permissions=sorted(identity.permissions),
        roles=identity.roles,
    )


@router.patch("", response_model=MeResponse)
async def patch_me(body: PatchMeIn, identity: Identity = Depends(require_authenticated)):
    """Update basic profile fields for the current authenticated user."""
    rt = get_runtime()
    async with rt.session_maker() as db:
        user = (await db.execute(select(User).where(User.id == identity.user_id))).scalar_one()
        if body.display_name is not None:
            user.display_name = body.display_name
        if body.avatar_url is not None:
            user.avatar_url = body.avatar_url
        await db.commit()
    return await me(identity=identity)


@router.post("/password")
async def change_password(
    body: ChangePasswordIn,
    identity: Identity = Depends(require_authenticated),
):
    """Change the current user's password after validating the old password."""
    if len(body.new_password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "new_password must be at least 8 characters")

    rt = get_runtime()
    async with rt.session_maker() as db:
        user = (await db.execute(select(User).where(User.id == identity.user_id))).scalar_one()
        if not user.password_hash:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "password login not initialized for this user")
        if not verify_password(body.old_password, user.password_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "old password is incorrect")

        user.password_hash = hash_password(body.new_password)
        await db.commit()
    return {"status": "ok"}


@router.post("/switch-tenant")
async def switch_tenant(
    body: SwitchTenantIn,
    request: Request,
    response: Response,
    identity: Identity = Depends(require_authenticated),
):
    rt = get_runtime()
    async with rt.session_maker() as db:
        # Verify membership.
        q = select(Membership).where(
            Membership.user_id == identity.user_id,
            Membership.tenant_id == body.tenant_id,
            Membership.status == 1,
        )
        if (await db.execute(q)).scalar_one_or_none() is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not a member of this tenant")
        tenant = (await db.execute(select(Tenant).where(Tenant.id == body.tenant_id))).scalar_one()
        ws = (await db.execute(select(Workspace).where(Workspace.tenant_id == tenant.id).order_by(Workspace.slug))).scalars().first()
        user = (await db.execute(select(User).where(User.id == identity.user_id))).scalar_one()
        new_identity = await build_identity_for_user(db, user, tenant, ws)

    # Update session's tenant and re-issue access token (same sid).
    if identity.session_id:
        await rt.session_store.update_tenant(identity.session_id, tenant.id)

    # Re-issue token using the shared helper so cookie attributes (esp.
    # max_age) stay aligned with /api/auth/login. Helper imports are local
    # to avoid a circular dependency between me.py and auth.py.
    from app.gateway.identity.routers.auth import _issue_access_for, _set_session_cookie

    new_token = _issue_access_for(new_identity, identity.session_id or "")
    _set_session_cookie(response, new_token)
    return {"access_token": new_token, "token_type": "Bearer", "expires_in": rt.access_ttl_sec}


@router.get("/tokens", response_model=list[TokenListItem])
async def list_tokens(identity: Identity = Depends(require_authenticated)):
    rt = get_runtime()
    async with rt.session_maker() as db:
        rows = (await db.execute(select(ApiToken).where(ApiToken.user_id == identity.user_id, ApiToken.revoked_at.is_(None)).order_by(ApiToken.created_at.desc()))).scalars().all()
    return [
        TokenListItem(
            id=r.id,
            name=r.name,
            prefix=r.prefix,
            scopes=list(r.scopes or []),
            workspace_id=r.workspace_id,
            created_at=r.created_at,
            expires_at=r.expires_at,
            last_used_at=r.last_used_at,
        )
        for r in rows
    ]


@router.post("/tokens", response_model=CreateTokenOut)
async def create_token(body: CreateTokenIn, identity: Identity = Depends(require_authenticated)):
    rt = get_runtime()
    if identity.tenant_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no active tenant")
    async with rt.session_maker() as db:
        created = await create_api_token(
            db,
            user_id=identity.user_id,
            tenant_id=identity.tenant_id,
            workspace_id=body.workspace_id,
            name=body.name,
            scopes=body.scopes,
            expires_at=body.expires_at,
            created_by=identity.user_id,
        )
    return CreateTokenOut(id=created.token_id, plaintext=created.plaintext, prefix=created.prefix)


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: int, identity: Identity = Depends(require_authenticated)):
    rt = get_runtime()
    async with rt.session_maker() as db:
        row = (await db.execute(select(ApiToken).where(ApiToken.id == token_id))).scalar_one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
        if row.user_id != identity.user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot revoke another user's token")
        await revoke_api_token(db, token_id=token_id, by_user_id=identity.user_id)
    return {"status": "revoked"}


@router.get("/sessions", response_model=list[SessionListItem])
async def list_sessions(identity: Identity = Depends(require_authenticated)):
    rt = get_runtime()
    records = await rt.session_store.list_for_user(identity.user_id)
    return [SessionListItem(sid=r.sid, created_at=r.created_at, ip=r.ip, user_agent=r.user_agent) for r in records]


@router.delete("/sessions/{sid}")
async def revoke_session(sid: str, identity: Identity = Depends(require_authenticated)):
    rt = get_runtime()
    rec = await rt.session_store.get(sid)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if rec.user_id != identity.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot revoke another user's session")
    await rt.session_store.revoke(sid)
    return {"status": "revoked"}
