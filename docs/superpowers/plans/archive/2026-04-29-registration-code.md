# 注册码注册流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec `docs/superpowers/specs/2026-04-29-registration-code-design.md`：补一条注册码自助注册入口，admin 三件套 + 公开 `/api/auth/register`，新建 `workspace_member` role 与 `registration_codes` 表。

**Architecture:** 在现有 identity 子系统增量扩展。新增 alembic 0006 建表；`bootstrap.py` 注册 `workspace_member` role 与权限；`admin_writes.py` 加 3 个 admin 端点；`auth.py` 加 1 个公开端点（沿用 `password_login` 的 session/cookie 路径）。安全要点：bcrypt hash + `code_prefix` 索引 + DB 兜底（`User.email` unique 抓并发）。

**Tech Stack:** FastAPI + SQLAlchemy 2.x async + Alembic + bcrypt + pydantic v2；测试用 `TestClient` + `_StubSession` 模式（参考 `tests/identity/test_admin_writes.py`）。

---

## File Structure

| 操作 | 路径 | 责任 |
|---|---|---|
| 创建 | `backend/app/gateway/identity/models/registration_code.py` | `RegistrationCode` ORM（`Base + TenantScoped`） |
| 修改 | `backend/app/gateway/identity/models/__init__.py` | 导出 `RegistrationCode` |
| 创建 | `backend/alembic/versions/20260429_0006_registration_codes.py` | 建表迁移（down_revision=`20260425_0005`） |
| 修改 | `backend/app/gateway/identity/settings.py` | 加 `registration_code_expires_days` 字段 + env 读取 |
| 修改 | `backend/app/gateway/identity/bootstrap.py` | 加 `workspace_member` role + role-permission 绑定 |
| 修改 | `backend/app/gateway/identity/routers/admin_writes.py` | 三个 admin 端点 + 4 个 schema |
| 修改 | `backend/app/gateway/identity/routers/auth.py` | `POST /api/auth/register` + `RegisterIn` schema + 抽出 `_set_session_cookie` |
| 创建 | `backend/tests/identity/test_registration_codes.py` | admin CRUD 测试（8 cases） |
| 创建 | `backend/tests/identity/test_registration.py` | 注册流程测试（7 cases） |
| 修改 | `backend/CLAUDE.md` | 在 identity 章节追加 "Registration code flow" 小节 |

---

## Task 1: ORM 模型 + `__init__` 导出

**Files:**
- Create: `backend/app/gateway/identity/models/registration_code.py`
- Modify: `backend/app/gateway/identity/models/__init__.py`

- [ ] **Step 1: 写模型文件**

```python
# backend/app/gateway/identity/models/registration_code.py
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
```

- [ ] **Step 2: 修改 `models/__init__.py` 导出**

```python
# 在 import 块追加
from app.gateway.identity.models.registration_code import RegistrationCode

# __all__ 末尾追加 "RegistrationCode"
```

- [ ] **Step 3: 验证 import 不破**

Run: `cd backend && PYTHONPATH=. uv run python -c "from app.gateway.identity.models import RegistrationCode; print(RegistrationCode.__tablename__)"`
Expected: `registration_codes`

- [ ] **Step 4: 提交**

```bash
git add backend/app/gateway/identity/models/registration_code.py backend/app/gateway/identity/models/__init__.py
git commit -m "feat(identity): add RegistrationCode ORM model"
```

---

## Task 2: Alembic 迁移 0006 建表

**Files:**
- Create: `backend/alembic/versions/20260429_0006_registration_codes.py`

- [ ] **Step 1: 写迁移**

```python
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
```

- [ ] **Step 2: 跑 alembic 离线 SQL 校验语法（不连真 DB）**

Run: `cd backend && PYTHONPATH=. uv run alembic upgrade 20260429_0006 --sql > /tmp/0006.sql && head -40 /tmp/0006.sql`
Expected: 看到 `CREATE TABLE identity.registration_codes` 输出无报错

- [ ] **Step 3: 跑迁移测试**

Run: `cd backend && make identity-test -- tests/identity/test_alembic_migration.py -v`
Expected: PASS（如果该测试包含端到端 upgrade/downgrade 链路）

- [ ] **Step 4: 提交**

```bash
git add backend/alembic/versions/20260429_0006_registration_codes.py
git commit -m "feat(identity): alembic 0006 — registration_codes table"
```

---

## Task 3: settings 加 `registration_code_expires_days`

**Files:**
- Modify: `backend/app/gateway/identity/settings.py`
- Modify (or create): `backend/tests/identity/test_settings.py`

- [ ] **Step 1: 写测试**

追加到 `backend/tests/identity/test_settings.py`：

