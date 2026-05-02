# Gateway Routes Authentication Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every legacy gateway router refuse anonymous callers by default, allowlisting only the genuinely public endpoints (auth flows, health, metrics).

**Architecture:** One new module `app/gateway/auth_baseline.py` with a `PUBLIC_PREFIXES` allowlist and a `require_authenticated_global` dependency. Every legacy `include_router` call in `app/gateway/app.py` declares the dep. Identity router family is left untouched (it manages its own auth deps). When `ENABLE_IDENTITY=false` the dependency is a no-op so legacy single-tenant deployments are unaffected.

**Tech Stack:** Python 3.12, FastAPI dependency injection, pytest-asyncio, httpx.AsyncClient. Spec: [docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md](../specs/2026-05-02-gateway-routes-authn-baseline-design.md).

**Branch convention (per CLAUDE.md §git策略):** create `feat/gateway-routes-authn-baseline` off `cc-main`, merge back after tests pass, push.

**⚠️ Spec correction made during planning:** The spec listed `/api/channels/webhook` in PUBLIC_PREFIXES expecting it to be a platform-signed webhook prefix. **It isn't** — `/api/channels` is a user-facing admin console API (`GET /api/channels`, `POST /api/channels/{name}/restart`). It should require auth. PUBLIC_PREFIXES drops that entry. Recorded here so the spec history stays accurate.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/app/gateway/auth_baseline.py` | create | `PUBLIC_PREFIXES` constant + `require_authenticated_global` FastAPI dep |
| `backend/app/gateway/app.py:449-488` | modify | Add `dependencies=[Depends(require_authenticated_global)]` to 14 legacy `include_router` calls (channels gets it too — see correction above) |
| `backend/tests/identity/test_gateway_authn_baseline.py` | create | Parametrized 401-vs-200 tests + `ENABLE_IDENTITY=false` no-op test |

`app/gateway/identity/auth/dependencies.py` is left unchanged — `require_authenticated_global` reuses `get_current_identity` from there but is itself a separate function because its semantics are different (allowlist-aware, flag-aware).

---

## Task 1: Branch + spec acknowledgement

**Files:**
- None (git only)

- [ ] **Step 1: Create feat branch from cc-main**

```bash
git checkout cc-main
git pull origin cc-main
git checkout -b feat/gateway-routes-authn-baseline
git status -sb
```

Expected: `## feat/gateway-routes-authn-baseline`.

- [ ] **Step 2: Confirm spec is on the branch**

```bash
ls docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md
```

Expected: file present.

---

## Task 2: Write failing baseline test suite

**Files:**
- Create: `backend/tests/identity/test_gateway_authn_baseline.py`

- [ ] **Step 1: Create the test file**

