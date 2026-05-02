> 📦 **归档于 2026-05-02 — 已 ship**：merged into `cc-main` as `3f9d35f5`. 23 pytest 全绿（含 14 legacy router 真实应用 smoke）。Browser-validated 6 endpoints × {logged-out, logged-in}：`/api/models`, `/api/memory`, `/api/skills`, `/api/threads/dummy/skills` 在 logged-out 时由 200 改为 401，logged-in 仍 200；`/api/auth/providers`, `/health` 维持 200。Plan 中已记录的 spec 修正（`/api/channels/webhook` 不是真路径）落实到 PUBLIC_PREFIXES 中。
>
> 实施额外补丁：测试用 `_build_real_app_anonymous()` 共享 `real_app.router.routes` 进 fresh FastAPI clone（绕过 Starlette "cannot add middleware after start" 限制），`raise_server_exceptions=False`（让 handler 内部错误不掩盖 auth dep 行为）。两者都是测试基础设施层面的解决，不影响 prod。

---

# Gateway Routes Authentication Baseline

**Date:** 2026-05-02
**Status:** ✅ Shipped (see banner above)
**Owner:** backend (gateway)
**Touches:**
- `backend/app/gateway/app.py` — global auth dependency on legacy routers
- `backend/app/gateway/routers/*.py` — opt-out markers for genuinely public endpoints
- `backend/tests/identity/test_gateway_authn_baseline.py` (new)

## Problem

Discovered during the 2026-05-02 browser-debug session: with
`ENABLE_IDENTITY=true`, almost every legacy gateway endpoint accepts requests
**without any cookie or token**:

```
GET  /api/me                              → 401  ✓ correct
POST /api/auth/refresh                    → 401  ✓ correct
GET  /api/auth/providers                  → 200  ✓ public by design
GET  /api/models                          → 200  ❌ leaks model config
GET  /api/memory                          → 200  ❌ leaks user memory
GET  /api/threads/{id}/skills             → 200  ❌ leaks thread metadata
```

Verified manually via fetch calls in the live app after `POST /api/auth/logout`
cleared the cookie. Sixteen legacy gateway routers are registered in
`app.py:449-488`; **none** of them attach `Depends(require_authenticated)` or
`Depends(requires(...))`. The identity middleware does set
`request.state.identity` to `Identity.anonymous()` for unauthenticated callers,
but every router happily proceeds to do work for that anonymous identity —
e.g., `extract_scope()` returns `(None, None)` and the handler silently falls
back to legacy single-tenant filesystem layout, exposing the data of whatever
that legacy path resolves to.

This is a P0-class authorization defect that is logically independent of the
session-management bugs (Issues ① and ②). It exists with or without those.

## Scope clarification

**In scope (this spec):** baseline authentication. Every legacy gateway endpoint
that is not on a documented allowlist must require an authenticated identity
(any logged-in user, any tenant). The result for an anonymous caller is `401`.

**Out of scope (future spec):** fine-grained authorization. Tenant-scoped or
permission-scoped (`requires("thread:write", "workspace")`-style) checks for
specific endpoints. The current `extract_scope()` + `Paths.resolve_*` helpers
already partially handle tenant isolation when the caller is authenticated —
this spec keeps that working but does not extend it.

The two spec layers (authn baseline → authz refinement) are decoupled because:

- authn baseline is a single global dependency injection
- authz refinement is a per-route policy decision that takes much longer to
  audit and approve

## Goals

- All 16 legacy gateway routers refuse anonymous callers by default with `401`.
- Genuinely public endpoints (login, refresh, providers, register, health,
  metrics) are explicitly allowlisted.
- Identity router family is unaffected (it already manages its own deps).
- LangGraph compat routers (`assistants_compat`, `runs`, `thread_runs`,
  `threads`) — verify whether their callers (the SDK) currently send the
  cookie. They do — verified in the same browser session — so requiring auth
  does not break the SDK.
- Tests assert each router refuses unauthenticated callers.

## Non-goals

- ❌ Per-endpoint permission tags (`thread:write`, `skill:invoke`, etc.) —
  handled by a future spec.
- ❌ Tenant boundary enforcement on individual handlers (the
  `extract_scope()` + path-guard system already handles this for callers that
  reach the handler — and after this spec, they only reach it when
  authenticated).
- ❌ Rate limiting or anti-CSRF (separate concerns).
- ❌ API-token (`dft_*`) flows — already covered by `IdentityMiddleware`'s
  Bearer support; just need to make sure the dependency lets them through.
- ❌ Channels (Slack/Telegram/Feishu webhooks) require their own signature
  verification, not user identity. Out of this spec; keep current behavior.

## Approach

**Layered defense at the FastAPI app level**, not router-by-router. We add a
single `app.dependency_overrides`-style global dependency on the legacy router
*include points* and explicitly allowlist public endpoints by path prefix.

