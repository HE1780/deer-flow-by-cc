# Cookie Max-Age Decouple Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the browser from auto-deleting `deerflow_session` after 15 min so `/api/auth/refresh` can keep working for any session that's still alive in Redis.

**Architecture:** Single-helper change in `_set_session_cookie` (auth.py) plus a refactor of `me.py::switch_tenant` to call the same helper instead of its hand-rolled duplicate. Backend authorization semantics are unchanged — every request still verifies JWT signature + sid in Redis. Cookie lifetime now tracks `refresh_ttl_sec` (Redis session TTL) instead of `access_ttl_sec` (token TTL).

**Tech Stack:** Python 3.12, FastAPI, pytest-asyncio, Starlette `Response.set_cookie`. Spec: [docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md](../specs/2026-05-02-cookie-max-age-decouple-design.md).

**Branch convention (per CLAUDE.md §git策略):** create `feat/cookie-max-age-decouple` off `cc-main`, merge back to `cc-main` after tests pass, push.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/app/gateway/identity/routers/auth.py` | modify | Fix `_set_session_cookie::max_age` + replace docstring |
| `backend/app/gateway/identity/routers/me.py` | modify | Replace inline cookie code in `switch_tenant` with call to `_set_session_cookie` |
| `backend/tests/identity/auth/test_session_cookie_max_age.py` | create | Regression tests covering both endpoints |

No new files in `app/`. The helper is reused, not split out.

---

## Task 1: Branch + spec acknowledgement

**Files:**
- None (git only)

- [ ] **Step 1: Create feat branch from cc-main**

```bash
git checkout cc-main
git pull origin cc-main
git checkout -b feat/cookie-max-age-decouple
git status -sb
```

Expected: `## feat/cookie-max-age-decouple`

- [ ] **Step 2: Confirm spec is on the branch**

```bash
ls docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md
```

Expected: file present.

---

## Task 2: Write failing tests for `/api/auth/login` cookie lifetime

**Files:**
- Create: `backend/tests/identity/auth/test_session_cookie_max_age.py`

- [ ] **Step 1: Create the test file with the login regression**

```python
# backend/tests/identity/auth/test_session_cookie_max_age.py
"""Regression: cookie max_age must equal refresh_ttl_sec, not access_ttl_sec.

Prior bug: _set_session_cookie used access_ttl_sec for max_age, causing the
browser to drop the cookie ~15 min after login. The next request hit
/api/auth/refresh with no cookie → 401 "no session" → frontend modal.
Cookie lifetime must outlive its token so refresh can read sid out of an
expired-but-still-decodable JWT.

See: docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.gateway.identity.auth.passwords import hash_password
from app.gateway.identity.models.user import User


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://t",
        follow_redirects=False,
    )


async def _seed_password_user(app_handle, email: str, password: str) -> int:
    """Insert a User row with a valid password_hash so /api/auth/login succeeds."""
    async with app_handle.runtime.session_maker() as db:
        existing = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name="cookie-test",
            status=1,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    # Membership in default tenant is auto-provisioned by the login path
    # (auto_provision=True on the test runtime), so no extra setup needed.
    return user.id


@pytest.mark.asyncio
async def test_login_cookie_max_age_matches_refresh_ttl(app_handle):
    """Set-Cookie Max-Age must equal refresh_ttl_sec, not access_ttl_sec."""
    email = f"cookie-{uuid.uuid4().hex[:8]}@example.com"
    password = "ChangeMe!2026"
    await _seed_password_user(app_handle, email, password)

    async with _client(app_handle.app) as c:
        r = await c.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
    assert r.status_code == 200, r.text

    set_cookie = r.headers.get("set-cookie", "")
    assert "deerflow_session=" in set_cookie

    refresh_ttl = app_handle.runtime.refresh_ttl_sec
    access_ttl = app_handle.runtime.access_ttl_sec
    assert refresh_ttl != access_ttl, (
        "test runtime must distinguish the two TTLs to be meaningful; "
        f"got refresh={refresh_ttl} access={access_ttl}"
    )

    # Positive assertion: cookie lifetime tracks the Redis session TTL.
    assert f"Max-Age={refresh_ttl}" in set_cookie, set_cookie
    # Negative assertion: defends against re-coupling to access TTL.
    assert f"Max-Age={access_ttl}" not in set_cookie, set_cookie
```

