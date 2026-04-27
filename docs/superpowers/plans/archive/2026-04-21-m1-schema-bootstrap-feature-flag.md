# M1: Identity Schema + Bootstrap + Feature Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the Postgres identity schema, Alembic migrations, seed data bootstrap, and the global `ENABLE_IDENTITY` feature flag (default off) so that the rest of the P0 work has a foundation without breaking any existing behavior.

**Architecture:** Add `identity` schema via Alembic to Postgres (new dependency). Introduce SQLAlchemy async engine + session factory under `app/gateway/identity/db.py`. Wire an idempotent `bootstrap()` that seeds roles, permissions, the `default` tenant, and the first `platform_admin` user. Add `ENABLE_IDENTITY` env var; when off, everything short-circuits and the legacy single-user behavior is preserved. Compose adds a `postgres:16` service and a `redis:7` service (Redis is introduced here to avoid a second dependency bump later).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, asyncpg, alembic, redis[hiredis], pytest + testcontainers, Postgres 16, Redis 7.

**Spec reference:** `docs/superpowers/specs/2026-04-21-deerflow-identity-foundation-design.md` §4 (Data model), §10.1-10.4 (Feature flag, migration stages 0-1, bootstrap), §10.6 (Dependency changes), §10.9 (Dev/CI).

**Scope boundary (non-goals for M1):**
- No OIDC / JWT / API token (M2)
- No RBAC checks wired to routes (M3)
- No middleware registration that enforces identity (stays inert while flag=false)
- No storage path changes (M4)
- No LangGraph integration (M5)
- No audit middleware (M6)
- No admin UI (M7)

M1 delivers: code can run with `ENABLE_IDENTITY=false` exactly as before; with the flag on, Postgres tables exist, seed data is in place, and `bootstrap()` is verified. That's all.

---

## File Structure

### Created

```
backend/app/gateway/identity/
  __init__.py                       # package marker, exports `Identity` dataclass stub
  settings.py                       # reads ENABLE_IDENTITY, DATABASE_URL, REDIS_URL, BOOTSTRAP_ADMIN_EMAIL
  db.py                             # async engine, AsyncSession factory, `get_session` dependency
  bootstrap.py                      # idempotent seed of roles/permissions/default tenant/first admin
  context.py                        # ContextVars for current_identity / current_tenant_id (used later)
  models/
    __init__.py                     # re-exports ORM classes
    base.py                         # DeclarativeBase + TenantScoped/WorkspaceScoped mixins (no event listeners yet)
    tenant.py                       # Tenant, Workspace
    user.py                         # User, Membership, WorkspaceMember
    role.py                         # Role, Permission, RolePermission, UserRole
    token.py                        # ApiToken
    audit.py                        # AuditLog (table only; no writer in M1)

backend/alembic.ini
backend/alembic/
  env.py                            # async Alembic env wired to identity models
  script.py.mako                    # default
  versions/
    20260421_0001_identity_schema.py  # CREATE SCHEMA identity + all 11 tables + indexes

backend/tests/identity/             # new subdir - allowed; conftest auto-discovers
  __init__.py
  conftest.py                       # pg_container, redis_container, db_session, alembic_upgrade fixtures
  test_settings.py                  # settings loading, flag defaults
  test_models.py                    # ORM round-trip + constraint sanity
  test_alembic_migration.py         # upgrade head from empty DB creates all tables + seed
  test_bootstrap.py                 # idempotent seed + first admin creation
  test_feature_flag_offline.py      # flag=false: no DB required, gateway starts without postgres
```

### Modified

```
backend/pyproject.toml               # add sqlalchemy[asyncio], asyncpg, alembic, redis[hiredis], testcontainers (dev)
backend/Makefile                     # add `make db-upgrade`, `make db-downgrade-one`, `make identity-bootstrap`
backend/app/gateway/app.py           # read ENABLE_IDENTITY; if on → init engine in lifespan + run bootstrap
backend/app/gateway/config.py        # expose get_identity_settings()
docker/docker-compose.yaml           # append postgres + redis services + volumes
backend/tests/conftest.py            # no change expected; new identity tests live under tests/identity/ with own conftest
.github/workflows/backend-unit-tests.yml  # new job: backend-identity-tests (pg + redis services)
```

### Intentionally NOT modified in M1

- `backend/packages/harness/deerflow/**` — harness stays untouched (the harness → app boundary test protects us)
- `backend/app/gateway/routers/**` — no router changes until M2+
- `backend/app/gateway/deps.py` — no middleware registration yet
- `skills/` directory layout — M4 owns that
- `frontend/**` — M7 owns UI

---

## Conventions

- **Imports:** `ruff` with `known-first-party = ["deerflow", "app"]`. New identity code imports only `from app.gateway.identity.*` and stdlib / 3rd-party. No harness imports.
- **Lint:** line-length 240, double quotes, 4-space indent. Run `uvx ruff check . && uvx ruff format --check .` before every commit.
- **Tests:** `PYTHONPATH=. uv run pytest tests/identity/ -v`. Integration tests that need Postgres gate on `_HAVE_POSTGRES` and `pytest.skip` when unavailable, so a bare `make test` on a laptop without docker still passes.
- **Commits:** conventional commits, `feat(identity): ...`, `test(identity): ...`, `chore(identity): ...`, `docs(identity): ...`. One logical step per commit. Always include the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer when the commit was produced in this assistive workflow.
- **Branching:** work on `feat/m1-identity-schema` (created from `main`). Open PR against `HE1780/deer-flow:main` when M1 is complete.

---

## Pre-flight

### Task 0: Prepare branch

- [ ] **Step 0.1: Confirm clean tree and branch off main**

```bash
cd /Users/lydoc/projectscoding/deer-flow
git status
# Expected: "On branch main", "working tree clean" (loader.py is in stash@{0}, that's fine)
git checkout -b feat/m1-identity-schema
```

- [ ] **Step 0.2: Sanity-check existing tests still pass**

```bash
cd backend
make test 2>&1 | tail -5
# Expected: all green (baseline)
```

If any existing test is red on `main`, stop and fix or file an issue. Do not proceed with red baseline — M1 changes must not be blamed for pre-existing red.

---

## Task 1: Add dependencies

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1.1: Add runtime deps to `[project].dependencies`**

Open `backend/pyproject.toml` and update `dependencies`:

```toml
dependencies = [
    "deerflow-harness",
    "fastapi>=0.115.0",
    "httpx>=0.28.0",
    "python-multipart>=0.0.26",
    "sse-starlette>=2.1.0",
    "uvicorn[standard]>=0.34.0",
    "lark-oapi>=1.4.0",
    "slack-sdk>=3.33.0",
    "python-telegram-bot>=21.0",
    "langgraph-sdk>=0.1.51",
    "markdown-to-mrkdwn>=0.3.1",
    "wecom-aibot-python-sdk>=0.1.6",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "redis[hiredis]>=5.0.0",
]
```

- [ ] **Step 1.2: Add dev deps**

```toml
[dependency-groups]
dev = [
    "pytest>=9.0.3",
    "ruff>=0.14.11",
    "pytest-asyncio>=0.24.0",
    "testcontainers[postgres,redis]>=4.0.0",
]
```

- [ ] **Step 1.3: Sync**

Run: `cd backend && uv sync`
Expected: resolves, downloads wheels, no errors.

- [ ] **Step 1.4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore(identity): add sqlalchemy/asyncpg/alembic/redis deps

