> 📦 **归档于 2026-04-29 — 已 ship**
>
> **当前事实**：401 refresh+retry interceptor 已合并到 `cc-main`（merge commit `d6497326`）。`identityFetch` singleflight 行为在 [frontend/src/core/identity/fetcher.ts](../../../../frontend/src/core/identity/fetcher.ts) line 41-128 实现，9 个 vitest 全绿。
>
> **遗留议题**：LangGraph SDK 直连路径（`/api/langgraph/*`）当前不走 identityFetch 拦截器，已知容忍 — 详见 [OPEN_ISSUES.md](../../../OPEN_ISSUES.md)。
>
> 下文为施工时的原始 plan，仅作历史档案保留。

---

# Session Refresh Interceptor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `identityFetch` transparently recover from access-token expiry by calling `POST /api/auth/refresh` on 401 and retrying the original request once. Eliminate the false "Session expired" modal that fires mid-conversation and during workspace switch.

**Architecture:** Single-file singleflight interceptor inside `frontend/src/core/identity/fetcher.ts`. A module-scope `pendingRefresh` promise coalesces concurrent 401s into one refresh call. An internal `_skipRefreshOn401` flag (typed extension of `RequestInit`, never exported) prevents recursion: it is set on the refresh call itself and on the post-refresh retry, so a real 401 surfaces cleanly to `emitSessionExpired()`.

**Tech Stack:** TypeScript, Vitest (jsdom env), no new dependencies.

**Spec:** [`docs/superpowers/specs/2026-04-28-session-refresh-interceptor-design.md`](../specs/2026-04-28-session-refresh-interceptor-design.md)

**Branch:** `feat/session-refresh-interceptor` (per [frontend/CLAUDE.md](../../../frontend/CLAUDE.md) §"分支操作约束": all code work on `feat/*`, merge to `cc-main` after lint+test+build pass, push immediately, no PR ceremony).

---

## Task 0: Branch setup

**Files:** none (git only).

- [ ] **Step 1: Confirm starting state**

Run:
```bash
git status -sb
git log --oneline -3
```
Expected: clean working tree, on `cc-main`, latest commit is `13404f93 docs(spec): session refresh interceptor for /api/* 401s`.

- [ ] **Step 2: Create feature branch**

Run:
```bash
git checkout -b feat/session-refresh-interceptor
git status -sb
```
Expected: `## feat/session-refresh-interceptor`

---

## Task 1: Add the internal flag type and shared module state

**Files:**
- Modify: `frontend/src/core/identity/fetcher.ts`

**Why this task is first:** Establishes the types and module-level slot used by every later task. No behavior change yet.

- [ ] **Step 1: Add the internal-init type and singleflight slot**

Open `frontend/src/core/identity/fetcher.ts`. After the existing `Listener` / `listeners` declarations near the top (currently line 4-6), insert these lines just below `let sessionExpiredPending = false;`:

```typescript
/** Internal-only extension of RequestInit. Set to `true` on the refresh
 *  call itself and on the single post-refresh retry, so a real 401 in
 *  either of those code paths surfaces directly without recursing. */
type InternalInit = RequestInit & { _skipRefreshOn401?: boolean };

/** Singleflight slot. While a refresh is in-flight, all concurrent 401
 *  callers await the same promise. `null` once the refresh resolves so a
 *  later 401 starts a fresh attempt. */
let pendingRefresh: Promise<boolean> | null = null;
```

- [ ] **Step 2: Verify the file still type-checks**

Run:
```bash
cd frontend && pnpm typecheck
```
Expected: PASS (no errors). The type and variable are unused but valid.

- [ ] **Step 3: Commit**

Run:
```bash
git add frontend/src/core/identity/fetcher.ts
git commit -m "refactor(identity): add InternalInit type + pendingRefresh slot

Scaffolding for the upcoming 401 → refresh → retry interceptor.
No behavior change yet — type + module slot only."
```

---

## Task 2: Add the refreshSession helper

**Files:**
- Modify: `frontend/src/core/identity/fetcher.ts`

**Why TDD-light here:** The helper is only callable from inside the same module (the existing `identityApi.refresh` will be rewired in Task 6 to delegate to it). End-to-end behavior is exercised by the interceptor tests in Task 5. Writing a unit test that stubs the helper itself adds no signal. Skip the test for this isolated step; tests come in Tasks 4 and 5.