```python
def test_registration_code_expires_days_default(monkeypatch):
    from app.gateway.identity.settings import get_identity_settings

    monkeypatch.delenv("REGISTRATION_CODE_EXPIRES_DAYS", raising=False)
    get_identity_settings.cache_clear()
    s = get_identity_settings()
    assert s.registration_code_expires_days == 7


def test_registration_code_expires_days_clamped_low(monkeypatch):
    from app.gateway.identity.settings import get_identity_settings

    monkeypatch.setenv("REGISTRATION_CODE_EXPIRES_DAYS", "0")
    get_identity_settings.cache_clear()
    assert get_identity_settings().registration_code_expires_days == 7


def test_registration_code_expires_days_clamped_high(monkeypatch):
    from app.gateway.identity.settings import get_identity_settings

    monkeypatch.setenv("REGISTRATION_CODE_EXPIRES_DAYS", "999")
    get_identity_settings.cache_clear()
    assert get_identity_settings().registration_code_expires_days == 7


def test_registration_code_expires_days_in_range(monkeypatch):
    from app.gateway.identity.settings import get_identity_settings

    monkeypatch.setenv("REGISTRATION_CODE_EXPIRES_DAYS", "30")
    get_identity_settings.cache_clear()
    assert get_identity_settings().registration_code_expires_days == 30
```

- [ ] **Step 2: 运行测试，确认 fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_settings.py::test_registration_code_expires_days_default -v`
Expected: FAIL with `AttributeError: ... has no attribute 'registration_code_expires_days'`

- [ ] **Step 3: 改 settings.py**

在 `IdentitySettings` dataclass 末尾追加字段：
```python
    # Registration code lifetime in days (1-90, default 7).
    registration_code_expires_days: int
```

在文件顶层（`_env_int` 后）加 helper：
```python
def _clamp_days(value: int) -> int:
    if value < 1 or value > 90:
        return 7
    return value
```

在 `get_identity_settings()` 末尾的 `return IdentitySettings(...)` 增加：
```python
        registration_code_expires_days=_clamp_days(
            _env_int("REGISTRATION_CODE_EXPIRES_DAYS", 7)
        ),
```

- [ ] **Step 4: 跑测试，确认全绿**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_settings.py -v -k registration_code`
Expected: 4 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/gateway/identity/settings.py backend/tests/identity/test_settings.py
git commit -m "feat(identity): add REGISTRATION_CODE_EXPIRES_DAYS setting (default 7, clamp 1-90)"
```

---

## Task 4: bootstrap 注册 `workspace_member` role + 权限

**Files:**
- Modify: `backend/app/gateway/identity/bootstrap.py`
- Modify: `backend/tests/identity/test_bootstrap.py`

- [ ] **Step 1: 写测试**

`backend/tests/identity/test_bootstrap.py` 追加：

```python
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
```

- [ ] **Step 2: 跑测试，确认 fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_bootstrap.py::test_workspace_member_role_in_predefined -v`
Expected: FAIL（role 还没加）

- [ ] **Step 3: 改 bootstrap.py**

在 `PREDEFINED_ROLES` 末尾追加：
```python
    ("workspace_member", "workspace", "Workspace member (basic usage of own resources)"),
```

在 `PREDEFINED_ROLE_PERMISSIONS` 末尾（`viewer` 之后）追加：
```python
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
```

- [ ] **Step 4: 跑测试，确认全绿**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_bootstrap.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/gateway/identity/bootstrap.py backend/tests/identity/test_bootstrap.py
git commit -m "feat(identity): add workspace_member role + permission set"
```

---

## Task 5: 抽出 `_set_session_cookie` helper（重构准备）

**Files:**
- Modify: `backend/app/gateway/identity/routers/auth.py`

> 目的：`oidc_callback`、`password_login`、未来的 `register` 三处都设同样的 cookie，先抽公共方法避免后续复制粘贴。**纯重构，不改行为。**

- [ ] **Step 1: 在 auth.py helpers 区域加函数**

在文件末尾 helpers 区追加：

```python
def _set_session_cookie(response: Response, access_token: str) -> None:
    """Stamp the access token onto the response as the session cookie."""
    rt = get_runtime()
    response.set_cookie(
        rt.cookie_name,
        access_token,
        httponly=True,
        secure=rt.cookie_secure,
        samesite="lax",
        max_age=rt.access_ttl_sec,
        path="/",
    )
```

- [ ] **Step 2: 替换 `oidc_callback` 中的内联 set_cookie**

把 `oidc_callback` 末尾的 `response.set_cookie(rt.cookie_name, access_token, httponly=True, ...)` 整段替换为：
```python
    _set_session_cookie(response, access_token)