$(printf '%s\n\n%s' 'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 2: Settings module (feature flag + env)

**Files:**
- Create: `backend/app/gateway/identity/__init__.py`
- Create: `backend/app/gateway/identity/settings.py`
- Create: `backend/tests/identity/__init__.py`
- Create: `backend/tests/identity/conftest.py` (skeleton; fixtures added in Task 5)
- Create: `backend/tests/identity/test_settings.py`

- [ ] **Step 2.1: Create package marker**

Create `backend/app/gateway/identity/__init__.py`:

```python
"""Enterprise identity subsystem (tenants, users, roles, tokens, audit).

Spec: docs/superpowers/specs/2026-04-21-deerflow-identity-foundation-design.md
"""
```

- [ ] **Step 2.2: Create test conftest skeleton**

Create `backend/tests/identity/__init__.py`:

```python
```

Create `backend/tests/identity/conftest.py`:

```python
"""Shared fixtures for identity tests.

Fixtures that require Postgres/Redis are guarded: tests skip when the
containers are unavailable so a bare `make test` passes on laptops.
"""

import os
import pytest

_HAVE_DOCKER = os.environ.get("IDENTITY_TEST_BACKEND", "auto") != "off"


@pytest.fixture(scope="session")
def have_docker() -> bool:
    return _HAVE_DOCKER
```

(More fixtures land in Task 5.)

- [ ] **Step 2.3: Write the failing test for settings**

Create `backend/tests/identity/test_settings.py`:

```python
"""Tests for app.gateway.identity.settings."""

import os
from unittest.mock import patch

from app.gateway.identity.settings import IdentitySettings, get_identity_settings


def test_defaults_flag_off_when_env_unset():
    with patch.dict(os.environ, {}, clear=False):
        # ensure the var is actually unset
        os.environ.pop("ENABLE_IDENTITY", None)
        get_identity_settings.cache_clear()
        settings = get_identity_settings()
    assert settings.enabled is False


def test_flag_on_when_truthy_env():
    for val in ["1", "true", "True", "TRUE", "yes", "on"]:
        with patch.dict(os.environ, {"ENABLE_IDENTITY": val}):
            get_identity_settings.cache_clear()
            assert get_identity_settings().enabled is True, f"ENABLE_IDENTITY={val!r} should enable"


def test_flag_off_when_falsy_env():
    for val in ["0", "false", "False", "no", "off", ""]:
        with patch.dict(os.environ, {"ENABLE_IDENTITY": val}):
            get_identity_settings.cache_clear()
            assert get_identity_settings().enabled is False, f"ENABLE_IDENTITY={val!r} should disable"


def test_database_url_default():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DEERFLOW_DATABASE_URL", None)
        get_identity_settings.cache_clear()
        assert get_identity_settings().database_url == "postgresql+asyncpg://deerflow:deerflow@localhost:5432/deerflow"


def test_database_url_from_env():
    with patch.dict(os.environ, {"DEERFLOW_DATABASE_URL": "postgresql+asyncpg://u:p@h:1/d"}):
        get_identity_settings.cache_clear()
        assert get_identity_settings().database_url == "postgresql+asyncpg://u:p@h:1/d"


def test_redis_url_default_and_override():
    get_identity_settings.cache_clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DEERFLOW_REDIS_URL", None)
        get_identity_settings.cache_clear()
        assert get_identity_settings().redis_url == "redis://localhost:6379/0"
    with patch.dict(os.environ, {"DEERFLOW_REDIS_URL": "redis://r:6379/5"}):
        get_identity_settings.cache_clear()
        assert get_identity_settings().redis_url == "redis://r:6379/5"


def test_bootstrap_admin_email_optional():
    get_identity_settings.cache_clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DEERFLOW_BOOTSTRAP_ADMIN_EMAIL", None)
        get_identity_settings.cache_clear()
        assert get_identity_settings().bootstrap_admin_email is None
    with patch.dict(os.environ, {"DEERFLOW_BOOTSTRAP_ADMIN_EMAIL": "admin@example.com"}):
        get_identity_settings.cache_clear()
        assert get_identity_settings().bootstrap_admin_email == "admin@example.com"


def test_settings_cached_between_calls():
    get_identity_settings.cache_clear()
    first = get_identity_settings()
    second = get_identity_settings()
    assert first is second
```

- [ ] **Step 2.4: Run test to verify failure**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_settings.py -v`
Expected: ImportError / ModuleNotFoundError for `app.gateway.identity.settings`.

- [ ] **Step 2.5: Implement `settings.py`**

Create `backend/app/gateway/identity/settings.py`:

```python
"""Identity subsystem settings loaded from environment variables."""

from dataclasses import dataclass
from functools import lru_cache
import os

_TRUTHY = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


@dataclass(frozen=True)
class IdentitySettings:
    """Process-level settings for the identity subsystem.

    Read at startup and cached via `get_identity_settings()`. Tests can
    clear the cache with `get_identity_settings.cache_clear()`.
    """

    enabled: bool
    database_url: str
    redis_url: str
    bootstrap_admin_email: str | None
    auto_provision_tenant: bool  # IDENTITY_AUTO_PROVISION_TENANT, M2 will honor this


@lru_cache(maxsize=1)
def get_identity_settings() -> IdentitySettings:
    return IdentitySettings(
        enabled=_env_bool("ENABLE_IDENTITY", default=False),
        database_url=os.environ.get(
            "DEERFLOW_DATABASE_URL",
            "postgresql+asyncpg://deerflow:deerflow@localhost:5432/deerflow",
        ),
        redis_url=os.environ.get("DEERFLOW_REDIS_URL", "redis://localhost:6379/0"),
        bootstrap_admin_email=os.environ.get("DEERFLOW_BOOTSTRAP_ADMIN_EMAIL") or None,
        auto_provision_tenant=_env_bool("IDENTITY_AUTO_PROVISION_TENANT", default=False),
    )
```

- [ ] **Step 2.6: Run tests to verify pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_settings.py -v`
Expected: all 8 tests pass.

- [ ] **Step 2.7: Lint**

Run: `cd backend && uvx ruff check app/gateway/identity/ tests/identity/ && uvx ruff format --check app/gateway/identity/ tests/identity/`
Expected: clean (or fix with `uvx ruff format ...`).

- [ ] **Step 2.8: Commit**

```bash
git add backend/app/gateway/identity/__init__.py \
        backend/app/gateway/identity/settings.py \
        backend/tests/identity/__init__.py \
        backend/tests/identity/conftest.py \
        backend/tests/identity/test_settings.py
git commit -m "feat(identity): add settings module with ENABLE_IDENTITY flag

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: SQLAlchemy Base + TenantScoped/WorkspaceScoped mixins

**Files:**
- Create: `backend/app/gateway/identity/models/__init__.py`
- Create: `backend/app/gateway/identity/models/base.py`
- Create: `backend/tests/identity/test_models_base.py`

- [ ] **Step 3.1: Write failing test for Base + mixins**

Create `backend/tests/identity/test_models_base.py`:

```python
"""Tests for models.base: declarative Base, TenantScoped, WorkspaceScoped mixins."""

from sqlalchemy import Column, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.gateway.identity.models.base import Base, TenantScoped, WorkspaceScoped


def test_base_has_metadata():
    assert Base.metadata is not None
    assert Base.metadata.schema == "identity"


def test_tenant_scoped_adds_tenant_id_column():
    class Widget(TenantScoped, Base):
        __tablename__ = "widgets_test_ts"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)

    cols = {c.name for c in Widget.__table__.columns}
    assert "tenant_id" in cols
    assert Widget.__table__.columns["tenant_id"].nullable is False


def test_workspace_scoped_adds_both_columns():
    class Gadget(WorkspaceScoped, Base):
        __tablename__ = "gadgets_test_ws"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)

    cols = {c.name for c in Gadget.__table__.columns}
    assert "tenant_id" in cols
    assert "workspace_id" in cols


def test_mixins_create_indexes_on_scope_cols():
    class Thing(WorkspaceScoped, Base):
        __tablename__ = "things_test_idx"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)

    indexed_cols = set()
    for idx in Thing.__table__.indexes:
        for col in idx.columns:
            indexed_cols.add(col.name)
    assert "tenant_id" in indexed_cols
    assert "workspace_id" in indexed_cols
```

- [ ] **Step 3.2: Run test to verify failure**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_models_base.py -v`
Expected: ImportError.

- [ ] **Step 3.3: Implement base**

Create `backend/app/gateway/identity/models/__init__.py`:

```python
"""ORM models for identity schema."""
from app.gateway.identity.models.base import Base, TenantScoped, WorkspaceScoped

__all__ = ["Base", "TenantScoped", "WorkspaceScoped"]
```

Create `backend/app/gateway/identity/models/base.py`:

```python
"""Declarative Base and scope mixins for identity ORM models."""

from sqlalchemy import BigInteger, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_SCHEMA = "identity"


class Base(DeclarativeBase):
    """Declarative base scoped to the `identity` Postgres schema."""

    metadata = MetaData(schema=_SCHEMA)


class TenantScoped:
    """Mixin: adds indexed `tenant_id BIGINT NOT NULL`. Classes using this mixin
    plus Base become candidates for the auto-filter middleware added in M3.
    """

    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)


class WorkspaceScoped(TenantScoped):
    """Mixin: adds indexed `workspace_id BIGINT NOT NULL` in addition to tenant_id."""

    workspace_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
```