- [ ] **Step 2: Run the test to verify it fails (or its absence at least exercises the right branch)**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/auth/test_session_cookie_max_age.py::test_login_cookie_max_age_matches_refresh_ttl -v
```

Expected: **FAIL** with `assert "Max-Age=3600" in '... Max-Age=900 ...'`. The test asserts `Max-Age=refresh_ttl_sec=3600` but production code currently emits `Max-Age=access_ttl_sec=900`.

If the test errors out for a different reason (fixture wiring, import path), fix that first — the test must reach its assertions and fail there.

- [ ] **Step 3: Commit the failing test**

```bash
git add backend/tests/identity/auth/test_session_cookie_max_age.py
git commit -m "test(identity): regression for cookie max_age vs refresh_ttl_sec"
```

---

## Task 3: Fix `_set_session_cookie` to use `refresh_ttl_sec`

**Files:**
- Modify: `backend/app/gateway/identity/routers/auth.py:423-434`

- [ ] **Step 1: Replace the helper implementation**

Open `backend/app/gateway/identity/routers/auth.py`. The current function spans lines 423-434:

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

Replace it with:

```python
def _set_session_cookie(response: Response, access_token: str) -> None:
    """Stamp the access token onto the response as the session cookie.

    Cookie lifetime intentionally tracks the Redis session TTL (refresh
    window), NOT the access-token TTL. Browser-side cookie expiry would
    otherwise force a re-login as soon as the access token rolls over:
    /api/auth/refresh reads sid out of the (possibly-expired-but-still-
    decodable) cookie, so the cookie must outlive its token. Backend
    security is unchanged - every request still re-verifies the JWT
    signature and checks sid in Redis.

    See: docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md
    """
    rt = get_runtime()
    response.set_cookie(
        rt.cookie_name,
        access_token,
        httponly=True,
        secure=rt.cookie_secure,
        samesite="lax",
        max_age=rt.refresh_ttl_sec,
        path="/",
    )
```

The single substantive change is `max_age=rt.access_ttl_sec` → `max_age=rt.refresh_ttl_sec`. The expanded docstring is the durable why-comment that prevents future re-coupling.

- [ ] **Step 2: Run the failing test from Task 2 — it should now pass**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/auth/test_session_cookie_max_age.py::test_login_cookie_max_age_matches_refresh_ttl -v
```

Expected: **PASS**.

- [ ] **Step 3: Run the broader auth router suite — must remain green**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/auth/test_auth_router.py -v
```

Expected: all pass. If any test fails because it asserted `Max-Age=900` literally, fix the test to read from `app_handle.runtime.refresh_ttl_sec` (per spec audit, this should be zero hits — but check if any new tests landed since).

- [ ] **Step 4: Commit**

```bash
git add backend/app/gateway/identity/routers/auth.py
git commit -m "fix(identity): cookie max_age tracks refresh_ttl_sec not access_ttl_sec

Browser was deleting deerflow_session 15 min after login because
Set-Cookie Max-Age was bound to access_ttl_sec (900s). After the cookie
disappeared /api/auth/refresh could not read sid → 401 → Session expired
modal. Decouple cookie lifetime from token lifetime: backend continues to
verify JWT exp + sid on every request, so longer cookie has no security
cost.

