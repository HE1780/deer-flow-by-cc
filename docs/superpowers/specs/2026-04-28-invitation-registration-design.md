# 邀请制一般用户注册 — 设计方案

> 状态：待评审 | 日期：2026-04-28 | 关联计划：`docs/superpowers/plans/2026-04-28-invitation-registration.md`

## 1. 需求描述

### 1.1 背景

当前 DeerFlow 身份系统（M1-M7）支持三种用户创建路径：

1. **OIDC 自动配置** — 首次 OIDC 登录时自动创建用户（需 `IDENTITY_AUTO_PROVISION_TENANT=true`，自动创建个人租户）
2. **Bootstrap Admin 种子** — 启动时通过 `DEERFLOW_BOOTSTRAP_ADMIN_EMAIL` 创建平台管理员
3. **管理员 API 直接创建** — `POST /api/tenants/{tid}/users`（需已认证的管理员身份）

**缺失的能力：** 没有面向一般用户的自助注册流程。一般用户无法自行注册并加入已有组织（租户）。

### 1.2 用户角色与注册策略

| 角色 | 注册方式 | 说明 |
|------|---------|------|
| 平台管理员 | 不开放注册 | 通过 Bootstrap 种子 + 严格初始化保障 |
| 组织管理员（租户管理员） | 平台管理员创建 | 调用 Admin API 分配 `tenant_owner` 角色 |
| 一般用户 | **邀请制自助注册**（本次实现） | 组织管理员发邀请，用户凭 token 注册 |

### 1.3 核心问题：身份判断

一般用户注册时需要确定他属于哪个组织（租户）。邀请制方案的核心逻辑是：**由组织管理员预先指定邮箱 + 生成一次性 token，用户注册时携带 token，系统通过 token 反查目标租户，从而完成身份判定。**

### 1.4 功能需求

**FR1 — 创建邀请**
- 组织管理员可通过 API 创建邀请，指定目标邮箱和有效期
- 系统生成加密随机 token（URL-safe，64 字符）
- token 不通过 API 返回（仅存 DB），由管理员通过外部渠道（邮件/Slack 等）发给用户

**FR2 — 查看邀请列表**
- 组织管理员可查看本租户的邀请列表（支持分页）
- 可区分 pending / accepted / expired / revoked 状态

**FR3 — 撤销邀请**
- 组织管理员可撤销尚未被接受的邀请
- 已接受的邀请不可撤销

**FR4 — 用户注册**
- 用户无需登录，调用公开注册端点
- 提供 invitation_token + password（+ 可选 display_name）
- 系统校验 token 有效性（存在、未过期、未被使用、未被撤销）
- 自动创建/复用 User 记录，创建 Membership 关联到目标租户
- 注册成功后自动登录（设置 session cookie）

**FR5 — 安全约束**
- token 一次性使用，注册后标记为 accepted
- token 过期后自动标记为 expired
- 弱密码拒绝（< 8 字符）
- 已在目标租户中的邮箱不能重复注册（409）

---

## 2. 系统现状分析

### 2.1 涉及的数据模型

**已有模型（不变）：**

```
User (identity.users)
├── id BIGINT PK
├── email VARCHAR(255) UNIQUE NOT NULL
├── display_name VARCHAR(128)
├── password_hash TEXT           # M7 新增，bcrypt 哈希
├── status SMALLINT DEFAULT 1   # 1=active, 0=disabled
├── oidc_subject / oidc_provider # OIDC 绑定
└── last_login_at / last_login_ip

Membership (identity.memberships)
├── user_id FK → users
├── tenant_id FK → tenants
├── status SMALLINT DEFAULT 1   # 1=active
└── UNIQUE(user_id, tenant_id)

Tenant (identity.tenants)
├── id BIGINT PK
├── slug VARCHAR(64) UNIQUE
├── name VARCHAR(128)
├── status SMALLINT DEFAULT 1
└── ...
```

**新增模型：**

```
Invitation (identity.invitations)
├── id BIGINT PK
├── tenant_id FK → tenants ON DELETE CASCADE
├── inviter_id FK → users ON DELETE CASCADE
├── email VARCHAR(255) NOT NULL       # 目标邮箱
├── token VARCHAR(128) UNIQUE NOT NULL # secrets.token_urlsafe(48)
├── status SMALLINT DEFAULT 0         # 0=pending, 1=accepted, 2=expired, 3=revoked
├── expires_at TIMESTAMPTZ NOT NULL
├── accepted_by FK → users ON DELETE SET NULL
└── created_at TIMESTAMPTZ DEFAULT now()
```

### 2.2 涉及的 API 端点

