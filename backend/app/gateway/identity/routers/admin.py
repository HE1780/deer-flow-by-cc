"""Admin read endpoints (M7 A2).

Paired with ``routers/admin_stub.py`` — the stub ``POST /api/admin/tenants``
stays put until A3 replaces it with a real handler. This module only adds
reads.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.identity.audit.events import AuditEvent
from app.gateway.identity.auth.dependencies import require_authenticated
from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.db import get_session
from app.gateway.identity.models import (
    ApiToken,
    Membership,
    Role,
    Tenant,
    User,
    UserRole,
    Workspace,
    WorkspaceMember,
)
from app.gateway.identity.rbac.decorator import requires
from app.gateway.identity.tasks.org_key_rotation import generate_org_key

router = APIRouter(tags=["identity-admin"])


def _tenant_row(t: Tenant) -> dict[str, Any]:
    return {
        "id": t.id,
        "slug": t.slug,
        "name": t.name,
        "plan": t.plan,
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get(
    "/api/admin/tenants",
    dependencies=[Depends(requires("tenant:read", "platform"))],
)
async def list_tenants(
    q: str | None = Query(default=None, description="Filter by slug (ILIKE)"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    conditions = []
    if q:
        conditions.append(Tenant.slug.ilike(f"%{q}%"))
    stmt = select(Tenant)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Tenant.created_at.desc()).offset(offset).limit(limit)

    count_stmt = select(func.count()).select_from(Tenant)
    if conditions:
        count_stmt = count_stmt.where(*conditions)

    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(count_stmt)).scalar() or 0
    return {"items": [_tenant_row(t) for t in rows], "total": int(total)}


@router.get(
    "/api/admin/tenants/{tid}",
    dependencies=[Depends(requires("tenant:read", "platform"))],
)
async def get_tenant(
    tid: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    tenant = (await session.execute(select(Tenant).where(Tenant.id == tid))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    member_count = (await session.execute(select(func.count()).select_from(Membership).where(Membership.tenant_id == tid))).scalar() or 0
    workspace_count = (await session.execute(select(func.count()).select_from(Workspace).where(Workspace.tenant_id == tid))).scalar() or 0
    return {
        **_tenant_row(tenant),
        "member_count": int(member_count),
        "workspace_count": int(workspace_count),
    }


def _user_row(u: User, role_keys: list[str]) -> dict[str, Any]:
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "avatar_url": u.avatar_url,
        "status": u.status,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "roles": role_keys,
    }


@router.get(
    "/api/tenants/{tid}/users",
    dependencies=[Depends(requires("membership:read", "tenant"))],
)
async def list_users(
    tid: int,
    q: str | None = Query(default=None, description="Filter by email (ILIKE)"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    u_stmt = select(User).join(Membership, Membership.user_id == User.id).where(Membership.tenant_id == tid).order_by(User.created_at.desc()).offset(offset).limit(limit)
    if q:
        u_stmt = u_stmt.where(User.email.ilike(f"%{q}%"))
    users = (await session.execute(u_stmt)).scalars().all()

    count_stmt = select(func.count(User.id.distinct())).select_from(User).join(Membership, Membership.user_id == User.id).where(Membership.tenant_id == tid)
    if q:
        count_stmt = count_stmt.where(User.email.ilike(f"%{q}%"))
    total = (await session.execute(count_stmt)).scalar() or 0

    # Roles per listed user (one query, then pivot). NULL tenant_id = platform grant.
    user_ids = [u.id for u in users]
    if user_ids:
        role_stmt = select(UserRole.user_id, Role.role_key).join(Role, Role.id == UserRole.role_id).where(UserRole.user_id.in_(user_ids)).where((UserRole.tenant_id == tid) | (UserRole.tenant_id.is_(None)))
        role_pairs = (await session.execute(role_stmt)).all()
    else:
        role_pairs = []
    by_user: dict[int, list[str]] = {}
    for uid, rk in role_pairs:
        by_user.setdefault(uid, []).append(rk)

    return {
        "items": [_user_row(u, sorted(by_user.get(u.id, []))) for u in users],
        "total": int(total),
    }


@router.get(
    "/api/tenants/{tid}/users/{uid}",
    dependencies=[Depends(requires("membership:read", "tenant"))],
)
async def get_user(
    tid: int,
    uid: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    u_stmt = select(User).join(Membership, Membership.user_id == User.id).where(Membership.tenant_id == tid, User.id == uid)
    user = (await session.execute(u_stmt)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    role_stmt = select(Role.role_key).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == uid).where((UserRole.tenant_id == tid) | (UserRole.tenant_id.is_(None)))
    role_keys = [r[0] for r in (await session.execute(role_stmt)).all()]
    return _user_row(user, sorted(role_keys))


def _workspace_row(w: Workspace, member_count: int) -> dict[str, Any]:
    return {
        "id": w.id,
        "tenant_id": w.tenant_id,
        "slug": w.slug,
        "name": w.name,
        "description": w.description,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "member_count": member_count,
    }


@router.get(
    "/api/tenants/{tid}/workspaces",
    dependencies=[Depends(requires("workspace:read", "tenant"))],
)
async def list_workspaces(
    tid: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    w_stmt = select(Workspace).where(Workspace.tenant_id == tid).order_by(Workspace.created_at.desc()).offset(offset).limit(limit)
    workspaces = (await session.execute(w_stmt)).scalars().all()

    count_stmt = select(func.count()).select_from(Workspace).where(Workspace.tenant_id == tid)
    total = (await session.execute(count_stmt)).scalar() or 0

    ws_ids = [w.id for w in workspaces]
    if ws_ids:
        mc_stmt = select(WorkspaceMember.workspace_id, func.count(WorkspaceMember.user_id)).where(WorkspaceMember.workspace_id.in_(ws_ids)).group_by(WorkspaceMember.workspace_id)
        mc_pairs = (await session.execute(mc_stmt)).all()
    else:
        mc_pairs = []
    counts = {wid: int(c) for wid, c in mc_pairs}

    return {
        "items": [_workspace_row(w, counts.get(w.id, 0)) for w in workspaces],
        "total": int(total),
    }


@router.get(
    "/api/tenants/{tid}/workspaces/{wid}/members",
    dependencies=[Depends(requires("membership:read", "tenant"))],
)
async def list_workspace_members(
    tid: int,
    wid: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    m_stmt = (
        select(User, Role.role_key, WorkspaceMember.joined_at)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .join(Role, Role.id == WorkspaceMember.role_id)
        .where(WorkspaceMember.workspace_id == wid)
        .order_by(WorkspaceMember.joined_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(m_stmt)).all()

    count_stmt = select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == wid)
    total = (await session.execute(count_stmt)).scalar() or 0

    return {
        "items": [
            {
                "id": u.id,
                "email": u.email,
                "display_name": u.display_name,
                "avatar_url": u.avatar_url,
                "status": u.status,
                "role": role_key,
                "joined_at": joined_at.isoformat() if joined_at else None,
            }
            for (u, role_key, joined_at) in rows
        ],
        "total": int(total),
    }


@router.get(
    "/api/tenants/{tid}/tokens",
    dependencies=[Depends(requires("token:read", "tenant"))],
)
async def list_tenant_tokens(
    tid: int,
    include_revoked: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(ApiToken).where(ApiToken.tenant_id == tid).order_by(ApiToken.created_at.desc()).offset(offset).limit(limit)
    if not include_revoked:
        stmt = stmt.where(ApiToken.revoked_at.is_(None))

    rows = (await session.execute(stmt)).scalars().all()

    count_stmt = select(func.count()).select_from(ApiToken).where(ApiToken.tenant_id == tid)
    if not include_revoked:
        count_stmt = count_stmt.where(ApiToken.revoked_at.is_(None))
    total = (await session.execute(count_stmt)).scalar() or 0

    return {
        "items": [
            {
                "id": t.id,
                "tenant_id": t.tenant_id,
                "user_id": t.user_id,
                "workspace_id": t.workspace_id,
                "name": t.name,
                "prefix": t.prefix,
                "scopes": list(t.scopes or []),
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
                "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in rows
        ],
        "total": int(total),
    }


# ---------------------------------------------------------------------------
# Org API key management (Task 5.1c)
# ---------------------------------------------------------------------------

_AUTO_ROTATE_INTERVAL_DAYS = 365  # permanent keys rotate annually


class CreateOrgKeyIn(BaseModel):
    name: str
    no_expiry: bool = True
    expires_in_days: int | None = None  # required when no_expiry=False; range 30-730
    allowed_skills: list[str] = []


def _org_key_row(row: Any, *, include_plaintext: str | None = None) -> dict:
    out: dict = {
        "id": row["id"],
        "prefix": row["prefix"],
        "name": row["name"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "no_expiry": row["no_expiry"],
        "auto_rotate_at": row["auto_rotate_at"].isoformat() if row["auto_rotate_at"] else None,
        "last_used_at": row["last_used_at"].isoformat() if row["last_used_at"] else None,
        "revoked_at": row["revoked_at"].isoformat() if row["revoked_at"] else None,
    }
    if include_plaintext is not None:
        out["plaintext"] = include_plaintext
    return out


@router.get(
    "/api/admin/org-keys",
    dependencies=[Depends(requires("token:read", "tenant"))],
)
async def list_org_keys(
    request: Request,
    identity: Identity = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List all org API keys for the current tenant (requires membership:read)."""
    if identity.tenant_id is None:
        raise HTTPException(status_code=400, detail="no active tenant")
    stmt = text(
        """
        SELECT id, tenant_id, name, prefix, no_expiry, allowed_skills,
               expires_at, auto_rotate_at, last_rotated_at, last_used_at,
               revoked_at, created_at
        FROM identity.org_api_keys
        WHERE tenant_id = :tenant_id
        ORDER BY created_at DESC
        """
    )
    result = await session.execute(stmt, {"tenant_id": identity.tenant_id})
    rows = result.mappings().all()
    return {"keys": [_org_key_row(r) for r in rows]}