Spec: docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md"
```

---

## Task 4: Add the switch-tenant test (still failing because me.py duplicate)

**Files:**
- Modify: `backend/tests/identity/auth/test_session_cookie_max_age.py` (append)

- [ ] **Step 1: Add the second test**

Append to `backend/tests/identity/auth/test_session_cookie_max_age.py`:

```python
@pytest.mark.asyncio
async def test_switch_tenant_cookie_max_age_matches_refresh_ttl(app_handle):
    """/api/me/switch-tenant must reuse _set_session_cookie (not its own copy)."""
    # The test app_handle from auth/conftest.py only mounts auth_router. We
    # need me_router for this test, so build a parallel app handle here.
    from fastapi import FastAPI
    from app.gateway.identity.routers import me as me_router_module

    app2 = FastAPI()
    # Re-use the same middleware + runtime as app_handle so the test stays
    # self-contained and doesn't have to re-seed RSA keys, Redis, etc.
    for mw in app_handle.app.user_middleware:
        app2.user_middleware.append(mw)
    app2.include_router(me_router_module.router)

    # Seed a user with membership in two tenants. The auto-provision flag on
    # the runtime makes the first login auto-create one tenant; we add a
    # second one manually so switch-tenant has somewhere to switch to.
    email = f"switch-{uuid.uuid4().hex[:8]}@example.com"
    password = "ChangeMe!2026"
    user_id = await _seed_password_user(app_handle, email, password)

    from app.gateway.identity.models.tenant import Tenant
    from app.gateway.identity.models.membership import Membership
    async with app_handle.runtime.session_maker() as db:
        # The login below will auto-provision tenant #1 + membership.
        # Pre-create tenant #2 + membership so switch-tenant can target it.
        t2 = Tenant(slug=f"t2-{uuid.uuid4().hex[:6]}", name="T2")
        db.add(t2)
        await db.flush()
        db.add(Membership(user_id=user_id, tenant_id=t2.id, status=1))
        await db.commit()
        target_tenant_id = t2.id

    # Log in to get a session cookie.
    async with _client(app_handle.app) as c:
        login = await c.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
    assert login.status_code == 200, login.text
    cookie_header = login.headers["set-cookie"]
    # Extract just the deerflow_session=VALUE; pair for the next request.
    session_cookie = cookie_header.split(";", 1)[0]

    # Switch tenant on the second app — passes the cookie manually.
    async with _client(app2) as c:
        r = await c.post(
            "/api/me/switch-tenant",
            json={"tenant_id": target_tenant_id},
            headers={"cookie": session_cookie},
        )
    assert r.status_code == 200, r.text

    set_cookie = r.headers.get("set-cookie", "")
    assert "deerflow_session=" in set_cookie

    refresh_ttl = app_handle.runtime.refresh_ttl_sec
    access_ttl = app_handle.runtime.access_ttl_sec
    assert f"Max-Age={refresh_ttl}" in set_cookie, set_cookie
    assert f"Max-Age={access_ttl}" not in set_cookie, set_cookie
```

- [ ] **Step 2: Run the new test — should fail because me.py has its own inline cookie call**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/auth/test_session_cookie_max_age.py::test_switch_tenant_cookie_max_age_matches_refresh_ttl -v
```

Expected: **FAIL** with `assert "Max-Age=3600" in '...Max-Age=900...'`. Confirms me.py is still duplicating the bug.

- [ ] **Step 3: Commit the failing test**

```bash
git add backend/tests/identity/auth/test_session_cookie_max_age.py
git commit -m "test(identity): regression for switch-tenant cookie max_age"
```

---

## Task 5: Refactor `me.py::switch_tenant` to use the shared helper

**Files:**
- Modify: `backend/app/gateway/identity/routers/me.py:177-185`

- [ ] **Step 1: Read the current `switch_tenant` cookie block to understand the imports**

```bash
sed -n '170,190p' backend/app/gateway/identity/routers/me.py
```

You should see the inline `response.set_cookie(...)` block at 177-185 and the `from app.gateway.identity.routers.auth import _issue_access_for` at 174.

- [ ] **Step 2: Replace the inline call with `_set_session_cookie`**

Open `backend/app/gateway/identity/routers/me.py`. Replace lines 174-185 (the `from ... import _issue_access_for` import + the `response.set_cookie(...)` block) with:

