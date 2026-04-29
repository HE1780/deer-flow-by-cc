// frontend/tests/unit/core/identity/fetcher.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  consumeSessionExpired,
  identityFetch,
  onSessionExpired,
  resetSessionExpiredListeners,
} from "@/core/identity/fetcher";

/** Build a fetch mock that returns a different response per matched (url+method)
 *  call, with a fallthrough error if anything unexpected hits it. Each entry's
 *  responses array is consumed in order. */
function makeSequencedFetchMock(
  routes: Record<string, Response[]>,
): ReturnType<typeof vi.fn> {
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
      throw new Error(`fetch route exhausted: ${key} (only ${queue.length} responses defined)`);
    }
    cursors[key] = idx + 1;
    // Response objects can only be read once. Each slot in the routes array is a
    // distinct new Response(...), so returning it directly is safe — it will be
    // consumed exactly once by the caller.
    return resp;
  });
}

describe("identityFetch", () => {
  afterEach(() => {
    resetSessionExpiredListeners();
    vi.restoreAllMocks();
  });

  it("forwards credentials and parses JSON on 200", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ hello: "world" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await identityFetch<{ hello: string }>("/api/me");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/me",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(result).toEqual({ hello: "world" });
  });

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

  it("throws forbidden error on 403 with missing permission", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: { missing: "tenant:read" } }), {
        status: 403,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(identityFetch("/api/admin/tenants")).rejects.toMatchObject({
      kind: "forbidden",
      missing: "tenant:read",
    });
  });

  it("throws network error on 500", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("boom", { status: 500 }),
    );

    await expect(identityFetch("/api/me")).rejects.toMatchObject({
      kind: "network",
      status: 500,
    });
  });

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
    expect(results.map((r) => r.i).sort((a, b) => a - b)).toEqual([0, 1, 2, 3, 4]);
    expect(listener).not.toHaveBeenCalled();

    // Specifically: refresh URL was hit exactly once.
    const refreshCalls = mock.mock.calls.filter(
      ([url, init]) =>
        (typeof url === "string" ? url : url.toString()) ===
          "/api/auth/refresh" && (init?.method ?? "GET") === "POST",
    );
    expect(refreshCalls).toHaveLength(1);
  });

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
});