@router.post(
    "/api/admin/org-keys",
    dependencies=[Depends(requires("token:create", "tenant"))],
    status_code=201,
)
async def create_org_key(
    body: CreateOrgKeyIn,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a new org API key for the current tenant. Plaintext shown once."""
    if identity.tenant_id is None:
        raise HTTPException(status_code=400, detail="no active tenant")
    if not body.no_expiry:
        if body.expires_in_days is None or not (30 <= body.expires_in_days <= 730):
            raise HTTPException(status_code=422, detail="expires_in_days must be between 30 and 730 when no_expiry=false")

    plaintext, token_hash, prefix = generate_org_key()
    now = datetime.now(UTC)

    expires_at: datetime | None = None
    auto_rotate_at: datetime | None = None
    if body.no_expiry:
        auto_rotate_at = now + timedelta(days=_AUTO_ROTATE_INTERVAL_DAYS)
    else:
        expires_at = now + timedelta(days=body.expires_in_days)  # type: ignore[arg-type]

    insert_stmt = text(
        """
        INSERT INTO identity.org_api_keys
            (tenant_id, name, prefix, token_hash, allowed_skills, no_expiry,
             expires_at, auto_rotate_at, created_by, created_at)
        VALUES
            (:tenant_id, :name, :prefix, :token_hash, CAST(:allowed_skills AS jsonb),
             :no_expiry, :expires_at, :auto_rotate_at, :created_by, :now)
        RETURNING id, name, prefix, no_expiry, expires_at, auto_rotate_at,
                  last_used_at, revoked_at, created_at
        """
    )
    result = await session.execute(
        insert_stmt,
        {
            "tenant_id": identity.tenant_id,
            "name": body.name,
            "prefix": prefix,
            "token_hash": token_hash,
            "allowed_skills": json.dumps(body.allowed_skills),
            "no_expiry": body.no_expiry,
            "expires_at": expires_at,
            "auto_rotate_at": auto_rotate_at,
            "created_by": identity.user_id,
            "now": now,
        },
    )
    row = result.mappings().one()
    await session.commit()

    # Emit audit event (best-effort)
    writer = getattr(getattr(request.app, "state", None), "audit_writer", None)
    if writer is not None:
        try:
            await writer.enqueue(
                AuditEvent(
                    action="org_key.created",
                    result="success",
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    resource_type="org_api_key",
                    resource_id=str(row["id"]),
                    metadata={"key_name": body.name, "prefix": prefix},
                ),
                critical=False,
            )
        except Exception:
            pass

    return _org_key_row(row, include_plaintext=plaintext)


@router.delete(
    "/api/admin/org-keys/{key_id}",
    dependencies=[Depends(requires("token:revoke", "tenant"))],
)
async def revoke_org_key(
    key_id: int,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Revoke an org API key (set revoked_at = now())."""
    if identity.tenant_id is None:
        raise HTTPException(status_code=400, detail="no active tenant")
    # Verify ownership by tenant
    check_stmt = text(
        "SELECT id, name, tenant_id, revoked_at FROM identity.org_api_keys WHERE id = :id"
    )
    result = await session.execute(check_stmt, {"id": key_id})
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="org key not found")
    if row["tenant_id"] != identity.tenant_id:
        raise HTTPException(status_code=403, detail="cannot revoke key belonging to another tenant")
    if row["revoked_at"] is not None:
        raise HTTPException(status_code=409, detail="key already revoked")

    now = datetime.now(UTC)
    await session.execute(
        text("UPDATE identity.org_api_keys SET revoked_at = :now WHERE id = :id"),
        {"now": now, "id": key_id},
    )
    await session.commit()

    # Emit audit event (best-effort)
    writer = getattr(getattr(request.app, "state", None), "audit_writer", None)
    if writer is not None:
        try:
            await writer.enqueue(
                AuditEvent(
                    action="org_key.revoked",
                    result="success",
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    resource_type="org_api_key",
                    resource_id=str(key_id),
                    metadata={"key_name": row["name"]},
                ),
                critical=False,
            )
        except Exception:
            pass

    return {"status": "revoked"}