```python
    # Re-issue token using the shared helper so cookie attributes (esp.
    # max_age) stay aligned with /api/auth/login. Helper imports are local
    # to avoid a circular dependency between me.py and auth.py.
    from app.gateway.identity.routers.auth import _issue_access_for, _set_session_cookie

    new_token = _issue_access_for(new_identity, identity.session_id or "")
    _set_session_cookie(response, new_token)
```

The 8-line inline `response.set_cookie(...)` block disappears entirely. The `return {...}` line below it stays unchanged.

- [ ] **Step 3: Run both new tests — both should pass**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/auth/test_session_cookie_max_age.py -v
```

Expected: both tests **PASS**.

- [ ] **Step 4: Run the me-router suite to confirm no regression**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/auth/test_me_router.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/identity/routers/me.py
git commit -m "refactor(identity): switch-tenant uses _set_session_cookie helper

Eliminate duplicated inline response.set_cookie() block in
me.py::switch_tenant. The helper is now the single source of truth for
deerflow_session attributes (HttpOnly, SameSite, Secure, Max-Age, Path).
Same effect as Task 3 propagates to switch-tenant.

Spec: docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md"
```

---

## Task 6: Broad backend regression sweep

**Files:**
- None (test execution only)

- [ ] **Step 1: Run the full identity test suite**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/identity/ -v
```

Expected: all pass. If any test fails:
- A literal `Max-Age=900` assertion → update test to use `runtime.refresh_ttl_sec`
- An unrelated failure → outside the scope of this plan; flag and stop

- [ ] **Step 2: Run lint**

```bash
cd backend && make lint
```

Expected: no errors. `ruff` may flag the in-function import in `switch_tenant`; if so, leave it (the comment explains why) and add a `# noqa: PLC0415` only if ruff strictly requires.

- [ ] **Step 3: Optional — broader test sweep**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/ -x --ignore=tests/identity 2>&1 | tail -20
```

Skip if it would take >2 min; the identity suite is the only one impacted by these changes.

---

## Task 7: Manual smoke (acceptance criterion from spec)

**Files:**
- None (browser observation)

- [ ] **Step 1: Start the stack if not already running**

```bash
make dev    # or confirm services on 2026/3110/2024/8100
```

- [ ] **Step 2: Log in via the browser**

Open `http://localhost:2026/login`. Sign in with any valid account.

- [ ] **Step 3: Inspect the cookie expiry**

DevTools → Application → Cookies → `http://localhost:2026` → row `deerflow_session`. Read the `Expires / Max-Age` column.

- [ ] **Step 4: Record the result**

Expected: `Expires` column shows ~7 days from now (≈ `now + refresh_ttl_sec`). With the dev default `DEERFLOW_REFRESH_TOKEN_TTL_SEC=604800` that means today + 7 days.

- **Pass criterion:** Expires ≥ 24 h from now.
- **Fail criterion:** Expires shows ~15 min — Task 3 didn't deploy.

Save a screenshot or copy the value to the merge commit description.

- [ ] **Step 5 (optional): Confirm switch-tenant also stamps the long lifetime**

If your account has 2+ tenants, click the tenant switcher in the workspace header. Re-inspect the cookie — `Expires` should be reset to ~7 days from the switch moment.

---

## Task 8: Merge to cc-main

**Files:**
- None (git only)

- [ ] **Step 1: Confirm clean tree on the feat branch**

```bash
git status -sb
```

Expected: `## feat/cookie-max-age-decouple` and no uncommitted changes.

- [ ] **Step 2: Switch to cc-main and merge**

```bash
git checkout cc-main
git merge --no-ff feat/cookie-max-age-decouple -m "merge: cookie max-age decouple (1 helper fix + 1 refactor + 2 regression tests)

Fixes Session-expired modal popping ~15 min into a chat session.

Spec: docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md
Plan: docs/superpowers/plans/2026-05-02-cookie-max-age-decouple.md"
```