**已有（不变）：**
- `POST /api/auth/login` — 密码登录，用于注册后用户再登录
- `POST /api/tenants/{tid}/users` — 管理员直接创建用户（admin_writes.py）

**新增：**

| 方法 | 路径 | 文件 | 权限 | 状态码 |
|------|------|------|------|--------|
| `POST` | `/api/tenants/{tid}/invitations` | `admin_writes.py` | `membership:invite` | 201 |
| `GET` | `/api/tenants/{tid}/invitations` | `admin_writes.py` | `membership:read` | 200 |
| `DELETE` | `/api/tenants/{tid}/invitations/{iid}` | `admin_writes.py` | `membership:invite` | 204 |
| `POST` | `/api/auth/register` | `auth.py` | 无（公开） | 201 |

### 2.3 涉及的认证流程复用

注册端点的登录逻辑完全复用现有密码登录的 session 创建模式（`auth.py:password_login`）：

```python
# 已有模式 (auth.py:221-243)
refresh = generate_refresh_token()
sess = await rt.session_store.create(user_id=..., tenant_id=..., refresh_token=..., ip=..., ua=...)
access_token = _issue_access_for(identity, sess.sid)
response.set_cookie(rt.cookie_name, access_token, httponly=True, secure=..., samesite="lax", max_age=..., path="/")
```

### 2.4 关键文件路径

```
backend/
├── app/gateway/identity/
│   ├── models/
│   │   ├── __init__.py              # [修改] 导出 Invitation
│   │   ├── invitation.py            # [新建] Invitation ORM 模型
│   │   ├── user.py                  # [不改] User, Membership
│   │   ├── tenant.py                # [不改] Tenant, Workspace
│   │   └── base.py                  # [不改] Base
│   ├── routers/
│   │   ├── admin_writes.py          # [修改] 新增 3 个邀请端点
│   │   └── auth.py                  # [修改] 新增 register 端点
│   ├── auth/
│   │   ├── session.py               # [不改] SessionStore
│   │   ├── jwt.py                   # [不改] JWT issue/verify
│   │   ├── identity_factory.py      # [不改] build_identity_for_user, resolve_active_tenant
│   │   └── runtime.py               # [不改] AuthRuntime
│   └── rbac/
│       └── decorator.py             # [不改] @requires()
├── alembic/versions/
│   └── 20260428_0006_invitations.py # [新建] DB migration
└── tests/identity/
    ├── test_invitations.py          # [新建] 邀请 CRUD 测试
    └── test_registration.py         # [新建] 注册流程测试
```

---

## 3. 设计决策

### 3.1 为什么 token 不哈希？

对比 `ApiToken`（bcrypt 哈希存储），Invitation token 选择明文存储，理由：

- token 是一次性使用，生命周期短（默认 7 天）
- 管理员需要在 UI 上复制 token 发给用户（虽然 API 不返回，但管理员可能通过 DB 查询或未来的管理 UI 获取）
- 无需支持 "前缀查找 + 哈希验证" 模式（ApiToken 的 `dft_xxx_xxx` 模式是因为需要在不暴露完整 token 的情况下做前缀检索）
- 即使泄露，影响面有限（只能注册一个已指定邮箱的用户）

### 3.2 为什么注册端点不返回 token 而是直接设置 cookie？

- 与现有 `POST /api/auth/login` 行为一致（密码登录也直接设置 cookie）
- 减少前端改动（注册后用户直接处于登录态，无需二次调用 login）
- Cookie 是 HttpOnly + SameSite=Lax，安全性已保障

### 3.3 为什么邀请端点放在 admin_writes.py 而不是新建文件？

- 邀请端点的权限 `membership:invite` 与同文件的 `create_user` 端点共享
- 邀请是管理员写入操作，与现有文件语义一致
- 文件当前 ~280 行，新增 ~80 行后约 360 行，仍在合理范围

### 3.4 为什么注册不区分 "新用户" 和 "已有用户"？

- 与现有 `POST /api/tenants/{tid}/users`（管理员创建用户）的幂等逻辑一致：按 email 查找，有则复用，无则创建
- 实际场景：管理员可能先用 Admin API 创建了用户，然后用户通过邀请链接完成注册（只是补设密码）

### 3.5 为什么不在注册时分配 workspace 角色？

- 与现有 `create_user` 管理员端点行为一致（只创建 Membership，不分配 workspace）
- Workspace 分配是独立操作（`POST /api/tenants/{tid}/workspaces/{wid}/members`）
- YAGNI：可以在后续按需扩展

---

## 4. 代码修改详案

### 4.1 新建：Invitation 模型

**文件：** `backend/app/gateway/identity/models/invitation.py`