# ---------------------------------------------------------------------------
# Skill approval workflow (Task 5.4)
# ---------------------------------------------------------------------------


class RejectSkillIn(BaseModel):
    reason: str = ""


@router.get(
    "/api/admin/skills/pending",
    dependencies=[Depends(requires("skill:manage", "platform"))],
)
async def list_pending_skills(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List skills with status='pending_review'."""
    stmt = text(
        """
        SELECT id, name, version, scope, status, created_at, created_by, storage_path
        FROM identity.skill_registry
        WHERE status = 'pending_review'
        ORDER BY created_at ASC
        """
    )
    result = await session.execute(stmt)
    rows = result.mappings().all()
    return {
        "skills": [
            {
                "id": r["id"],
                "name": r["name"],
                "version": r["version"],
                "scope": r["scope"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "created_by": r["created_by"],
                "storage_path": r["storage_path"],
            }
            for r in rows
        ]
    }


@router.post(
    "/api/admin/skills/{skill_id}/approve",
    dependencies=[Depends(requires("skill:manage", "platform"))],
)
async def approve_skill(
    skill_id: int,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Approve a pending skill: set status='active', reviewed_by, reviewed_at."""
    # Verify skill exists and is pending
    check = await session.execute(
        text("SELECT id, name, version, scope, status, tenant_id FROM identity.skill_registry WHERE id = :id"),
        {"id": skill_id},
    )
    row = check.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="skill not found")
    if row["status"] != "pending_review":
        raise HTTPException(status_code=409, detail=f"skill status is '{row['status']}', expected 'pending_review'")

    now = datetime.now(UTC)
    await session.execute(
        text(
            """
            UPDATE identity.skill_registry
            SET status = 'active', reviewed_by = :reviewed_by, reviewed_at = :reviewed_at
            WHERE id = :id
            """
        ),
        {"reviewed_by": identity.user_id, "reviewed_at": now, "id": skill_id},
    )

    # Set is_default=true if this (name, scope) has no other active version.
    # For org-scoped skills, restrict the check to the same tenant so that
    # one tenant's active skill does not affect another tenant's default flag.
    skill_tenant_id = row["tenant_id"]
    default_check = await session.execute(
        text(
            """
            SELECT id FROM identity.skill_registry
            WHERE name = :name AND scope = :scope AND status = 'active' AND id != :id
              AND ((:scope = 'public') OR (tenant_id = :tenant_id))
            LIMIT 1
            """
        ),
        {"name": row["name"], "scope": row["scope"], "id": skill_id, "tenant_id": skill_tenant_id},
    )
    if default_check.fetchone() is None:
        # No other active version → mark this one as default
        await session.execute(
            text("UPDATE identity.skill_registry SET is_default = true WHERE id = :id"),
            {"id": skill_id},
        )

    await session.commit()

    # Emit audit event (best-effort)
    writer = getattr(getattr(request.app, "state", None), "audit_writer", None)
    if writer is not None:
        try:
            await writer.enqueue(
                AuditEvent(
                    action="skill.review.approved",
                    result="success",
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    resource_type="skill",
                    resource_id=str(skill_id),
                    metadata={"name": row["name"], "version": row["version"], "scope": row["scope"]},
                ),
                critical=False,
            )
        except Exception:
            pass

    return {"status": "active", "skill_id": skill_id}


