> 📦 **归档于 2026-04-29 — 已 ship**：interceptor 已合入 `cc-main`（merge `d6497326`），9 个 vitest 全绿。LangGraph SDK 路径未拦的已知容忍点见 [OPEN_ISSUES.md](../../../OPEN_ISSUES.md)。

---

# Session Refresh Interceptor — Design

**Date:** 2026-04-28
**Status:** ✅ Shipped（详见上方 banner）
**Owner:** frontend
**Touches:** `frontend/src/core/identity/fetcher.ts`, `frontend/tests/unit/core/identity/fetcher.test.ts` (new)

## Problem

Users see the "Session expired / Your session is no longer valid" modal during normal use:

1. **Mid-conversation waiting.** Agent runs >15 min; access token (TTL 900 s) expires; the next background `/api/me` re-fetch (TanStack `staleTime=60s`) hits 401 and pops the modal even though the Redis session is still valid (refresh-token TTL = 7 days).
2. **Workspace (tenant) switch.** `useSwitchTenant` calls `qc.invalidateQueries({ queryKey: identityKeys.all })`, fanning out 5–10 concurrent requests. If the access token has just expired, several of them race the new cookie and return 401 before it lands in the cookie jar — pops the modal even though refresh would have rescued them.

Root cause traced in this session's brainstorm. Key facts:

- Access-token JWT in cookie `deerflow_session`. Default TTL = `DEERFLOW_ACCESS_TOKEN_TTL_SEC=900` ([backend/app/gateway/identity/settings.py:107](backend/app/gateway/identity/settings.py#L107)). Not overridden in `.env`.
- Backend route `POST /api/auth/refresh` ([backend/app/gateway/identity/routers/auth.py:124-167](backend/app/gateway/identity/routers/auth.py#L124-L167)) re-issues an access token from the still-live Redis session record (refresh-TTL = 7 days).
- Frontend has `identityApi.refresh` defined ([frontend/src/core/identity/api.ts:57-61](frontend/src/core/identity/api.ts#L57-L61)) but **no caller** invokes it. The 401 path in [frontend/src/core/identity/fetcher.ts:62-65](frontend/src/core/identity/fetcher.ts#L62-L65) jumps straight to `emitSessionExpired()`.

## Non-goals

- **Not** changing access-token TTL (separate decision; can be a one-line `.env` knob if desired).
- **Not** wrapping the LangGraph SDK's internal fetch (decision: scope A — only `identityFetch` paths). LangGraph SDK 401s during user-driven actions remain possible. We accept this because (a) the highest-frequency 401 sources — TanStack background revalidate and the post-`switchTenant` query-invalidation fanout — all go through `identityFetch`, and (b) any user action that touches an identity-scoped query (which is most of them) will trigger a `/api/me` revalidate first, refreshing the cookie before the LangGraph call goes out.
- **Not** doing proactive/timer-based refresh (deferred; track separately as "C" in original brainstorm).

## Approach

Add a singleflight 401-refresh-retry interceptor inside `identityFetch`. On 401:

1. Trigger `POST /api/auth/refresh` exactly once across all concurrent 401s (singleflight via a module-level `pendingRefresh: Promise<boolean> | null`).
2. If refresh succeeds, **retry the original request once**. If retry returns 200/2xx, return its body normally.
3. If refresh fails (network or 401), or retry still returns 401, fire `emitSessionExpired()` and throw `IdentityFetchError({kind: "unauthenticated"})` — preserving today's error contract.
4. The `refresh` call itself **must not** go through the interceptor (would recurse infinitely on a real expiry). Implementation: bypass via internal call-site flag passed to `identityFetch`, **not** via raw `fetch()`, so we don't fragment cookie/credentials/headers handling.

## Detailed contract

### State (module-scope)

```ts
let pendingRefresh: Promise<boolean> | null = null;
```

Reset to `null` in `.finally()` of the refresh promise so a later 401 (e.g., 1 hour later) gets a fresh attempt rather than a cached `false`.

### Refresh helper

```ts
async function refreshSession(): Promise<boolean> {
  if (pendingRefresh) return pendingRefresh;
  pendingRefresh = identityFetch<unknown>("/api/auth/refresh", {
    method: "POST",
    _skipRefreshOn401: true, // internal flag — see below
  })
    .then(() => true)
    .catch(() => false)
    .finally(() => { pendingRefresh = null; });
  return pendingRefresh;
}
```

### Flag

`identityFetch` accepts an extra optional internal flag (typed but kept un-exported) that suppresses the interceptor for the refresh call itself:

```ts
type InternalInit = RequestInit & { _skipRefreshOn401?: boolean };
```

Public callers never set it. Only `refreshSession()` does.

### Modified 401 branch

```ts
if (resp.status === 401) {
  if ((init as InternalInit | undefined)?._skipRefreshOn401) {
    // refresh itself failed (or any other internal-flagged caller)
    throw new IdentityFetchError({ kind: "unauthenticated" });
  }
  const refreshed = await refreshSession();
  if (refreshed) {
    // single retry, this time with the flag set so a second 401 doesn't loop
    return identityFetch<T>(input, {
      ...init,
      _skipRefreshOn401: true,
    } as InternalInit);
  }
  emitSessionExpired();
  throw new IdentityFetchError({ kind: "unauthenticated" });
}
```

Note: we set `_skipRefreshOn401: true` on the **retry** itself, so if the retry returns 401 we go straight to `emitSessionExpired` rather than triggering another refresh. This makes the "1 retry max per request" rule explicit at the call boundary.

### Notable invariants preserved

- `identityFetch` still uses `credentials: "include"` for both initial and retry (cookie semantics unchanged).
- 403 / non-401 errors: untouched code path.
- `emitSessionExpired` coalescing (one modal per burst) still works because retries that succeed never call it.
- `refresh()` exported on `identityApi` ([frontend/src/core/identity/api.ts:57-61](frontend/src/core/identity/api.ts#L57-L61)) is **rewritten** to delegate to the internal `refreshSession()` singleflight, so any future manual caller automatically participates in coalescing. Its public return shape (`{access_token, expires_in}` from the backend) is preserved for callers that read it; today nobody does.

### Where the flag lives in the type system

`_skipRefreshOn401` is a private extension of `RequestInit`. It's never serialized into HTTP — `identityFetch` reads it before constructing the `fetch` call and passes only the standard fields onward. We add a small line to strip it before spreading into the real `fetch`:

```ts
const { _skipRefreshOn401, ...realInit } = (init ?? {}) as InternalInit;
const resp = await fetch(input, {
  credentials: "include",
  headers: { ... },
  ...realInit,
});
```

## Behavior matrix

| Scenario | Before | After |
|---|---|---|
| 200 response | passthrough | passthrough (unchanged) |
| 403 forbidden | throws `forbidden` | throws `forbidden` (unchanged) |
| Single 401, refresh succeeds, retry 200 | modal | silent recovery, returns body |
| Single 401, refresh succeeds, retry 401 | modal | modal (real failure) |
| Single 401, refresh fails (network) | modal | modal |
| Single 401, refresh fails (its own 401) | modal | modal |
| 5× concurrent 401 + refresh succeeds | 5× modal triggers (coalesced to 1 modal but all 5 throw) | 1 refresh, 5 retries, 5× 200, 0 modal |
| Refresh endpoint reached → still 401 | recursion bug avoided by `_skipRefreshOn401` flag | bypasses interceptor, throws cleanly |

## Tests

New file `frontend/tests/unit/core/identity/fetcher.test.ts`. Mocks global `fetch` per test using `vi.stubGlobal("fetch", ...)`. Resets `resetSessionExpiredListeners()` and `consumeSessionExpired()` between tests.

1. **happy path** — `fetch` mock returns 200. `identityFetch` returns body. `fetch` called once.
2. **401 → refresh OK → retry OK** — first call 401, refresh call 200, retry call 200. Final body matches retry. Refresh fetch called once. Modal listener never invoked.
3. **401 → refresh 401** — first call 401, refresh call 401. Modal listener invoked once. `IdentityFetchError(kind="unauthenticated")` thrown.
4. **5 concurrent 401 → singleflight refresh → all retry OK** — issue 5 `identityFetch("/api/me")` in parallel against the same URL. Mock matches by URL+method+attempt-count: returns 401 on first hit per call, 200 with body `{ok: i}` on the retry (i = 0..4). For `/api/auth/refresh`, returns 200 the first time, fails the assertion if called more than once. After all 5 promises resolve, assert: refresh-URL called exactly 1 time, total fetch calls = 11 (5 originals + 1 refresh + 5 retries), modal listener never invoked.
5. **401 → refresh OK → retry still 401** — first call 401, refresh call 200, retry call 401. Modal listener invoked once. Error thrown. Retry-after-retry never happens (verified by total fetch call count = 3, not 4+).

## Out of scope (named explicitly)

- LangGraph SDK fetch interception.
- Proactive refresh based on JWT `exp` claim.
- Backend changes.
- Changing `staleTime` / `refetchOnWindowFocus` defaults to reduce 401 frequency.
- Changing the `_skipRefreshOn401` field name to something fancier — keep it short, internal, type-private.

## Risks

- **Refresh endpoint slow under burst.** Singleflight means it gets called once per burst, so this is not amplified.
- **Cookie not yet reflected in next request after 200 from refresh.** Browsers commit `Set-Cookie` synchronously before the response promise resolves, so the next `fetch` will include the new cookie. No additional delay needed.
- **Refresh succeeds but tenant scope changed mid-request** (e.g., user switched workspace at the exact moment). Out of scope — that path is `useSwitchTenant`, which already invalidates queries to re-fire them with the new cookie.

## Implementation footprint

- Edit: `frontend/src/core/identity/fetcher.ts` — ~30 added lines (singleflight helper + flag plumbing + retry branch).
- Add: `frontend/tests/unit/core/identity/fetcher.test.ts` — new file, ~120 lines.
- Run: `pnpm check` + `pnpm test` before push.
- No backend changes. No config changes.

## Rollback

Single-file revert. No DB or persisted state involved.