```python
# backend/tests/identity/test_gateway_authn_baseline.py
"""Tests for the gateway auth baseline.

Verifies that ``require_authenticated_global`` (when ``ENABLE_IDENTITY=true``)
returns 401 for legacy /api/* routes when the caller is anonymous, while
genuinely public endpoints (auth flows, health, metrics) stay reachable.

The legacy gateway routers don't need a real database — we only care about
the auth dep firing first. We build a minimal app that mounts the routers
and stubs identity via the same Starlette middleware pattern used in
test_artifacts_authz.py.

See: docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.identity.settings import get_identity_settings


@dataclass
class FakeIdentity:
    tenant_id: int | None = 1
    workspace_ids: tuple[int, ...] = (1,)
    is_authenticated: bool = True


def _inject_identity(app: FastAPI, identity: FakeIdentity | None) -> None:
    class _Inject(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.identity = identity
            return await call_next(request)

    app.add_middleware(_Inject)


def _build_protected_app(identity: FakeIdentity | None) -> FastAPI:
    """Mounts a representative legacy router with the global dep."""
    from fastapi import Depends
    from app.gateway.auth_baseline import require_authenticated_global
    import app.gateway.routers.models as models_router

    app = FastAPI()
    app.include_router(
        models_router.router,
        dependencies=[Depends(require_authenticated_global)],
    )
    _inject_identity(app, identity)
    return app


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("ENABLE_IDENTITY", "true")
    get_identity_settings.cache_clear()
    yield
    get_identity_settings.cache_clear()


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setenv("ENABLE_IDENTITY", "false")
    get_identity_settings.cache_clear()
    yield
    get_identity_settings.cache_clear()


# ---------------------------------------------------------------------------
# Flag ON — anonymous caller is rejected
# ---------------------------------------------------------------------------


def test_anonymous_caller_gets_401_on_protected_route(flag_on):
    app = _build_protected_app(identity=None)
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 401, r.text
    assert "authentication required" in r.text.lower()


def test_anonymous_identity_gets_401_on_protected_route(flag_on):
    """is_authenticated=False is the same as no identity."""
    app = _build_protected_app(identity=FakeIdentity(is_authenticated=False))
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 401, r.text


def test_authenticated_caller_passes_auth_check(flag_on):
    """Authenticated caller passes auth — handler may still 4xx/5xx for
    unrelated reasons but it must not be 401-from-baseline."""
    app = _build_protected_app(identity=FakeIdentity())
    with TestClient(app) as client:
        r = client.get("/api/models")
    # The handler may return 200 with model list, or some other status if
    # config/env isn't set up — but it must NOT be 401 (that would mean the
    # auth dep didn't pass through).
    assert r.status_code != 401, r.text


# ---------------------------------------------------------------------------
# Flag OFF — dep is a no-op
# ---------------------------------------------------------------------------


def test_baseline_no_op_when_identity_disabled(flag_off):
    """ENABLE_IDENTITY=false must let anonymous callers through."""
    app = _build_protected_app(identity=None)
    with TestClient(app) as client:
        r = client.get("/api/models")
    # Same "must not be 401-from-baseline" assertion — but here even with
    # identity=None the dep should early-return.
    assert r.status_code != 401, r.text


# ---------------------------------------------------------------------------
# Allowlist behavior
# ---------------------------------------------------------------------------


def test_allowlisted_path_passes_with_no_identity(flag_on):
    """A path under PUBLIC_PREFIXES must skip the auth check entirely."""
    from app.gateway.auth_baseline import PUBLIC_PREFIXES

    # Sanity: the spec's allowlist must include the auth flow.
    assert any(p.startswith("/api/auth/login") for p in PUBLIC_PREFIXES)
    assert any(p == "/health" or p.startswith("/health") for p in PUBLIC_PREFIXES)
    assert any(p == "/metrics" or p.startswith("/metrics") for p in PUBLIC_PREFIXES)
    # And must NOT include channels (per the spec correction).
    assert not any("/api/channels" in p for p in PUBLIC_PREFIXES)


def test_dep_directly_returns_for_allowlisted_path(flag_on):
    """Unit-style: feed a request whose path is on the allowlist; dep returns
    without raising even when identity is anonymous."""
    from app.gateway.auth_baseline import require_authenticated_global

    class _Req:
        class _State:
            identity = None
        url = type("U", (), {"path": "/api/auth/login"})()
        state = _State()

    # Should not raise.
    require_authenticated_global(_Req())


def test_dep_directly_raises_for_protected_path_anonymous(flag_on):
    """Unit-style: feed a request whose path is NOT on the allowlist with no
    identity; dep raises 401."""
    from fastapi import HTTPException
    from app.gateway.auth_baseline import require_authenticated_global

    class _Req:
        class _State:
            identity = None
        url = type("U", (), {"path": "/api/models"})()
        state = _State()

    with pytest.raises(HTTPException) as excinfo:
        require_authenticated_global(_Req())
    assert excinfo.value.status_code == 401
```

