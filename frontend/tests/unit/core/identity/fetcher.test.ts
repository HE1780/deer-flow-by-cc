// frontend/tests/unit/core/identity/fetcher.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  consumeSessionExpired,
  identityFetch,
  onSessionExpired,
  resetSessionExpiredListeners,
} from "@/core/identity/fetcher";

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

  it("throws and emits session-expired event on 401", async () => {
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

  it("coalesces repeated 401 events until consumed", async () => {
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
});