- [ ] **Step 1: Add the helper**

Open `frontend/src/core/identity/fetcher.ts`. Insert this **between** the existing `emitSessionExpired` function (currently lines 22-26) and the `IdentityFetchError` class (currently lines 31-46):

```typescript
/** Singleflight refresh helper. Returns `true` if the access cookie was
 *  re-issued, `false` otherwise. Internal-only — the only caller is
 *  identityFetch's 401 branch (and `identityApi.refresh` via re-export). */
async function refreshSession(): Promise<boolean> {
  if (pendingRefresh) return pendingRefresh;
  pendingRefresh = identityFetch<unknown>("/api/auth/refresh", {
    method: "POST",
    _skipRefreshOn401: true,
  } as InternalInit)
    .then(() => true)
    .catch(() => false)
    .finally(() => {
      pendingRefresh = null;
    });
  return pendingRefresh;
}

export { refreshSession as _refreshSessionForIdentityApi };
```

The named re-export lets `identityApi.refresh` (Task 6) call into the same singleflight. Underscore prefix marks it as not part of the public surface.

- [ ] **Step 2: Verify the file still type-checks**

Run:
```bash
cd frontend && pnpm typecheck
```
Expected: PASS. `refreshSession` references `identityFetch` which is defined later in the same file — JS hoisting via `function` declaration vs the ordering rule of TypeScript: this is fine because both are top-level and resolved at module init, not call time.

- [ ] **Step 3: Commit**

Run:
```bash
git add frontend/src/core/identity/fetcher.ts
git commit -m "feat(identity): add refreshSession singleflight helper

Coalesces concurrent refresh calls into one POST /api/auth/refresh.
Sets _skipRefreshOn401 on the inner call so a real 401 from refresh
itself does not recurse. Wired into identityFetch in the next commit."
```

---

## Task 3: Wire the interceptor into the 401 branch + strip the internal flag

**Files:**
- Modify: `frontend/src/core/identity/fetcher.ts:48-86` (the `identityFetch` function body)

This is the behavior-changing edit. Tests in Task 4 (update existing) and Task 5 (add new) will validate it.

- [ ] **Step 1: Replace the function body**

Open `frontend/src/core/identity/fetcher.ts`. Replace the existing `export async function identityFetch<T>(...)` body (currently lines 48-86) with this version. **Keep the function signature and exports exactly as they are** — only the body changes:

```typescript
export async function identityFetch<T>(
  input: string,
  init?: RequestInit,
): Promise<T> {
  const { _skipRefreshOn401, ...realInit } = (init ?? {}) as InternalInit;

  const resp = await fetch(input, {
    credentials: "include",
    headers: {
      accept: "application/json",
      ...(realInit.body ? { "content-type": "application/json" } : {}),
      ...realInit.headers,
    },
    ...realInit,
  });

  if (resp.status === 401) {
    if (_skipRefreshOn401) {
      emitSessionExpired();
      throw new IdentityFetchError({ kind: "unauthenticated" });
    }
    const refreshed = await refreshSession();
    if (refreshed) {
      return identityFetch<T>(input, {
        ...init,
        _skipRefreshOn401: true,
      } as InternalInit);
    }
    emitSessionExpired();
    throw new IdentityFetchError({ kind: "unauthenticated" });
  }
  if (resp.status === 403) {
    let missing: string | undefined;
    try {
      const body = (await resp.json()) as { detail?: { missing?: string } };
      missing = body?.detail?.missing;
    } catch {
      // 403 without JSON body is valid; missing stays undefined.
    }
    throw new IdentityFetchError({ kind: "forbidden", missing });
  }
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new IdentityFetchError({
      kind: "network",
      status: resp.status,
      message: text,
    });
  }

  return (await resp.json()) as T;
}
```

Key differences from the original:
1. Destructures `_skipRefreshOn401` out of `init` before spreading into `fetch` so the internal flag never reaches the network layer.
2. The `realInit` is what flows into `fetch`; `init` (with the flag still attached) is what we forward into the recursive retry.
3. The 401 branch now: (a) if internal-flagged, emit + throw immediately; (b) otherwise call `refreshSession()`, retry on success, emit + throw on failure.
4. The retry call sets `_skipRefreshOn401: true` so a second 401 routes into branch (a) above — at most one retry per request.