- [ ] **Step 3.4: Run test to verify pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_models_base.py -v`
Expected: 4 pass.

- [ ] **Step 3.5: Commit**

```bash
git add backend/app/gateway/identity/models/
git commit -m "feat(identity): add ORM Base and TenantScoped/WorkspaceScoped mixins

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: ORM models for all 11 tables

**Files:**
- Create: `backend/app/gateway/identity/models/tenant.py`
- Create: `backend/app/gateway/identity/models/user.py`
- Create: `backend/app/gateway/identity/models/role.py`
- Create: `backend/app/gateway/identity/models/token.py`
- Create: `backend/app/gateway/identity/models/audit.py`
- Modify: `backend/app/gateway/identity/models/__init__.py`
- Create: `backend/tests/identity/test_models_definitions.py`

Break this into one file per domain cluster. Each step writes the model then the sanity test that the table columns/constraints match the spec DDL.

- [ ] **Step 4.1: Write failing test for all model definitions**

Create `backend/tests/identity/test_models_definitions.py`:

```python
"""Structural tests: ORM definitions must match spec DDL."""

from app.gateway.identity.models import (
    ApiToken,
    AuditLog,
    Membership,
    Permission,
    Role,
    RolePermission,
    Tenant,
    User,
    UserRole,
    Workspace,
    WorkspaceMember,
)


def _colnames(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


def test_tenant_columns():
    cols = _colnames(Tenant)
    assert cols >= {"id", "slug", "name", "logo_url", "plan", "status", "owner_id", "expires_at", "created_at", "created_by", "updated_at"}


def test_user_columns_and_unique_constraints():
    cols = _colnames(User)
    assert cols >= {"id", "email", "display_name", "avatar_url", "status", "oidc_subject", "oidc_provider", "last_login_at", "last_login_ip", "created_at"}
    uniques = {tuple(sorted(c.name for c in constraint.columns)) for constraint in User.__table__.constraints if constraint.__class__.__name__ == "UniqueConstraint"}
    assert ("email",) in uniques
    assert ("oidc_provider", "oidc_subject") in uniques


def test_workspace_unique_slug_per_tenant():
    uniques = {tuple(sorted(c.name for c in constraint.columns)) for constraint in Workspace.__table__.constraints if constraint.__class__.__name__ == "UniqueConstraint"}
    assert ("slug", "tenant_id") in uniques


def test_membership_unique_user_tenant():
    uniques = {tuple(sorted(c.name for c in constraint.columns)) for constraint in Membership.__table__.constraints if constraint.__class__.__name__ == "UniqueConstraint"}
    assert ("tenant_id", "user_id") in uniques


def test_permission_tag_unique():
    uniques = {tuple(sorted(c.name for c in constraint.columns)) for constraint in Permission.__table__.constraints if constraint.__class__.__name__ == "UniqueConstraint"}
    assert ("tag",) in uniques


def test_role_unique_key_scope():
    uniques = {tuple(sorted(c.name for c in constraint.columns)) for constraint in Role.__table__.constraints if constraint.__class__.__name__ == "UniqueConstraint"}
    assert ("role_key", "scope") in uniques


def test_role_permission_composite_pk():
    pk_cols = {c.name for c in RolePermission.__table__.primary_key.columns}
    assert pk_cols == {"role_id", "permission_id"}


def test_user_role_composite_pk():
    pk_cols = {c.name for c in UserRole.__table__.primary_key.columns}
    assert pk_cols == {"user_id", "tenant_id", "role_id"}


def test_workspace_member_composite_pk():
    pk_cols = {c.name for c in WorkspaceMember.__table__.primary_key.columns}
    assert pk_cols == {"user_id", "workspace_id"}


def test_api_token_columns():
    cols = _colnames(ApiToken)
    assert cols >= {
        "id", "tenant_id", "user_id", "workspace_id",
        "name", "prefix", "token_hash", "scopes",
        "expires_at", "last_used_at", "last_used_ip",
        "revoked_at", "created_at", "created_by",
    }


def test_audit_log_columns():
    cols = _colnames(AuditLog)
    assert cols >= {
        "id", "tenant_id", "user_id", "workspace_id",
        "action", "resource_type", "resource_id",
        "ip", "user_agent", "result", "error_code", "duration_ms",
        "metadata", "created_at",
    }


def test_api_token_scopes_is_array_of_strings():
    col = ApiToken.__table__.columns["scopes"]
    # SQLAlchemy ARRAY type carries item_type
    assert col.type.__class__.__name__ == "ARRAY"
```

- [ ] **Step 4.2: Run test → fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_models_definitions.py -v`
Expected: ImportError.

- [ ] **Step 4.3: Implement `tenant.py`**

Create `backend/app/gateway/identity/models/tenant.py`:

```python
"""Tenant and Workspace ORM models."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.gateway.identity.models.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[str] = mapped_column(String(32), server_default="free")
    status: Mapped[int] = mapped_column(SmallInteger, server_default="1")  # 1 active / 0 suspended / -1 deleted
    owner_id: Mapped[int | None] = mapped_column(BigInteger)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4.4: Implement `user.py`**

Create `backend/app/gateway/identity/models/user.py`:

```python
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
```

- [ ] **Step 4.5: Implement `role.py`**

Create `backend/app/gateway/identity/models/role.py`:

```python
"""Role, Permission, RolePermission, UserRole ORM models."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.gateway.identity.models.base import Base


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tag: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)  # platform | tenant | workspace
    description: Mapped[str | None] = mapped_column(Text)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("role_key", "scope", name="uq_roles_key_scope"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, server_default="true")
    display_name: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.permissions.id", ondelete="CASCADE"), primary_key=True)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.users.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("identity.tenants.id", ondelete="CASCADE"), primary_key=True, nullable=True)  # NULL = platform_admin
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.roles.id"), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Note: Postgres allows NULL in composite PK via `nullable=True`, but the standard treats NULLs as distinct. This means `(user_id=1, tenant_id=NULL, role_id=R)` can appear multiple times. The seed writes it exactly once for platform_admin and guards via unique index in the migration (Step 6.x).

- [ ] **Step 4.6: Implement `token.py`**

Create `backend/app/gateway/identity/models/token.py`:

```python
"""ApiToken ORM model."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY, INET
from sqlalchemy.orm import Mapped, mapped_column

from app.gateway.identity.models.base import Base


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("identity.workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_ip: Mapped[str | None] = mapped_column(INET)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(BigInteger)
```

- [ ] **Step 4.7: Implement `audit.py`**

Create `backend/app/gateway/identity/models/audit.py`:

```python
"""AuditLog ORM model (table only; writer and API land in M6)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gateway.identity.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    workspace_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    log_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Note: `metadata` is a reserved Python attribute on `DeclarativeBase` (it's the `MetaData` instance). Using `metadata` directly as a Python attribute name raises `InvalidRequestError`. Solution: use Python attribute `log_metadata` with the explicit column name `"metadata"` (first positional arg to `mapped_column`). Verified locally with SQLAlchemy 2.0+:

```python
# AuditLog.log_metadata  → Python-side access
# AuditLog.__table__.columns["metadata"]  → DB column lookup
```

**Update tests accordingly**: the structural test in `test_models_definitions.py` checks `_colnames(AuditLog)` which reads the DB column name, so it still matches `"metadata"`. Any code that reads/writes the value uses the Python attribute `log_metadata`. The test file already asserts `"metadata"` in the colname set (Task 4.1), so that stays correct.

- [ ] **Step 4.8: Update `models/__init__.py` re-exports**

Replace `backend/app/gateway/identity/models/__init__.py` with:

```python
"""ORM models for identity schema."""

from app.gateway.identity.models.audit import AuditLog
from app.gateway.identity.models.base import Base, TenantScoped, WorkspaceScoped
from app.gateway.identity.models.role import Permission, Role, RolePermission, UserRole
from app.gateway.identity.models.tenant import Tenant, Workspace
from app.gateway.identity.models.token import ApiToken
from app.gateway.identity.models.user import Membership, User, WorkspaceMember

__all__ = [
    "Base",
    "TenantScoped",
    "WorkspaceScoped",
    "Tenant",
    "Workspace",
    "User",
    "Membership",
    "WorkspaceMember",
    "Permission",
    "Role",
    "RolePermission",
    "UserRole",
    "ApiToken",
    "AuditLog",
]
```

- [ ] **Step 4.9: Run full structural tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_models_definitions.py tests/identity/test_models_base.py -v`
Expected: all pass.

- [ ] **Step 4.10: Lint**

Run: `cd backend && uvx ruff check app/gateway/identity/ tests/identity/ && uvx ruff format app/gateway/identity/ tests/identity/`