- [ ] **Step 3: Push to origin**

```bash
git push origin cc-main
```

Expected: branch tip advances on `origin/cc-main`.

- [ ] **Step 4: Delete the local feat branch (optional)**

```bash
git branch -d feat/cookie-max-age-decouple
```

---

## Task 9: Archive spec + plan, update memory

**Files:**
- Move: `docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md` → `archive/`
- Move: `docs/superpowers/plans/2026-05-02-cookie-max-age-decouple.md` → `archive/`
- Update: `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/MEMORY.md` (add entry)

- [ ] **Step 1: Add a "Shipped" banner at the top of the spec**

Edit the first line of `docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md` to add:

```markdown
> 📦 **归档于 YYYY-MM-DD — 已 ship**：merged into `cc-main` as commit `<short-sha>`. Manual smoke confirmed Expires ≈ now + 7 days.

---
```

(Replace `<short-sha>` with the merge commit hash from Task 8.)

- [ ] **Step 2: Move spec + plan to archive**

```bash
git mv docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md \
       docs/superpowers/specs/archive/
git mv docs/superpowers/plans/2026-05-02-cookie-max-age-decouple.md \
       docs/superpowers/plans/archive/
```

- [ ] **Step 3: Add a memory entry**

Append to `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/MEMORY.md`:

```markdown
- [P0 fix: cookie max_age 解耦](spec_cookie_max_age_decouple.md) — ✅ 已闭环（YYYY-MM-DD）：cookie 寿命 = refresh_ttl_sec（7d）而非 access_ttl_sec（15min），1 helper + me.py 重构 + 2 regression test；merge `<short-sha>`
```

And create `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/spec_cookie_max_age_decouple.md` with frontmatter:

```markdown
---
name: P0 fix — cookie max_age 解耦
description: deerflow_session 的 Max-Age 从 access_ttl_sec 改为 refresh_ttl_sec；治本 Session-expired modal
type: project
---

## 现象
用户 chat 进行 ~15 分钟后弹"Session expired"，refresh 必失败。

## 根因
_set_session_cookie 把 cookie 的 Max-Age 绑死成 access_ttl_sec（900s）；浏览器主动删 cookie 后 /api/auth/refresh 读不到 sid → 401。

## 修法
- backend/app/gateway/identity/routers/auth.py:432: max_age=rt.refresh_ttl_sec
- backend/app/gateway/identity/routers/me.py: switch_tenant 改用 _set_session_cookie helper（消除 inline 重复）
- 2 regression test（login + switch-tenant）

## 状态
✅ shipped YYYY-MM-DD as `<short-sha>`. Manual smoke 通过（DevTools Expires ≈ now+7d）。
```

- [ ] **Step 4: Commit and push the archive move**

```bash
git add docs/superpowers/specs/archive/2026-05-02-cookie-max-age-decouple-design.md \
        docs/superpowers/plans/archive/2026-05-02-cookie-max-age-decouple.md \
        docs/superpowers/specs/2026-05-02-cookie-max-age-decouple-design.md \
        docs/superpowers/plans/2026-05-02-cookie-max-age-decouple.md
git commit -m "docs(specs): archive shipped cookie max-age decouple spec + plan"
git push origin cc-main
```

(The two `git mv`s appear in `git status` as both deletions and additions; `git add` after the mv is what stages them.)

---

## Definition of Done

All checked:

- [ ] `_set_session_cookie` references `refresh_ttl_sec` (Task 3)
- [ ] `me.py::switch_tenant` calls `_set_session_cookie` (Task 5)
- [ ] Both regression tests pass (Tasks 2-5)
- [ ] `make identity-test` is green (Task 6)
- [ ] `make lint` is green (Task 6)
- [ ] Manual smoke recorded: `Expires` ≈ now + 7 d (Task 7)
- [ ] Merged to `cc-main` and pushed (Task 8)
- [ ] Spec + plan archived; memory updated (Task 9)
