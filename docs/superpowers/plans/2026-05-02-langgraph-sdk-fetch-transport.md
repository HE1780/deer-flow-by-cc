# LangGraph SDK Fetch Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LangGraph SDK calls share `identityFetch`'s 401 → refresh → retry behavior, so token-rollover during streaming/non-streaming SDK use no longer surfaces as broken UI.

**Architecture:** Promote `refreshSession` from a private alias in `fetcher.ts` to a regular module export. Inject a wrapper `sdkFetchWithRefresh` into `LangGraphClient` via `callerOptions.fetch`; the wrapper retries non-streaming 401s once after a singleflight refresh and emits `emitSessionExpired()` on hard failure. SSE/streaming requests opt out (mid-stream replay is unsafe).

**Tech Stack:** TypeScript, `@langchain/langgraph-sdk` 1.6.0, Vitest + jsdom. Spec: [docs/superpowers/specs/2026-05-02-langgraph-sdk-fetch-transport-design.md](../specs/2026-05-02-langgraph-sdk-fetch-transport-design.md).

**Branch convention (per CLAUDE.md §git策略):** create `feat/langgraph-sdk-fetch-transport` off `cc-main`, merge back after tests pass, push.

**Recommended order:** ship after Spec ① (cookie-max-age) so the manual smoke actually exercises this path.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `frontend/src/core/identity/fetcher.ts` | modify | Promote `refreshSession` to a public export (rename of an existing `_refreshSessionForIdentityApi` alias) |
| `frontend/src/core/api/api-client.ts` | modify | Define `sdkFetchWithRefresh`; pass it via `callerOptions.fetch` |
| `frontend/tests/unit/core/api/api-client.test.ts` | create | 4 vitest cases covering retry / SSE-skip / hard-fail / singleflight |

No new architectural layers — the wrapper lives in `api-client.ts` next to the existing `createCompatibleClient` so the whole "SDK construction" concept stays in one file.

---

## Task 1: Branch + spec acknowledgement

**Files:**
- None (git only)

- [ ] **Step 1: Create feat branch from cc-main**

```bash
git checkout cc-main
git pull origin cc-main
git checkout -b feat/langgraph-sdk-fetch-transport
git status -sb
```

Expected: `## feat/langgraph-sdk-fetch-transport`.

- [ ] **Step 2: Confirm spec is on the branch**

```bash
ls docs/superpowers/specs/2026-05-02-langgraph-sdk-fetch-transport-design.md
```

Expected: file present.

---

## Task 2: Promote `refreshSession` to a regular export

**Files:**
- Modify: `frontend/src/core/identity/fetcher.ts:41-55`

- [ ] **Step 1: Inspect the current shape**

```bash
sed -n '38,56p' frontend/src/core/identity/fetcher.ts
```

You should see:

```ts
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

- [ ] **Step 2: Make `refreshSession` a regular export, keep the alias for backward compat**

Replace the snippet above with:

```ts
/** Singleflight session refresh. Returns true if /api/auth/refresh succeeded.
 *  Shared by identityFetch and the LangGraph SDK transport so concurrent 401s
 *  across both fan in to a single refresh attempt. While a refresh is
 *  in-flight, all concurrent callers await the same promise. */