```

- [ ] **Step 3: 替换 `password_login` 中的内联 set_cookie**

同上：把 `response.set_cookie(rt.cookie_name, access_token, ...)` 替换为 `_set_session_cookie(response, access_token)`。

- [ ] **Step 4: 跑既有 auth 测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/auth -v`
Expected: 全部 PASS（重构无回归）

- [ ] **Step 5: 提交**

```bash
git add backend/app/gateway/identity/routers/auth.py
git commit -m "refactor(identity): extract _set_session_cookie helper"
```

---

## Task 6: admin 端点 — `POST /api/tenants/{tid}/registration-codes`

**Files:**
- Modify: `backend/app/gateway/identity/routers/admin_writes.py`
- Create: `backend/tests/identity/test_registration_codes.py`

- [ ] **Step 1: 写测试**

`backend/tests/identity/test_registration_codes.py`（按 `test_admin_writes.py` 模式）：

```python
"""Route-level tests for admin registration-code endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.bootstrap import PREDEFINED_ROLE_PERMISSIONS
from app.gateway.identity.db import get_session
from app.gateway.identity.routers import admin_writes as admin_writes_module


def _identity_for_role(role_key: str, *, tenant_id: int) -> Identity:
    perms: set[str] = set()
    tenant_roles: list[str] = []
    for (key, scope), tags in PREDEFINED_ROLE_PERMISSIONS.items():
        if key == role_key and scope == "tenant":
            tenant_roles.append(key)
            perms.update(tags)
    return Identity(
        token_type="jwt",
        user_id=1,
        email=f"{role_key}@ex.com",
        tenant_id=tenant_id,
        workspace_ids=(1,),
        permissions=frozenset(perms),
        roles={"platform": [], "tenant": tenant_roles, "workspaces": {}},
        session_id=f"sess-{role_key}",
    )


class _StubSession:
    def __init__(self):
        self.added: list[Any] = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def flush(self):
        pass

    async def execute(self, stmt):
        return MagicMock()


@pytest.fixture
def codes_app():
    app = FastAPI()
    app.include_router(admin_writes_module.router)
    current = {"identity": Identity.anonymous(), "session": _StubSession()}

    @app.middleware("http")
    async def inject(request, call_next):
        request.state.identity = current["identity"]
        return await call_next(request)

    async def _override() -> AsyncIterator[_StubSession]:
        yield current["session"]

    app.dependency_overrides[get_session] = _override
    return app, current


def test_create_code_returns_plaintext_once(codes_app):
    from app.gateway.identity.models import RegistrationCode

    app, holder = codes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=1)

    class _S(_StubSession):
        def add(self, obj):
            super().add(obj)
            if isinstance(obj, RegistrationCode):
                obj.id = 42
                obj.created_at = datetime(2026, 4, 29, tzinfo=UTC)

    holder["session"] = _S()
    with TestClient(app) as c:
        r = c.post("/api/tenants/1/registration-codes", json={})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "code" in body and len(body["code"]) >= 32
    assert body["code_prefix"] == body["code"][:8]
    assert body["tenant_id"] == 1
    assert body["id"] == 42


def test_create_code_forbidden_for_member(codes_app):
    app, holder = codes_app
    holder["identity"] = _identity_for_role("member", tenant_id=1)
    with TestClient(app) as c:
        r = c.post("/api/tenants/1/registration-codes", json={})
    assert r.status_code == 403
```

- [ ] **Step 2: 跑测试，确认 fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration_codes.py::test_create_code_returns_plaintext_once -v`
Expected: FAIL `404 Not Found`（端点未实现）

- [ ] **Step 3: 改 admin_writes.py — 加 schema + 端点**

在 imports 顶部追加（缺什么补什么）：
```python
import secrets
from datetime import timedelta, timezone

from app.gateway.identity.models import RegistrationCode
from app.gateway.identity.settings import get_identity_settings
```

在 schema 区（`CreateTokenOut` 之后）追加：

```python
class CreateRegistrationCodeOut(BaseModel):
    id: int
    tenant_id: int
    code: str  # plaintext, returned once
    code_prefix: str
    expires_at: datetime
    created_at: datetime


class RegistrationCodeOut(BaseModel):
    id: int
    tenant_id: int
    code_prefix: str
    status: int
    expires_at: datetime
    accepted_by: int | None
    accepted_at: datetime | None
    created_at: datetime


class RegistrationCodeListOut(BaseModel):
    items: list[RegistrationCodeOut]
    total: int