Note: in branch (a) we still call `emitSessionExpired()` so the modal fires when the user's refresh attempt fails (via the refresh code path) or when retry-after-refresh still 401s (true session loss). This matches the spec's "behavior matrix" table.

- [ ] **Step 2: Verify type-check passes**

Run:
```bash
cd frontend && pnpm typecheck
```
Expected: PASS.

- [ ] **Step 3: Run existing tests to confirm what breaks**

Run:
```bash
cd frontend && pnpm test fetcher
```
Expected: tests #2 and #3 (`"throws and emits session-expired event on 401"` and `"coalesces repeated 401 events until consumed"`) **fail** because the global fetch mock returns 401 for every call, and our new code will treat the refresh call as 401 → retry as 401 → eventually reach `emitSessionExpired`. They probably still pass actually because the same mock returns 401 for refresh too, but with extra fetch calls. Just observe the output and proceed — Task 4 fixes them properly.

- [ ] **Step 4: Do NOT commit yet** — the next two tasks update tests and add new ones, all part of the same logical change. Commit at the end of Task 5.

---

## Task 4: Update existing tests for the new behavior

**Files:**
- Modify: `frontend/tests/unit/core/identity/fetcher.test.ts:34-69`

The existing tests #2 and #3 assume "401 from server → modal fires". Under the new code, that path now routes through refresh first. We update those tests so the **refresh endpoint** also returns 401, simulating "real session loss" — that's the scenario where the modal *should* still fire.

- [ ] **Step 1: Update test #2 ("throws and emits session-expired event on 401")**

In `frontend/tests/unit/core/identity/fetcher.test.ts`, replace the body of the test currently at lines 34-46 with:

```typescript
  it("throws and emits session-expired event on 401 when refresh also fails", async () => {
    // Both the original request and the refresh return 401 → real session loss.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("", { status: 401 }),
    );

    const listener = vi.fn();
    onSessionExpired(listener);

    await expect(identityFetch("/api/me")).rejects.toMatchObject({
      kind: "unauthenticated",
    });
    expect(listener).toHaveBeenCalledTimes(1);
  });
```

