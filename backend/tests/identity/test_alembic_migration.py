"""Verify alembic upgrade head creates all tables and downgrade cleans up."""

import asyncio

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_upgrade_then_downgrade(pg_url, monkeypatch):
    monkeypatch.setenv("DEERFLOW_DATABASE_URL", pg_url)
    from app.gateway.identity.settings import get_identity_settings

    get_identity_settings.cache_clear()

    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)

    # alembic's run_migrations_online() uses asyncio.run(), which cannot run
    # inside an already-running loop. Execute alembic in a worker thread.
    await asyncio.to_thread(command.upgrade, cfg, "head")

    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(pg_url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'identity' ORDER BY tablename"))).all()
    await engine.dispose()

    table_names = {r[0] for r in rows}
    expected = {
        "tenants",
        "users",
        "memberships",
        "workspaces",
        "permissions",
        "roles",
        "role_permissions",
        "user_roles",
        "workspace_members",
        "api_tokens",
        "audit_logs",
        "registration_codes",
    }
    assert expected.issubset(table_names)

    await asyncio.to_thread(command.downgrade, cfg, "base")

    # After downgrade only alembic_version (the migration bookkeeping table)
    # should remain in the identity schema; all app tables are gone.
    engine = create_async_engine(pg_url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'identity'"))).all()
    await engine.dispose()
    remaining = {r[0] for r in rows}
    assert remaining <= {"alembic_version"}, f"unexpected tables after downgrade: {remaining}"