export async function refreshSession(): Promise<boolean> {
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

// Backward-compat alias used by identityApi.refresh — unchanged shape.
export { refreshSession as _refreshSessionForIdentityApi };
```

The implementation is byte-identical; only the export visibility changed.

- [ ] **Step 3: Run the existing fetcher.test.ts — must remain green**

```bash
cd frontend && pnpm test --run tests/unit/core/identity/fetcher.test.ts
```

Expected: 9 cases pass.

- [ ] **Step 4: Run typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/identity/fetcher.ts
git commit -m "refactor(identity): export refreshSession for cross-layer reuse

Promote refreshSession from a private alias-only export to a regular
named export. Implementation is byte-identical; the alias
_refreshSessionForIdentityApi is retained so identityApi.refresh keeps
working unchanged. Prepares the SDK transport (next task) to share the
same singleflight refresh state.

Spec: docs/superpowers/specs/2026-05-02-langgraph-sdk-fetch-transport-design.md"
```

---

## Task 3: Write failing vitest for SDK transport

**Files:**
- Create: `frontend/tests/unit/core/api/api-client.test.ts`

- [ ] **Step 1: Create the test file with all 4 cases**

```ts
// frontend/tests/unit/core/api/api-client.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getAPIClient } from "@/core/api/api-client";
import {
  onSessionExpired,
  resetSessionExpiredListeners,
} from "@/core/identity/fetcher";

/** Mirror of the helper in fetcher.test.ts: returns a sequenced response per
 *  (method url) call. Calls outside the configured set throw — surfaces
 *  unintentional fetches loudly. */
function makeSequencedFetchMock(routes: Record<string, Response[]>) {
  const cursors: Record<string, number> = {};
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    const queue = routes[key];
    if (!queue) {
      throw new Error(`unexpected fetch: ${key}`);
    }
    const idx = cursors[key] ?? 0;
    const resp = queue[idx];
    if (!resp) {
      throw new Error(`fetch route exhausted: ${key}`);
    }
    cursors[key] = idx + 1;
    return resp;
  });
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

const empty = (status: number) => new Response("", { status });

// Reset the module-level LangGraphClient cache between tests so each test
// gets a fresh client whose callerOptions.fetch resolves through the patched
// globalThis.fetch.
beforeEach(async () => {
  vi.resetModules();
});

afterEach(() => {
  resetSessionExpiredListeners();
  vi.restoreAllMocks();
});

describe("api-client — sdk fetch transport", () => {
  it("retries non-streaming SDK calls once after a successful refresh", async () => {
    // threads.search posts to /threads/search with a JSON body. We don't need
    // to know the exact URL the SDK builds — we mock both the langgraph-base
    // path and the refresh path with sequenced responses.
    const mock = makeSequencedFetchMock({
      // First SDK call → 401, second (after refresh) → 200 list.
      "POST http://localhost:2024/threads/search": [
        empty(401),
        json(200, []),
      ],
      // Refresh succeeds.
      "POST /api/auth/refresh": [json(200, { ok: true })],
    });
    vi.stubGlobal("fetch", mock);

    const { getAPIClient } = await import("@/core/api/api-client");
    const result = await getAPIClient().threads.search({});

    expect(result).toEqual([]);
    // Exactly: original 401 + refresh + retry = 3 calls
    expect(mock).toHaveBeenCalledTimes(3);
  });

  it("does not retry SSE/streaming requests on 401", async () => {
    const mock = makeSequencedFetchMock({
      // Streaming endpoint returns 401; transport must NOT call refresh and
      // must NOT retry — it just surfaces the 401 to onError downstream.
      "POST http://localhost:2024/threads/abc/runs/stream": [empty(401)],
    });
    vi.stubGlobal("fetch", mock);

    const { getAPIClient } = await import("@/core/api/api-client");
    // The SDK's streaming methods reject when the initial connection 401s.
    // We don't iterate the AsyncGenerator — just collect the rejection.
    const stream = getAPIClient().runs.stream("abc", "lead_agent", {
      input: {},
    });
    await expect(stream.next()).rejects.toBeDefined();

    // Exactly one call. No refresh attempt.
    expect(mock).toHaveBeenCalledTimes(1);
    const calls = mock.mock.calls.map(
      ([input]) =>
        (typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : (input as Request).url),
    );
    expect(calls.find((u) => u.includes("/api/auth/refresh"))).toBeUndefined();
  });

  it("emits session-expired when refresh itself returns 401", async () => {
    const mock = makeSequencedFetchMock({
      "POST http://localhost:2024/threads/search": [empty(401)],
      "POST /api/auth/refresh": [empty(401)],
    });
    vi.stubGlobal("fetch", mock);

    const listener = vi.fn();
    onSessionExpired(listener);

    const { getAPIClient } = await import("@/core/api/api-client");
    await expect(getAPIClient().threads.search({})).rejects.toBeDefined();

    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("singleflight: 5 concurrent 401s issue exactly one refresh", async () => {
    const mock = makeSequencedFetchMock({
      "POST http://localhost:2024/threads/search": [
        empty(401), empty(401), empty(401), empty(401), empty(401),
        // Retries after refresh succeeds.
        json(200, []), json(200, []), json(200, []), json(200, []), json(200, []),
      ],
      "POST /api/auth/refresh": [json(200, { ok: true })],
    });
    vi.stubGlobal("fetch", mock);

    const { getAPIClient } = await import("@/core/api/api-client");
    const client = getAPIClient();
    await Promise.all(
      Array.from({ length: 5 }, () => client.threads.search({})),
    );

    const refreshCalls = mock.mock.calls.filter(([input]) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : (input as Request).url;
      return url.includes("/api/auth/refresh");
    });
    expect(refreshCalls.length).toBe(1);
  });
});
```

> **Note on URLs**: the host `http://localhost:2024` matches `getLangGraphBaseURL()` in the dev environment. If `frontend/.env` overrides this for the test run (`NEXT_PUBLIC_LANGGRAPH_BASE_URL`), the test will fail in unexpected fetch and you'll see the actual URL in the error message — update the route key to match. The first failure message tells you the answer.

- [ ] **Step 2: Run the test to verify it fails (transport not yet wired)**

```bash
cd frontend && pnpm test --run tests/unit/core/api/api-client.test.ts
```

Expected: **all 4 cases fail**. The first one fails because there's no transport, so the second mocked response is never consumed and the test throws "unexpected fetch" or returns the 401 directly.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/unit/core/api/api-client.test.ts
git commit -m "test(api): regression for SDK fetch 401-refresh-retry transport"
```

---

## Task 4: Wire `sdkFetchWithRefresh` into `getAPIClient()`

**Files:**
- Modify: `frontend/src/core/api/api-client.ts`

- [ ] **Step 1: Read the current file**

```bash
cat frontend/src/core/api/api-client.ts
```

Confirms the existing shape: `createCompatibleClient` constructs `LangGraphClient` then monkey-patches `runs.stream` / `runs.joinStream` for `streamMode` sanitization.

- [ ] **Step 2: Replace with the transport-aware version**

Overwrite `frontend/src/core/api/api-client.ts` with:

```ts
"use client";

import { Client as LangGraphClient } from "@langchain/langgraph-sdk/client";

import {
  emitSessionExpired,
  refreshSession,
} from "@/core/identity/fetcher";
import { getLangGraphBaseURL } from "../config";

import { sanitizeRunStreamOptions } from "./stream-mode";

/** Streaming requests must not be retried — replaying a half-consumed SSE
 *  connection corrupts message ordering. We detect them by accept header and
 *  by URL substring (defense-in-depth: the SDK might omit the header in some
 *  versions). */
function isStreamingRequest(input: RequestInfo | URL, init?: RequestInit): boolean {
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
  if (url.includes("/runs/stream") || url.includes("/runs/join")) return true;

  const headers = init?.headers;
  if (!headers) return false;
  const accept =
    headers instanceof Headers
      ? headers.get("accept")
      : Array.isArray(headers)
        ? headers.find(([k]) => k.toLowerCase() === "accept")?.[1]
        : (headers as Record<string, string>)["accept"] ??
          (headers as Record<string, string>)["Accept"];
  return typeof accept === "string" && accept.includes("text/event-stream");
}

/** Wraps fetch for the LangGraph SDK so SDK-originated 401s share the same
 *  singleflight refresh-and-retry behavior as identityFetch. Streaming
 *  requests fall through unchanged. */
async function sdkFetchWithRefresh(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const resp = await fetch(input, init);
  if (resp.status !== 401) return resp;
  if (isStreamingRequest(input, init)) return resp;

  const refreshed = await refreshSession();
  if (!refreshed) {
    emitSessionExpired();
    return resp;
  }
  const retry = await fetch(input, init);
  if (retry.status === 401) emitSessionExpired();
  return retry;
}

function createCompatibleClient(isMock?: boolean): LangGraphClient {
  const client = new LangGraphClient({
    apiUrl: getLangGraphBaseURL(isMock),
    callerOptions: { fetch: sdkFetchWithRefresh },
  });

  // Existing wrappers for streamMode sanitization — unchanged.
  const originalRunStream = client.runs.stream.bind(client.runs);
  client.runs.stream = ((threadId, assistantId, payload) =>
    originalRunStream(
      threadId,
      assistantId,
      sanitizeRunStreamOptions(payload),
    )) as typeof client.runs.stream;

  const originalJoinStream = client.runs.joinStream.bind(client.runs);
  client.runs.joinStream = ((threadId, runId, options) =>
    originalJoinStream(
      threadId,
      runId,
      sanitizeRunStreamOptions(options),
    )) as typeof client.runs.joinStream;

  return client;
}

const _clients = new Map<string, LangGraphClient>();
export function getAPIClient(isMock?: boolean): LangGraphClient {
  const cacheKey = isMock ? "mock" : "default";
  let client = _clients.get(cacheKey);

  if (!client) {
    client = createCompatibleClient(isMock);
    _clients.set(cacheKey, client);
  }

  return client;
}
```

- [ ] **Step 3: Run the failing tests — should now pass**

```bash
cd frontend && pnpm test --run tests/unit/core/api/api-client.test.ts
```

Expected: all 4 cases **PASS**.

If "retries non-streaming SDK calls once after a successful refresh" fails with `expected 3 calls, received 2` or similar:
- The SDK might be using a different URL path; read the failure message for the actual URL and update the route key in the test.
- The SDK might be passing `accept: application/json` plus something that the streaming detector misclassifies; verify `isStreamingRequest` returns `false` for the test URL.

If "does not retry SSE/streaming requests on 401" fails because no error is thrown:
- The SDK might silently reconnect on 401 in some streaming modes. The test asserts the mock is called exactly once — if it's called twice, our `isStreamingRequest` failed; check the URL/headers used.

- [ ] **Step 4: Run the full identity test suite — must remain green**

```bash
cd frontend && pnpm test --run tests/unit/core/identity/
```

Expected: 9 cases pass.

- [ ] **Step 5: Run `pnpm check` (lint + typecheck)**

```bash
cd frontend && pnpm check
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/core/api/api-client.ts frontend/tests/unit/core/api/api-client.test.ts
git commit -m "feat(api): SDK fetch transport with 401-refresh-retry singleflight

LangGraph SDK calls (threads.search, runs.create, threads.update, etc.)
now share identityFetch's session-refresh logic via callerOptions.fetch.
Streaming requests (SSE) opt out — replay would corrupt message order.

After this change, mid-conversation token rollovers no longer surface as
toast errors or hung UI; the SDK request transparently refreshes and
retries. Concurrent 401s across identityFetch and SDK both fan in to a
single /api/auth/refresh call (singleflight via shared module state).

Closes the LangGraph SDK gap left as scope-A deferral in
docs/superpowers/specs/archive/2026-04-28-session-refresh-interceptor-design.md.

Spec: docs/superpowers/specs/2026-05-02-langgraph-sdk-fetch-transport-design.md"
```

---

## Task 5: Manual smoke (acceptance criterion from spec)

**Files:**
- None (browser observation; only meaningful AFTER Spec ① is shipped)

- [ ] **Step 1: Confirm Spec ① already shipped**

If `_set_session_cookie` still uses `access_ttl_sec`, this smoke is meaningless — you'll just trigger the cookie-deletion path. Either ship Spec ① first or jump to Task 6.

```bash
grep "max_age=" backend/app/gateway/identity/routers/auth.py
```

Expected: `max_age=rt.refresh_ttl_sec,`. If you see `access_ttl_sec`, abort the smoke.

- [ ] **Step 2: Start the stack**

```bash
make dev
```

- [ ] **Step 3: Log in and idle 16 minutes**

Open `http://localhost:2026/workspace/chats/new`, log in, then leave the tab open and untouched for **16 minutes**. (15 min is the default `access_ttl_sec` — wait one extra minute to ensure JWT exp is past.)

While idling, do not switch tabs (window-focus refetch would refresh the cookie via `useIdentity`'s staleTime invalidation, masking the bug).

- [ ] **Step 4: Send a chat message**

Type "hello" in the chat input and submit. Watch DevTools → Network panel.

Expected sequence (the heart of the fix):
1. `POST /api/langgraph/threads` or similar SDK call → **401**
2. `POST /api/auth/refresh` → **200**
3. The original SDK call automatically retried → **200** with the message accepted
4. Chat streams normally; no toast, no modal

Failure modes:
- Toast appears + chat stalls → Task 4 didn't deploy (transport not wired)
- Modal pops → Spec ① wasn't deployed (cookie was deleted, not just token expired)
- 401 response surfaces with no refresh attempt → `isStreamingRequest` is misclassifying the request type

- [ ] **Step 5: Record the result**

Save the network panel screenshot to the merge commit description.

---

## Task 6: Merge to cc-main

**Files:**
- None (git only)

- [ ] **Step 1: Confirm clean tree**

```bash
git status -sb
```

Expected: `## feat/langgraph-sdk-fetch-transport`, no uncommitted changes.

- [ ] **Step 2: Switch to cc-main and merge**

```bash
git checkout cc-main
git merge --no-ff feat/langgraph-sdk-fetch-transport -m "merge: LangGraph SDK fetch transport (4 vitest)

Closes the LangGraph SDK 401-handling gap left as scope-A deferral in
the 2026-04-28 session-refresh-interceptor work.

Spec: docs/superpowers/specs/2026-05-02-langgraph-sdk-fetch-transport-design.md
Plan: docs/superpowers/plans/2026-05-02-langgraph-sdk-fetch-transport.md"
```

- [ ] **Step 3: Push**

```bash
git push origin cc-main
```

- [ ] **Step 4: Delete local feat branch (optional)**

```bash
git branch -d feat/langgraph-sdk-fetch-transport
```

---

## Task 7: Archive spec + plan, update memory

**Files:**
- Move: `docs/superpowers/specs/2026-05-02-langgraph-sdk-fetch-transport-design.md` → `archive/`
- Move: `docs/superpowers/plans/2026-05-02-langgraph-sdk-fetch-transport.md` → `archive/`
- Update: `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/MEMORY.md`

- [ ] **Step 1: Add a "Shipped" banner to the spec**

Add at the top of the spec file:

```markdown
> 📦 **归档于 YYYY-MM-DD — 已 ship**：merged into `cc-main` as `<short-sha>`. 4 vitest 全绿；manual 16-min idle smoke 通过。

---
```

- [ ] **Step 2: Move spec + plan to archive**

```bash
git mv docs/superpowers/specs/2026-05-02-langgraph-sdk-fetch-transport-design.md \
       docs/superpowers/specs/archive/
git mv docs/superpowers/plans/2026-05-02-langgraph-sdk-fetch-transport.md \
       docs/superpowers/plans/archive/
```

- [ ] **Step 3: Update memory**

Append to `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/MEMORY.md`:

```markdown
- [P1 fix: LangGraph SDK 401-refresh transport](spec_langgraph_sdk_fetch_transport.md) — ✅ 已闭环（YYYY-MM-DD）：callerOptions.fetch 注入；SSE 不重试；singleflight 与 identityFetch 共享；merge `<short-sha>`
```

Create `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/spec_langgraph_sdk_fetch_transport.md`:

```markdown
---
name: P1 fix — LangGraph SDK 401-refresh transport
description: SDK 经 callerOptions.fetch 共享 identityFetch 的 401→refresh→retry，闭合 scope-A 容忍点
type: project
---

## 现象
mid-conversation 流式或非流式 SDK 调用碰到 token 过期 → 401 直冒到 UI（toast/卡死）。

## 修法
- frontend/src/core/identity/fetcher.ts: refreshSession 改为公开 export
- frontend/src/core/api/api-client.ts: 新 sdkFetchWithRefresh + isStreamingRequest，注入到 LangGraphClient.callerOptions.fetch
- 4 vitest（retry / SSE-skip / hard-fail / singleflight）

## 状态
✅ shipped YYYY-MM-DD as `<short-sha>`. 16-min idle manual smoke 通过。
```

- [ ] **Step 4: Commit and push**

```bash
git add docs/superpowers/specs/ docs/superpowers/plans/
git commit -m "docs(specs): archive shipped LangGraph SDK fetch transport spec + plan"
git push origin cc-main
```

---

## Definition of Done

- [ ] `refreshSession` is a public export in `fetcher.ts` (Task 2)
- [ ] `getAPIClient()` passes `callerOptions: { fetch: sdkFetchWithRefresh }` (Task 4)
- [ ] `sdkFetchWithRefresh` skips retry on streaming requests (Task 4)
- [ ] All 4 new vitest cases pass (Tasks 3-4)
- [ ] `fetcher.test.ts` (9 cases) still green (Task 4)
- [ ] `pnpm check` is green (Task 4)
- [ ] Manual 16-min idle smoke recorded (Task 5)
- [ ] Merged to `cc-main` and pushed (Task 6)
- [ ] Spec + plan archived; memory updated (Task 7)
