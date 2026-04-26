"""Add password_hash to users for local password login.

Revision ID: 20260425_0004
Revises: 20260421_0003
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa

revision = "20260425_0004"
down_revision = "20260421_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.Text(), nullable=True),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash", schema="identity")