```python
"""Invitation model for user registration via invite tokens."""
import secrets
from datetime import datetime

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
    # 0=pending, 1=accepted, 2=expired, 3=revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("identity.users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 4.2 新建：DB Migration

**文件：** `backend/alembic/versions/20260428_0006_invitations.py`

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
        sa.Column("tenant_id", sa.BigInteger,
                  sa.ForeignKey("identity.tenants.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("inviter_id", sa.BigInteger,
                  sa.ForeignKey("identity.users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("status", sa.SmallInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by", sa.BigInteger,
                  sa.ForeignKey("identity.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token", name="uq_invitations_token"),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_table("invitations", schema="identity")
```

### 4.3 修改：models/__init__.py 导出 Invitation

```python
from app.gateway.identity.models.invitation import Invitation  # 新增这一行
```

并在 `__all__` 列表中加入 `"Invitation"`。

### 4.4 修改：admin_writes.py — 新增邀请管理端点

**新增 Schema（放在 `CreateTokenOut` 之后）：**

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

**新增 Import（文件顶部）：**

```python
from datetime import datetime, timedelta, timezone
from app.gateway.identity.models.invitation import Invitation
```

**新增 Helper：**

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

**新增端点（放在 `create_user` 端点之后）：**

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

    if invitation.status not in (0,):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "only pending invitations can be revoked",
        )

    invitation.status = 3  # revoked
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

### 4.5 修改：auth.py — 新增注册端点

**新增 Schema（放在 `SetPasswordIn` 之后）：**

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

**新增 Import（文件顶部）：**

```python
from datetime import datetime, timezone
from app.gateway.identity.models.invitation import Invitation
from app.gateway.identity.models.user import Membership
```

**新增端点（放在 `password_login` 之后）：**

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
        invitation = (
            await db.execute(
                select(Invitation).where(Invitation.token == body.invitation_token)
            )
        ).scalar_one_or_none()

        if invitation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invalid invitation token")

        if invitation.status == 1:
            raise HTTPException(status.HTTP_410_GONE, "invitation already accepted")
        if invitation.status == 3:
            raise HTTPException(status.HTTP_410_GONE, "invitation has been revoked")
        if invitation.expires_at < datetime.now(timezone.utc):
            invitation.status = 2
            await db.flush()
            raise HTTPException(status.HTTP_410_GONE, "invitation has expired")
        if invitation.status != 0:
            raise HTTPException(status.HTTP_410_GONE, "invitation is no longer valid")

        target_email = invitation.email
        target_tenant_id = invitation.tenant_id

        existing_user = (
            await db.execute(select(User).where(User.email == target_email))
        ).scalar_one_or_none()

        if existing_user is not None:
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

        db.add(Membership(user_id=user.id, tenant_id=target_tenant_id))

        invitation.status = 1
        invitation.accepted_by = user.id

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

### 4.6 新建：测试文件

详见实现计划 `docs/superpowers/plans/2026-04-28-invitation-registration.md`，覆盖：

| 测试类 | 用例数 | 覆盖场景 |
|--------|--------|---------|
| `TestCreateInvitation` | 3 | 正常创建、权限拒绝 (403)、无效邮箱 (422) |
| `TestListInvitations` | 2 | 列表查询、匿名拒绝 (401) |
| `TestRevokeInvitation` | 4 | 正常撤销、不存在 (404)、已接受不可撤销 (409)、权限拒绝 (403) |
| `TestRegister` | 6 | 正常注册、无效 token (404)、弱密码 (422)、过期 (410)、已撤销 (410)、已加入用户 (409) |
| `TestRegister` (Task 5) | 1 | 同一 token 重复使用 (410) |

---

## 5. 不变式与边界条件

- **Token 不通过 API 暴露** — `InvitationOut` 不含 `token` 字段。token 仅在 DB 中存储，由管理员通过外部渠道（邮件/Slack 等）传递
- **Token 一次性使用** — 注册成功后 `status → 1 (accepted)`，不可复用
- **过期处理** — 注册时检测 `expires_at < now`，自动标记 `status → 2 (expired)` 并拒绝
- **重复成员拒绝** — 已在目标租户中的邮箱返回 409
- **管理员已有创建用户的幂等逻辑保持一致** — 注册时如果用户已存在（被管理员预创建），则复用 User 记录，补设密码
- **不分配 workspace** — 与管理员 `create_user` 端点行为一致，workspace 角色另行分配

## 6. 不在本次范围

- 邮件发送基础设施（token 传递由外部渠道完成）
- 邮箱验证（`email_verified` 字段）
- 密码重置流程
- 注册审批流程
- 前端邀请管理 UI（后端 API 先行）