Behavior under the new code: original `/api/me` 401 → calls `refreshSession()` → fetch `/api/auth/refresh` 401 (with `_skipRefreshOn401`) → emits + throws → `refreshSession` catches and returns `false` → outer 401 branch falls through to `emitSessionExpired()` + throw. **Note:** `emitSessionExpired` will be called twice (once from the refresh's internal-flagged 401 path, once from the outer fallthrough), but `sessionExpiredPending` coalesces the listener to one call. The assertion `toHaveBeenCalledTimes(1)` still holds.

- [ ] **Step 2: Update test #3 ("coalesces repeated 401 events until consumed")**

Replace the test currently at lines 48-69. The structure of the test stays similar but we drain `pendingRefresh` between calls by `await`ing the failure, and we use `consumeSessionExpired` between rounds:

```typescript
  it("coalesces repeated 401 events until consumed (with refresh failures)", async () => {
    // Every fetch returns 401 — both the original and the refresh.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("", { status: 401 }),
    );

    const listener = vi.fn();
    onSessionExpired(listener);

    await expect(identityFetch("/api/me")).rejects.toMatchObject({
      kind: "unauthenticated",
    });
    await expect(identityFetch("/api/admin/tenants")).rejects.toMatchObject({
      kind: "unauthenticated",
    });
    expect(listener).toHaveBeenCalledTimes(1);

    consumeSessionExpired();
    await expect(identityFetch("/api/me")).rejects.toMatchObject({
      kind: "unauthenticated",
    });
    expect(listener).toHaveBeenCalledTimes(2);
  });
```

Reasoning: each `identityFetch("/api/me")` call serializes through `await`, so by the time the second call starts, `pendingRefresh` is already cleared (the first attempt's `.finally()` ran). Each round triggers its own (failing) refresh, but `sessionExpiredPending` keeps the listener at 1 invocation per coalescence window.

- [ ] **Step 3: Run tests, expect them to pass**

Run:
```bash
cd frontend && pnpm test fetcher
```
Expected: all 5 existing tests pass under the new code.

If they fail, do NOT change the source — re-read the test and the new `identityFetch` body together until you understand which assumption is wrong, then fix the test (the source is the spec'd behavior).

- [ ] **Step 4: Do NOT commit yet** — Task 5 adds the new tests in the same commit.

---

## Task 5: Add new tests for refresh+retry behavior

**Files:**
- Modify: `frontend/tests/unit/core/identity/fetcher.test.ts` (append inside the existing `describe("identityFetch", ...)` block)

Append these 4 tests just before the closing `});` of the `describe` block (currently around line 95).

- [ ] **Step 1: Add helper for per-call mock at top of file**

Add this helper just after the imports, **outside** the `describe` block:

```typescript
/** Build a fetch mock that returns a different response per matched (url+method)
 *  call, with a fallthrough error if anything unexpected hits it. Each entry's
 *  responses array is consumed in order. */
function makeSequencedFetchMock(
  routes: Record<string, Response[]>,
): ReturnType<typeof vi.fn> {
  const cursors: Record<string, number> = {};
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    const queue = routes[key];
    if (!queue) {
      throw new Error(`unexpected fetch: ${key}`);
    }
    const idx = cursors[key] ?? 0;
    const resp = queue[idx];
    if (!resp) {
      throw new Error(`fetch route exhausted: ${key} (only ${queue.length} responses defined)`);
    }
    cursors[key] = idx + 1;
    // Response objects can only be read once — clone before returning so a single
    // pre-built Response can serve a single call. Tests build new Response per slot.
    return resp;
  });
}
```

- [ ] **Step 2: Add test "401 → refresh OK → retry OK"**

Inside the `describe` block, append:

```typescript
  it("retries the original request once after a successful refresh", async () => {
    const mock = makeSequencedFetchMock({
      "GET /api/me": [
        new Response("", { status: 401 }),
        new Response(JSON.stringify({ user: "ok" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ],
      "POST /api/auth/refresh": [
        new Response(JSON.stringify({ access_token: "new", expires_in: 900 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ],
    });
    vi.stubGlobal("fetch", mock);

    const listener = vi.fn();
    onSessionExpired(listener);

    const result = await identityFetch<{ user: string }>("/api/me");

    expect(result).toEqual({ user: "ok" });
    expect(mock).toHaveBeenCalledTimes(3); // original 401 + refresh + retry 200
    expect(listener).not.toHaveBeenCalled();
  });
```

- [ ] **Step 3: Add test "5 concurrent 401 → singleflight refresh → all retry OK"**

```typescript
  it("singleflights refresh across concurrent 401s", async () => {
    const mock = makeSequencedFetchMock({
      "GET /api/me": [
        new Response("", { status: 401 }),
        new Response("", { status: 401 }),
        new Response("", { status: 401 }),
        new Response("", { status: 401 }),
        new Response("", { status: 401 }),
        new Response(JSON.stringify({ i: 0 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
        new Response(JSON.stringify({ i: 1 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
        new Response(JSON.stringify({ i: 2 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
        new Response(JSON.stringify({ i: 3 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
        new Response(JSON.stringify({ i: 4 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ],
      "POST /api/auth/refresh": [
        new Response(JSON.stringify({ access_token: "new", expires_in: 900 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ],
    });
    vi.stubGlobal("fetch", mock);

    const listener = vi.fn();
    onSessionExpired(listener);

    const results = await Promise.all(
      Array.from({ length: 5 }, () => identityFetch<{ i: number }>("/api/me")),
    );

    // 5 originals (all 401) + 1 refresh + 5 retries (all 200) = 11
    expect(mock).toHaveBeenCalledTimes(11);
    expect(results).toHaveLength(5);
    // All retries succeeded; bodies are returned in some order but each `i`
    // appears exactly once.
    expect(results.map((r) => r.i).sort()).toEqual([0, 1, 2, 3, 4]);
    expect(listener).not.toHaveBeenCalled();

    // Specifically: refresh URL was hit exactly once.
    const refreshCalls = mock.mock.calls.filter(
      ([url, init]) =>
        (typeof url === "string" ? url : url.toString()) ===
          "/api/auth/refresh" && (init?.method ?? "GET") === "POST",
    );
    expect(refreshCalls).toHaveLength(1);
  });
```

- [ ] **Step 4: Add test "401 → refresh OK → retry still 401"**

```typescript
  it("emits session-expired when retry-after-refresh is still 401", async () => {
    const mock = makeSequencedFetchMock({
      "GET /api/me": [
        new Response("", { status: 401 }), // initial
        new Response("", { status: 401 }), // retry
      ],
      "POST /api/auth/refresh": [
        new Response(JSON.stringify({ access_token: "new", expires_in: 900 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ],
    });
    vi.stubGlobal("fetch", mock);

    const listener = vi.fn();
    onSessionExpired(listener);

    await expect(identityFetch("/api/me")).rejects.toMatchObject({
      kind: "unauthenticated",
    });
    expect(mock).toHaveBeenCalledTimes(3); // original + refresh + retry
    expect(listener).toHaveBeenCalledTimes(1);
  });
```

- [ ] **Step 5: Add test "refresh endpoint not recursing on its own 401"**

```typescript
  it("does not recurse when the refresh endpoint itself returns 401", async () => {
    const mock = makeSequencedFetchMock({
      "GET /api/me": [new Response("", { status: 401 })],
      "POST /api/auth/refresh": [new Response("", { status: 401 })],
    });
    vi.stubGlobal("fetch", mock);

    const listener = vi.fn();
    onSessionExpired(listener);

    await expect(identityFetch("/api/me")).rejects.toMatchObject({
      kind: "unauthenticated",
    });
    // 1 original + 1 refresh. No retry, no second refresh.
    expect(mock).toHaveBeenCalledTimes(2);
    expect(listener).toHaveBeenCalledTimes(1);
  });
```

- [ ] **Step 6: Run the full fetcher test suite**

Run:
```bash
cd frontend && pnpm test fetcher
```
Expected: all 9 tests pass (5 original + 4 new).

If any new test fails, debug by adding `console.log` in the test to inspect call sequences. Do not change source code unless you've ruled out a test bug.

- [ ] **Step 7: Run the full unit test suite**

Run:
```bash
cd frontend && pnpm test
```
Expected: all tests pass. The `session-expired-modal.test.tsx`, `RequirePermission.test.tsx`, `admin-hooks.test.tsx`, `hooks.test.tsx` should all still pass — they don't trigger the new code path because they don't return 401 from real fetches; they mock at higher layers.

- [ ] **Step 8: Commit Tasks 3-5 together**

Run:
```bash
git add frontend/src/core/identity/fetcher.ts frontend/tests/unit/core/identity/fetcher.test.ts
git commit -m "feat(identity): refresh access token on 401 instead of forcing re-login

identityFetch now intercepts 401 responses, calls POST /api/auth/refresh
once (singleflight across concurrent 401s), and retries the original
request once. Real session loss (refresh itself 401, or retry still 401)
still emits session-expired and pops the modal as before.

Closes the false 'Session expired' modal that fired mid-conversation
(>15min stream) and during workspace switch (TanStack invalidate fanout).

Tests: 5 existing updated for new semantics, 4 new added covering
refresh+retry, singleflight coalescing, retry-401, and refresh-self-401."
```

---

## Task 6: Rewire identityApi.refresh to share the singleflight

**Files:**
- Modify: `frontend/src/core/identity/api.ts:57-61`

`identityApi.refresh` is currently exported but has no callers. We rewire it to delegate to the internal `refreshSession()` so any future caller automatically participates in coalescing. Public return shape preserved (the resolution is a placeholder; nobody reads it today).

- [ ] **Step 1: Replace the refresh implementation**

Open `frontend/src/core/identity/api.ts`. Replace lines 57-61:

```typescript
  refresh: () =>
    identityFetch<{ access_token: string; expires_in: number }>(
      "/api/auth/refresh",
      { method: "POST" },
    ),
```

with:

```typescript
  refresh: async () => {
    // Delegates to fetcher's internal singleflight so concurrent callers
    // (interceptor + any future direct caller) coalesce into one network
    // call. The resolved shape is preserved for back-compat; today no
    // caller reads it.
    const ok = await _refreshSessionForIdentityApi();
    if (!ok) {
      throw new IdentityFetchError({ kind: "unauthenticated" });
    }
    return { access_token: "", expires_in: 0 };
  },
```

- [ ] **Step 2: Add the imports at the top of api.ts**

In the existing imports block at the top of `frontend/src/core/identity/api.ts` (currently importing `identityFetch` from `./fetcher`), extend that import line:

```typescript
import {
  IdentityFetchError,
  _refreshSessionForIdentityApi,
  identityFetch,
} from "./fetcher";
```

- [ ] **Step 3: Verify type-check**

Run:
```bash
cd frontend && pnpm typecheck
```
Expected: PASS.

- [ ] **Step 4: Run tests**

Run:
```bash
cd frontend && pnpm test
```
Expected: PASS.

- [ ] **Step 5: Commit**

Run:
```bash
git add frontend/src/core/identity/api.ts
git commit -m "refactor(identity): identityApi.refresh delegates to shared singleflight

Any future direct caller of identityApi.refresh now coalesces with the
identityFetch interceptor's refresh call. Public return shape preserved
for back-compat; no caller reads it today."
```

---

## Task 7: Lint + build verification

**Files:** none — runs project-level checks.

- [ ] **Step 1: Lint**

Run:
```bash
cd frontend && pnpm lint
```
Expected: PASS, zero warnings on the touched files.

If ESLint flags the underscore-prefixed export `_refreshSessionForIdentityApi` (per the project rule "Unused variables: Prefix with `_`"), the import in `api.ts` makes it used, so no issue. If lint complains about unused destructured `_skipRefreshOn401` in `fetcher.ts`, leave a `// eslint-disable-next-line` only as a last resort — the variable IS used (controls the conditional). If the rule fires erroneously, prefer to rename the destructure to a non-underscore name and use it directly — but it's the convention name so try without.

- [ ] **Step 2: Type check standalone**

Run:
```bash
cd frontend && pnpm typecheck
```
Expected: PASS.

- [ ] **Step 3: Build**

Run:
```bash
cd frontend && pnpm build
```
Expected: PASS. The build output should not be substantially different in size — we added ~30 lines of code.

- [ ] **Step 4: If any check fails — debug and fix in the smallest possible commit**

Don't bypass with `--no-verify`. If lint/build fails for a reason caused by Tasks 1-6, fix it in a small follow-up commit on this branch.

---

## Task 8: Manual smoke test

**Files:** none — manual verification.

Per `feedback_local_only_workflow.md` and the project's "verification before completion" rule, run a quick local smoke before merging.

- [ ] **Step 1: Start dev environment**

Run from project root:
```bash
make dev
```
Wait for "All services started". Open `http://localhost:2026`.

- [ ] **Step 2: Log in**

Use dev login (`DEERFLOW_DEV_LOGIN=true` is in `.env`). Confirm you land on the workspace page without the session-expired modal flashing.

- [ ] **Step 3: Force a token-expiry scenario**

Easiest method: in DevTools → Application → Cookies → `localhost:2026`, find `deerflow_session`, **delete it**. This simulates token expiry.

- [ ] **Step 4: Trigger any background fetch**

Click a sidebar item or refresh a panel that causes `/api/me` to be re-fetched. **Expected:** the page should silently re-authenticate via `/api/auth/refresh` (you'll see the refresh request in DevTools Network tab), and the modal does NOT pop.

**Hold on** — if the cookie is fully deleted (not just expired), the refresh endpoint also can't find the session ID inside the (now-missing) cookie and will return 401. In that case the modal SHOULD pop. So this test demonstrates the **session-loss** path correctly.

To test the **expiry-but-session-alive** path more precisely, the proper way is:
- Set `DEERFLOW_ACCESS_TOKEN_TTL_SEC=10` in `.env`, restart, log in, wait 11 seconds, click anything. Without our fix → modal. With our fix → silent recovery.

If you don't want to restart the gateway for this: the deletion test above is sufficient evidence that the interceptor is wired up — you'll see the network request go to `/api/auth/refresh`. Pair that with the unit tests for confidence.

- [ ] **Step 5: Test workspace (tenant) switch (only if your account has 2+ tenants)**

If the dev admin user has only one tenant, skip this step — the unit test for singleflight covers the concurrent case. If multi-tenant, click the tenant switcher dropdown, switch tenants, and confirm no modal pops. DevTools Network tab should show one refresh call (or none, if cookie was fresh) and a fanout of `/api/me`, `/api/tenants/.../*` requests all returning 200.

- [ ] **Step 6: Stop dev**

Run from project root:
```bash
make stop
```

---

## Task 9: Merge to cc-main and push

**Files:** none.

Per `frontend/CLAUDE.md` §"分支操作约束" item 5: each `feat/*` branch merges to `cc-main` after lint + test + build pass, and `push origin cc-main` immediately, no PR.

- [ ] **Step 1: Confirm clean state on feature branch**

Run:
```bash
git status -sb
git log --oneline cc-main..HEAD
```
Expected: clean tree, 4 commits ahead of `cc-main` (Tasks 1, 2, 3-5, 6 — 4 commits total since Task 0 was branch-only and Tasks 7-8 are verification-only).

- [ ] **Step 2: Switch to cc-main and merge**

Run:
```bash
git checkout cc-main
git merge --no-ff feat/session-refresh-interceptor -m "Merge feat/session-refresh-interceptor: 401 refresh+retry interceptor"
```

Use `--no-ff` to keep the feature branch as a visible group of commits, matching the merge style in recent history (e.g. `c4c353f4 Merge feat/frontend-artifact-cache-invalidation`).

- [ ] **Step 3: Push to origin**

Run:
```bash
git push origin cc-main
```
Expected: success.

- [ ] **Step 4: Update memory**

Append a one-line entry to `/Users/lydoc/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/MEMORY.md`:

```markdown
- [P1 bug：access token 过期弹"Session expired"误伤会话](spec_session_refresh_interceptor.md) — ✅ 已闭环（2026-04-28）：identityFetch 加 401 → refresh → retry singleflight 拦截器，5+4 vitest 全绿；scope A 只覆盖 identityFetch（LangGraph SDK 路径已知容忍）
```

And write the linked memory body file at `/Users/lydoc/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/spec_session_refresh_interceptor.md`:

```markdown
---
name: P1 bug — access token 过期弹"Session expired"误伤会话
description: 访问令牌 15min TTL + 前端无 refresh 逻辑导致会话等待和 workspace 切换时误弹模态；已修
type: project
---

## 现象
- 会话等待中（agent 跑十几分钟）忽然弹"Session expired / sign in again"
- 切 tenant 时偶发同一模态
- 后端 Redis session 还活着（refresh-token TTL=7d），只是 access token cookie 过期（默认 900s）

## 根因
- `frontend/src/core/identity/fetcher.ts:62-65` 把所有 401 直通 `emitSessionExpired`，从不调 `/api/auth/refresh`。
- `identityApi.refresh` 定义但无人调用。
- TanStack `staleTime=60s` 的 `/api/me` 重拉 + `useSwitchTenant` 的 invalidateQueries 风暴是最常见触发点。

## 修法（scope A）
2026-04-28 落地：identityFetch 加 401 → refresh → retry singleflight 拦截器（仅覆盖 identityFetch 路径）。
LangGraph SDK 自身的 fetch 不拦，依靠 /api/me 先于 LangGraph 调用刷新 cookie 兜底。

## 后续可做
- C 方案（proactive refresh based on JWT exp）单独做
- 或者最简版：把 `DEERFLOW_ACCESS_TOKEN_TTL_SEC` 拉到 1 天，自托管单租户够用

## 关键路径
- 设计 spec: `docs/superpowers/specs/2026-04-28-session-refresh-interceptor-design.md`
- 实施 plan: `docs/superpowers/plans/2026-04-28-session-refresh-interceptor.md`
- 改动文件: `frontend/src/core/identity/fetcher.ts`, `frontend/src/core/identity/api.ts`, `frontend/tests/unit/core/identity/fetcher.test.ts`
```

- [ ] **Step 5: Final verify**

Run:
```bash
git log --oneline cc-main -10
git status -sb
```
Expected: cc-main is up to date with origin, working tree clean, the merge commit and 4 feat commits all visible at the top.

---

## Done

The interceptor is live on `cc-main`, pushed to origin, smoke-tested locally, and 9 unit tests gate any regression. The "Session expired" modal will only fire when the user's session is actually invalid (refresh fails or retry-after-refresh still 401), not on routine token expiry.

If a follow-up reveals that LangGraph SDK 401s are still firing the modal more than expected, the next iteration is **scope B** (wrap LangGraph SDK fetch with a custom transport that injects the same retry logic) — track separately, not in this plan.