@router.post(
    "/api/admin/skills/{skill_id}/reject",
    dependencies=[Depends(requires("skill:manage", "platform"))],
)
async def reject_skill(
    skill_id: int,
    body: RejectSkillIn,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Reject a pending skill: set status='rejected', rejection_reason, reviewed_by, reviewed_at."""
    check = await session.execute(
        text("SELECT id, name, version, scope, status FROM identity.skill_registry WHERE id = :id"),
        {"id": skill_id},
    )
    row = check.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="skill not found")
    if row["status"] != "pending_review":
        raise HTTPException(status_code=409, detail=f"skill status is '{row['status']}', expected 'pending_review'")

    now = datetime.now(UTC)
    await session.execute(
        text(
            """
            UPDATE identity.skill_registry
            SET status = 'rejected',
                rejection_reason = :reason,
                reviewed_by = :reviewed_by,
                reviewed_at = :reviewed_at
            WHERE id = :id
            """
        ),
        {"reason": body.reason, "reviewed_by": identity.user_id, "reviewed_at": now, "id": skill_id},
    )
    await session.commit()

    # Emit audit event (best-effort)
    writer = getattr(getattr(request.app, "state", None), "audit_writer", None)
    if writer is not None:
        try:
            await writer.enqueue(
                AuditEvent(
                    action="skill.review.rejected",
                    result="success",
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    resource_type="skill",
                    resource_id=str(skill_id),
                    metadata={"name": row["name"], "version": row["version"], "scope": row["scope"], "reason": body.reason},
                ),
                critical=False,
            )
        except Exception:
            pass

    return {"status": "rejected", "skill_id": skill_id}


@router.get(
    "/api/admin/skills/reviewed",
    dependencies=[Depends(requires("skill:manage", "platform"))],
)
async def list_reviewed_skills(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List skills with status in ('rejected', 'archived')."""
    stmt = text(
        """
        SELECT id, name, version, scope, status, rejection_reason,
               created_at, created_by, reviewed_at, storage_path
        FROM identity.skill_registry
        WHERE status IN ('rejected', 'archived')
        ORDER BY reviewed_at DESC NULLS LAST
        """
    )
    result = await session.execute(stmt)
    rows = result.mappings().all()
    return {
        "skills": [
            {
                "id": r["id"],
                "name": r["name"],
                "version": r["version"],
                "scope": r["scope"],
                "status": r["status"],
                "rejection_reason": r["rejection_reason"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "created_by": r["created_by"],
                "reviewed_at": r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
                "storage_path": r["storage_path"],
            }
            for r in rows
        ]
    }


@router.get(
    "/api/skills/{skill_name}/review-status",
)
async def get_skill_review_status(
    skill_name: str,
    identity: Identity = Depends(require_authenticated),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the review status of a skill. Only the skill creator can query this."""
    stmt = await session.execute(
        text(
            """
            SELECT id, name, version, scope, status, rejection_reason, created_by
            FROM identity.skill_registry
            WHERE name = :name
              AND (scope = 'public' OR tenant_id = :caller_tenant_id OR owner_id = :caller_user_id)
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"name": skill_name, "caller_tenant_id": identity.tenant_id, "caller_user_id": identity.user_id},
    )
    row = stmt.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="skill not found")

    # Only the creator or a user with skill:manage can view
    if row["created_by"] != identity.user_id and not identity.has_permission("skill:manage"):
        raise HTTPException(status_code=403, detail="access denied")

    return {
        "name": row["name"],
        "version": row["version"],
        "status": row["status"],
        "rejection_reason": row["rejection_reason"],
    }