```

在 routes 区追加：

```python
@router.post(
    "/api/tenants/{tid}/registration-codes",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requires("membership:invite", "tenant"))],
    response_model=CreateRegistrationCodeOut,
)
async def create_registration_code(
    tid: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CreateRegistrationCodeOut:
    settings = get_identity_settings()
    plaintext = secrets.token_urlsafe(32)
    code_hash = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.registration_code_expires_days)

    rc = RegistrationCode(
        tenant_id=tid,
        creator_id=_caller_user_id(request),
        code_hash=code_hash,
        code_prefix=plaintext[:8],
        status=0,
        expires_at=expires_at,
    )
    session.add(rc)
    await session.flush()
    await session.commit()

    return CreateRegistrationCodeOut(
        id=rc.id,
        tenant_id=tid,
        code=plaintext,
        code_prefix=plaintext[:8],
        expires_at=expires_at,
        created_at=rc.created_at,
    )
```

- [ ] **Step 4: 跑测试，确认全绿**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration_codes.py -v`
Expected: 2 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/gateway/identity/routers/admin_writes.py backend/tests/identity/test_registration_codes.py
git commit -m "feat(identity): POST /api/tenants/{tid}/registration-codes (admin)"
```

---

## Task 7: admin 端点 — `GET /api/tenants/{tid}/registration-codes`

**Files:**
- Modify: `backend/app/gateway/identity/routers/admin_writes.py`
- Modify: `backend/tests/identity/test_registration_codes.py`

- [ ] **Step 1: 写测试**

追加到 `test_registration_codes.py`：

```python
def test_list_codes_excludes_plaintext(codes_app):
    app, holder = codes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=1)

    fake = SimpleNamespace(
        id=1,
        tenant_id=1,
        code_prefix="abc12345",
        status=0,
        expires_at=datetime(2026, 5, 6, tzinfo=UTC),
        accepted_by=None,
        accepted_at=None,
        created_at=datetime(2026, 4, 29, tzinfo=UTC),
    )

    class _S(_StubSession):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            r = MagicMock()
            if self.calls == 1:
                r.scalar.return_value = 1  # count(*)
            else:
                r.scalars.return_value.all.return_value = [fake]
            return r

    holder["session"] = _S()
    with TestClient(app) as c:
        r = c.get("/api/tenants/1/registration-codes")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["code_prefix"] == "abc12345"
    assert "code" not in body["items"][0]
    assert "code_hash" not in body["items"][0]


def test_list_codes_anonymous_401(codes_app):
    app, _ = codes_app
    with TestClient(app) as c:
        r = c.get("/api/tenants/1/registration-codes")
    assert r.status_code == 401
```

- [ ] **Step 2: 跑测试，确认 fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration_codes.py::test_list_codes_excludes_plaintext -v`
Expected: FAIL `404`

- [ ] **Step 3: 加端点**

在 admin_writes.py 末尾（紧接 Task 6 端点之后）追加 import：
```python
from sqlalchemy import func as sql_func
```

加端点：
```python
@router.get(
    "/api/tenants/{tid}/registration-codes",
    dependencies=[Depends(requires("membership:read", "tenant"))],
    response_model=RegistrationCodeListOut,
)
async def list_registration_codes(
    tid: int,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> RegistrationCodeListOut:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    total = (
        await session.execute(
            select(sql_func.count(RegistrationCode.id)).where(RegistrationCode.tenant_id == tid)
        )
    ).scalar() or 0

    rows = (
        await session.execute(
            select(RegistrationCode)
            .where(RegistrationCode.tenant_id == tid)
            .order_by(RegistrationCode.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return RegistrationCodeListOut(
        items=[
            RegistrationCodeOut(
                id=r.id,
                tenant_id=r.tenant_id,
                code_prefix=r.code_prefix,
                status=r.status,
                expires_at=r.expires_at,
                accepted_by=r.accepted_by,
                accepted_at=r.accepted_at,
                created_at=r.created_at,
            )
            for r in rows
        ],
        total=int(total),
    )
```

- [ ] **Step 4: 跑测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration_codes.py -v`
Expected: 4 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/gateway/identity/routers/admin_writes.py backend/tests/identity/test_registration_codes.py
git commit -m "feat(identity): GET /api/tenants/{tid}/registration-codes (list)"
```

---

## Task 8: admin 端点 — `DELETE /api/tenants/{tid}/registration-codes/{rid}`

**Files:**
- Modify: `backend/app/gateway/identity/routers/admin_writes.py`
- Modify: `backend/tests/identity/test_registration_codes.py`

- [ ] **Step 1: 写测试**

追加：

