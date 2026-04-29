> 📦 **归档于 2026-04-29 — 实施未启动（待讨论是否纳入下一期）**
>
> **当前事实**：
> - **代码全部未动**：`backend/app/gateway/identity/models/invitation.py` MISSING，无 Alembic 0006 迁移，`auth.py` 无 `/register` 端点，`admin_writes.py` 无 invitations 三端点。
> - 设计 + plan 完整可执行，依赖项（M2 password_login + bcrypt + session）已就绪。
> - 见 [OPEN_ISSUES.md OI-4](../../../OPEN_ISSUES.md) — 待讨论是否纳入下一期。
>
> 下文为原始 plan，可直接拾取执行。

---

# Invitation-Based User Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add invitation-based user registration so organization admins can invite users by email, and invited users can self-register with a password to join a specific tenant.

**Architecture:** Add an `invitations` table to the identity schema, three admin endpoints (create/list/revoke invitations) in the existing `admin_writes.py` router, and one public `POST /api/auth/register` endpoint in `auth.py`. The invitation token is the identity-proof mechanism — only someone who receives the token from an authorized admin can join the target tenant.

**Tech Stack:** FastAPI, SQLAlchemy async, bcrypt, PostgreSQL, Redis (session store, reused from existing M2 auth)

**Test fixtures assumed from existing conftest:** `db_session` (async session that rolls back), `admin_client` (authenticated as bootstrap platform_admin), `member_client` (authenticated as regular tenant member), `anon_client` (unauthenticated). The bootstrap creates tenant id=1, user id=1.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/app/gateway/identity/models/invitation.py` | `Invitation` ORM model |
| Modify | `backend/app/gateway/identity/models/__init__.py` | Re-export `Invitation` |
| Create | `backend/alembic/versions/20260428_0006_invitations.py` | DB migration |
| Modify | `backend/app/gateway/identity/routers/admin_writes.py` | 3 invitation admin endpoints |
| Modify | `backend/app/gateway/identity/routers/auth.py` | `POST /api/auth/register` |
| Create | `backend/tests/identity/test_invitations.py` | Admin CRUD tests |
| Create | `backend/tests/identity/test_registration.py` | Registration flow tests |

---

### Task 1: Invitation Model + DB Migration

**Files:**
- Create: `backend/app/gateway/identity/models/invitation.py`
- Create: `backend/alembic/versions/20260428_0006_invitations.py`
- Modify: `backend/app/gateway/identity/models/__init__.py`

- [ ] **Step 1: Write the Invitation model**

```python
"""Invitation model for user registration via invite tokens."""
import secrets
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.gateway.identity.models.base import Base


