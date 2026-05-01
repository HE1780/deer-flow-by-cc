import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
});
