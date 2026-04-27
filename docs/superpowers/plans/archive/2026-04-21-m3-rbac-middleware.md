# M3: RBAC + Tenant/Identity Middleware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Detail level: **signature-level TDD**.

**Goal:** Enforce permissions at three decision points — Gateway API routes (via `@requires` dependency), SQLAlchemy queries (auto `tenant_id` / `workspace_id` filter), and ContextVars propagated from IdentityMiddleware. Deliver the permission matrix for 5 seed roles. Expose `GET /api/roles` and `GET /api/permissions` (read-only).

**Architecture:** `rbac/decorator.py` exports `requires(tag, scope)` — a FastAPI dependency that reads `request.state.identity` (set in M2), matches path params against identity memberships/workspace_ids, raises 403 otherwise. `middlewares/tenant_scope.py` registers SQLAlchemy `do_orm_execute` event listener that injects `WHERE tenant_id = ?` and `workspace_id IN (...)` via `with_loader_criteria`. Adds **horizontal-access regression tests** across the 5 predefined roles.

**Prerequisites:** M2 merged. Branch `feat/m3-rbac` off `main`.

**Spec reference:** §6 (RBAC + middlewares), §4.3 (SQLAlchemy auto-filter).

**Non-goals:** no resource-instance-level ACL (P1); no custom-role editor (P1); no route enforcement for LangGraph tool calls (M5); no audit logging of denies (M6 — `authz.api.denied` is queued as an AuditEvent stub here but written by M6).

---

## File Structure

### Created

```
backend/app/gateway/identity/rbac/
  __init__.py
  decorator.py           # @requires factory + FastAPI Depends
  permissions.py         # flatten helpers; PermissionSet utility
  routes.py              # ROUTE_PERMISSION_MAP registry (optional — consumed by tests)
  errors.py              # PermissionDeniedError, with audit tagging

backend/app/gateway/identity/middlewares/
  tenant_scope.py        # SQLAlchemy event listener that injects filter; bypass helpers

backend/app/gateway/identity/routers/
  roles.py               # GET /api/roles, GET /api/permissions (read-only)

backend/tests/identity/rbac/
  __init__.py
  test_decorator.py
  test_permissions.py
  test_tenant_scope_filter.py
  test_horizontal_access.py     # matrix of 5 roles × key routes
  test_role_routes.py
```

### Modified

```
backend/app/gateway/identity/context.py          # add current_workspace_ids ContextVar, with_platform_privilege context manager
backend/app/gateway/app.py                       # register TenantScopeMiddleware (event listener) when flag on; include roles router
backend/app/gateway/identity/auth/identity_factory.py  # already populates identity.permissions / workspace_ids (M2)
backend/CLAUDE.md
```

---

## Task 1: `Identity` dataclass final shape

Ensure the `Identity` dataclass (introduced in M2) has the fields RBAC needs:

```python
@dataclass(frozen=True)
class Identity:
    user_id: int | None
    tenant_id: int | None
    workspace_ids: tuple[int, ...]
    permissions: frozenset[str]
    roles: dict             # {"platform": [...], "tenant": [...], "workspaces": {id: role_key}}
    session_id: str | None
    token_type: str         # "jwt" | "api_token" | "anonymous"
    ip: str | None
    is_platform_admin: bool

    def has_permission(self, tag: str) -> bool: ...
    def in_tenant(self, tenant_id: int) -> bool: ...
    def in_workspace(self, workspace_id: int) -> bool: ...
```

**Tests** (`test_permissions.py`): `has_permission` for platform_admin returns True for any tag (bypass); `in_tenant` true only when matches identity.tenant_id; `in_workspace` via `workspace_ids`.

---

## Task 2: `@requires` decorator

**Signature:**

```python
# rbac/decorator.py
from typing import Literal

Scope = Literal["platform", "tenant", "workspace"]

def requires(tag: str, scope: Scope):
    """FastAPI dependency factory.
    For scope='tenant', expects 'tenant_id' (or 'tid') as path param;
    for scope='workspace', expects 'ws_id' or 'workspace_id'; platform: no param.
    """
    async def dep(
        request: Request,
        **path_params,
    ) -> Identity:
        identity: Identity = request.state.identity
        if identity.token_type == "anonymous":
            raise HTTPException(status_code=401, detail={"error_code": "UNAUTHENTICATED"})
        if not identity.has_permission(tag):
            _queue_denied(identity, tag, scope, request)
            raise HTTPException(status_code=403, detail={"error_code": "PERMISSION_DENIED", "missing": tag})
        if scope == "tenant":
            tid = _extract_tenant_id(request)
            if tid is not None and not identity.in_tenant(tid):
                _queue_denied(identity, tag, scope, request, horizontal=True)
                raise HTTPException(status_code=403, detail={"error_code": "PERMISSION_DENIED"})
        elif scope == "workspace":
            wid = _extract_workspace_id(request)
            if wid is not None and not identity.in_workspace(wid):
                _queue_denied(identity, tag, scope, request, horizontal=True)
                raise HTTPException(status_code=403, detail={"error_code": "PERMISSION_DENIED"})
        return identity
    return dep


def _queue_denied(identity, tag, scope, request, *, horizontal: bool = False) -> None:
    """Emit AuditEvent via the event hook. M6 hooks actual writer; in M3 a no-op sink."""
```

