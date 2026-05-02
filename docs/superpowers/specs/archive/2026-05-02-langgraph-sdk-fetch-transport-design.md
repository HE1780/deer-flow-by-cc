> 📦 **归档于 2026-05-02 — 已 ship**：merged into `cc-main` as `4433a412`. 5 vitest 全绿（含 `runs.join` 回归测试 — code review 抓出 `/runs/join` 误归类为 SSE 的 bug）。Browser smoke：401 → refresh-200 → retry-200 → no modal，session-expired modal 在 cookie 续期场景下不再误触发。
>
> 实现期间发现并落实了 spec/plan 没明确的 3 个必要扩展：
> - `emitSessionExpired` 升为 public export（被 `sdkFetchWithRefresh` 调用）
> - `fetcher.ts` 内部 state（listeners / pendingRefresh / sessionExpiredPending）迁到 `globalThis[Symbol.for("deerflow.identity.fetcherState")]`，让 `vi.resetModules()` 测试隔离与 prod singleflight 同一份 state
> - `callerOptions.maxConcurrency: Infinity` —— SDK 默认 4 会序列化并发请求，破坏 singleflight；这是生产正确性修复非测试 hack

---

# LangGraph SDK Fetch Transport — 401 Refresh Retry

**Date:** 2026-05-02
**Status:** ✅ Shipped (see banner above)
**Owner:** frontend (core/api)
**Touches:**
- `frontend/src/core/api/api-client.ts` — inject `callerOptions.fetch`
- `frontend/src/core/identity/fetcher.ts` — extract reusable refresh primitive
- `frontend/tests/unit/core/api/api-client.test.ts` (new)

## Problem

