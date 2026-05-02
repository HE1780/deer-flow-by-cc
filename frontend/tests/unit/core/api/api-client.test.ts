// frontend/tests/unit/core/api/api-client.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
      "POST http://localhost:3000/api/langgraph-compat/threads/search": [
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
      "POST http://localhost:3000/api/langgraph-compat/threads/abc/runs/stream": [
        empty(401),
      ],
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
            : input.url),
    );
    expect(calls.find((u) => u.includes("/api/auth/refresh"))).toBeUndefined();
  });

  it("retries runs.join (non-streaming /join URL) on 401 — must NOT be classified as SSE", async () => {
    // runs.join URL is /threads/{tid}/runs/{rid}/join — it contains the
    // substring `/runs/` and an `/join` segment but is NOT streaming.
    // Earlier impl mistakenly matched `/runs/join` as streaming, which
    // would skip refresh-and-retry on a token-rollover during a blocking
    // wait. Defends against re-introducing that classification bug.
    const mock = makeSequencedFetchMock({
      "GET http://localhost:3000/api/langgraph-compat/threads/abc/runs/xyz/join": [
        empty(401),
        json(200, { run_id: "xyz", status: "success" }),
      ],
      "POST /api/auth/refresh": [json(200, { ok: true })],
    });
    vi.stubGlobal("fetch", mock);

    const { getAPIClient } = await import("@/core/api/api-client");
    const result = await getAPIClient().runs.join("abc", "xyz");

    expect(result).toEqual({ run_id: "xyz", status: "success" });
    // Original 401 + refresh + retry = 3 calls (the proof that runs.join
    // went through the refresh-and-retry path, not classified as SSE).
    expect(mock).toHaveBeenCalledTimes(3);
  });

  it("emits session-expired when refresh itself returns 401", async () => {
    const mock = makeSequencedFetchMock({
      "POST http://localhost:3000/api/langgraph-compat/threads/search": [empty(401)],
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
      "POST http://localhost:3000/api/langgraph-compat/threads/search": [
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
            : input.url;
      return url.includes("/api/auth/refresh");
    });
    expect(refreshCalls.length).toBe(1);
  });
});
