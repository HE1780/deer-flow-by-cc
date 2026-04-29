"""registration_codes table

Revision ID: 20260429_0006
Revises: 20260425_0005
Create Date: 2026-04-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260429_0006"
down_revision: str | None = "20260425_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "registration_codes",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger,
            sa.ForeignKey("identity.tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "creator_id",
            sa.BigInteger,
            sa.ForeignKey("identity.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(60), nullable=False),
        sa.Column("code_prefix", sa.String(8), nullable=False, index=True),
        sa.Column("status", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "accepted_by",
            sa.BigInteger,
            sa.ForeignKey("identity.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_table("registration_codes", schema="identity")