The session-refresh interceptor that landed in `archive/2026-04-28-session-refresh-interceptor-design.md`
covers `identityFetch` only. LangGraph SDK calls
([frontend/src/core/api/api-client.ts:10](../../../frontend/src/core/api/api-client.ts#L10))
go through the SDK's own `BaseClient.fetch`, which never sees a 401 retry.

Concrete failure scenario, even **after** Issue ① (`Cookie max-age decouple`)
ships:

1. User logs in. Cookie now valid for 7 d.
2. User idles 16 min in the same tab. Access-token JWT `exp` has passed; the
   cookie is still in the browser.
3. User submits a new chat message → `useStream` calls `client.runs.stream`.
4. SDK's internal `fetch` posts to `/api/langgraph/...` with the (still-attached)
   cookie. Backend rejects 401 because JWT is expired.
5. SDK throws → `useStream`'s `onError` fires → toast error → user is stuck
   sending messages until they reload.

The frontend already has a working refresh primitive
([fetcher.ts:42-53](../../../frontend/src/core/identity/fetcher.ts#L42-L53)),
but it is private to `identityFetch`. We need to lift it so the SDK's transport
can use the same singleflight refresh.

## Goals

- Any LangGraph SDK call that 401s gets one transparent refresh-and-retry.
- Refresh is singleflight-shared with `identityFetch` — concurrent 401s across
  both layers trigger at most one `/api/auth/refresh`.
- Streaming requests (SSE) are not retried (mid-stream replay is unsafe and
  loses message ordering); they fall back to current `onError` behavior.
- Zero impact on non-401 paths.

## Non-goals

- ❌ Wrap `globalThis.fetch`. The blast radius is too large; we'd intercept
  Next.js's own server fetches, RSC fetches, etc.
- ❌ Monkey-patch SDK methods individually. The pattern in
  [api-client.ts:14-28](../../../frontend/src/core/api/api-client.ts#L14-L28)
  works for `runs.stream`/`runs.joinStream` because those needed `streamMode`
  sanitization — wrapping every SDK method would be brittle.
- ❌ Proactive timer-based refresh based on JWT `exp`.
- ❌ Change the SDK version pin (1.6.0 stays).
- ❌ Show a different UI for SDK-originated 401s (still use the existing
  session-expired modal pathway via `emitSessionExpired`).

## Approach

LangGraph SDK 1.6.0 exposes `callerOptions.fetch` on `ClientConfig.callerOptions`
([@langchain/langgraph-sdk/dist/utils/async_caller.d.ts:20](../../../frontend/node_modules/@langchain/langgraph-sdk/dist/utils/async_caller.d.ts#L20)):

```ts
interface AsyncCallerParams {
  fetch?: typeof fetch | ((...args: any[]) => any);
  // ...
}
```

`BaseClient.fetch` delegates through `AsyncCaller` which uses this fetch when
provided. Inject a wrapper at construction time:

### Step 1 — extract the refresh primitive in `fetcher.ts`

Currently `refreshSession` is a private async fn re-exported only as
`_refreshSessionForIdentityApi`. Promote it to a documented internal API the
SDK transport can also call:

```ts
// fetcher.ts
/** Singleflight session refresh. Returns true if /api/auth/refresh succeeded.
 *  Shared by identityFetch and the LangGraph SDK transport so concurrent 401s
 *  across both fan in to a single refresh attempt. */
export async function refreshSession(): Promise<boolean> { /* unchanged */ }

// keep the existing alias for backward compat — Issue ①+② can land in either order
export { refreshSession as _refreshSessionForIdentityApi };
```

The internals don't change; only the export visibility does.

### Step 2 — write the SDK transport in `api-client.ts`

```ts
// api-client.ts
import {
  emitSessionExpired,
  refreshSession,
} from "@/core/identity/fetcher";

const SDK_RETRY_ELIGIBLE = (init?: RequestInit): boolean => {
  // SSE streaming requests carry accept: text/event-stream. Retrying them is
  // unsafe (loses partial frames). Defer to onError + the modal flow.
  const accept = String(init?.headers?.["accept" as never] ?? "");
  return !accept.includes("text/event-stream");
};

async function sdkFetchWithRefresh(
  input: Parameters<typeof fetch>[0],
  init?: Parameters<typeof fetch>[1],
): ReturnType<typeof fetch> {
  const resp = await fetch(input, init);
  if (resp.status !== 401 || !SDK_RETRY_ELIGIBLE(init)) return resp;

  const refreshed = await refreshSession();
  if (!refreshed) {
    emitSessionExpired();
    return resp; // surface the original 401 to the SDK's error handling
  }
  // Retry once. If retry still 401, signal session-expired.
  const retry = await fetch(input, init);
  if (retry.status === 401) emitSessionExpired();
  return retry;
}

function createCompatibleClient(isMock?: boolean): LangGraphClient {
  const client = new LangGraphClient({
    apiUrl: getLangGraphBaseURL(isMock),
    callerOptions: { fetch: sdkFetchWithRefresh },
  });
  // existing runs.stream/joinStream wrapping stays as-is
  // ...
  return client;
}
```

### Why this design

| Property | Mechanism |
|---|---|
| 401 retry coverage | SDK's `AsyncCaller` calls `callerOptions.fetch` for every backend request internally — `threads.search`, `threads.delete`, `threads.update`, `runs.create`, `runs.wait`, etc. |
| Streaming exclusion | `accept: text/event-stream` heuristic; SSE replay is intentionally not attempted |
| Singleflight with `identityFetch` | both layers call the same `refreshSession()` module-scope state |
| No global side effects | only the fetch passed to `LangGraphClient` is wrapped; `globalThis.fetch` untouched |
| Aligns with existing modal flow | `emitSessionExpired()` is the same emit `identityFetch` uses |

## Contract delta

| Scenario | Before | After |
|---|---|---|
| `client.threads.search` mid-session, token just expired | 401 propagates to caller, often surfaces as broken UI | refreshes, retries, returns 200 |
| `client.runs.stream` 401 | onError fires, toast | onError still fires, but **also** triggers `emitSessionExpired` if the cause is auth (consistent UX) |
| `client.runs.wait` 401 (Slack/Telegram channels) | hard error | refresh + retry |
| Concurrent 401s from `useIdentity()` + `client.threads.search` | two refresh calls (today: only one — identityFetch's; SDK was unrefreshed) | exactly one refresh call (singleflight) |
| Refresh itself returns 401 | `identityFetch` emits modal; SDK silently fails | both emit modal — single source of truth |

## Test plan

### New unit tests (`api-client.test.ts`)

```ts
describe("getAPIClient — sdk fetch transport", () => {
  it("retries non-streaming SDK calls once after a successful refresh", async () => {
    // mock global fetch:
    //   1st call to /api/langgraph/threads/search → 401
    //   call to /api/auth/refresh → 200
    //   retry of /api/langgraph/threads/search → 200
    // assert: getAPIClient().threads.search() resolves to the 200 body
    // assert: refresh was called exactly once
  });

  it("does not retry SSE/streaming requests on 401", async () => {
    // mock global fetch:
    //   /api/langgraph/runs/stream with accept: text/event-stream → 401
    // assert: refresh NOT called, response is the original 401
  });

  it("emits session-expired when refresh itself returns 401", async () => {
    // assert: onSessionExpired listener fires once
  });

  it("singleflight: 5 concurrent 401s issue exactly one refresh", async () => {
    // assert: refresh fetch invoked exactly once across all 5 retries
  });
});
```

Mock harness uses `vi.fn()` over `globalThis.fetch` (Vitest), restored in
`afterEach`.

### Existing test suites

- `fetcher.test.ts` (9 vitest in scope A) must remain green.
- `useThreadStream` tests (if any) must remain green — `onError` contract
  unchanged.
- `pnpm check` (lint + typecheck) green.

### Manual smoke (acceptance criterion)

After Issue ① ships **and** this Issue ②, do:

1. Log in. Wait 16 min idle (let JWT expire while cookie remains).
2. Submit a chat message.
3. **Pass**: message goes through, no toast, no modal. Network panel shows
   `/api/langgraph/...` 401 → `/api/auth/refresh` 200 → `/api/langgraph/...`
   200 retry.
4. **Fail (regression of bug)**: toast / broken UI / modal pops because of
   transient 401.

This 17-minute test is the only way to exercise the full path; it does not
need to run in CI.

## Definition of Done

- [ ] `refreshSession` exported from `fetcher.ts` (no longer alias-only)
- [ ] `getAPIClient()` passes `callerOptions: { fetch: sdkFetchWithRefresh }`
- [ ] `sdkFetchWithRefresh` skips retry on `accept: text/event-stream`
- [ ] 4 new vitest cases pass
- [ ] `fetcher.test.ts` (9 cases) still green
- [ ] `pnpm check` green
- [ ] Manual 17-min idle smoke captured in PR description
- [ ] Commit message references this spec path

## Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| SDK 1.6.0 ignores `callerOptions.fetch` for some code path | low | partial coverage | type contract is explicit ([async_caller.d.ts:20](../../../frontend/node_modules/@langchain/langgraph-sdk/dist/utils/async_caller.d.ts#L20)); test asserts actual fetch routing |
| SSE detection via `accept` header fails (request lacks header) | medium | streaming retry triggers, possibly duplicating SSE messages | fallback heuristic: also skip retry when URL contains `/runs/stream` or `/runs/join` (hard-coded path check, additive) |
| `refreshSession` export breaks tree-shaking | low | bundle size +200 B | accept; the function is called from prod paths |
| Future SDK upgrade renames `callerOptions` | medium | silent regression | a dedicated test asserts the wrapper is invoked at least once during `client.threads.search()` |

## Rollback

Revert the `api-client.ts` change. The `fetcher.ts` rename of an export does
not break any caller (the `_refreshSessionForIdentityApi` alias stays). Single
file, fully reversible.

## Dependency on Issue ①

Independent. Either order ships fine:

- ② before ①: SDK 401 retry works, but cookie still self-deletes at 15 min;
  long-idle users get a hard reload anyway.
- ① before ②: long-idle covered, but SDK calls during a token-rollover window
  (rare but real, e.g., reconnect after 16 min idle) still surface 401s.
- ① and ② together: complete coverage.

Recommend shipping ② **after** ① so the manual smoke (17-min idle) actually
exercises the SDK retry path rather than the modal-due-to-cookie-gone path.

## References

- Prior interceptor scope-A spec:
  `archive/2026-04-28-session-refresh-interceptor-design.md`
- Browser-validated reproduction: this conversation, 2026-05-02
- LangGraph SDK fetch hook contract:
  `frontend/node_modules/@langchain/langgraph-sdk/dist/utils/async_caller.d.ts`
