"""Tests for bootstrap: idempotent seed + first admin creation."""

import asyncio

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import select

from alembic import command
from app.gateway.identity.bootstrap import (
    PREDEFINED_PERMISSIONS,
    PREDEFINED_ROLE_PERMISSIONS,
    PREDEFINED_ROLES,
    bootstrap,
)
from app.gateway.identity.db import create_engine_and_sessionmaker
from app.gateway.identity.models import Permission, Role, Tenant, User, UserRole, Workspace


@pytest_asyncio.fixture
async def fresh_db(pg_url, monkeypatch):
    """Run migrations, yield (engine, maker), drop schema at teardown."""
    monkeypatch.setenv("DEERFLOW_DATABASE_URL", pg_url)
    from app.gateway.identity.settings import get_identity_settings

    get_identity_settings.cache_clear()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine, maker = create_engine_and_sessionmaker(pg_url)
    try:
        yield engine, maker
    finally:
        await engine.dispose()
        await asyncio.to_thread(command.downgrade, cfg, "base")


@pytest.mark.asyncio
async def test_bootstrap_creates_roles_and_permissions(fresh_db):
    _, maker = fresh_db
    async with maker() as session:
        await bootstrap(session, bootstrap_admin_email=None)

        perms = (await session.execute(select(Permission))).scalars().all()
        roles = (await session.execute(select(Role))).scalars().all()

        assert {p.tag for p in perms} == {tag for tag, _scope in PREDEFINED_PERMISSIONS}
        assert {(r.role_key, r.scope) for r in roles} == {(k, s) for k, s, _desc in PREDEFINED_ROLES}


@pytest.mark.asyncio
async def test_bootstrap_creates_default_tenant_and_workspace(fresh_db):
    _, maker = fresh_db
    async with maker() as session:
        await bootstrap(session, bootstrap_admin_email=None)
        tenants = (await session.execute(select(Tenant).where(Tenant.slug == "default"))).scalars().all()
        workspaces = (await session.execute(select(Workspace).where(Workspace.slug == "default"))).scalars().all()
        assert len(tenants) == 1
        assert len(workspaces) == 1
        assert workspaces[0].tenant_id == tenants[0].id


@pytest.mark.asyncio
async def test_bootstrap_idempotent(fresh_db):
    _, maker = fresh_db
    async with maker() as session:
        await bootstrap(session, bootstrap_admin_email=None)
        await bootstrap(session, bootstrap_admin_email=None)
        await bootstrap(session, bootstrap_admin_email=None)

        perms = (await session.execute(select(Permission))).scalars().all()
        roles = (await session.execute(select(Role))).scalars().all()
        tenants = (await session.execute(select(Tenant))).scalars().all()
        assert len(perms) == len(PREDEFINED_PERMISSIONS)
        assert len(roles) == len(PREDEFINED_ROLES)
        assert len([t for t in tenants if t.slug == "default"]) == 1


@pytest.mark.asyncio
async def test_bootstrap_creates_first_platform_admin(fresh_db):
    _, maker = fresh_db
    async with maker() as session:
        await bootstrap(session, bootstrap_admin_email="admin@example.com")

        users = (await session.execute(select(User).where(User.email == "admin@example.com"))).scalars().all()
        assert len(users) == 1
        admin = users[0]

        ur = (await session.execute(select(UserRole).where(UserRole.user_id == admin.id, UserRole.tenant_id.is_(None)))).scalars().all()
        assert len(ur) == 1


@pytest.mark.asyncio
async def test_bootstrap_skips_platform_admin_if_already_exists(fresh_db):
    _, maker = fresh_db
    async with maker() as session:
        await bootstrap(session, bootstrap_admin_email="admin@example.com")
        await bootstrap(session, bootstrap_admin_email="another@example.com")

        users = (await session.execute(select(User))).scalars().all()
        platform_admin_emails = {u.email for u in users}
        assert "admin@example.com" in platform_admin_emails
        assert "another@example.com" not in platform_admin_emails


@pytest.mark.asyncio
async def test_role_permission_map_covers_all_roles(fresh_db):
    _, maker = fresh_db
    async with maker() as session:
        await bootstrap(session, bootstrap_admin_email=None)
        for role_key, scope, _ in PREDEFINED_ROLES:
            perms_for_role = PREDEFINED_ROLE_PERMISSIONS.get((role_key, scope), [])
            assert len(perms_for_role) > 0, f"Role {role_key}/{scope} has no permissions"


def test_workspace_member_role_in_predefined():
    from app.gateway.identity.bootstrap import PREDEFINED_ROLES, PREDEFINED_ROLE_PERMISSIONS

    keys = {(k, s) for k, s, _ in PREDEFINED_ROLES}
    assert ("workspace_member", "workspace") in keys

    perms = PREDEFINED_ROLE_PERMISSIONS[("workspace_member", "workspace")]
    expected = {
        "thread:read", "thread:write", "thread:delete",
        "skill:read", "skill:invoke",
        "knowledge:read", "knowledge:write",
        "workflow:read", "workflow:run",
        "settings:read",
    }
    assert set(perms) == expected
    # Confirm publish/manage are NOT granted.
    assert "skill:publish" not in perms
    assert "skill:manage" not in perms
    assert "knowledge:manage" not in perms
    assert "workflow:manage" not in perms
    assert "settings:update" not in perms
