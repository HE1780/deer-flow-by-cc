"""RegistrationCode ORM model — single-use self-service registration tokens."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.gateway.identity.models.base import Base, TenantScoped


class RegistrationCode(Base, TenantScoped):
    __tablename__ = "registration_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("identity.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(60), nullable=False)
    code_prefix: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("identity.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
