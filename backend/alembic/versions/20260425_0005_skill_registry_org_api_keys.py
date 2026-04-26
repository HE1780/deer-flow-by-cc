"""Add skill_registry and org_api_keys tables (阶段5.1a).

Revision ID: 20260425_0005
Revises: 20260425_0004
Create Date: 2026-04-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260425_0005"
down_revision: str | None = "20260425_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE identity.skill_registry (
            id              BIGSERIAL PRIMARY KEY,
            name            TEXT NOT NULL,
            version         TEXT NOT NULL,
            scope           TEXT NOT NULL CHECK (scope IN ('public', 'org', 'private')),
            tenant_id       BIGINT REFERENCES identity.tenants(id) ON DELETE CASCADE,
            owner_id        BIGINT REFERENCES identity.users(id) ON DELETE CASCADE,
            enabled         BOOLEAN NOT NULL DEFAULT true,
            is_default      BOOLEAN NOT NULL DEFAULT false,
            status          TEXT NOT NULL DEFAULT 'pending_review'
                            CHECK (status IN ('active', 'pending_review', 'rejected', 'archived')),
            storage_path    TEXT NOT NULL,
            created_by      BIGINT REFERENCES identity.users(id),
            rejection_reason TEXT,
            reviewed_by     BIGINT REFERENCES identity.users(id),
            reviewed_at     TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (name, version, tenant_id),
            UNIQUE (name, version, owner_id)
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX skill_registry_default_public
            ON identity.skill_registry (name)
            WHERE is_default = true AND scope = 'public'
    """)

    op.execute("""
        CREATE UNIQUE INDEX skill_registry_default_org
            ON identity.skill_registry (name, tenant_id)
            WHERE is_default = true AND scope = 'org'
    """)

    op.execute("""
        CREATE UNIQUE INDEX skill_registry_default_private
            ON identity.skill_registry (name, owner_id)
            WHERE is_default = true AND scope = 'private'
    """)

    op.execute("""
        CREATE TABLE identity.org_api_keys (
            id              BIGSERIAL PRIMARY KEY,
            tenant_id       BIGINT NOT NULL REFERENCES identity.tenants(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            prefix          TEXT NOT NULL,
            token_hash      TEXT NOT NULL,
            allowed_skills  JSONB NOT NULL DEFAULT '[]',
            scopes          JSONB NOT NULL DEFAULT '["skill:invoke"]',
            no_expiry       BOOLEAN NOT NULL DEFAULT false,
            auto_rotate_at  TIMESTAMPTZ,
            last_rotated_at TIMESTAMPTZ,
            created_by      BIGINT REFERENCES identity.users(id),
            expires_at      TIMESTAMPTZ,
            revoked_at      TIMESTAMPTZ,
            last_used_at    TIMESTAMPTZ,
            last_used_ip    INET,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX uq_org_api_keys_active_prefix
            ON identity.org_api_keys (prefix)
            WHERE revoked_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS identity.uq_org_api_keys_active_prefix")
    op.execute("DROP TABLE IF EXISTS identity.org_api_keys")

    op.execute("DROP INDEX IF EXISTS identity.skill_registry_default_private")
    op.execute("DROP INDEX IF EXISTS identity.skill_registry_default_org")
    op.execute("DROP INDEX IF EXISTS identity.skill_registry_default_public")

    op.execute("DROP TABLE IF EXISTS identity.skill_registry")