- [ ] **Step 4.11: Commit**

```bash
git add backend/app/gateway/identity/models/ backend/tests/identity/test_models_definitions.py
git commit -m "feat(identity): add 11 ORM models matching spec DDL

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Testcontainers fixtures (Postgres + Redis)

**Files:**
- Modify: `backend/tests/identity/conftest.py`
- Create: `backend/tests/identity/test_containers_smoke.py`

- [ ] **Step 5.1: Extend conftest with session-scoped pg/redis containers**

Replace `backend/tests/identity/conftest.py` with:

```python
"""Shared fixtures for identity tests.

Integration fixtures skip gracefully if Docker/testcontainers is unavailable
(`IDENTITY_TEST_BACKEND=off`) so `make test` stays green on laptops.
"""

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio

_BACKEND = os.environ.get("IDENTITY_TEST_BACKEND", "auto").lower()
_SKIP_REASON = "set IDENTITY_TEST_BACKEND=on (or install docker + testcontainers) to run integration tests"


def _skip_if_no_docker():
    if _BACKEND == "off":
        pytest.skip(_SKIP_REASON)
    if _BACKEND == "auto":
        try:
            import docker  # noqa: F401
            import testcontainers.postgres  # noqa: F401
            import testcontainers.redis  # noqa: F401
        except Exception:
            pytest.skip(_SKIP_REASON)


@pytest.fixture(scope="session")
def pg_container() -> Iterator["PostgresContainer"]:
    _skip_if_no_docker()
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine", username="deerflow", password="deerflow", dbname="deerflow", driver="asyncpg")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def pg_url(pg_container) -> str:
    # testcontainers returns sync URL; asyncpg driver is injected via constructor arg above
    url = pg_container.get_connection_url()
    # Some testcontainers versions emit "postgresql+psycopg2://"; normalize to asyncpg
    return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace("postgresql://", "postgresql+asyncpg://")


@pytest.fixture(scope="session")
def redis_container() -> Iterator["RedisContainer"]:
    _skip_if_no_docker()
    from testcontainers.redis import RedisContainer

    container = RedisContainer("redis:7-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def redis_url(redis_container) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


@pytest_asyncio.fixture
async def async_engine(pg_url: str) -> AsyncIterator:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(pg_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncIterator:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(async_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
```

- [ ] **Step 5.2: Add pytest-asyncio config**

Edit `backend/pyproject.toml`, append under `[tool.pytest.ini_options]` (create section if absent):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 5.3: Smoke test containers**

Create `backend/tests/identity/test_containers_smoke.py`:

```python
"""Verify pg/redis fixtures bootstrap cleanly."""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_pg_container_reachable(async_engine):
    async with async_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


def test_redis_container_reachable(redis_url):
    import redis

    r = redis.Redis.from_url(redis_url, decode_responses=True)
    assert r.ping() is True
```

- [ ] **Step 5.4: Run smoke test**

Run: `cd backend && PYTHONPATH=. IDENTITY_TEST_BACKEND=on uv run pytest tests/identity/test_containers_smoke.py -v`

Expected: 2 pass (takes ~30s first run while pulling images).

If Docker is unavailable on this machine, skip with `IDENTITY_TEST_BACKEND=off` and validate skip path:

Run: `cd backend && PYTHONPATH=. IDENTITY_TEST_BACKEND=off uv run pytest tests/identity/test_containers_smoke.py -v`
Expected: 2 skipped.

- [ ] **Step 5.5: Commit**

```bash
git add backend/tests/identity/conftest.py \
        backend/tests/identity/test_containers_smoke.py \
        backend/pyproject.toml
git commit -m "test(identity): add testcontainers pg/redis fixtures

Fixtures gate on IDENTITY_TEST_BACKEND env var so plain 'make test'
stays green on laptops without Docker.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Alembic setup + initial migration

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/20260421_0001_identity_schema.py`
- Create: `backend/tests/identity/test_alembic_migration.py`

- [ ] **Step 6.1: Scaffold alembic layout manually (not via `alembic init`) to control paths**

Create `backend/alembic.ini`:

```ini
[alembic]
script_location = alembic
file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

Create `backend/alembic/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 6.2: Write env.py with async support**

Create `backend/alembic/env.py`:

```python
"""Alembic env configured for async engine + app.gateway.identity metadata."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.gateway.identity.models import Base  # populates metadata
from app.gateway.identity.settings import get_identity_settings

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_identity_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        version_table_schema="identity",
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        version_table_schema="identity",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 6.3: Write the initial migration**

Create `backend/alembic/versions/20260421_0001_identity_schema.py`:

```python
"""identity schema initial

Revision ID: 20260421_0001
Revises: None
Create Date: 2026-04-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB

revision: str = "20260421_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS identity")

    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("logo_url", sa.Text),
        sa.Column("plan", sa.String(32), server_default="free"),
        sa.Column("status", sa.SmallInteger, server_default="1"),
        sa.Column("owner_id", sa.BigInteger),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.BigInteger),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="identity",
    )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128)),
        sa.Column("avatar_url", sa.Text),
        sa.Column("status", sa.SmallInteger, server_default="1"),
        sa.Column("oidc_subject", sa.String(255)),
        sa.Column("oidc_provider", sa.String(64)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("last_login_ip", INET),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("oidc_provider", "oidc_subject", name="uq_users_oidc"),
        schema="identity",
    )

    op.create_table(
        "memberships",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.SmallInteger, server_default="1"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),
        schema="identity",
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"], schema="identity")
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"], schema="identity")

    op.create_table(
        "workspaces",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_by", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),
        schema="identity",
    )
    op.create_index("ix_workspaces_tenant_id", "workspaces", ["tenant_id"], schema="identity")

    op.create_table(
        "permissions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tag", sa.String(64), nullable=False, unique=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("description", sa.Text),
        schema="identity",
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("role_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("is_builtin", sa.Boolean, server_default="true"),
        sa.Column("display_name", sa.String(128)),
        sa.Column("description", sa.Text),
        sa.UniqueConstraint("role_key", "scope", name="uq_roles_key_scope"),
        schema="identity",
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.BigInteger, sa.ForeignKey("identity.roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", sa.BigInteger, sa.ForeignKey("identity.permissions.id", ondelete="CASCADE"), primary_key=True),
        schema="identity",
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("identity.users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("identity.tenants.id", ondelete="CASCADE"), primary_key=True, nullable=True),
        sa.Column("role_id", sa.BigInteger, sa.ForeignKey("identity.roles.id"), primary_key=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="identity",
    )
    # Platform-admin rows have NULL tenant_id; enforce uniqueness separately via partial unique index
    op.execute("""
        CREATE UNIQUE INDEX uq_user_roles_platform
        ON identity.user_roles (user_id, role_id)
        WHERE tenant_id IS NULL
    """)

    op.create_table(
        "workspace_members",
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("identity.users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger, sa.ForeignKey("identity.workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.BigInteger, sa.ForeignKey("identity.roles.id"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="identity",
    )

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger, sa.ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.BigInteger, sa.ForeignKey("identity.workspaces.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("scopes", ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_ip", INET),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.BigInteger),
        schema="identity",
    )
    op.create_index("ix_api_tokens_tenant_revoked", "api_tokens", ["tenant_id", "revoked_at"], schema="identity")
    op.create_index("ix_api_tokens_prefix", "api_tokens", ["prefix"], schema="identity")

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger),
        sa.Column("user_id", sa.BigInteger),
        sa.Column("workspace_id", sa.BigInteger),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("ip", INET),
        sa.Column("user_agent", sa.Text),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="identity",
    )
    op.create_index("ix_audit_logs_tenant_created", "audit_logs", ["tenant_id", sa.text("created_at DESC")], schema="identity")
    op.create_index("ix_audit_logs_user_created", "audit_logs", ["user_id", sa.text("created_at DESC")], schema="identity")
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], schema="identity")


def downgrade() -> None:
    for name in ["audit_logs", "api_tokens", "workspace_members", "user_roles", "role_permissions", "roles", "permissions", "workspaces", "memberships", "users", "tenants"]:
        op.drop_table(name, schema="identity")
    op.execute("DROP SCHEMA identity CASCADE")