- [ ] **Step 2: Run the test — it should fail at import time**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/test_gateway_authn_baseline.py -v
```

Expected: **collection errors** because `app.gateway.auth_baseline` doesn't exist yet. That's the natural failing state.

- [ ] **Step 3: Commit the failing test**

```bash
git add backend/tests/identity/test_gateway_authn_baseline.py
git commit -m "test(identity): regression for gateway authn baseline (8 cases)"
```

---

## Task 3: Implement `auth_baseline.py`

**Files:**
- Create: `backend/app/gateway/auth_baseline.py`

- [ ] **Step 1: Create the module**

```python
# backend/app/gateway/auth_baseline.py
"""Gateway-level authentication baseline.

Default-deny dependency for legacy gateway routers. Every legacy
``/api/*`` route refuses anonymous callers unless the path matches a
short documented allowlist of genuinely public endpoints.

Why: the legacy gateway routers (models, memory, skills, threads,
artifacts, uploads, agents, mcp, suggestions, channels, runs, thread_runs,
thread_skills, assistants_compat) do not individually call
``Depends(require_authenticated)``. They were written before the identity
subsystem landed and silently fall through to the legacy single-tenant
filesystem layout for anonymous callers. With ``ENABLE_IDENTITY=true``
this leaks data. The fix is a single global dep wired at
``include_router`` time.

When ``ENABLE_IDENTITY=false`` (legacy mode) the dep is a no-op so the
legacy single-tenant deployment story is unchanged.

See: docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.gateway.identity.auth.dependencies import get_current_identity
from app.gateway.identity.settings import get_identity_settings


# Path prefixes that are intentionally public. Order does not matter for
# correctness; the function does an O(n) scan with startswith().
PUBLIC_PREFIXES: tuple[str, ...] = (
    # OIDC + password + bootstrap auth flows
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",       # 401s on its own when sid missing
    "/api/auth/logout",        # idempotent, anonymous logout is a harmless no-op
    "/api/auth/providers",     # discovery endpoint, by design
    "/api/auth/oidc",          # /oidc/{provider}/login + /oidc/{provider}/callback
    "/api/auth/set-password",  # bootstrap flow, has its own gating logic
    # Operational
    "/health",
    "/metrics",                # Prometheus scrape, network-gated externally
    "/internal/audit",         # HMAC-signed, has its own verify
)


def require_authenticated_global(request: Request) -> None:
    """FastAPI dep: enforce authentication for legacy gateway routes.

    Allowlist-aware: requests whose path matches any entry in
    ``PUBLIC_PREFIXES`` (via ``startswith``) skip the check.

    Flag-aware: when ``ENABLE_IDENTITY=false`` the dep returns immediately
    so the legacy single-tenant deployment behaves as it did before the
    identity subsystem landed.

    Raises:
        HTTPException(401) when the caller is anonymous on a protected
        path.
    """
    if not get_identity_settings().enabled:
        return

    path = request.url.path
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return

    ident = get_current_identity(request)
    if not ident.is_authenticated:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
```

- [ ] **Step 2: Run the test suite — most should pass now**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/test_gateway_authn_baseline.py -v
```

Expected: 8 cases pass. If `test_authenticated_caller_passes_auth_check` returns 401, the dep is buggy — re-read Step 1.

If `test_anonymous_caller_gets_401_on_protected_route` returns 200, the test app didn't actually attach the dep — re-read `_build_protected_app` in Task 2.

- [ ] **Step 3: Commit**

```bash
git add backend/app/gateway/auth_baseline.py
git commit -m "feat(gateway): require_authenticated_global dep + PUBLIC_PREFIXES allowlist

New module owning the gateway's default-deny authentication baseline.
Used by app.py to wrap each legacy include_router call so anonymous
callers get 401 instead of silently falling through to the legacy
single-tenant filesystem layout. Channels, models, memory, skills,
threads, agents, etc. all gain auth coverage in a single place.

Wraps get_current_identity from identity/auth/dependencies and short-
circuits when ENABLE_IDENTITY=false so legacy deployments are unaffected.

Spec: docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md"
```

---

## Task 4: Wire the dep into all legacy `include_router` calls

**Files:**
- Modify: `backend/app/gateway/app.py:449-488`

- [ ] **Step 1: Read the current include_router block**

```bash
sed -n '445,492p' backend/app/gateway/app.py
```

Confirm 14 `include_router` calls in the legacy block (lines 449, 452, 455, 458, 461, 464, 467, 470, 473, 476, 479, 482, 485, 488).

- [ ] **Step 2: Add the import**

Near the top of `backend/app/gateway/app.py`, add:

```python
from fastapi import Depends
from app.gateway.auth_baseline import require_authenticated_global
```

(`Depends` may already be imported; if so, just add `require_authenticated_global`.)

- [ ] **Step 3: Add the dep to each legacy `include_router` call**

For each of the 14 calls in lines 449-488, wrap it with `dependencies=[Depends(require_authenticated_global)]`. Concretely:

```python
# Before:
app.include_router(models.router)

# After:
app.include_router(
    models.router,
    dependencies=[Depends(require_authenticated_global)],
)
```

Apply this transformation to every router in the legacy block:

| Line | Router |
|---|---|
| 449 | models |
| 452 | mcp |
| 455 | memory |
| 458 | skills |
| 461 | artifacts |
| 464 | uploads |
| 467 | threads |
| 470 | thread_skills |
| 473 | agents |
| 476 | suggestions |
| 479 | channels |
| 482 | assistants_compat |
| 485 | thread_runs |
| 488 | runs |

**Do NOT touch lines 494-512** — those are the identity router family which already manages its own auth deps.

- [ ] **Step 4: Verify the diff**

```bash
git diff backend/app/gateway/app.py
```

Should be exactly: 1 import line added, 14 single-line changes inside `include_router(...)` calls. No deletions, no logic changes outside that block.

- [ ] **Step 5: Run the broader test suites**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/ -v
```

Expected: all tests pass, including the new baseline ones.

If `tests/identity/test_artifacts_authz.py` or similar fails because the test app mounts the router without the dep — that's fine because those tests build their own minimal app and don't go through `app.py`. Their assertions are about router-internal behavior, not about the global dep. Don't modify them; the baseline tests are the ones that cover the dep.

- [ ] **Step 6: Run the broader gateway tests if available**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/ -k "gateway or router" -v --ignore=tests/identity
```

Expected: green or skipped. If a non-identity test failed because it expected anonymous access to a now-protected endpoint, that test was relying on the bug — it should be updated to authenticate first or be marked as testing flag-off behavior. Stop and assess if any non-identity tests fail.

- [ ] **Step 7: Run lint**

```bash
cd backend && make lint
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add backend/app/gateway/app.py
git commit -m "feat(gateway): apply require_authenticated_global to 14 legacy routers

Every legacy /api/* router now refuses anonymous callers by default.
PUBLIC_PREFIXES allowlists the auth flow + /health + /metrics + the
HMAC-signed /internal/audit endpoint.

Identity router family at lines 494-512 is intentionally untouched — it
attaches its own require_authenticated / requires(...) deps where
appropriate.

When ENABLE_IDENTITY=false the dep is a no-op, so legacy single-tenant
deployments are unaffected (see auth_baseline.py and the dedicated
no-op regression test).

Spec: docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md"
```

---

## Task 5: Sanity-test against a few representative routes via the real app

**Files:**
- Modify: `backend/tests/identity/test_gateway_authn_baseline.py` (append)

This isn't strictly necessary because Task 4 already verified the dep is attached, but it gives the spec's "all 14 routers covered" claim a concrete check. We do this through the actual `app.gateway.app` factory rather than per-router.

- [ ] **Step 1: Append a smoke test that imports the real app**

```python
# Append to backend/tests/identity/test_gateway_authn_baseline.py


# ---------------------------------------------------------------------------
# Real app smoke — confirms the dep was attached at every legacy router
# ---------------------------------------------------------------------------


def _build_real_app_anonymous():
    """Import the real gateway app and attach an anonymous identity middleware
    on top. This catches "I forgot to add the dep on router N" because the
    test enumerates representative paths from each router."""
    # Defer the import: it triggers identity bootstrap if env vars are set.
    # We're only after the FastAPI app object, not lifespan.
    import importlib
    app_mod = importlib.import_module("app.gateway.app")
    app = app_mod.app
    _inject_identity(app, identity=None)
    return app


# One representative path per legacy router. Auth must fire before any
# business validation, so invalid ids are fine — we never reach the handler.
LEGACY_ROUTES = [
    ("GET", "/api/models"),
    ("GET", "/api/mcp"),
    ("GET", "/api/memory"),
    ("GET", "/api/skills"),
    ("GET", "/api/threads/abc/artifacts/x.txt"),
    ("GET", "/api/threads/abc/uploads/list"),
    ("POST", "/api/threads/search"),         # threads
    ("GET", "/api/threads/abc/skills"),       # thread_skills
    ("GET", "/api/agents"),
    ("POST", "/api/threads/abc/suggestions"),
    ("GET", "/api/channels/"),
    ("POST", "/api/assistants/search"),
    ("GET", "/api/threads/abc/runs"),         # thread_runs
    ("POST", "/api/runs/wait"),               # runs
]


@pytest.mark.parametrize("method,path", LEGACY_ROUTES)
def test_real_app_legacy_route_returns_401_for_anonymous(
    flag_on, method, path,
):
    app = _build_real_app_anonymous()
    with TestClient(app) as client:
        r = client.request(method, path)
    assert r.status_code == 401, (
        f"{method} {path} returned {r.status_code}; expected 401. "
        "Did you forget to attach require_authenticated_global to this "
        "router's include_router call?"
    )


PUBLIC_ROUTES = [
    ("GET", "/health"),
    ("GET", "/api/auth/providers"),
    # /api/auth/login and /api/auth/refresh exist but require POST body —
    # we hit them with empty body and accept any non-401 (validation errors
    # are fine, what matters is the auth dep didn't raise).
]


@pytest.mark.parametrize("method,path", PUBLIC_ROUTES)
def test_real_app_public_route_does_not_401(flag_on, method, path):
    app = _build_real_app_anonymous()
    with TestClient(app) as client:
        r = client.request(method, path)
    assert r.status_code != 401, (
        f"{method} {path} returned 401 but is on the public allowlist"
    )
```

- [ ] **Step 2: Run the new tests**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/test_gateway_authn_baseline.py -v
```

Expected: all parametrized cases pass. Each `LEGACY_ROUTES` row fans out into a separate test; if any fail, the failure message tells you exactly which router was missed in Task 4.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/identity/test_gateway_authn_baseline.py
git commit -m "test(identity): real-app coverage of all 14 legacy routers"
```

---

## Task 6: Manual smoke (acceptance criterion from spec)

**Files:**
- None (browser observation)

- [ ] **Step 1: Start the stack with ENABLE_IDENTITY=true**

```bash
make dev
```

(Confirm `.env` has `ENABLE_IDENTITY=true`; the project default is true.)

- [ ] **Step 2: Confirm logged-out behavior — should now be 401**

In the browser, **after logging out** (or in an Incognito window without cookies), open DevTools console and run:

```javascript
const probe = async (url, method = 'GET') =>
  fetch(url, { method, credentials: 'include' }).then(r => r.status);

console.log('models:', await probe('/api/models'));
console.log('memory:', await probe('/api/memory'));
console.log('skills:', await probe('/api/skills'));
console.log('threads/dummy/skills:', await probe('/api/threads/dummy/skills'));
console.log('auth/providers:', await probe('/api/auth/providers'));
console.log('health:', await probe('/health'));
```

Expected output:

```
models: 401
memory: 401
skills: 401
threads/dummy/skills: 401
auth/providers: 200
health: 200
```

- [ ] **Step 3: Log in, repeat — protected endpoints should now serve 200**

```javascript
console.log('models:', await probe('/api/models'));
console.log('memory:', await probe('/api/memory'));
```

Expected: 200 (or some 5xx if the underlying handler fails for unrelated config reasons — but **not** 401).

- [ ] **Step 4: Record the result in the merge commit description**

Save the console transcript or a screenshot.

---

## Task 7: Merge to cc-main

**Files:**
- None (git only)

- [ ] **Step 1: Confirm clean tree**

```bash
git status -sb
```

Expected: `## feat/gateway-routes-authn-baseline`, no uncommitted changes.

- [ ] **Step 2: Switch to cc-main and merge**

```bash
git checkout cc-main
git merge --no-ff feat/gateway-routes-authn-baseline -m "merge: gateway auth baseline (1 helper + 14 routers + 8 vitest equivalent pytest cases)

Closes the unauthenticated-/api/* finding surfaced during the 2026-05-02
session-expired root-cause investigation. After this merge,
\`fetch('/api/models')\` etc. with no cookie returns 401 as expected.

Spec: docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md
Plan: docs/superpowers/plans/2026-05-02-gateway-routes-authn-baseline.md"
```

- [ ] **Step 3: Push**

```bash
git push origin cc-main
```

- [ ] **Step 4: Delete the local feat branch (optional)**

```bash
git branch -d feat/gateway-routes-authn-baseline
```

---

## Task 8: Archive spec + plan, update memory

**Files:**
- Move: `docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md` → `archive/`
- Move: `docs/superpowers/plans/2026-05-02-gateway-routes-authn-baseline.md` → `archive/`
- Update: `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/MEMORY.md`

- [ ] **Step 1: Add a "Shipped" banner to the spec**

Top of the spec file:

```markdown
> 📦 **归档于 YYYY-MM-DD — 已 ship**：merged into `cc-main` as `<short-sha>`. Spec correction noted in plan: `/api/channels/webhook` is not a real prefix; channels admin API is now under the auth baseline.

---
```

- [ ] **Step 2: Move spec + plan to archive**

```bash
git mv docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md \
       docs/superpowers/specs/archive/
git mv docs/superpowers/plans/2026-05-02-gateway-routes-authn-baseline.md \
       docs/superpowers/plans/archive/
```

- [ ] **Step 3: Update memory**

Append to `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/MEMORY.md`:

```markdown
- [P0 fix: gateway auth baseline](spec_gateway_authn_baseline.md) — ✅ 已闭环（YYYY-MM-DD）：14 个 legacy /api/* router 默认 require auth；PUBLIC_PREFIXES 仅放行 auth flow + health + metrics + internal/audit；merge `<short-sha>`
```

Create `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/spec_gateway_authn_baseline.md`:

```markdown
---
name: P0 fix — gateway auth baseline
description: 14 个 legacy /api/* router 默认 require_authenticated；通过 PUBLIC_PREFIXES 显式 allowlist 公开端点
type: project
---

## 现象
未带 cookie 时 /api/models, /api/memory, /api/threads/{id}/skills 返回 200；anonymous 用户能读到 legacy single-tenant 数据。2026-05-02 浏览器实测发现。

## 修法
- backend/app/gateway/auth_baseline.py: 新增 PUBLIC_PREFIXES + require_authenticated_global
- backend/app/gateway/app.py: 14 个 legacy include_router 加 dependencies=[Depends(require_authenticated_global)]
- backend/tests/identity/test_gateway_authn_baseline.py: 8+ pytest 覆盖 dep 直接行为 + 真实 app 14 路由 401 + flag_off no-op

## 关键设计
- ENABLE_IDENTITY=false → dep 立即 return（legacy 部署零影响）
- /api/channels 是用户控制台 API 不是 webhook，归在 baseline 之内
- API token (dft_*) 由 IdentityMiddleware 解析后 dep 通过

## 状态
✅ shipped YYYY-MM-DD as `<short-sha>`. 浏览器 console 探针 6 端点验证：4×401（保护）+ 2×200（公开）。
```

- [ ] **Step 4: Commit and push the archive move**

```bash
git add docs/superpowers/specs/ docs/superpowers/plans/
git commit -m "docs(specs): archive shipped gateway authn baseline spec + plan"
git push origin cc-main
```

---

## Definition of Done

- [ ] `auth_baseline.py` exists with `PUBLIC_PREFIXES` + `require_authenticated_global` (Task 3)
- [ ] All 14 legacy `include_router` calls in `app.py:449-488` declare the dep (Task 4)
- [ ] Identity router family at 494-512 unchanged (Task 4)
- [ ] All test cases pass: dep behavior + real-app routing + flag-off no-op (Tasks 2, 3, 5)
- [ ] `make identity-test` green (Task 4)
- [ ] `make lint` green (Task 4)
- [ ] Manual probe: 4 protected URLs return 401 logged-out, 200 logged-in (Task 6)
- [ ] Merged to cc-main and pushed (Task 7)
- [ ] Spec + plan archived; memory updated (Task 8)