### Step 1 — define the allowlist

In a new `backend/app/gateway/auth_baseline.py`:

```python
from fastapi import Depends, HTTPException, Request, status
from app.gateway.identity.auth.dependencies import get_current_identity
from app.gateway.identity.settings import get_identity_settings

# Path prefixes that are intentionally public. Order matters: the first match
# wins. Uses startswith() against request.url.path.
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",     # 401 on its own when sid missing — see auth.py
    "/api/auth/logout",      # idempotent; no-op on anonymous is fine
    "/api/auth/providers",   # discovery endpoint, by design
    "/api/auth/oidc",        # OIDC redirect + callback
    "/api/auth/set-password",  # admin bootstrap; gated by its own logic
    "/health",
    "/metrics",              # Prometheus scrape, network-gated
    "/internal/audit",       # HMAC-signed, has its own verify
    "/api/channels/webhook", # platform-signed, out of scope
)


async def require_authenticated_global(request: Request) -> None:
    """Module-level FastAPI dep: enforce authentication for legacy gateway
    routes unless the path matches PUBLIC_PREFIXES.

    Anonymous request → 401. API tokens (dft_*) and JWT cookies both work
    because IdentityMiddleware already resolved them into request.state.identity.
    """
    if not get_identity_settings().enabled:
        return  # ENABLE_IDENTITY=false → fully open, legacy mode

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

### Step 2 — apply at include time

`backend/app/gateway/app.py`:

```python
from app.gateway.auth_baseline import require_authenticated_global

# Existing legacy routers — gain the global dep:
app.include_router(models.router, dependencies=[Depends(require_authenticated_global)])
app.include_router(mcp.router,    dependencies=[Depends(require_authenticated_global)])
# ... 14 more legacy include_router calls likewise
```

(Apply only to the **legacy** include_router block at lines 449-488. The
identity router family at 494-512 is left untouched — those routers already
embed their own `require_authenticated` / `requires(...)` deps where
appropriate, and would otherwise double-check.)

### Why this design

| Property | Mechanism |
|---|---|
| Single source of truth | one allowlist, one dep, one place to audit |
| Backward-compatible with `ENABLE_IDENTITY=false` | dep early-returns when flag is off |
| Backward-compatible with API tokens | `IdentityMiddleware` already populates identity from `Authorization: Bearer dft_...` headers |
| Doesn't touch identity router family | only legacy includes are wrapped |
| Allowlist-not-blocklist | safer default; new routers automatically inherit auth |
| Gradual rollout possible | dep is a single import; can be disabled per-router by passing an empty `dependencies=[]` if a regression appears |

### Why not per-route Depends?

Per-route `Depends(require_authenticated)` was the obvious alternative. It
loses on three counts:

1. **Volume**: ~70 route handlers across 16 files. Each needs an edit.
2. **Drift**: a future contributor adding a new endpoint forgets to attach
   the dep. The bug recurs.
3. **Audit cost**: reviewers can't tell at a glance which routes are protected
   without grep-ing every file.

Allowlist-at-include solves all three.

## Contract delta

| Endpoint | Before (anonymous caller) | After |
|---|---|---|
| `GET /api/models` | 200 | 401 |
| `GET /api/memory` | 200 | 401 |
| `GET /api/skills` | 200 | 401 |
| `GET /api/threads/{id}/skills` | 200 | 401 |
| `POST /api/threads/{id}/uploads` | 200 (silently writes to legacy path) | 401 |
| `GET /api/threads/{id}/artifacts/...` | 200 (serves legacy artifact) | 401 |
| `GET /api/agents` | 200 | 401 |
| `POST /api/auth/login` | 200/401 | unchanged |
| `POST /api/auth/refresh` | 401 (no session) | unchanged |
| `GET /api/auth/providers` | 200 | unchanged |
| `GET /health` | 200 | unchanged |
| `GET /metrics` | 200 | unchanged |
| `POST /api/channels/webhook` | (whatever channel signature check returns) | unchanged |
| Authenticated cookie / valid `dft_*` token | 200 | unchanged |

## Test plan

### New baseline test suite

`backend/tests/identity/test_gateway_authn_baseline.py`:

```python
import pytest

# Routes that MUST require auth. One representative per legacy router.
PROTECTED_ROUTES = [
    ("GET", "/api/models"),
    ("GET", "/api/memory"),
    ("GET", "/api/skills"),
    ("GET", "/api/threads/abc/skills"),  # invalid id, but auth checked first
    ("GET", "/api/threads/abc/uploads/list"),
    ("GET", "/api/threads/abc/artifacts/anything.md"),
    ("GET", "/api/agents"),
    ("POST", "/api/threads/search"),
    ("GET", "/api/mcp"),
    ("POST", "/api/threads/abc/suggestions"),
    ("GET", "/api/channels"),
    ("POST", "/api/runs/wait"),
    ("POST", "/api/threads/abc/runs/wait"),
    ("POST", "/api/assistants/search"),
]