```

- [ ] **Step 6.4: Write failing migration test**

Create `backend/tests/identity/test_alembic_migration.py`:

```python
"""Verify alembic upgrade head creates all tables and downgrade cleans up."""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_upgrade_then_downgrade(pg_url, monkeypatch):
    monkeypatch.setenv("DEERFLOW_DATABASE_URL", pg_url)
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)

    command.upgrade(cfg, "head")

    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(pg_url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text("""
            SELECT tablename FROM pg_tables WHERE schemaname = 'identity' ORDER BY tablename
        """))).all()
    await engine.dispose()

    table_names = {r[0] for r in rows}
    expected = {"tenants", "users", "memberships", "workspaces", "permissions", "roles", "role_permissions", "user_roles", "workspace_members", "api_tokens", "audit_logs"}
    assert expected.issubset(table_names)

    command.downgrade(cfg, "base")

    engine = create_async_engine(pg_url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text("""
            SELECT tablename FROM pg_tables WHERE schemaname = 'identity'
        """))).all()
    await engine.dispose()
    assert len(rows) == 0
```

- [ ] **Step 6.5: Run migration test**

Run: `cd backend && PYTHONPATH=. IDENTITY_TEST_BACKEND=on uv run pytest tests/identity/test_alembic_migration.py -v`
Expected: 1 pass.

Iteratively fix column type/constraint mismatches if any. **Do not edit the migration to silence the test** — if spec DDL is wrong, open a spec PR first.

- [ ] **Step 6.6: Commit**

```bash
git add backend/alembic.ini backend/alembic/ backend/tests/identity/test_alembic_migration.py
git commit -m "feat(identity): alembic setup + initial schema migration

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: DB engine + session factory

**Files:**
- Create: `backend/app/gateway/identity/db.py`
- Create: `backend/app/gateway/identity/context.py`
- Create: `backend/tests/identity/test_db.py`

- [ ] **Step 7.1: Write failing test**

Create `backend/tests/identity/test_db.py`:

```python
"""Tests for db engine/session factory and context vars."""

import pytest
from sqlalchemy import text

from app.gateway.identity.context import current_identity, current_tenant_id
from app.gateway.identity.db import create_engine_and_sessionmaker


@pytest.mark.asyncio
async def test_engine_sessionmaker_roundtrip(pg_url):
    engine, maker = create_engine_and_sessionmaker(pg_url)
    try:
        async with maker() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1
    finally:
        await engine.dispose()


def test_context_vars_default_none():
    assert current_tenant_id.get() is None
    assert current_identity.get() is None


def test_context_vars_scoped():
    token = current_tenant_id.set(42)
    try:
        assert current_tenant_id.get() == 42
    finally:
        current_tenant_id.reset(token)
    assert current_tenant_id.get() is None
```

- [ ] **Step 7.2: Implement context vars**

Create `backend/app/gateway/identity/context.py`:

```python
"""ContextVars used by middleware/filters in later milestones.

M1 defines them so M3's SQL auto-filter and M6's audit writer can read
them without further structural changes.
"""

from contextvars import ContextVar
from typing import Any

current_identity: ContextVar[Any | None] = ContextVar("current_identity", default=None)
current_tenant_id: ContextVar[int | None] = ContextVar("current_tenant_id", default=None)
```

- [ ] **Step 7.3: Implement db module**

Create `backend/app/gateway/identity/db.py`:

```python
"""Async engine + session factory used by the identity subsystem.

A single engine is created at gateway startup when `ENABLE_IDENTITY=true`
and disposed on shutdown. Milestones after M1 register a
`Depends(get_session)` for routers.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine_and_sessionmaker(database_url: str, *, pool_size: int = 10, max_overflow: int = 5) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, maker


# Populated in lifespan when ENABLE_IDENTITY=true. None otherwise.
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def set_global_engine(engine: AsyncEngine, maker: async_sessionmaker[AsyncSession]) -> None:
    global _engine, _sessionmaker
    _engine = engine
    _sessionmaker = maker


def clear_global_engine() -> None:
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency; raises if identity subsystem was not initialised.

    Reserved for M2+; M1 just validates the scaffold.
    """
    if _sessionmaker is None:
        raise RuntimeError("Identity subsystem not initialised (ENABLE_IDENTITY=false?)")
    async with _sessionmaker() as session:
        try:
            yield session
        finally:
            await session.close()
```

- [ ] **Step 7.4: Run tests**

Run: `cd backend && PYTHONPATH=. IDENTITY_TEST_BACKEND=on uv run pytest tests/identity/test_db.py -v`
Expected: 3 pass.

- [ ] **Step 7.5: Commit**

```bash
git add backend/app/gateway/identity/db.py backend/app/gateway/identity/context.py backend/tests/identity/test_db.py
git commit -m "feat(identity): async engine, sessionmaker, and context vars

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Bootstrap (idempotent seed)

**Files:**
- Create: `backend/app/gateway/identity/bootstrap.py`
- Create: `backend/tests/identity/test_bootstrap.py`

Spec §4.2 + §10.4 define seed content: 5 roles, ~24 permissions, role_permissions map, default tenant + workspace, optional first platform_admin.

- [ ] **Step 8.1: Write failing test**

Create `backend/tests/identity/test_bootstrap.py`:

```python
"""Tests for bootstrap: idempotent seed + first admin creation."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.gateway.identity.bootstrap import (
    PREDEFINED_PERMISSIONS,
    PREDEFINED_ROLE_PERMISSIONS,
    PREDEFINED_ROLES,
    bootstrap,
)
from app.gateway.identity.db import create_engine_and_sessionmaker
from app.gateway.identity.models import Permission, Role, Tenant, User, UserRole, Workspace


@pytest.fixture
async def fresh_db(pg_url, monkeypatch):
    """Run migrations, yield (engine, maker), drop schema at teardown."""
    monkeypatch.setenv("DEERFLOW_DATABASE_URL", pg_url)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)
    command.upgrade(cfg, "head")
    engine, maker = create_engine_and_sessionmaker(pg_url)
    try:
        yield engine, maker
    finally:
        await engine.dispose()
        command.downgrade(cfg, "base")


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

        ur = (await session.execute(
            select(UserRole).where(UserRole.user_id == admin.id, UserRole.tenant_id.is_(None))
        )).scalars().all()
        assert len(ur) == 1  # one platform_admin grant


@pytest.mark.asyncio
async def test_bootstrap_skips_platform_admin_if_already_exists(fresh_db):
    _, maker = fresh_db
    async with maker() as session:
        await bootstrap(session, bootstrap_admin_email="admin@example.com")
        await bootstrap(session, bootstrap_admin_email="another@example.com")

        users = (await session.execute(select(User))).scalars().all()
        platform_admin_emails = {u.email for u in users}
        # Second email not added because a platform_admin already exists.
        assert "admin@example.com" in platform_admin_emails
        assert "another@example.com" not in platform_admin_emails


@pytest.mark.asyncio
async def test_role_permission_map_covers_all_roles(fresh_db):
    _, maker = fresh_db
    async with maker() as session:
        await bootstrap(session, bootstrap_admin_email=None)
        # Each role must have at least one permission (viewer has *:read only, etc.)
        for role_key, scope, _ in PREDEFINED_ROLES:
            perms_for_role = PREDEFINED_ROLE_PERMISSIONS.get((role_key, scope), [])
            assert len(perms_for_role) > 0, f"Role {role_key}/{scope} has no permissions"
```

- [ ] **Step 8.2: Run test → fail**

Run: `cd backend && PYTHONPATH=. IDENTITY_TEST_BACKEND=on uv run pytest tests/identity/test_bootstrap.py -v`
Expected: ImportError.

- [ ] **Step 8.3: Implement `bootstrap.py`**

Create `backend/app/gateway/identity/bootstrap.py`:

```python
"""Idempotent seed of roles, permissions, default tenant/workspace, first admin.

