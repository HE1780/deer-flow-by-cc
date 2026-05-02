> 📦 **归档于 2026-05-02 — 已 ship**：merged into `cc-main` as `a730bdcb`. Browser-validated manual smoke confirmed `Set-Cookie: deerflow_session=...; HttpOnly; Max-Age=604800; Path=/; SameSite=lax` (was `Max-Age=900` before fix). 28 cookie/auth/me/registration tests all green.

---

# Cookie Max-Age Decouple — Design

**Date:** 2026-05-02
**Status:** ✅ Shipped (see banner above)
**Owner:** backend (gateway/identity)
**Touches:**
- `backend/app/gateway/identity/routers/auth.py::_set_session_cookie`
- `backend/app/gateway/identity/routers/me.py::switch_tenant` (refactor inline cookie code → helper)
- `backend/tests/identity/test_session_cookie_max_age.py` (new)

## Problem

Users see "Session expired / Your session is no longer valid" in mid-conversation,
even though the Redis session is still alive.

Browser-validated root cause (verified via chrome-devtools-mcp on 2026-05-02):

1. `POST /api/auth/login` returns
   `Set-Cookie: deerflow_session=...; HttpOnly; Max-Age=900; Path=/; SameSite=lax`
2. After 900 s the browser deletes the cookie autonomously.
3. The next request fires with **no** `deerflow_session` cookie.
4. The frontend interceptor catches 401 and posts `/api/auth/refresh` to renew.
5. But `/api/auth/refresh`
   ([backend/app/gateway/identity/routers/auth.py:124-159](../../../backend/app/gateway/identity/routers/auth.py#L124-L159))
   reads the access cookie to extract `sid`. With no cookie it returns
   `401 {"detail":"no session"}`.
6. The frontend interceptor sees the refresh failure and fires
   `emitSessionExpired()` → modal pops.

The defect: cookie lifetime is bound to **access-token TTL** (`access_ttl_sec`,
default 900 s) instead of **session TTL** (`refresh_ttl_sec`, default 604 800 s).
The cookie must outlive its token because `/api/auth/refresh` needs to decode
`sid` out of an expired-but-still-decodable JWT.

Reproduction transcript (2026-05-02):

```
POST /api/auth/logout              → 200    (mimics browser dropping cookie)
GET  /api/me                       → 401
POST /api/auth/refresh             → 401  body: {"detail":"no session"}
                                            ↑ would trigger emitSessionExpired
```

## Goals

- Decouple browser cookie lifetime from access-token TTL.
- `/api/auth/refresh` succeeds for any user whose Redis session is still alive.
- Zero change to backend authorization semantics (still verifies JWT + checks
  Redis sid on every request).
- Single regression test that fails if anyone re-couples cookie max-age to
  access-token TTL.

## Non-goals

- ❌ Change `access_ttl_sec` (token TTL) — unaffected.
- ❌ Wrap the LangGraph SDK fetch transport — separate spec (Issue ②).
- ❌ Add authentication to currently-unauthenticated `/api/*` routes
  (`/api/models`, `/api/memory`, `/api/threads/{id}/skills`) — separate spec
  (Issue ③), surfaced during the same browser-debug session but unrelated.
- ❌ Proactive timer-based refresh.
- ❌ Move cookie max-age to a new env var or `AuthRuntime` field. The natural
  binding is `refresh_ttl_sec`.
- ❌ Modify cookie attributes other than `max_age` (HttpOnly / Secure /
  SameSite / Path stay as-is).
- ❌ Any OAuth-style dual-cookie refactor.

## Approach

Single source of truth for the cookie: `_set_session_cookie` in
`backend/app/gateway/identity/routers/auth.py`. Two changes:

### Change A — fix the helper

```python
def _set_session_cookie(response: Response, access_token: str) -> None:
    """Stamp the access token onto the response as the session cookie.

    Cookie lifetime intentionally tracks the Redis session TTL (refresh
    window), NOT the access-token TTL. Browser-side cookie expiry would
    otherwise force a re-login as soon as the access token rolls over:
    /api/auth/refresh reads sid out of the (possibly-expired-but-still-
    decodable) cookie, so the cookie must outlive its token. Backend
    security is unchanged — every request still re-verifies the JWT
    signature and checks sid in Redis.
    """
    rt = get_runtime()
    response.set_cookie(
        rt.cookie_name,
        access_token,
        httponly=True,
        secure=rt.cookie_secure,
        samesite="lax",
        max_age=rt.refresh_ttl_sec,   # ← was access_ttl_sec
        path="/",
    )
```

### Change B — collapse the inline duplicate

`backend/app/gateway/identity/routers/me.py::switch_tenant` ([:177-185](../../../backend/app/gateway/identity/routers/me.py#L177-L185))
hand-rolled its own `response.set_cookie(...)` call instead of calling the
helper. Replace it with a call to `_set_session_cookie(response, new_token)`.

Why bundle this with the fix instead of a separate cleanup commit:

- Without it, switch-tenant would still drop a 900 s cookie even after
  Change A — partial fix is worse than no fix.
- It's the minimum diff that makes the helper a true single source of truth.
- It deletes 8 lines of duplicated configuration.

## Contract delta

| Dimension                        | Before                          | After                                         |
|----------------------------------|---------------------------------|-----------------------------------------------|
| Browser cookie lifetime          | `access_ttl_sec` (900 s)        | `refresh_ttl_sec` (604 800 s = 7 d)           |
| Server-trusted window per call   | JWT `exp` + Redis sid           | unchanged                                     |
| `/api/auth/refresh` happy path   | breaks once cookie auto-deleted | works for any sid still in Redis              |
| JWT signature/expiry check       | strict                          | unchanged                                     |
| Logout / revoke                  | `delete_cookie()` + Redis revoke| unchanged                                     |
| `access_ttl_sec`                 | 900 s                           | unchanged                                     |
| `me.py::switch_tenant` cookie    | hand-rolled, 900 s              | calls `_set_session_cookie`, 604 800 s        |

All 5 cookie-issuing endpoints — OIDC callback, login, refresh, register,
switch-tenant — share `_set_session_cookie` after Change B and inherit the
new lifetime uniformly.

## Security argument

A 7-day cookie does **not** add real attack surface beyond what the existing
7-day Redis session already permits.

| Vector                                                 | Old (15 min cookie)    | New (7 d cookie)               | Net change |
|--------------------------------------------------------|------------------------|--------------------------------|------------|
| Stolen cookie replay before access-token expiry        | up to 15 min           | up to 15 min (token TTL same)  | 0          |
| Stolen cookie + attacker drives `/api/auth/refresh`    | possible inside TTL    | possible inside TTL            | 0          |
| Idle attacker returns later, replays cookie            | cookie gone, blocked   | cookie present but token `exp` past → forced refresh; refresh succeeds only if Redis sid still alive (== same 7-day window the legitimate user has) | 0  |
| Server-side revoke takes effect                        | immediate (sid check)  | immediate (sid check)          | 0          |
| Logout                                                 | `delete_cookie()`      | unchanged                      | 0          |

Short-lived cookies provide no incremental defense over what JWT `exp`
verification + Redis sid check already enforce. The "15 min cookie" was
defense-in-depth theater for an attack the backend already blocks.

## Test plan

### New regression test

`backend/tests/identity/test_session_cookie_max_age.py`:

```python
"""Regression: cookie max_age must equal refresh_ttl_sec, not access_ttl_sec."""
import pytest

from app.gateway.identity.auth.runtime import get_runtime


@pytest.mark.asyncio
async def test_login_cookie_max_age_matches_refresh_ttl(
    identity_client, seeded_password_user
):
    email, password = seeded_password_user
    resp = await identity_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200

    set_cookie = resp.headers.get("set-cookie", "")
    assert "deerflow_session=" in set_cookie

    rt = get_runtime()
    assert f"Max-Age={rt.refresh_ttl_sec}" in set_cookie
    # Negative: defends against re-coupling
    assert f"Max-Age={rt.access_ttl_sec}" not in set_cookie
```

Both the positive and negative assertions are required — the negative one is
what catches a future revert of `_set_session_cookie`.

Fixture names (`identity_client`, `seeded_password_user`) are placeholders;
the implementation plan resolves them against the existing
`backend/tests/identity/auth/conftest.py`.

A second test exercises `/api/me/switch-tenant` to confirm Change B took
effect:

```python
@pytest.mark.asyncio
async def test_switch_tenant_cookie_max_age_matches_refresh_ttl(
    authed_client, second_tenant_id
):
    resp = await authed_client.post(
        "/api/me/switch-tenant", json={"tenant_id": second_tenant_id}
    )
    assert resp.status_code == 200
    rt = get_runtime()
    assert f"Max-Age={rt.refresh_ttl_sec}" in resp.headers.get("set-cookie", "")
```

### Existing test suite

`make identity-test` must remain green. Audited:
- `backend/tests/identity/auth/test_auth_router.py:181` only asserts
  `"deerflow_session" in set-cookie` (no `Max-Age` literal) — passes.
- `test_me_router.py:96`, `test_registration.py:54`, `test_auth_router.py:109`
  set `access_ttl_sec=900` as a fixture default for unrelated logic — passes.
- No test currently asserts `Max-Age=900` literally — confirmed via
  `grep -rn "Max-Age=900" backend/tests/`.

### Manual smoke (acceptance criterion)

After deploy:

1. Log in via the UI.
2. DevTools → Application → Cookies → `localhost:2026` → `deerflow_session`.
3. **Pass**: `Expires/Max-Age` column shows ≈ now + 7 d.
4. **Fail**: shows ≈ now + 15 min.

This 30-second check is the cheapest way to confirm the cookie attribute is
actually what we asked for at the wire level.

## Definition of Done

- [ ] `_set_session_cookie` references `refresh_ttl_sec`
- [ ] `me.py::switch_tenant` calls `_set_session_cookie` instead of inline
      `response.set_cookie(...)`
- [ ] New `test_session_cookie_max_age.py` passes locally
- [ ] `make identity-test` is green
- [ ] Manual smoke recorded in commit/PR description: DevTools shows 7-day
      `Expires`
- [ ] Commit message references this spec path

## Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Hidden 6th cookie-setter that I missed | low | that endpoint stays buggy | `grep -rn "set_cookie" backend/app/gateway/identity/` already confirms only auth.py:426 + me.py:177 set `deerflow_session`; me.py is folded into Change B |
| Existing pre-fix cookies in users' browsers still expire at 900 s | 100% | users see one more modal until next login | acceptable; one-time |
| Hidden test asserts `Max-Age=900` literal | low | test red after change | grep already shows zero hits — confirmed clean |

## Rollback

Revert the two-file diff. No data migration, no config change. One commit,
fully reversible.

## References

- Browser-validated reproduction: this conversation, 2026-05-02
- Prior interceptor work (frontend): `archive/2026-04-28-session-refresh-interceptor-design.md`
- Memory record:
  `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/spec_session_refresh_interceptor.md`