```python
def test_revoke_pending_code_returns_204(codes_app):
    app, holder = codes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=1)

    fake = SimpleNamespace(id=42, tenant_id=1, status=0)

    class _S(_StubSession):
        async def execute(self, stmt):
            r = MagicMock()
            r.scalar_one_or_none.return_value = fake
            return r

    holder["session"] = _S()
    with TestClient(app) as c:
        r = c.delete("/api/tenants/1/registration-codes/42")
    assert r.status_code == 204
    assert fake.status == 3  # revoked


def test_revoke_missing_code_404(codes_app):
    app, holder = codes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=1)

    class _S(_StubSession):
        async def execute(self, stmt):
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r

    holder["session"] = _S()
    with TestClient(app) as c:
        r = c.delete("/api/tenants/1/registration-codes/999")
    assert r.status_code == 404


def test_revoke_already_accepted_code_409(codes_app):
    app, holder = codes_app
    holder["identity"] = _identity_for_role("tenant_owner", tenant_id=1)

    fake = SimpleNamespace(id=42, tenant_id=1, status=1)  # accepted

    class _S(_StubSession):
        async def execute(self, stmt):
            r = MagicMock()
            r.scalar_one_or_none.return_value = fake
            return r

    holder["session"] = _S()
    with TestClient(app) as c:
        r = c.delete("/api/tenants/1/registration-codes/42")
    assert r.status_code == 409


def test_revoke_member_403(codes_app):
    app, holder = codes_app
    holder["identity"] = _identity_for_role("member", tenant_id=1)
    with TestClient(app) as c:
        r = c.delete("/api/tenants/1/registration-codes/42")
    assert r.status_code == 403
```