Called at gateway startup when ENABLE_IDENTITY=true. Safe to run repeatedly.
"""

from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.identity.models import (
    Membership,
    Permission,
    Role,
    RolePermission,
    Tenant,
    User,
    UserRole,
    Workspace,
    WorkspaceMember,
)

logger = logging.getLogger(__name__)

# --- Seed data (spec §4.2) ---

PREDEFINED_PERMISSIONS: list[tuple[str, str]] = [
    # platform scope
    ("tenant:create", "platform"),
    ("tenant:read", "platform"),
    ("tenant:update", "platform"),
    ("tenant:delete", "platform"),
    ("user:read", "platform"),
    ("user:disable", "platform"),
    ("audit:read.all", "platform"),
    # tenant scope
    ("workspace:create", "tenant"),
    ("workspace:read", "tenant"),
    ("workspace:update", "tenant"),
    ("workspace:delete", "tenant"),
    ("membership:invite", "tenant"),
    ("membership:read", "tenant"),
    ("membership:remove", "tenant"),
    ("role:read", "tenant"),
    ("token:create", "tenant"),
    ("token:revoke", "tenant"),
    ("token:read", "tenant"),
    ("audit:read", "tenant"),
    # workspace scope
    ("thread:read", "workspace"),
    ("thread:write", "workspace"),
    ("thread:delete", "workspace"),
    ("skill:read", "workspace"),
    ("skill:invoke", "workspace"),
    ("skill:manage", "workspace"),
    ("knowledge:read", "workspace"),
    ("knowledge:write", "workspace"),
    ("knowledge:manage", "workspace"),
    ("workflow:read", "workspace"),
    ("workflow:run", "workspace"),
    ("workflow:manage", "workspace"),
    ("settings:read", "workspace"),
    ("settings:update", "workspace"),
]

PREDEFINED_ROLES: list[tuple[str, str, str]] = [
    ("platform_admin", "platform", "Platform super-administrator (cross-tenant)"),
    ("tenant_owner", "tenant", "Tenant owner (manages workspaces, members, tokens)"),
    ("workspace_admin", "workspace", "Workspace administrator (manages resources + members)"),
    ("member", "workspace", "Workspace member (create threads, invoke skills)"),
    ("viewer", "workspace", "Read-only viewer"),
]

_PLATFORM_PERMS = [tag for tag, scope in PREDEFINED_PERMISSIONS if scope == "platform"]
_TENANT_PERMS = [tag for tag, scope in PREDEFINED_PERMISSIONS if scope == "tenant"]
_WORKSPACE_PERMS = [tag for tag, scope in PREDEFINED_PERMISSIONS if scope == "workspace"]

PREDEFINED_ROLE_PERMISSIONS: dict[tuple[str, str], list[str]] = {
    ("platform_admin", "platform"): _PLATFORM_PERMS + _TENANT_PERMS + _WORKSPACE_PERMS,
    ("tenant_owner", "tenant"): _TENANT_PERMS + _WORKSPACE_PERMS,
    ("workspace_admin", "workspace"): _WORKSPACE_PERMS,
    ("member", "workspace"): [
        "thread:read", "thread:write", "thread:delete",
        "skill:read", "skill:invoke",
        "knowledge:read", "knowledge:write",
        "workflow:read", "workflow:run",
        "settings:read",
    ],
    ("viewer", "workspace"): [p for p in _WORKSPACE_PERMS if p.endswith(":read")],
}


async def bootstrap(session: AsyncSession, *, bootstrap_admin_email: str | None) -> None:
    """Seed identity schema. Idempotent. Call inside a single transaction."""
    perm_map = await _seed_permissions(session)
    role_map = await _seed_roles(session)
    await _seed_role_permissions(session, role_map, perm_map)

    default_tenant = await _ensure_tenant(session, slug="default", name="Default")
    default_ws = await _ensure_workspace(session, tenant_id=default_tenant.id, slug="default", name="Default")

    if bootstrap_admin_email:
        await _ensure_first_platform_admin(
            session,
            email=bootstrap_admin_email,
            default_tenant_id=default_tenant.id,
            default_workspace_id=default_ws.id,
            role_map=role_map,
        )

    await session.commit()
    logger.info("identity bootstrap complete")


async def _seed_permissions(session: AsyncSession) -> dict[str, int]:
    existing = {p.tag: p.id for p in (await session.execute(select(Permission))).scalars()}
    for tag, scope in PREDEFINED_PERMISSIONS:
        if tag not in existing:
            session.add(Permission(tag=tag, scope=scope))
    await session.flush()
    return {p.tag: p.id for p in (await session.execute(select(Permission))).scalars()}


async def _seed_roles(session: AsyncSession) -> dict[tuple[str, str], int]:
    existing = {(r.role_key, r.scope): r.id for r in (await session.execute(select(Role))).scalars()}
    for key, scope, desc in PREDEFINED_ROLES:
        if (key, scope) not in existing:
            session.add(Role(role_key=key, scope=scope, is_builtin=True, display_name=key.replace("_", " ").title(), description=desc))
    await session.flush()
    return {(r.role_key, r.scope): r.id for r in (await session.execute(select(Role))).scalars()}


async def _seed_role_permissions(session: AsyncSession, role_map: dict, perm_map: dict) -> None:
    existing = {(rp.role_id, rp.permission_id) for rp in (await session.execute(select(RolePermission))).scalars()}
    for (role_key, scope), perm_tags in PREDEFINED_ROLE_PERMISSIONS.items():
        role_id = role_map[(role_key, scope)]
        for tag in perm_tags:
            perm_id = perm_map[tag]
            if (role_id, perm_id) not in existing:
                session.add(RolePermission(role_id=role_id, permission_id=perm_id))
    await session.flush()


async def _ensure_tenant(session: AsyncSession, *, slug: str, name: str) -> Tenant:
    result = await session.execute(select(Tenant).where(Tenant.slug == slug))
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    t = Tenant(slug=slug, name=name)
    session.add(t)
    await session.flush()
    return t


async def _ensure_workspace(session: AsyncSession, *, tenant_id: int, slug: str, name: str) -> Workspace:
    result = await session.execute(select(Workspace).where(Workspace.tenant_id == tenant_id, Workspace.slug == slug))
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    w = Workspace(tenant_id=tenant_id, slug=slug, name=name, description="Default workspace")
    session.add(w)
    await session.flush()
    return w


async def _ensure_first_platform_admin(
    session: AsyncSession,
    *,
    email: str,
    default_tenant_id: int,
    default_workspace_id: int,
    role_map: dict,
) -> None:
    """If any platform_admin already exists, do nothing (even for a different email)."""
    platform_admin_role_id = role_map[("platform_admin", "platform")]
    existing_admin = await session.execute(
        select(UserRole).where(UserRole.role_id == platform_admin_role_id, UserRole.tenant_id.is_(None))
    )
    if existing_admin.first() is not None:
        logger.info("platform_admin already exists; skipping bootstrap of %s", email)
        return

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email, display_name=email.split("@")[0], status=1)
        session.add(user)
        await session.flush()

    session.add(UserRole(user_id=user.id, tenant_id=None, role_id=platform_admin_role_id))
    session.add(Membership(user_id=user.id, tenant_id=default_tenant_id))
    session.add(UserRole(user_id=user.id, tenant_id=default_tenant_id, role_id=role_map[("tenant_owner", "tenant")]))
    session.add(WorkspaceMember(user_id=user.id, workspace_id=default_workspace_id, role_id=role_map[("workspace_admin", "workspace")]))
    await session.flush()
    logger.info("bootstrapped first platform_admin: %s", email)
```

- [ ] **Step 8.4: Run tests**

Run: `cd backend && PYTHONPATH=. IDENTITY_TEST_BACKEND=on uv run pytest tests/identity/test_bootstrap.py -v`
Expected: 6 pass.

- [ ] **Step 8.5: Lint**

Run: `cd backend && uvx ruff check app/gateway/identity/ tests/identity/ && uvx ruff format app/gateway/identity/ tests/identity/`

- [ ] **Step 8.6: Commit**

```bash
git add backend/app/gateway/identity/bootstrap.py backend/tests/identity/test_bootstrap.py
git commit -m "feat(identity): idempotent bootstrap (roles, perms, default tenant, first admin)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Wire bootstrap into gateway lifespan (gated by flag)

**Files:**
- Modify: `backend/app/gateway/app.py`
- Create: `backend/tests/identity/test_gateway_identity_lifespan.py`

- [ ] **Step 9.1: Write failing test for both flag states**

Create `backend/tests/identity/test_gateway_identity_lifespan.py`:

```python
"""Gateway must preserve legacy behavior when flag=false,
and must init engine + bootstrap when flag=true."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_flag_off_skips_identity_init(monkeypatch):
    monkeypatch.setenv("ENABLE_IDENTITY", "false")
    # Clear the settings cache since we changed the env var
    from app.gateway.identity.settings import get_identity_settings

    get_identity_settings.cache_clear()

    with patch("app.gateway.identity.db.create_engine_and_sessionmaker") as ce:
        from app.gateway.app import _init_identity_subsystem  # helper we're about to create

        await _init_identity_subsystem()
        assert ce.call_count == 0