def _new_invitation_token() -> str:
    return secrets.token_urlsafe(48)


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("token", name="uq_invitations_token"),
        {"schema": "identity"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inviter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(128), nullable=False, default=_new_invitation_token)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=func.text("0"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("identity.users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: Write the alembic migration**

`backend/alembic/versions/20260428_0006_invitations.py`:

```python
"""invitations table

Revision ID: 20260428_0006
Revises: 20260425_0005
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260428_0006"
down_revision: str | None = "20260425_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("inviter_id", sa.BigInteger, sa.ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("status", sa.SmallInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by", sa.BigInteger, sa.ForeignKey("identity.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token", name="uq_invitations_token"),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_table("invitations", schema="identity")
```

- [ ] **Step 3: Update models __init__.py to export Invitation**

In `backend/app/gateway/identity/models/__init__.py`, add:

```python
from app.gateway.identity.models.invitation import Invitation
```

And add `"Invitation"` to `__all__` if it exists.

- [ ] **Step 4: Run the migration and verify**

```bash
cd backend && PYTHONPATH=. uv run alembic upgrade head
```

Expected: migration runs without error. Verify table exists with:
```bash
cd backend && PYTHONPATH=. uv run python -c "
from sqlalchemy import inspect, text
from app.gateway.identity.db import create_engine_and_sessionmaker
from app.gateway.identity.settings import get_identity_settings
import asyncio

async def check():
    settings = get_identity_settings()
    engine, _ = create_engine_and_sessionmaker(settings.database_url)
    async with engine.connect() as conn:
        result = await conn.execute(text(\"SELECT table_name FROM information_schema.tables WHERE table_schema = 'identity' AND table_name = 'invitations'\"))
        print('Table exists:', result.scalar())
    await engine.dispose()

asyncio.run(check())
"
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/identity/models/invitation.py \
        backend/app/gateway/identity/models/__init__.py \
        backend/alembic/versions/20260428_0006_invitations.py
git commit -m "feat(identity): add Invitation model and migration for user registration"
```

---

### Task 2: Create Invitation Endpoint (POST)

**Files:**
- Create: `backend/tests/identity/test_invitations.py`
- Modify: `backend/app/gateway/identity/routers/admin_writes.py`

- [ ] **Step 1: Write the failing test for create invitation**

```python
"""Tests for invitation admin CRUD and registration flow."""
import pytest
from fastapi.testclient import TestClient


class TestCreateInvitation:
    async def test_tenant_owner_can_create_invitation(
        self, admin_client: TestClient
    ):
        body = {"email": "newuser@example.com", "expires_in_days": 7}
        resp = admin_client.post("/api/tenants/1/invitations", json=body)
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "newuser@example.com"
        assert data["status"] == 0  # pending
        assert data["tenant_id"] == 1
        assert "token" not in data  # token is never exposed in API responses
        assert "id" in data

    async def test_create_invitation_requires_membership_invite_permission(
        self, member_client: TestClient
    ):
        body = {"email": "someone@example.com"}
        resp = member_client.post("/api/tenants/1/invitations", json=body)
        assert resp.status_code == 403

    async def test_create_invitation_invalid_email(
        self, admin_client: TestClient
    ):
        body = {"email": "not-an-email"}
        resp = admin_client.post("/api/tenants/1/invitations", json=body)
        assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/test_invitations.py::TestCreateInvitation -v
```

Expected: FAIL (endpoint not found — 404)

- [ ] **Step 3: Implement the schemas and create endpoint in admin_writes.py**

Add these schemas after the existing ones (after `CreateTokenOut`):

```python
class CreateInvitationIn(BaseModel):
    email: str
    expires_in_days: int = 7

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email format")
        return v

    @field_validator("expires_in_days")
    @classmethod
    def _expires_range(cls, v: int) -> int:
        if not 1 <= v <= 90:
            raise ValueError("expires_in_days must be between 1 and 90")
        return v


class InvitationOut(BaseModel):
    id: int
    tenant_id: int
    email: str
    status: int
    expires_at: str
    created_at: str
```

Add this import:

```python
from datetime import datetime, timedelta, timezone
from app.gateway.identity.models.invitation import Invitation
```

Add the `_invitation_out` helper:

```python
def _invitation_out(inv: Invitation | Any) -> InvitationOut:
    return InvitationOut(
        id=inv.id,
        tenant_id=inv.tenant_id,
        email=inv.email,
        status=inv.status,
        expires_at=inv.expires_at.isoformat() if inv.expires_at else None,
        created_at=inv.created_at.isoformat() if inv.created_at else None,
    )
```

Add the create endpoint after `create_user`:

```python
@router.post(
    "/api/tenants/{tid}/invitations",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires("membership:invite", "tenant"))],
    response_model=InvitationOut,
)
async def create_invitation(
    tid: int,
    body: CreateInvitationIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> InvitationOut:
    inviter_id = _caller_user_id(request)
    invitation = Invitation(
        tenant_id=tid,
        inviter_id=inviter_id,
        email=body.email.strip(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=body.expires_in_days),
    )
    session.add(invitation)
    await session.commit()
    return _invitation_out(invitation)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/test_invitations.py::TestCreateInvitation -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/identity/routers/admin_writes.py \
        backend/tests/identity/test_invitations.py
git commit -m "feat(identity): add POST /api/tenants/{tid}/invitations endpoint"
```

---

### Task 3: List & Revoke Invitation Endpoints

**Files:**
- Modify: `backend/tests/identity/test_invitations.py`
- Modify: `backend/app/gateway/identity/routers/admin_writes.py`

- [ ] **Step 1: Extend tests for list and revoke**

Add these imports to the top of `test_invitations.py`:

```python
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from app.gateway.identity.models.invitation import Invitation
```

Add to `test_invitations.py`:

```python
class TestListInvitations:
    async def test_list_invitations(
        self, admin_client: TestClient
    ):
        # Create two invitations first
        admin_client.post("/api/tenants/1/invitations", json={"email": "a@example.com"})
        admin_client.post("/api/tenants/1/invitations", json={"email": "b@example.com"})

        resp = admin_client.get("/api/tenants/1/invitations")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] >= 2
        assert all(item["tenant_id"] == 1 for item in data["items"])

    async def test_list_requires_membership_read(
        self, anon_client: TestClient
    ):
        resp = anon_client.get("/api/tenants/1/invitations")
        assert resp.status_code == 401


class TestRevokeInvitation:
    async def test_revoke_invitation(
        self, admin_client: TestClient
    ):
        create_resp = admin_client.post(
            "/api/tenants/1/invitations", json={"email": "revoke@example.com"}
        )
        inv_id = create_resp.json()["id"]

        resp = admin_client.delete(f"/api/tenants/1/invitations/{inv_id}")
        assert resp.status_code == 204

        list_resp = admin_client.get("/api/tenants/1/invitations")
        items = list_resp.json()["items"]
        revoked = [i for i in items if i["id"] == inv_id]
        assert len(revoked) == 1
        assert revoked[0]["status"] == 3  # revoked

    async def test_revoke_nonexistent_returns_404(
        self, admin_client: TestClient
    ):
        resp = admin_client.delete("/api/tenants/1/invitations/99999")
        assert resp.status_code == 404

    async def test_cannot_revoke_accepted_invitation(
        self, admin_client: TestClient, db_session: AsyncSession
    ):
        """Revoking an already-accepted invitation returns 409."""
        import secrets
        from datetime import datetime, timedelta, timezone

        token = secrets.token_urlsafe(48)
        invitation = Invitation(
            tenant_id=1,
            inviter_id=1,
            email="accepted@example.com",
            token=token,
            status=1,  # already accepted
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(invitation)
        await db_session.flush()

        resp = admin_client.delete(f"/api/tenants/1/invitations/{invitation.id}")
        assert resp.status_code == 409

    async def test_revoke_requires_membership_invite(
        self, member_client: TestClient
    ):
        resp = member_client.delete("/api/tenants/1/invitations/1")
        assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/test_invitations.py::TestListInvitations tests/identity/test_invitations.py::TestRevokeInvitation -v
```

Expected: FAIL (endpoints not found — 404)

- [ ] **Step 3: Implement list and revoke endpoints**

Add to `admin_writes.py`, after the create_invitation endpoint:

```python
@router.get(
    "/api/tenants/{tid}/invitations",
    dependencies=[Depends(requires("membership:read", "tenant"))],
)
async def list_invitations(
    tid: int,
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    offset: int = 0,
) -> dict:
    total_q = select(Invitation).where(Invitation.tenant_id == tid)
    items_q = (
        select(Invitation)
        .where(Invitation.tenant_id == tid)
        .order_by(Invitation.created_at.desc())
        .offset(offset)
        .limit(min(limit, 200))
    )
    total = (await session.execute(total_q.with_only_columns(Invitation.id))).scalars().all()
    items = (await session.execute(items_q)).scalars().all()
    return {"items": [_invitation_out(inv) for inv in items], "total": len(total)}


@router.delete(
    "/api/tenants/{tid}/invitations/{iid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requires("membership:invite", "tenant"))],
)
async def revoke_invitation(
    tid: int,
    iid: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    invitation = (await session.execute(
        select(Invitation).where(Invitation.id == iid, Invitation.tenant_id == tid)
    )).scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invitation not found")

    if invitation.status not in (0,):  # only pending can be revoked
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "only pending invitations can be revoked",
        )

    invitation.status = 3  # revoked
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/test_invitations.py::TestListInvitations tests/identity/test_invitations.py::TestRevokeInvitation -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/identity/routers/admin_writes.py \
        backend/tests/identity/test_invitations.py
git commit -m "feat(identity): add list and revoke invitation endpoints"
```

---

### Task 4: User Registration Endpoint

**Files:**
- Create: `backend/tests/identity/test_registration.py`
- Modify: `backend/app/gateway/identity/routers/auth.py`

- [ ] **Step 1: Write the failing tests for registration**

```python
"""Tests for POST /api/auth/register."""
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.identity.models.invitation import Invitation
from app.gateway.identity.models.user import User, Membership


class TestRegister:
    async def test_register_with_valid_invitation(
        self,
        anon_client: TestClient,
        db_session: AsyncSession,
    ):
        """Full happy path: create invitation, register with token, verify membership."""
        token = secrets.token_urlsafe(48)
        invitation = Invitation(
            tenant_id=1,  # bootstrap default tenant
            inviter_id=1,  # bootstrap admin
            email="register-test@example.com",
            token=token,
            status=0,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(invitation)
        await db_session.flush()

        body = {
            "invitation_token": token,
            "password": "securepass123",
            "display_name": "Test User",
        }
        resp = anon_client.post("/api/auth/register", json=body)
        assert resp.status_code == 201

        data = resp.json()
        assert data["email"] == "register-test@example.com"
        assert data["status"] == "ok"

        # Verify user was created
        stmt = select(User).where(User.email == "register-test@example.com")
        user = (await db_session.execute(stmt)).scalar_one_or_none()
        assert user is not None
        assert user.password_hash is not None
        assert user.status == 1

        # Verify membership was created
        member_stmt = select(Membership).where(
            Membership.user_id == user.id,
            Membership.tenant_id == 1,
        )
        member = (await db_session.execute(member_stmt)).scalar_one_or_none()
        assert member is not None

        # Verify invitation was marked accepted
        await db_session.refresh(invitation)
        assert invitation.status == 1
        assert invitation.accepted_by == user.id

        # Verify cookie is set (user is logged in)
        assert "deerflow_session" in resp.cookies

    async def test_register_invalid_token(self, anon_client: TestClient):
        body = {"invitation_token": "not-a-real-token", "password": "securepass123"}
        resp = anon_client.post("/api/auth/register", json=body)
        assert resp.status_code == 404

    async def test_register_weak_password(self, anon_client: TestClient):
        body = {"invitation_token": "anything", "password": "123"}
        resp = anon_client.post("/api/auth/register", json=body)
        assert resp.status_code == 422

    async def test_register_expired_invitation(
        self, anon_client: TestClient, db_session: AsyncSession
    ):
        token = secrets.token_urlsafe(48)
        invitation = Invitation(
            tenant_id=1,
            inviter_id=1,
            email="expired@example.com",
            token=token,
            status=0,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db_session.add(invitation)
        await db_session.flush()

        body = {"invitation_token": token, "password": "securepass123"}
        resp = anon_client.post("/api/auth/register", json=body)
        assert resp.status_code == 410

    async def test_register_revoked_invitation(
        self, anon_client: TestClient, db_session: AsyncSession
    ):
        token = secrets.token_urlsafe(48)
        invitation = Invitation(
            tenant_id=1,
            inviter_id=1,
            email="revoked@example.com",
            token=token,
            status=3,  # revoked
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(invitation)
        await db_session.flush()

        body = {"invitation_token": token, "password": "securepass123"}
        resp = anon_client.post("/api/auth/register", json=body)
        assert resp.status_code == 410

    async def test_register_already_member(
        self, anon_client: TestClient, db_session: AsyncSession
    ):
        """If the invited email is already a member of the tenant, return 409."""
        user = User(
            email="existing@example.com",
            display_name="Existing",
            status=1,
            password_hash=bcrypt.hashpw("oldpass123".encode(), bcrypt.gensalt()).decode(),
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(Membership(user_id=user.id, tenant_id=1))
        await db_session.flush()

        token = secrets.token_urlsafe(48)
        invitation = Invitation(
            tenant_id=1,
            inviter_id=1,
            email="existing@example.com",
            token=token,
            status=0,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(invitation)
        await db_session.flush()

        body = {"invitation_token": token, "password": "securepass123"}
        resp = anon_client.post("/api/auth/register", json=body)
        assert resp.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration.py::TestRegister -v
```

Expected: FAIL (endpoint not found — 404)

- [ ] **Step 3: Implement the register endpoint in auth.py**

Add the `RegisterIn` schema (after the existing schemas):

```python
class RegisterIn(BaseModel):
    invitation_token: str
    password: str
    display_name: str | None = None

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v
```

Add the import for `Invitation` at the top of `auth.py`:

```python
from app.gateway.identity.models.invitation import Invitation
```

Add the register endpoint (after `password_login`):

```python
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, request: Request, response: Response):
    """Register a new user via invitation token.

    The invitation token proves which tenant the user belongs to.
    On success the user is logged in (session cookie set).
    """
    rt = get_runtime()
    ip = _client_ip(request)

    async with rt.session_maker() as db:
        # Look up the invitation by token
        invitation = (
            await db.execute(
                select(Invitation).where(Invitation.token == body.invitation_token)
            )
        ).scalar_one_or_none()

        if invitation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invalid invitation token")

        # Check invitation status
        if invitation.status == 1:
            raise HTTPException(status.HTTP_410_GONE, "invitation already accepted")
        if invitation.status == 3:
            raise HTTPException(status.HTTP_410_GONE, "invitation has been revoked")
        if invitation.expires_at < datetime.now(timezone.utc):
            # Mark as expired so it can't be retried
            invitation.status = 2
            await db.flush()
            raise HTTPException(status.HTTP_410_GONE, "invitation has expired")
        if invitation.status != 0:
            raise HTTPException(status.HTTP_410_GONE, "invitation is no longer valid")

        target_email = invitation.email
        target_tenant_id = invitation.tenant_id

        # Check if user already exists
        existing_user = (
            await db.execute(select(User).where(User.email == target_email))
        ).scalar_one_or_none()

        if existing_user is not None:
            # Check if already a member of this tenant
            existing_membership = (
                await db.execute(
                    select(Membership).where(
                        Membership.user_id == existing_user.id,
                        Membership.tenant_id == target_tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if existing_membership is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "user is already a member of this tenant",
                )
            user = existing_user
            # Set/update password for the existing user
            user.password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
            user.display_name = body.display_name or user.display_name
        else:
            hashed = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
            user = User(
                email=target_email,
                display_name=body.display_name or target_email.split("@")[0],
                status=1,
                password_hash=hashed,
            )
            db.add(user)
            await db.flush()

        # Create membership
        db.add(Membership(user_id=user.id, tenant_id=target_tenant_id))

        # Mark invitation as accepted
        invitation.status = 1
        invitation.accepted_by = user.id

        # Resolve tenant for identity/session
        tenant, workspace = await resolve_active_tenant(db, user, auto_provision=False)
        if tenant is None:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "failed to resolve tenant")

        identity = await build_identity_for_user(db, user, tenant, workspace)
        await db.commit()

    # Create session + set cookie (same pattern as password_login)
    refresh = generate_refresh_token()
    sess = await rt.session_store.create(
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        refresh_token=refresh,
        ip=ip,
        ua=_user_agent(request),
    )
    access_token = _issue_access_for(identity, sess.sid)

    response.set_cookie(
        rt.cookie_name,
        access_token,
        httponly=True,
        secure=rt.cookie_secure,
        samesite="lax",
        max_age=rt.access_ttl_sec,
        path="/",
    )
    return {"status": "ok", "email": target_email}
```

We also need to add these imports to `auth.py`:

```python
from datetime import datetime, timezone
from app.gateway.identity.models.user import Membership
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration.py::TestRegister -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/identity/routers/auth.py \
        backend/tests/identity/test_registration.py
git commit -m "feat(identity): add POST /api/auth/register endpoint"
```

---

### Task 5: Integration & Edge Case Verification

**Files:**
- Modify: `backend/tests/identity/test_registration.py`

- [ ] **Step 1: Add integration test for double-use prevention**

Add to `test_registration.py`:

```python
    async def test_register_twice_same_token_fails(
        self, anon_client: TestClient, db_session: AsyncSession
    ):
        """Using the same invitation token twice should fail on the second attempt."""
        import secrets
        from datetime import datetime, timedelta, timezone

        token = secrets.token_urlsafe(48)
        invitation = Invitation(
            tenant_id=1,
            inviter_id=1,
            email="doubleuse@example.com",
            token=token,
            status=0,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(invitation)
        await db_session.flush()

        # First registration
        body = {"invitation_token": token, "password": "securepass123"}
        resp1 = anon_client.post("/api/auth/register", json=body)
        assert resp1.status_code == 201

        # Second registration with same token
        resp2 = anon_client.post("/api/auth/register", json=body)
        assert resp2.status_code == 410
```

- [ ] **Step 2: Run full test suite for invitation + registration**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/test_invitations.py tests/identity/test_registration.py -v
```

Expected: all tests PASS

- [ ] **Step 3: Run the full identity test suite to check for regressions**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/ -v
```

Expected: no regressions (all previously passing tests still pass)

- [ ] **Step 4: Commit**

```bash
git add backend/tests/identity/test_registration.py
git commit -m "test(identity): add double-use prevention test for registration"
```

---

## Summary

After all tasks are committed, the following will be live:

| Method | Path | Auth | Permission | Status |
|--------|------|------|------------|--------|
| `POST` | `/api/tenants/{tid}/invitations` | Required | `membership:invite` | New |
| `GET` | `/api/tenants/{tid}/invitations` | Required | `membership:read` | New |
| `DELETE` | `/api/tenants/{tid}/invitations/{iid}` | Required | `membership:invite` | New |
| `POST` | `/api/auth/register` | None (public) | — | New |

**Registration flow:**
1. Admin creates invitation via `POST /api/tenants/{tid}/invitations` {email, expires_in_days}
2. Admin shares the invitation link (containing the token) with the user out-of-band
3. User calls `POST /api/auth/register` {invitation_token, password, display_name?}
4. System validates token → creates/updates user → creates membership → marks invitation accepted → logs user in (sets session cookie)

**Invariant:** The invitation token is the identity-proof — only someone who receives it from an authorized admin can join the target tenant. The token is never exposed in API responses (only stored in the DB), so the invitation link must be shared through an external channel (email, Slack, etc.).