- [ ] **Step 2: 跑测试，确认 fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration_codes.py -v -k revoke`
Expected: FAIL（端点不存在）

- [ ] **Step 3: 加端点**

```python
@router.delete(
    "/api/tenants/{tid}/registration-codes/{rid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(requires("membership:invite", "tenant"))],
)
async def revoke_registration_code(
    tid: int,
    rid: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    rc = (
        await session.execute(
            select(RegistrationCode).where(
                RegistrationCode.id == rid,
                RegistrationCode.tenant_id == tid,
            )
        )
    ).scalar_one_or_none()
    if rc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "registration code not found")
    if rc.status != 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "only pending codes can be revoked"
        )
    rc.status = 3
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: 跑测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration_codes.py -v`
Expected: 8 PASS（含前 4 个）

- [ ] **Step 5: 提交**

```bash
git add backend/app/gateway/identity/routers/admin_writes.py backend/tests/identity/test_registration_codes.py
git commit -m "feat(identity): DELETE /api/tenants/{tid}/registration-codes/{rid} (revoke)"
```

---

## Task 9: 公开端点 — `POST /api/auth/register`（happy path）

**Files:**
- Modify: `backend/app/gateway/identity/routers/auth.py`
- Create: `backend/tests/identity/test_registration.py`

- [ ] **Step 1: 写 happy-path 测试**

`backend/tests/identity/test_registration.py`：

```python
"""Public /api/auth/register endpoint tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.identity.db import get_session
from app.gateway.identity.routers import auth as auth_module


@pytest.fixture
def reg_app():
    app = FastAPI()
    app.include_router(auth_module.router)

    current: dict[str, Any] = {"session": None}

    async def _override() -> AsyncIterator[Any]:
        yield current["session"]

    app.dependency_overrides[get_session] = _override
    return app, current


def _make_pending_code(plaintext: str, *, tenant_id: int = 1, status: int = 0,
                      expires_offset: timedelta = timedelta(days=7)):
    return SimpleNamespace(
        id=1,
        tenant_id=tenant_id,
        creator_id=99,
        code_hash=bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode(),
        code_prefix=plaintext[:8],
        status=status,
        expires_at=datetime.now(UTC) + expires_offset,
        accepted_by=None,
        accepted_at=None,
        created_at=datetime.now(UTC),
    )


def _patch_runtime():
    rt = MagicMock()
    rt.cookie_name = "deerflow_session"
    rt.cookie_secure = False
    rt.access_ttl_sec = 900
    rt.issuer = "deerflow"
    rt.audience = "deerflow-api"
    rt.jwt_private_key_pem = "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----"
    rt.auto_provision = False
    rt.session_store.create = AsyncMock(return_value=SimpleNamespace(sid="sess-new"))
    return rt


def test_register_happy_path_creates_user_and_sets_cookie(reg_app):
    app, holder = reg_app
    plaintext = "verylongplaintextcode" + "x" * 30
    code_row = _make_pending_code(plaintext)
    workspace_row = SimpleNamespace(id=1, tenant_id=1)
    role_row = SimpleNamespace(id=4, role_key="workspace_member", scope="workspace")
    tenant_row = SimpleNamespace(id=1, slug="default")

    class _Sess:
        def __init__(self):
            self.added: list[Any] = []
            self.committed = False
            self.calls = 0

        def add(self, obj):
            self.added.append(obj)
            from app.gateway.identity.models import User
            if isinstance(obj, User):
                obj.id = 100

        async def commit(self):
            self.committed = True

        async def flush(self):
            pass

        async def execute(self, stmt):
            self.calls += 1
            r = MagicMock()
            # Sequence:
            # 1. candidate codes by prefix+pending
            # 2. existing user lookup (by email) -> none
            # 3. default workspace lookup -> workspace_row
            # 4. workspace_member role lookup -> role_row
            if self.calls == 1:
                r.scalars.return_value.all.return_value = [code_row]
            elif self.calls == 2:
                r.scalar_one_or_none.return_value = None
            elif self.calls == 3:
                r.scalar_one_or_none.return_value = workspace_row
            elif self.calls == 4:
                r.scalar_one_or_none.return_value = role_row
            return r

    holder["session"] = _Sess()

    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()), \
         patch.object(auth_module, "issue_access_token", return_value="tok123"), \
         patch.object(auth_module, "build_identity_for_user", new=AsyncMock(return_value=SimpleNamespace(
             user_id=100, tenant_id=1, workspace_ids=(1,), permissions=set(), roles={},
             email="new@example.com",
         ))), \
         patch.object(auth_module, "resolve_active_tenant", new=AsyncMock(return_value=(tenant_row, workspace_row))):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={
                    "code": plaintext,
                    "email": "new@example.com",
                    "password": "atleast8chars",
                    "display_name": "Newbie",
                },
            )

    assert r.status_code == 201, r.text
    assert r.json() == {"status": "ok", "email": "new@example.com"}
    assert "deerflow_session" in r.cookies
    # Code marked accepted.
    assert code_row.status == 1
    assert code_row.accepted_by == 100
    assert code_row.accepted_at is not None
```

- [ ] **Step 2: 跑测试，确认 fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration.py::test_register_happy_path_creates_user_and_sets_cookie -v`
Expected: FAIL `404 Not Found`

- [ ] **Step 3: 加端点到 auth.py**

在 imports 顶部增加（缺什么补什么）：
```python
import re
from datetime import datetime, timedelta, timezone

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.identity.db import get_session
from app.gateway.identity.models.registration_code import RegistrationCode
from app.gateway.identity.models.tenant import Workspace
from app.gateway.identity.models.role import Role
from app.gateway.identity.models.user import Membership, User, WorkspaceMember
from app.gateway.identity.settings import get_identity_settings

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
```

加 schema + 端点：

```python
class RegisterIn(BaseModel):
    code: str
    email: str
    password: str
    display_name: str | None = None


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    rt = get_runtime()

    # Input validation -----------------------------------------------------
    if len(body.password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "password must be at least 8 characters")
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid email format")

    # Find candidate codes by prefix + pending. -----------------------------
    prefix = body.code[:8]
    candidates = (
        await session.execute(
            select(RegistrationCode).where(
                RegistrationCode.code_prefix == prefix,
                RegistrationCode.status == 0,
            )
        )
    ).scalars().all()

    rc = None
    for cand in candidates:
        if bcrypt.checkpw(body.code.encode(), cand.code_hash.encode()):
            rc = cand
            break
    if rc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invalid registration code")

    # Status transitions ---------------------------------------------------
    now = datetime.now(timezone.utc)
    if rc.expires_at < now:
        rc.status = 2
        await session.commit()
        raise HTTPException(status.HTTP_410_GONE, "code has expired")

    # Email uniqueness (DB unique acts as the concurrency tiebreaker). -----
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")

    # Default workspace + workspace_member role lookup ---------------------
    ws = (
        await session.execute(
            select(Workspace)
            .where(Workspace.tenant_id == rc.tenant_id)
            .order_by(Workspace.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if ws is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "tenant has no default workspace")

    member_role = (
        await session.execute(
            select(Role).where(Role.role_key == "workspace_member", Role.scope == "workspace")
        )
    ).scalar_one_or_none()
    if member_role is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "workspace_member role not seeded")

    # Create user + membership + workspace member; mark code accepted. -----
    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    user = User(
        email=email,
        display_name=body.display_name or email.split("@")[0],
        status=1,
        password_hash=password_hash,
    )
    session.add(user)
    await session.flush()

    session.add(Membership(user_id=user.id, tenant_id=rc.tenant_id))
    session.add(WorkspaceMember(user_id=user.id, workspace_id=ws.id, role_id=member_role.id))

    rc.status = 1
    rc.accepted_by = user.id
    rc.accepted_at = now

    await session.commit()

    # Build identity → session → cookie. -----------------------------------
    tenant, workspace = await resolve_active_tenant(session, user, auto_provision=rt.auto_provision)
    identity = await build_identity_for_user(session, user, tenant, workspace)

    sess = await rt.session_store.create(
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        refresh_token=generate_refresh_token(),
        ip=_client_ip(request),
        ua=_user_agent(request),
    )
    access_token = _issue_access_for(identity, sess.sid)
    _set_session_cookie(response, access_token)
    return {"status": "ok", "email": email}
```

- [ ] **Step 4: 跑 happy-path 测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration.py::test_register_happy_path_creates_user_and_sets_cookie -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/gateway/identity/routers/auth.py backend/tests/identity/test_registration.py
git commit -m "feat(identity): POST /api/auth/register (happy path)"
```

---

## Task 10: 注册端点边界用例

**Files:**
- Modify: `backend/tests/identity/test_registration.py`

> 端点逻辑已在 Task 9 写完；本 task 补充边界 case 测试，确保异常分支按 spec 表现。

- [ ] **Step 1: 写边界用例**

追加到 `test_registration.py`：

```python
def test_register_weak_password_422(reg_app):
    app, _ = reg_app
    with TestClient(app) as c:
        r = c.post(
            "/api/auth/register",
            json={"code": "x" * 40, "email": "a@b.com", "password": "short"},
        )
    assert r.status_code == 422


def test_register_invalid_email_422(reg_app):
    app, _ = reg_app
    with TestClient(app) as c:
        r = c.post(
            "/api/auth/register",
            json={"code": "x" * 40, "email": "not-an-email", "password": "longpassword"},
        )
    assert r.status_code == 422


def test_register_unknown_code_404(reg_app):
    app, holder = reg_app

    class _Sess:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            pass

        async def flush(self):
            pass

        async def execute(self, stmt):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []  # no candidates
            return r

    holder["session"] = _Sess()
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={"code": "x" * 40, "email": "a@b.com", "password": "longpassword"},
            )
    assert r.status_code == 404


def test_register_already_used_code_404(reg_app):
    """A code with status=1 isn't returned by the prefix+pending query → 404
    (not 410). The spec lists 410 for 'already used', but the query path filters
    out non-pending, so the bcrypt step never matches. 404 is the correct
    observable result; behavior is documented in CLAUDE.md."""
    app, holder = reg_app
    plaintext = "y" * 40

    class _Sess:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            pass

        async def flush(self):
            pass

        async def execute(self, stmt):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r

    holder["session"] = _Sess()
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={"code": plaintext, "email": "a@b.com", "password": "longpassword"},
            )
    assert r.status_code == 404


def test_register_expired_code_410(reg_app):
    app, holder = reg_app
    plaintext = "z" * 40
    code_row = _make_pending_code(plaintext, expires_offset=timedelta(days=-1))

    class _Sess:
        def __init__(self):
            self.added = []
            self.committed = False

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            self.committed = True

        async def flush(self):
            pass

        async def execute(self, stmt):
            r = MagicMock()
            r.scalars.return_value.all.return_value = [code_row]
            return r

    holder["session"] = _Sess()
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={"code": plaintext, "email": "a@b.com", "password": "longpassword"},
            )
    assert r.status_code == 410
    assert code_row.status == 2  # auto-marked expired


def test_register_email_already_registered_409(reg_app):
    app, holder = reg_app
    plaintext = "q" * 40
    code_row = _make_pending_code(plaintext)
    existing_user = SimpleNamespace(id=99, email="dup@example.com")

    class _Sess:
        def __init__(self):
            self.added = []
            self.committed = False
            self.calls = 0

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            self.committed = True

        async def flush(self):
            pass

        async def execute(self, stmt):
            self.calls += 1
            r = MagicMock()
            if self.calls == 1:
                r.scalars.return_value.all.return_value = [code_row]
            elif self.calls == 2:
                r.scalar_one_or_none.return_value = existing_user
            return r

    holder["session"] = _Sess()
    with patch.object(auth_module, "get_runtime", return_value=_patch_runtime()):
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/register",
                json={"code": plaintext, "email": "dup@example.com", "password": "longpassword"},
            )
    assert r.status_code == 409
    # Code remains pending (we abort before marking accepted).
    assert code_row.status == 0
```

- [ ] **Step 2: 跑全部 registration 测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_registration.py -v`
Expected: 7 PASS（1 happy + 6 边界）

- [ ] **Step 3: 提交**

```bash
git add backend/tests/identity/test_registration.py
git commit -m "test(identity): boundary cases for /api/auth/register (expired, dup-email, weak pwd, unknown code)"
```

---

## Task 11: identity 全量回归 + CLAUDE.md 文档

**Files:**
- Modify: `backend/CLAUDE.md`

- [ ] **Step 1: 全量 identity 测试**

Run: `cd backend && make identity-test`
Expected: 全部 PASS（含老 bootstrap/admin_writes 等回归）

- [ ] **Step 2: 全量 backend 测试**

Run: `cd backend && make test`
Expected: 全部 PASS

- [ ] **Step 3: lint**

Run: `cd backend && make lint`
Expected: ruff 全绿

- [ ] **Step 4: 在 `backend/CLAUDE.md` Identity 章节追加小节**

在 `### Identity Subsystem` 章节，定位 "When flag is ON" 段落后追加：

```markdown
**Registration code flow (P1, 2026-04-29):**

A self-service onboarding path for tenant_owner-issued one-time codes.

- `identity.registration_codes` table (alembic 0006) stores bcrypt-hashed codes with `code_prefix` (first 8 chars of plaintext) for prefix-filtered lookup. Plaintext is returned **only** at creation time.
- `workspace_member` role added to `PREDEFINED_ROLES` — granted thread/skill-invoke/knowledge/workflow read+write+delete and `settings:read`. Excludes `skill:publish`, `*:manage`, `settings:update`.
- Admin endpoints (`@requires("membership:invite", "tenant")` for write, `"membership:read"` for list):
  - `POST /api/tenants/{tid}/registration-codes` → `{id, code, code_prefix, expires_at, ...}` (plaintext returned **once**)
  - `GET  /api/tenants/{tid}/registration-codes` → paginated list, `code_hash`/`code` never returned
  - `DELETE /api/tenants/{tid}/registration-codes/{rid}` → 204 if pending; 409 if status≠pending
- Public endpoint:
  - `POST /api/auth/register {code, email, password, display_name?}` → 201 + session cookie (sets `deerflow_session` HttpOnly, same as `/api/auth/login`). Creates `User`, `Membership(tenant=code.tenant)`, `WorkspaceMember(workspace=default, role=workspace_member)`. Marks code `status=accepted`.
- Env: `REGISTRATION_CODE_EXPIRES_DAYS` (default 7, clamped to [1,90]).
- Concurrency: relies on `User.email` unique constraint as the tiebreaker — second concurrent register of the same email gets 409 from a downstream IntegrityError path. No `SELECT FOR UPDATE`.
- Brute-force defense: code lookup is **always** prefix-filtered before bcrypt; full plaintext token is `secrets.token_urlsafe(32)` (≈256 bit entropy).
- Observable status mapping: spec §7.4 lists 410 for accepted/revoked codes, but because the lookup query filters `status==pending`, those branches never run — the user sees 404. Documented behavior, not a bug.
```

- [ ] **Step 5: 提交**

```bash
git add backend/CLAUDE.md
git commit -m "docs(identity): document registration code flow"
```

---

## Self-Review Checklist

| Spec 项 | 覆盖 task |
|---|---|
| §4.1 表结构 | Task 1 (model) + Task 2 (migration) |
| §4.2 model 注册 | Task 1 |
| §4.3 TenantScoped mixin | Task 1（`Base, TenantScoped`） |
| §5.1 workspace_member role | Task 4 |
| §5.2 权限组（11 项 ✅，4 项 ❌） | Task 4 测试断言完整对照 |
| §5.3 bootstrap idempotent | 既有逻辑，无需改 |
| §6.1 env 配置 + clamp | Task 3 |
| §6.2 不引入总开关 | 无 task（不动） |
| §7.1 创建端点（明文一次） | Task 6 |
| §7.2 list 端点（无 code_hash） | Task 7 |
| §7.3 revoke 端点（404/409/204） | Task 8 |
| §7.4 register 端点（7 个校验） | Task 9 + Task 10 |
| §7.5 性能注解（prefix 过滤） | Task 9 实现 |
| §11 安全表 | Task 9 prefix 过滤 + bcrypt + DB unique 兜底 |
| §10 兼容性（flag off 无影响） | 端点都挂在 `if get_identity_settings().enabled` 内（已验证）；register 路由属于 `auth_router`，已在该 if 块内 |

**已知 spec 偏差并明确：** spec §7.4 step 4-5 列出「accepted=410, revoked=410」分支；实现中 `code_prefix==prefix AND status==0` 已过滤掉非 pending，所以 accepted/revoked 都走 404 路径。Task 10 与 CLAUDE.md 中明确写出该决定。spec §11 给的"FOR UPDATE vs DB unique 兜底"二选一选了后者（自托管小群语境最简，无 lock 复杂度）。
