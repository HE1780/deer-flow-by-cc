import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { useToolGroups } from "@/core/agents/hooks";

function wrapper({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useToolGroups", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the tool_groups from the API response", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tool_groups: [{ name: "search" }, { name: "python" }] }),
    });

    const { result } = renderHook(() => useToolGroups(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.toolGroups).toEqual([
      { name: "search" },
      { name: "python" },
    ]);
  });

  it("surfaces errors", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      statusText: "Forbidden",
    });

    const { result } = renderHook(() => useToolGroups(), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.toolGroups).toEqual([]);
  });
});
