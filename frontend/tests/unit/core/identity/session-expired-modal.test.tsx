import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionExpiredModal } from "@/core/identity/components/SessionExpiredModal";
import { consumeSessionExpired, identityFetch, resetSessionExpiredListeners } from "@/core/identity/fetcher";

const pathnameMock = vi.fn(() => "/login");

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameMock(),
}));

describe("<SessionExpiredModal>", () => {
  afterEach(() => {
    consumeSessionExpired();
    resetSessionExpiredListeners();
    vi.restoreAllMocks();
  });

  it("suppresses session-expired modal on /login even when a 401 occurs", async () => {
    pathnameMock.mockReturnValue("/login");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 401 }));

    render(<SessionExpiredModal />);
    await expect(identityFetch("/api/me")).rejects.toMatchObject({
      kind: "unauthenticated",
    });

    await waitFor(() =>
      expect(screen.queryByText("Session expired")).toBeNull(),
    );
  });
});