@pytest.mark.asyncio
async def test_flag_on_inits_engine_and_bootstraps(monkeypatch, pg_url):
    monkeypatch.setenv("ENABLE_IDENTITY", "true")
    monkeypatch.setenv("DEERFLOW_DATABASE_URL", pg_url)
    monkeypatch.setenv("DEERFLOW_BOOTSTRAP_ADMIN_EMAIL", "boot@example.com")

    from app.gateway.identity.settings import get_identity_settings
    get_identity_settings.cache_clear()

    # Run alembic upgrade first so bootstrap has tables to write to
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)
    command.upgrade(cfg, "head")

    try:
        from app.gateway.app import _init_identity_subsystem, _shutdown_identity_subsystem

        await _init_identity_subsystem()

        # Verify bootstrap ran
        from sqlalchemy import select
        from app.gateway.identity.db import _sessionmaker as maker  # lifted from module state
        from app.gateway.identity.models import User

        assert maker is not None
        async with maker() as session:
            users = (await session.execute(select(User).where(User.email == "boot@example.com"))).scalars().all()
        assert len(users) == 1

        await _shutdown_identity_subsystem()
    finally:
        command.downgrade(cfg, "base")
```

- [ ] **Step 9.2: Run test → fail** (helpers don't exist yet)

Run: `cd backend && PYTHONPATH=. IDENTITY_TEST_BACKEND=on uv run pytest tests/identity/test_gateway_identity_lifespan.py -v`

- [ ] **Step 9.3: Modify `app/gateway/app.py`**

Open `backend/app/gateway/app.py`. Add imports at the top (keep existing imports):

```python
from app.gateway.identity.bootstrap import bootstrap as identity_bootstrap
from app.gateway.identity.db import clear_global_engine, create_engine_and_sessionmaker, set_global_engine
from app.gateway.identity.settings import get_identity_settings
```

Add module-level helpers below the logger configuration and above `lifespan`:

```python
async def _init_identity_subsystem() -> None:
    settings = get_identity_settings()
    if not settings.enabled:
        logger.info("ENABLE_IDENTITY=false; skipping identity subsystem initialization")
        return

    logger.info("ENABLE_IDENTITY=true; initializing identity subsystem")
    engine, maker = create_engine_and_sessionmaker(settings.database_url)
    set_global_engine(engine, maker)

    async with maker() as session:
        await identity_bootstrap(session, bootstrap_admin_email=settings.bootstrap_admin_email)


async def _shutdown_identity_subsystem() -> None:
    settings = get_identity_settings()
    if not settings.enabled:
        return
    from app.gateway.identity.db import _engine

    if _engine is not None:
        await _engine.dispose()
    clear_global_engine()
```

Inside `lifespan()`, after `logger.info(f"Starting API Gateway on {config.host}:{config.port}")` and before `async with langgraph_runtime(app):`, add:

```python
    await _init_identity_subsystem()
```

At the end of the `async with langgraph_runtime(app):` block (inside the try/finally structure, after the `yield`), add a shutdown:

```python
    await _shutdown_identity_subsystem()
```

Full patched flow (for reference; follow the file's existing structure when editing):

```python
    async with langgraph_runtime(app):
        logger.info("LangGraph runtime initialised")

        try:
            # Start IM channel service if any channels are configured
            # ... (existing channel service code) ...

            yield
        finally:
            await _shutdown_identity_subsystem()
```

- [ ] **Step 9.4: Run lifespan test**

Run: `cd backend && PYTHONPATH=. IDENTITY_TEST_BACKEND=on uv run pytest tests/identity/test_gateway_identity_lifespan.py -v`
Expected: 2 pass.

- [ ] **Step 9.5: Smoke — flag off, gateway still boots without postgres**

```bash
cd backend
# Ensure no postgres is running locally (or use a wrong URL so any accidental use fails fast)
ENABLE_IDENTITY=false DEERFLOW_DATABASE_URL=postgresql+asyncpg://nothing:nothing@127.0.0.1:1/none \
  PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 127.0.0.1 --port 18001 &
UVICORN_PID=$!
sleep 3
curl -sf http://127.0.0.1:18001/health && echo " OK"
kill $UVICORN_PID
```

Expected: `{"status": "ok"}` and "OK" echoed.

- [ ] **Step 9.6: Commit**

```bash
git add backend/app/gateway/app.py backend/tests/identity/test_gateway_identity_lifespan.py
git commit -m "feat(identity): wire bootstrap into gateway lifespan (flag-gated)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: docker-compose update + Makefile helpers

**Files:**
- Modify: `docker/docker-compose.yaml`
- Modify: `backend/Makefile`

- [ ] **Step 10.1: Append postgres + redis to docker-compose**

Open `docker/docker-compose.yaml`. Under the top-level `services:` mapping, append (merge with existing volumes and networks):

```yaml
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-deerflow}
      POSTGRES_USER: ${POSTGRES_USER:-deerflow}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-deerflow}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - deerflow_postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-deerflow} -d ${POSTGRES_DB:-deerflow}"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "${REDIS_PORT:-6379}:6379"
    volumes:
      - deerflow_redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
```

And under `volumes:`:

```yaml
  deerflow_postgres:
  deerflow_redis:
```

(If the compose file already defines `volumes:`, append these two keys to it rather than redefining.)

- [ ] **Step 10.2: Add Makefile helpers**

Open `backend/Makefile`. Append:

```makefile
db-upgrade:
	PYTHONPATH=. uv run alembic upgrade head

db-downgrade-one:
	PYTHONPATH=. uv run alembic downgrade -1

identity-bootstrap:
	PYTHONPATH=. uv run python -c "import asyncio; \
from app.gateway.identity.settings import get_identity_settings; \
from app.gateway.identity.db import create_engine_and_sessionmaker; \
from app.gateway.identity.bootstrap import bootstrap; \
async def _run(): \
  s = get_identity_settings(); \
  e, m = create_engine_and_sessionmaker(s.database_url); \
  async with m() as sess: await bootstrap(sess, bootstrap_admin_email=s.bootstrap_admin_email); \
  await e.dispose(); \
asyncio.run(_run())"

identity-test:
	PYTHONPATH=. IDENTITY_TEST_BACKEND=on uv run pytest tests/identity/ -v
```

- [ ] **Step 10.3: Run `make identity-test` locally (optional — CI is the authority)**

Run: `cd backend && make identity-test`
Expected: all identity tests pass.

- [ ] **Step 10.4: Commit**

```bash
git add docker/docker-compose.yaml backend/Makefile
git commit -m "chore(identity): docker-compose postgres/redis + Makefile helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: CI job for identity tests

**Files:**
- Modify: `.github/workflows/backend-unit-tests.yml`

- [ ] **Step 11.1: Append identity job**

Open `.github/workflows/backend-unit-tests.yml`. After the existing job(s), append a new job:

```yaml
  backend-identity-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: deerflow
          POSTGRES_USER: deerflow
          POSTGRES_PASSWORD: deerflow
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U deerflow -d deerflow"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Set up Python
        run: uv python install 3.12
      - name: Install deps
        working-directory: backend
        run: uv sync
      - name: Run identity tests
        working-directory: backend
        env:
          DEERFLOW_DATABASE_URL: postgresql+asyncpg://deerflow:deerflow@localhost:5432/deerflow
          DEERFLOW_REDIS_URL: redis://localhost:6379/0
          IDENTITY_TEST_BACKEND: on
        run: |
          PYTHONPATH=. uv run alembic upgrade head
          PYTHONPATH=. uv run alembic downgrade base
          PYTHONPATH=. uv run pytest tests/identity/ -v --tb=short
```

- [ ] **Step 11.2: Commit**

```bash
git add .github/workflows/backend-unit-tests.yml
git commit -m "ci(identity): add backend-identity-tests job (pg + redis services)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Feature-flag regression guard

**Files:**
- Create: `backend/tests/identity/test_feature_flag_offline.py`

Goal: a test that *specifically* proves legacy behavior is intact when the flag is off. This is the single most important guard for M1: it must stay green forever; if it ever goes red, M1 has broken something on the existing code path.

- [ ] **Step 12.1: Write the regression test**

Create `backend/tests/identity/test_feature_flag_offline.py`:

