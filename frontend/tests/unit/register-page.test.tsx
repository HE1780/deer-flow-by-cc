import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RegisterPage from "@/app/(public)/register/page";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => mockSearchParams,
}));

let mockSearchParams = new URLSearchParams();

const meMock = vi.fn();
vi.mock("@/core/identity/api", () => ({
  identityApi: {
    me: () => meMock(),
    logout: () => Promise.resolve({ status: "ok" }),
  },
}));

function renderWithClient() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <RegisterPage />
    </QueryClientProvider>,
  );
}

describe("RegisterPage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    mockSearchParams = new URLSearchParams();
    pushMock.mockReset();
    meMock.mockReset();
  });

  it("shows red banner and no form when URL has no ?code=", async () => {
    meMock.mockRejectedValue(new Error("401"));
    renderWithClient();

    // wait for /api/me query to settle
    await screen.findByRole("alert");

    expect(
      screen.getByRole("alert").textContent?.toLowerCase(),
    ).toMatch(/invalid invitation link/);
    expect(screen.queryByLabelText(/email/i)).toBeNull();
  });

  it("shows already-signed-in block with sign-out button when /api/me returns a user", async () => {
    meMock.mockResolvedValue({
      user_id: 42,
      email: "demo@example.com",
      display_name: "Demo",
      avatar_url: null,
      active_tenant_id: 1,
      tenants: [{ id: 1, slug: "default", name: "Default" }],
      workspaces: [],
      permissions: [],
      roles: {},
    });

    renderWithClient();

    // Wait until the sign-out button appears (query settled), then check the
    // surrounding paragraph text (split across a <span>).
    const btn = await screen.findByRole("button", { name: /sign out/i });
    const paragraph = btn.closest("main")?.querySelector("p");
    expect(paragraph?.textContent?.toLowerCase()).toMatch(
      /you are signed in as demo@example\.com/,
    );
    expect(
      screen.getByRole("button", { name: /sign out/i }),
    ).toBeTruthy();
    // The form must NOT render in this state.
    expect(screen.queryByLabelText(/^password$/i)).toBeNull();
  });
});