# Routes that MUST stay public.
PUBLIC_ROUTES = [
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/providers"),
    ("GET", "/health"),
    ("GET", "/metrics"),
]


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
async def test_protected_endpoint_returns_401_for_anonymous(
    gateway_client, method, path,
):
    resp = await gateway_client.request(method, path)
    assert resp.status_code == 401, (
        f"{method} {path} returned {resp.status_code}; expected 401 "
        "(missing auth dep on this router?)"
    )


@pytest.mark.parametrize("method,path", PUBLIC_ROUTES)
async def test_public_endpoint_does_not_require_auth(
    gateway_client, method, path,
):
    resp = await gateway_client.request(method, path)
    assert resp.status_code != 401, (
        f"{method} {path} returned 401 but is on the public allowlist"
    )
```

The protected list intentionally uses `abc` as a thread/skill/etc. id — the
auth check fires before any business logic, so the test never reaches the
"invalid id" branches.

### Negative regression: `ENABLE_IDENTITY=false`

```python
async def test_baseline_dep_no_op_when_identity_disabled(
    gateway_client_with_identity_off,
):
    resp = await gateway_client_with_identity_off.get("/api/models")
    assert resp.status_code == 200, "auth baseline must be no-op when flag off"
```

### Existing tests

`make identity-test` and the broader gateway test suite must remain green. The
baseline dep is additive — handler logic is untouched.

### Manual smoke (acceptance criterion)

After deploy, with `ENABLE_IDENTITY=true`:

1. Log out (clear cookie).
2. From browser console: `await fetch('/api/models').then(r => r.status)`.
3. **Pass**: 401.
4. Log in. Repeat.
5. **Pass**: 200.

Repeat for `/api/memory`, `/api/threads/dummy/skills`, `/api/skills`.

## Definition of Done

- [ ] `backend/app/gateway/auth_baseline.py` created with `PUBLIC_PREFIXES`
      and `require_authenticated_global`
- [ ] All 16 legacy `include_router` calls in `app.py:449-488` declare the
      dep
- [ ] Identity routers at 494-512 are **not** modified
- [ ] New baseline test suite passes
- [ ] `ENABLE_IDENTITY=false` regression test passes
- [ ] `make identity-test` and `make test` (broad backend) green
- [ ] Manual smoke (4 URLs × {logged-in, logged-out}) recorded in PR
- [ ] Commit message references this spec path

## Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Some non-browser caller relies on a leaked endpoint (CI, scripts, IM channels using user-scoped APIs without identity) | medium | broken integration | grep `app.channels/` and CI workflows for `/api/{models,memory,skills,threads}` calls; if any are found, they must adopt API-token auth — list them in the PR |
| `ENABLE_IDENTITY=false` test environment somewhere stops working | low | CI red | flag-off no-op is explicit; covered by the "no-op when flag off" test |
| Some endpoint legitimately should accept anonymous (forgot to allowlist) | low | 401 returned where shouldn't | the allowlist is in one file; PR review can spot omissions |
| Channels webhook at `/api/channels/webhook` doesn't actually exist on this prefix | medium | misallowlist either too narrow or too wide | implementation plan must verify the actual webhook route prefix; if Channels doesn't expose unauthenticated webhooks, drop that prefix from the allowlist |

## Rollback

The dependency is one decorator on each `include_router` plus a single new
file. If a sudden regression breaks an integration:

- Quickest revert: `git revert <baseline-commit>` — single file additions plus
  16 single-line edits in `app.py`.
- Per-router escape hatch: `dependencies=[]` on a specific include_router
  call to disable just that one (use during incident, file follow-up).

No data migration. Fully reversible.

## Dependency on Issues ① and ②

Independent. Can ship in any order. The 401 contract this spec adds is the
one Issue ② already retries against — i.e., shipping ③ first will trigger
more SDK 401s for legitimate requests that were previously sneaking through
unauthenticated, but Issue ②'s refresh-and-retry will fix them. Recommended
order: ① → ② → ③ to minimize transient user-visible 401s.

## References

- Browser-validated finding: this conversation, 2026-05-02
- Existing dep helper: `app/gateway/identity/auth/dependencies.py`
- Identity middleware (populates request.state.identity):
  `app/gateway/identity/middlewares/identity.py`
- Existing tenant-scope helper: `app/gateway/identity/request_scope.py`
- CLAUDE.md note that legacy paths fall back when `extract_scope` returns
  `(None, None)` — this is the silent failure mode this spec closes.