**Tests** (`test_decorator.py`):

- anonymous → 401
- authenticated without perm → 403
- authenticated with perm, correct tenant → pass
- authenticated with perm, wrong tenant_id in path → 403 (horizontal)
- platform_admin → always pass regardless of tenant_id path
- scope=workspace with wid not in identity.workspace_ids → 403
- missing path param (e.g. scope=tenant but route has no `{tid}`) → fall through, check permission only (allows platform-level list endpoints like `/api/admin/tenants`)

---

## Task 3: `TenantScopeMiddleware` (SQLAlchemy event)

**Signature:**

```python
# middlewares/tenant_scope.py
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.gateway.identity.models import TenantScoped, WorkspaceScoped
from app.gateway.identity.context import current_identity

def install_auto_filter(session_maker) -> None:
    """Attach do_orm_execute event to the session class used by this app."""
    @event.listens_for(Session, "do_orm_execute")
    def _filter(execute_state):
        if not execute_state.is_select:
            return
        identity = current_identity.get()
        if identity is None:
            return
        if identity.is_platform_admin and not _force_tenant_filter():
            return
        if identity.tenant_id is None:
            return  # anonymous or platform admin without active tenant context
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                TenantScoped,
                lambda cls: cls.tenant_id == identity.tenant_id,
                include_aliases=True,
            )
        )
        if identity.workspace_ids:
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    WorkspaceScoped,
                    lambda cls: cls.workspace_id.in_(identity.workspace_ids),
                    include_aliases=True,
                )
            )

    @event.listens_for(Session, "before_flush")
    def _insert_guard(session, flush_context, instances):
        identity = current_identity.get()
        if identity is None or identity.is_platform_admin:
            return
        for obj in session.new:
            if isinstance(obj, TenantScoped) and obj.tenant_id != identity.tenant_id:
                raise PermissionDeniedError("cross-tenant insert rejected")
            if isinstance(obj, WorkspaceScoped) and obj.workspace_id not in identity.workspace_ids:
                raise PermissionDeniedError("cross-workspace insert rejected")
```

**Also:**

```python
# context.py additions
from contextlib import contextmanager

_force_platform_mode: ContextVar[bool] = ContextVar("force_platform_mode", default=False)

@contextmanager
def with_platform_privilege():
    """Temporarily bypass auto-filter (e.g., for migration scripts, admin jobs).
    MUST emit audit event when used.
    """
    token = _force_platform_mode.set(True)
    try:
        yield
    finally:
        _force_platform_mode.reset(token)
```

**Tests** (`test_tenant_scope_filter.py`):

- Tenant A user queries threads → only tenant A rows returned
- Platform admin queries without active tenant → all rows
- Insert with mismatched tenant_id → `PermissionDeniedError`
- `with_platform_privilege()` → queries return all tenants; audit event emitted
- JOIN across two TenantScoped tables → filter applied to both
- Workspace filter applied when identity has workspace_ids

---

## Task 4: Roles / Permissions read-only router

```python
# routers/roles.py
@router.get("/api/roles")
async def list_roles(session=Depends(get_session)): ...

@router.get("/api/permissions")
async def list_permissions(session=Depends(get_session)): ...
```

Both routes require only `Depends(require_authenticated)` (any logged-in user; UI needs these to render guards).

**Tests** (`test_role_routes.py`): 5 seed roles returned; 24 permissions returned; anonymous gets 401.

---

## Task 5: Horizontal access matrix test

`test_horizontal_access.py`:

```python
import pytest

@pytest.mark.parametrize(
    "role,route,method,path_params,expected_status",
    [
        # viewer
        ("viewer",          "/api/tenants/{tid}/workspaces/{wid}/threads", "POST",   {"tid": 1, "wid": 1}, 403),
        ("viewer",          "/api/tenants/{tid}/workspaces/{wid}/threads", "GET",    {"tid": 1, "wid": 1}, 200),
        # member
        ("member",          "/api/tenants/{tid}/workspaces/{wid}/threads", "POST",   {"tid": 1, "wid": 1}, 201),
        ("member",          "/api/tenants/{tid}/workspaces/{wid}/skills/{skid}", "DELETE", {"tid": 1, "wid": 1, "skid": 1}, 403),
        # workspace_admin
        ("workspace_admin", "/api/tenants/{tid}/workspaces/{wid}/skills/{skid}", "DELETE", {"tid": 1, "wid": 1, "skid": 1}, 200),
        # tenant_owner
        ("tenant_owner",    "/api/tenants/{tid}/workspaces", "POST", {"tid": 1}, 201),
        ("tenant_owner",    "/api/admin/tenants", "POST", {}, 403),  # cross-tenant action
        # platform_admin
        ("platform_admin",  "/api/admin/tenants", "POST", {}, 201),
        # horizontal across tenants
        ("tenant_owner",    "/api/tenants/{tid}/workspaces", "POST", {"tid": 99}, 403),  # other tenant
    ],
)
async def test_rbac_matrix(role, route, method, path_params, expected_status, client, identity_factory):
    ...
```

Implement `identity_factory` fixture that signs a JWT for each role against the seed data. These routes need stubs in M3 that return 201/200 only to prove the decorator; actual business logic lands in M4/M7.

---

## Task 6: Wire middleware + routers

In `app/gateway/app.py::_init_identity_subsystem`, after M2 setup, add:

```python
from app.gateway.identity.middlewares.tenant_scope import install_auto_filter
install_auto_filter(_sessionmaker)

from app.gateway.identity.routers import roles as roles_router_module
app.include_router(roles_router_module.router)
```

Flag-off regression (from M1) still green.

---

## Task 7: Stub routes used by matrix test

Add thin routes in `app/gateway/routers/` (or dedicated `app/gateway/identity/routers/admin_stub.py`) to satisfy the matrix test. They return empty JSON with correct status after `Depends(requires(...))` passes. Real implementation lives in M7.

---

## Task 8: API-token permission cache + invalidation (spec §6.5)

**Rationale:** JWT carries permissions in claims so it needs no cache (permissions valid until `exp`). API tokens are verified every request and must avoid re-computing the permission set each hit.

**Signatures:**

```python
# rbac/permissions.py (additional helpers)
async def get_cached_permissions(redis, user_id: int, tenant_id: int | None) -> set[str] | None:
    """Return cached permissions set or None. Key: 'identity:perms:{user_id}:{tenant_id or "platform"}'. TTL 300s."""

async def set_cached_permissions(redis, user_id: int, tenant_id: int | None, perms: set[str]) -> None: ...

async def invalidate_permission_cache(redis, user_id: int, *, tenant_id: int | None = None) -> None:
    """If tenant_id provided, clear that one key; else delete all keys under 'identity:perms:{user_id}:*'."""

async def mark_user_sessions_stale(redis, user_id: int) -> None:
    """Add user_id to SET 'identity:perms:stale_users'. IdentityMiddleware checks this set on each request;
    if user is stale, forces a fresh flatten, writes new cache, and removes the mark.
    """
```

**Producers** (call invalidate when role/permission membership changes):
- M7 admin-ui role assignment endpoint → invalidate
- M7 membership add/remove → invalidate
- M1 seed changes (exceptional) → no runtime invalidate; requires restart (documented in runbook)

**UI signaling:** When `mark_user_sessions_stale` fires, the next `/api/me` response includes header `X-Deerflow-Session-Stale: 1` — frontend surfaces "your permissions were updated; please reload" banner (implemented in M7 Part A). No in-flight session upgrade (v1 simplification per spec §6.5).

**Tests:**
- `get_cached_permissions` cold → None
- `set_cached_permissions` + `get_cached_permissions` round-trip
- `invalidate_permission_cache` clears the key
- `mark_user_sessions_stale` + subsequent identity resolution → fresh flatten + cache write
- TTL 300s respected

---

## Task 9: Docs + PR

- Update `CLAUDE.md` with RBAC section (decision points, mixin usage, SQL filter).
- Update `README.md` roadmap.
- Push `feat/m3-rbac`, open PR.

## Self-review vs spec §6

- §6.1 three decision points → Task 2 (API), Task 3 (SQL), M5 (tools — deferred).
- §6.2 permission naming → uses seed from M1. ✓
- §6.3 predefined routes → stubbed in Task 7.
- §6.4 Guardrail upgrade → M5 (noted as deferred).
- §6.5 permissions flatten + cache → identity_factory handles flatten in M2; cache added when M6 audit + cache-invalidation lands (noted for M6).
- §6.6 switch-tenant → route landed in M2; M3 ensures new identity's permissions correctly flatten.
- §6.7/§6.9 non-goals and invariants → covered by Task 3 tests.
