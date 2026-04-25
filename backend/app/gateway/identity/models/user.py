"""User, Membership, WorkspaceMember ORM models."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.gateway.identity.models.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("oidc_provider", "oidc_subject", name="uq_users_oidc"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    oidc_subject: Mapped[str | None] = mapped_column(String(255))
    oidc_provider: Mapped[str | None] = mapped_column(String(64))
    password_hash: Mapped[str | None] = mapped_column(Text)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.users.id", ondelete="CASCADE"), primary_key=True)
    workspace_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.workspaces.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.roles.id"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
