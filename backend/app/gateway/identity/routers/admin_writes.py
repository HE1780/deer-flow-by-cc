"""Admin write endpoints (M7 A3).

These complement ``routers/admin.py`` (read-only) and ``routers/me.py``
(self-service). They are scoped to tenant_owner / platform_admin via
``@requires(...)`` and enforce cross-tenant safety inline.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func as sql_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.identity.auth.api_token import create_api_token, revoke_api_token
from app.gateway.identity.auth.passwords import hash_password
from app.gateway.identity.db import get_session
from app.gateway.identity.models import (
    ApiToken,
    Membership,
    RegistrationCode,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceMember,
)
from app.gateway.identity.rbac.decorator import requires
from app.gateway.identity.settings import get_identity_settings
from app.gateway.identity.validators import EMAIL_RE

router = APIRouter(tags=["identity-admin-writes"])


# --- Schemas ---------------------------------------------------------------


class CreateUserIn(BaseModel):
    email: str
    display_name: str | None = None
    initial_password: str | None = None

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError("invalid email format")
        return v

    @field_validator("initial_password")
    @classmethod
    def _password_shape(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if len(v) < 8:
            raise ValueError("initial_password must be at least 8 characters")
        return v


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str | None
    avatar_url: str | None
    status: int
    last_login_at: str | None


class AddWorkspaceMemberIn(BaseModel):
    user_id: int
    role: str  # role_key, must be a workspace-scoped role


class PatchWorkspaceMemberIn(BaseModel):
    role: str


class WorkspaceMemberOut(BaseModel):
    id: int
    email: str
    display_name: str | None
    avatar_url: str | None
    status: int
    role: str
    joined_at: str | None = None


class CreateTenantTokenIn(BaseModel):
    name: str
    scopes: list[str]
    user_id: int  # Whose token this is. Must be a tenant member.
    workspace_id: int | None = None
    expires_at: datetime | None = None


class CreateTokenOut(BaseModel):
    id: int
    plaintext: str
    prefix: str


class CreateRegistrationCodeOut(BaseModel):
    id: int
    tenant_id: int
    code: str  # plaintext, returned once
    code_prefix: str
    expires_at: datetime
    created_at: datetime


class RegistrationCodeOut(BaseModel):
    id: int
    tenant_id: int
    code_prefix: str
    status: int
    expires_at: datetime
    accepted_by: int | None
    accepted_at: datetime | None
    created_at: datetime


class RegistrationCodeListOut(BaseModel):
    items: list[RegistrationCodeOut]
    total: int


# --- Helpers ---------------------------------------------------------------


def _user_out(u: User | Any) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        avatar_url=u.avatar_url,
        status=u.status,
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
    )


def _caller_user_id(request: Request) -> int:
    identity = getattr(request.state, "identity", None)
    if identity is None or identity.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthenticated")
    return identity.user_id


# --- Routes ----------------------------------------------------------------


@router.post(
    "/api/tenants/{tid}/users",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires("membership:invite", "tenant"))],
    response_model=UserOut,
)
async def create_user(
    tid: int,
    body: CreateUserIn,
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    """Create (or attach) a user and add them to the tenant.

    Idempotency: if a user with the same email exists, reuse the row and just
    add the membership. If they're already a member, return 409.
    """
    existing = (await session.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if existing is None:
        password_hash = None
        if body.initial_password:
            password_hash = hash_password(body.initial_password)
        user = User(
            email=body.email,
            display_name=body.display_name or body.email.split("@")[0],
            status=1,
            password_hash=password_hash,
        )
        session.add(user)
        await session.flush()
    else:
        user = existing

    member_existing = (
        await session.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.tenant_id == tid,
            )
        )
    ).scalar_one_or_none()
    if member_existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "user is already a member of this tenant",
        )

    session.add(Membership(user_id=user.id, tenant_id=tid))
    await session.commit()
    return _user_out(user)


def _resolve_workspace(session_result, tid: int) -> Workspace:
    ws = session_result.scalar_one_or_none()
    if ws is None or ws.tenant_id != tid:
        # Generic 404 — never leak whether a workspace exists in another tenant.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
    return ws


@router.post(
    "/api/tenants/{tid}/workspaces/{wid}/members",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires("membership:invite", "tenant"))],
    response_model=WorkspaceMemberOut,
)
async def add_workspace_member(
    tid: int,
    wid: int,
    body: AddWorkspaceMemberIn,
    session: AsyncSession = Depends(get_session),
) -> WorkspaceMemberOut:
    ws = _resolve_workspace(
        await session.execute(select(Workspace).where(Workspace.id == wid)),
        tid,
    )
    user = (await session.execute(select(User).where(User.id == body.user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    membership = (await session.execute(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tid))).scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "user is not a member of this tenant",
        )

    role = (await session.execute(select(Role).where(Role.role_key == body.role, Role.scope == "workspace"))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown workspace role")

    existing_member = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing_member is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "user is already a workspace member",
        )

    session.add(
        WorkspaceMember(
            user_id=user.id,
            workspace_id=ws.id,
            role_id=role.id,
        )
    )
    await session.commit()
    return WorkspaceMemberOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        status=user.status,
        role=role.role_key,
    )


@router.patch(
    "/api/tenants/{tid}/workspaces/{wid}/members/{uid}",
    dependencies=[Depends(requires("membership:invite", "tenant"))],
    response_model=WorkspaceMemberOut,
)
async def patch_workspace_member(
    tid: int,
    wid: int,
    uid: int,
    body: PatchWorkspaceMemberIn,
    session: AsyncSession = Depends(get_session),
) -> WorkspaceMemberOut:
    ws = _resolve_workspace(
        await session.execute(select(Workspace).where(Workspace.id == wid)),
        tid,
    )
    member = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == uid,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")

    role = (await session.execute(select(Role).where(Role.role_key == body.role, Role.scope == "workspace"))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown workspace role")
    member.role_id = role.id

    user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if user is None:  # pragma: no cover — defensive
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    await session.commit()
    return WorkspaceMemberOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        status=user.status,
        role=role.role_key,
    )


@router.delete(
    "/api/tenants/{tid}/workspaces/{wid}/members/{uid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requires("membership:remove", "tenant"))],
)
async def remove_workspace_member(
    tid: int,
    wid: int,
    uid: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    ws = _resolve_workspace(
        await session.execute(select(Workspace).where(Workspace.id == wid)),
        tid,
    )
    member = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == uid,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")
    await session.delete(member)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/tenants/{tid}/tokens",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires("token:create", "tenant"))],
    response_model=CreateTokenOut,
)
async def create_tenant_token(
    tid: int,
    body: CreateTenantTokenIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CreateTokenOut:
    caller = _caller_user_id(request)
    created = await create_api_token(
        session,
        user_id=body.user_id,
        tenant_id=tid,
        workspace_id=body.workspace_id,
        name=body.name,
        scopes=body.scopes,
        expires_at=body.expires_at,
        created_by=caller,
    )
    return CreateTokenOut(id=created.token_id, plaintext=created.plaintext, prefix=created.prefix)


@router.delete(
    "/api/tenants/{tid}/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requires("token:revoke", "tenant"))],
)
async def revoke_tenant_token(
    tid: int,
    token_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    token = (await session.execute(select(ApiToken).where(ApiToken.id == token_id))).scalar_one_or_none()
    if token is None or token.tenant_id != tid:
        # Generic 404 keeps cross-tenant existence opaque.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
    await revoke_api_token(session, token_id=token_id, by_user_id=_caller_user_id(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Tenant CRUD (M7A item 2)
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9-]{2,64}$")


class CreateTenantIn(BaseModel):
    slug: str
    name: str

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, v: str) -> str:
        v = v.strip()
        if not _SLUG_RE.match(v):
            raise ValueError("slug must be 2-64 chars of [a-z0-9-]")
        return v

    @field_validator("name")
    @classmethod
    def _name_shape(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 128):
            raise ValueError("name must be 1-128 chars")
        return v


class PatchTenantIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name_shape(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 128):
            raise ValueError("name must be 1-128 chars")
        return v


class TenantOut(BaseModel):
    id: int
    slug: str
    name: str
    plan: str
    status: int


def _tenant_out(t: Tenant | Any) -> TenantOut:
    return TenantOut(
        id=t.id,
        slug=t.slug,
        name=t.name,
        plan=getattr(t, "plan", "free"),
        status=getattr(t, "status", 1),
    )


@router.post(
    "/api/admin/tenants",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires("tenant:create", "platform"))],
    response_model=TenantOut,
)
async def create_tenant(
    body: CreateTenantIn,
    session: AsyncSession = Depends(get_session),
) -> TenantOut:
    existing = (await session.execute(select(Tenant).where(Tenant.slug == body.slug))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "slug already in use")
    tenant = Tenant(slug=body.slug, name=body.name)
    session.add(tenant)
    await session.flush()
    await session.commit()
    return _tenant_out(tenant)


@router.patch(
    "/api/admin/tenants/{tid}",
    dependencies=[Depends(requires("tenant:update", "platform"))],
    response_model=TenantOut,
)
async def update_tenant(
    tid: int,
    body: PatchTenantIn,
    session: AsyncSession = Depends(get_session),
) -> TenantOut:
    tenant = (await session.execute(select(Tenant).where(Tenant.id == tid))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")
    tenant.name = body.name
    await session.commit()
    return _tenant_out(tenant)


@router.delete(
    "/api/admin/tenants/{tid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requires("tenant:delete", "platform"))],
)
async def delete_tenant(
    tid: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    tenant = (await session.execute(select(Tenant).where(Tenant.id == tid))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")
    # No deleted_at column; soft-deactivate by flipping status to 0.
    tenant.status = 0
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Workspace CRUD (M7A item 2)
# ---------------------------------------------------------------------------


class CreateWorkspaceIn(BaseModel):
    slug: str
    name: str

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, v: str) -> str:
        v = v.strip()
        if not _SLUG_RE.match(v):
            raise ValueError("slug must be 2-64 chars of [a-z0-9-]")
        return v

    @field_validator("name")
    @classmethod
    def _name_shape(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 128):
            raise ValueError("name must be 1-128 chars")
        return v


class PatchWorkspaceIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name_shape(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 128):
            raise ValueError("name must be 1-128 chars")
        return v


class WorkspaceOut(BaseModel):
    id: int
    tenant_id: int
    slug: str
    name: str


def _workspace_out(w: Workspace | Any) -> WorkspaceOut:
    return WorkspaceOut(id=w.id, tenant_id=w.tenant_id, slug=w.slug, name=w.name)


@router.post(
    "/api/tenants/{tid}/workspaces",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires("workspace:create", "tenant"))],
    response_model=WorkspaceOut,
)
async def create_workspace(
    tid: int,
    body: CreateWorkspaceIn,
    session: AsyncSession = Depends(get_session),
) -> WorkspaceOut:
    existing = (await session.execute(select(Workspace).where(Workspace.tenant_id == tid, Workspace.slug == body.slug))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "slug already in use")
    ws = Workspace(tenant_id=tid, slug=body.slug, name=body.name)
    session.add(ws)
    await session.flush()
    await session.commit()
    return _workspace_out(ws)


@router.patch(
    "/api/tenants/{tid}/workspaces/{wid}",
    dependencies=[Depends(requires("workspace:update", "tenant"))],
    response_model=WorkspaceOut,
)
async def update_workspace(
    tid: int,
    wid: int,
    body: PatchWorkspaceIn,
    session: AsyncSession = Depends(get_session),
) -> WorkspaceOut:
    ws = _resolve_workspace(
        await session.execute(select(Workspace).where(Workspace.id == wid)),
        tid,
    )
    ws.name = body.name
    await session.commit()
    return _workspace_out(ws)


@router.delete(
    "/api/tenants/{tid}/workspaces/{wid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requires("workspace:delete", "tenant"))],
)
async def delete_workspace(
    tid: int,
    wid: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    ws = _resolve_workspace(
        await session.execute(select(Workspace).where(Workspace.id == wid)),
        tid,
    )
    await session.delete(ws)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Registration codes (Tasks 6-8)
# ---------------------------------------------------------------------------


@router.post(
    "/api/tenants/{tid}/registration-codes",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires("membership:invite", "tenant"))],
    response_model=CreateRegistrationCodeOut,
)
async def create_registration_code(
    tid: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CreateRegistrationCodeOut:
    settings = get_identity_settings()
    plaintext = secrets.token_urlsafe(32)
    code_hash = hash_password(plaintext)
    expires_at = datetime.now(UTC) + timedelta(days=settings.registration_code_expires_days)

    rc = RegistrationCode(
        tenant_id=tid,
        creator_id=_caller_user_id(request),
        code_hash=code_hash,
        code_prefix=plaintext[:8],
        status=0,
        expires_at=expires_at,
    )
    session.add(rc)
    await session.flush()
    await session.commit()
    await session.refresh(rc)

    return CreateRegistrationCodeOut(
        id=rc.id,
        tenant_id=tid,
        code=plaintext,
        code_prefix=plaintext[:8],
        expires_at=expires_at,
        created_at=rc.created_at,
    )


@router.get(
    "/api/tenants/{tid}/registration-codes",
    dependencies=[Depends(requires("membership:read", "tenant"))],
    response_model=RegistrationCodeListOut,
)
async def list_registration_codes(
    tid: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> RegistrationCodeListOut:
    total = (
        await session.execute(
            select(sql_func.count(RegistrationCode.id)).where(RegistrationCode.tenant_id == tid)
        )
    ).scalar() or 0

    rows = (
        await session.execute(
            select(RegistrationCode)
            .where(RegistrationCode.tenant_id == tid)
            .order_by(RegistrationCode.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return RegistrationCodeListOut(
        items=[
            RegistrationCodeOut(
                id=r.id,
                tenant_id=r.tenant_id,
                code_prefix=r.code_prefix,
                status=r.status,
                expires_at=r.expires_at,
                accepted_by=r.accepted_by,
                accepted_at=r.accepted_at,
                created_at=r.created_at,
            )
            for r in rows
        ],
        total=int(total),
    )


@router.delete(
    "/api/tenants/{tid}/registration-codes/{rid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requires("membership:invite", "tenant"))],
)
async def revoke_registration_code(
    tid: int,
    rid: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    rc = (
        await session.execute(
            select(RegistrationCode).where(
                RegistrationCode.id == rid,
                RegistrationCode.tenant_id == tid,
            )
        )
    ).scalar_one_or_none()
    if rc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "registration code not found")
    if rc.status != 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "only pending codes can be revoked"
        )
    rc.status = 3
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