```python
"""Regression guard: with ENABLE_IDENTITY=false the gateway must behave
exactly like before (no DB required, legacy endpoints unaffected).

If this test fails, M1 has broken backwards compatibility. Fix that first."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_flag_off(monkeypatch):
    monkeypatch.setenv("ENABLE_IDENTITY", "false")
    # Point DATABASE_URL at nothing; any accidental use will surface fast.
    monkeypatch.setenv("DEERFLOW_DATABASE_URL", "postgresql+asyncpg://nobody:nobody@127.0.0.1:1/none")

    from app.gateway.identity.settings import get_identity_settings
    get_identity_settings.cache_clear()

    from app.gateway.app import app
    with TestClient(app) as c:
        yield c


def test_health_endpoint_still_responds(client_flag_off):
    r = client_flag_off.get("/health")
    assert r.status_code == 200


def test_identity_globals_not_initialised(client_flag_off):
    from app.gateway.identity.db import _engine, _sessionmaker
    assert _engine is None
    assert _sessionmaker is None


def test_models_endpoint_still_responds(client_flag_off):
    """Spot-check: a pre-existing gateway route works without identity."""
    r = client_flag_off.get("/api/models")
    # 200 with list, or 404/500 if config missing, but NOT an auth/identity error
    assert r.status_code in (200, 404, 500)
    body = r.text.lower()
    assert "identity" not in body, f"Identity leak into legacy endpoint: {body[:200]}"
```

- [ ] **Step 12.2: Run regression test**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_feature_flag_offline.py -v`
Expected: 3 pass without any postgres/redis container running.

- [ ] **Step 12.3: Commit**

```bash
git add backend/tests/identity/test_feature_flag_offline.py
git commit -m "test(identity): regression guard for ENABLE_IDENTITY=false

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Update docs

**Files:**
- Modify: `backend/CLAUDE.md`
- Modify: `README.md` (root)

- [ ] **Step 13.1: Add identity section to `backend/CLAUDE.md`**

Open `backend/CLAUDE.md`. Find the "## Architecture" section. After the existing "### Skills System" subsection (or wherever fits structurally), add:

```markdown
### Identity Subsystem (`app/gateway/identity/`)

**Status:** M1 scaffold landed. Gated behind `ENABLE_IDENTITY` env var (default off).

**Components** (M1 scope):
- `settings.py` — reads `ENABLE_IDENTITY`, `DEERFLOW_DATABASE_URL`, `DEERFLOW_REDIS_URL`, `DEERFLOW_BOOTSTRAP_ADMIN_EMAIL`
- `models/` — 11 ORM tables matching spec §4 (tenants, users, memberships, workspaces, permissions, roles, role_permissions, user_roles, workspace_members, api_tokens, audit_logs)
- `db.py` — async engine, session factory, `get_session()` dependency
- `context.py` — `current_identity` / `current_tenant_id` ContextVars (used by M3+)
- `bootstrap.py` — idempotent seed (roles, permissions, default tenant/workspace, first admin)

**Schema migration:**
```bash
make db-upgrade           # run alembic migrations
make db-downgrade-one     # rollback one revision
make identity-bootstrap   # run bootstrap seed manually
make identity-test        # run identity test suite (needs postgres+redis)
```

**When flag is OFF:** identity subsystem is completely inert. No DB connection attempted, no middleware registered, legacy endpoints unchanged. Verified by `tests/identity/test_feature_flag_offline.py`.

**When flag is ON:** gateway lifespan initializes engine + session factory, runs `bootstrap()`, then proceeds with LangGraph runtime. Bootstrap is idempotent (safe to restart).

**Roadmap:** M2 adds auth (OIDC + JWT + API token), M3 adds RBAC middleware, M4 adds storage isolation, M5 adds LangGraph integration, M6 adds audit writer, M7 adds admin UI + migration script. See `docs/superpowers/specs/2026-04-21-deerflow-identity-foundation-design.md`.
```

- [ ] **Step 13.2: Add identity section to root README.md**

Open `README.md`. Find the "## Configuration" or "## Setup" area. Add a new subsection:

```markdown
### Optional: Enterprise Identity (Preview)

DeerFlow includes an opt-in enterprise identity subsystem (multi-tenant, RBAC, audit). It is **off by default** — current single-user installations behave exactly as before.

To enable:

1. Provision Postgres 16 + Redis 7 (docker-compose includes both).
2. Run migrations: `cd backend && make db-upgrade`
3. Set env vars:
   - `ENABLE_IDENTITY=true`
   - `DEERFLOW_DATABASE_URL=postgresql+asyncpg://...`
   - `DEERFLOW_REDIS_URL=redis://...`
   - `DEERFLOW_BOOTSTRAP_ADMIN_EMAIL=you@example.com`
4. Start the gateway normally. Bootstrap runs idempotently at startup.

Full roadmap and design: `docs/superpowers/specs/2026-04-21-deerflow-identity-foundation-design.md`.
```

- [ ] **Step 13.3: Commit**

```bash
git add backend/CLAUDE.md README.md
git commit -m "docs(identity): document M1 identity subsystem and feature flag

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Final verification + PR

- [ ] **Step 14.1: Full local test sweep (flag off)**

Run:
```bash
cd backend
PYTHONPATH=. uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: everything green. Any new red from non-identity tests is a regression in M1 → fix it before PR.

- [ ] **Step 14.2: Full local test sweep (flag on with containers)**

Run:
```bash
cd backend
IDENTITY_TEST_BACKEND=on PYTHONPATH=. uv run pytest tests/identity/ -v --tb=short
```
Expected: all identity tests green.

- [ ] **Step 14.3: Lint/format**

Run:
```bash
cd backend
uvx ruff check .
uvx ruff format --check .
```
Expected: clean.

- [ ] **Step 14.4: Push and open PR**

```bash
git push -u origin feat/m1-identity-schema
```

Open PR on GitHub (`HE1780/deer-flow` → `main`). Title:

```
feat(identity): M1 schema + bootstrap + feature flag
```

Body:

```markdown
## Summary
First milestone of P0 identity foundation (see spec
`docs/superpowers/specs/2026-04-21-deerflow-identity-foundation-design.md`).

Adds:
- Postgres `identity` schema (11 tables) via Alembic
- 11 SQLAlchemy ORM models + TenantScoped/WorkspaceScoped mixins
- Async engine + session factory + ContextVars
- Idempotent bootstrap (5 roles, ~24 permissions, default tenant/workspace, first platform_admin)
- `ENABLE_IDENTITY` feature flag (default **off** — zero impact on existing deployments)
- `docker-compose` postgres + redis services
- `make db-upgrade` / `make identity-bootstrap` / `make identity-test`
- CI job `backend-identity-tests` with pg/redis service containers
- Regression guard: `tests/identity/test_feature_flag_offline.py`

## Non-goals (later milestones)
- No OIDC / JWT / API token (M2)
- No RBAC enforcement on routes (M3)
- No storage path changes (M4)
- No LangGraph integration (M5)
- No audit writer (M6)
- No admin UI (M7)

## Test plan
- [x] Unit tests: settings, models structure, base/mixins
- [x] Integration tests: alembic up/down, bootstrap idempotent, first admin creation, lifespan init/shutdown
- [x] Regression test: flag=off → gateway boots without DB, legacy endpoint responds
- [ ] Reviewer: run `make identity-test` locally with postgres+redis
- [ ] Reviewer: verify CI `backend-identity-tests` green

## Rollback
- Flag is off by default → revert is code-only, no data migration needed
- Alembic downgrade: `make db-downgrade-one` (drops all identity tables)
```

- [ ] **Step 14.5: Link PR in follow-up milestone plans**

Record the PR URL in the M2 plan's "Prerequisites" section before starting M2.

---

## M1 Self-Review Checklist

Run these mental checks before closing M1:

- [ ] Spec §4 DDL: every table in the migration? **Yes** (Task 6).
- [ ] Spec §4.2 seed content: 5 roles, ~24 permissions, default tenant, first admin? **Yes** (Task 8).
- [ ] Spec §10.1 feature flag default-off preserves legacy behavior? **Yes** (Task 12 regression guard).
- [ ] Spec §10.4 bootstrap is idempotent and handles multi-replica startup? **Idempotent ✓**; multi-replica race covered by unique constraints (Postgres will reject duplicates, M1 does not add advisory lock — noted for M7 migration hardening).
- [ ] Spec §10.6 postgres + redis deps? **Yes** (Tasks 1, 10).
- [ ] Spec §10.9 CI job? **Yes** (Task 11).
- [ ] Harness boundary preserved (no deerflow.* imports of app.*)? **Yes** — nothing in `packages/harness/` changes.
- [ ] Line length 240 / double quotes / ruff clean? **Enforced** (Task 14.3).
- [ ] Every code change has a test? **Yes** (TDD flow in each task).

If any item is red, fix before opening PR.
