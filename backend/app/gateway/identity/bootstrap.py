"""Idempotent seed of roles, permissions, default tenant/workspace, first admin.

Called at gateway startup when ENABLE_IDENTITY=true. Safe to run repeatedly.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.identity.models import (
    Membership,
    Permission,
    Role,
    RolePermission,
    Tenant,
    User,
    UserRole,
    Workspace,
    WorkspaceMember,
)

logger = logging.getLogger(__name__)

# --- Seed data (spec §4.2) ---

PREDEFINED_PERMISSIONS: list[tuple[str, str]] = [
    ("tenant:create", "platform"),
    ("tenant:read", "platform"),
    ("tenant:update", "platform"),
    ("tenant:delete", "platform"),
    ("user:read", "platform"),
    ("user:disable", "platform"),
    ("audit:read.all", "platform"),
    ("workspace:create", "tenant"),
    ("workspace:read", "tenant"),
    ("workspace:update", "tenant"),
    ("workspace:delete", "tenant"),
    ("membership:invite", "tenant"),
    ("membership:read", "tenant"),
    ("membership:remove", "tenant"),
    ("role:read", "tenant"),
    ("token:create", "tenant"),
    ("token:revoke", "tenant"),
    ("token:read", "tenant"),
    ("audit:read", "tenant"),
    ("thread:read", "workspace"),
    ("thread:write", "workspace"),
    ("thread:delete", "workspace"),
    ("skill:read", "workspace"),
    ("skill:invoke", "workspace"),
    ("skill:publish", "workspace"),
    ("skill:manage", "workspace"),
    ("knowledge:read", "workspace"),
    ("knowledge:write", "workspace"),
    ("knowledge:manage", "workspace"),
    ("workflow:read", "workspace"),
    ("workflow:run", "workspace"),
    ("workflow:manage", "workspace"),
    ("settings:read", "workspace"),
    ("settings:update", "workspace"),
]

PREDEFINED_ROLES: list[tuple[str, str, str]] = [
    ("platform_admin", "platform", "Platform super-administrator (cross-tenant)"),
    ("tenant_owner", "tenant", "Tenant owner (manages workspaces, members, tokens)"),
    ("workspace_admin", "workspace", "Workspace administrator (manages resources + members)"),
    ("member", "workspace", "Workspace member [legacy — pre-registration; includes skill:publish]"),
    ("viewer", "workspace", "Read-only viewer"),
    ("workspace_member", "workspace", "Workspace member (basic usage of own resources)"),
]

_PLATFORM_PERMS = [tag for tag, scope in PREDEFINED_PERMISSIONS if scope == "platform"]
_TENANT_PERMS = [tag for tag, scope in PREDEFINED_PERMISSIONS if scope == "tenant"]
_WORKSPACE_PERMS = [tag for tag, scope in PREDEFINED_PERMISSIONS if scope == "workspace"]

PREDEFINED_ROLE_PERMISSIONS: dict[tuple[str, str], list[str]] = {
    ("platform_admin", "platform"): _PLATFORM_PERMS + _TENANT_PERMS + _WORKSPACE_PERMS,
    ("tenant_owner", "tenant"): _TENANT_PERMS + _WORKSPACE_PERMS,
    ("workspace_admin", "workspace"): _WORKSPACE_PERMS,
    ("member", "workspace"): [
        "thread:read",
        "thread:write",
        "thread:delete",
        "skill:read",
        "skill:invoke",
        "skill:publish",
        "knowledge:read",
        "knowledge:write",
        "workflow:read",
        "workflow:run",
        "settings:read",
    ],
    ("viewer", "workspace"): [p for p in _WORKSPACE_PERMS if p.endswith(":read")],
    ("workspace_member", "workspace"): [
        "thread:read",
        "thread:write",
        "thread:delete",
        "skill:read",
        "skill:invoke",
        "knowledge:read",
        "knowledge:write",
        "workflow:read",
        "workflow:run",
        "settings:read",
    ],
}


async def bootstrap(session: AsyncSession, *, bootstrap_admin_email: str | None) -> None:
    """Seed identity schema. Idempotent. Call inside a single transaction."""
    perm_map = await _seed_permissions(session)
    role_map = await _seed_roles(session)
    await _seed_role_permissions(session, role_map, perm_map)

    default_tenant = await _ensure_tenant(session, slug="default", name="Default")
    default_ws = await _ensure_workspace(session, tenant_id=default_tenant.id, slug="default", name="Default")

    if bootstrap_admin_email:
        await _ensure_first_platform_admin(
            session,
            email=bootstrap_admin_email,
            default_tenant_id=default_tenant.id,
            default_workspace_id=default_ws.id,
            role_map=role_map,
        )

    await session.commit()
    logger.info("identity bootstrap complete")


async def _seed_permissions(session: AsyncSession) -> dict[str, int]:
    existing = {p.tag: p.id for p in (await session.execute(select(Permission))).scalars()}
    for tag, scope in PREDEFINED_PERMISSIONS:
        if tag not in existing:
            session.add(Permission(tag=tag, scope=scope))
    await session.flush()
    return {p.tag: p.id for p in (await session.execute(select(Permission))).scalars()}


async def _seed_roles(session: AsyncSession) -> dict[tuple[str, str], int]:
    existing = {(r.role_key, r.scope): r.id for r in (await session.execute(select(Role))).scalars()}
    for key, scope, desc in PREDEFINED_ROLES:
        if (key, scope) not in existing:
            session.add(Role(role_key=key, scope=scope, is_builtin=True, display_name=key.replace("_", " ").title(), description=desc))
    await session.flush()
    return {(r.role_key, r.scope): r.id for r in (await session.execute(select(Role))).scalars()}


async def _seed_role_permissions(session: AsyncSession, role_map: dict, perm_map: dict) -> None:
    existing = {(rp.role_id, rp.permission_id) for rp in (await session.execute(select(RolePermission))).scalars()}
    for (role_key, scope), perm_tags in PREDEFINED_ROLE_PERMISSIONS.items():
        role_id = role_map[(role_key, scope)]
        for tag in perm_tags:
            perm_id = perm_map[tag]
            if (role_id, perm_id) not in existing:
                session.add(RolePermission(role_id=role_id, permission_id=perm_id))
    await session.flush()


async def _ensure_tenant(session: AsyncSession, *, slug: str, name: str) -> Tenant:
    result = await session.execute(select(Tenant).where(Tenant.slug == slug))
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    t = Tenant(slug=slug, name=name)
    session.add(t)
    await session.flush()
    return t


async def _ensure_workspace(session: AsyncSession, *, tenant_id: int, slug: str, name: str) -> Workspace:
    result = await session.execute(select(Workspace).where(Workspace.tenant_id == tenant_id, Workspace.slug == slug))
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    w = Workspace(tenant_id=tenant_id, slug=slug, name=name, description="Default workspace")
    session.add(w)
    await session.flush()
    return w


async def _ensure_first_platform_admin(
    session: AsyncSession,
    *,
    email: str,
    default_tenant_id: int,
    default_workspace_id: int,
    role_map: dict,
) -> None:
    """If any platform_admin already exists, do nothing (even for a different email)."""
    platform_admin_role_id = role_map[("platform_admin", "platform")]
    existing_admin = await session.execute(select(UserRole).where(UserRole.role_id == platform_admin_role_id, UserRole.tenant_id.is_(None)))
    if existing_admin.first() is not None:
        logger.info("platform_admin already exists; skipping bootstrap of %s", email)
        return

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email, display_name=email.split("@")[0], status=1)
        session.add(user)
        await session.flush()

    session.add(UserRole(user_id=user.id, tenant_id=None, role_id=platform_admin_role_id))
    session.add(Membership(user_id=user.id, tenant_id=default_tenant_id))
    session.add(UserRole(user_id=user.id, tenant_id=default_tenant_id, role_id=role_map[("tenant_owner", "tenant")]))
    session.add(WorkspaceMember(user_id=user.id, workspace_id=default_workspace_id, role_id=role_map[("workspace_admin", "workspace")]))
    await session.flush()
    logger.info("bootstrapped first platform_admin: %s", email)
