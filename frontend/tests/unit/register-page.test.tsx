import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

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

const fetchMock = vi.fn();
beforeAll(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  fetchMock.mockReset();
});

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

  it("submits form on happy path and navigates to /", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    mockSearchParams = new URLSearchParams("code=invitex123");
    meMock.mockRejectedValue(new Error("401"));
    fetchMock.mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ status: "ok", email: "new@example.com" }),
    });

    renderWithClient();

    const email = await screen.findByLabelText(/^email$/i);
    const password = screen.getByLabelText(/^password$/i);

    await user.type(email, "new@example.com");
    await user.type(password, "longenoughpw");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/register",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: expect.stringContaining("invitex123"),
      }),
    );
    expect(pushMock).toHaveBeenCalledWith("/");
  });

  it("shows password field error on 422 with 'password' in detail", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    mockSearchParams = new URLSearchParams("code=invitex123");
    meMock.mockRejectedValue(new Error("401"));
    fetchMock.mockResolvedValue({
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: "password must be at least 8 characters" }),
    });

    renderWithClient();

    await user.type(await screen.findByLabelText(/^email$/i), "x@y.com");
    await user.type(screen.getByLabelText(/^password$/i), "short");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(
      await screen.findByText(/password must be at least 8 characters/i),
    ).toBeTruthy();
    // No banner.
    expect(screen.queryAllByRole("alert").length).toBe(1); // only the field-level alert
  });

  it("shows banner on 404 (invalid code)", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    mockSearchParams = new URLSearchParams("code=invitex123");
    meMock.mockRejectedValue(new Error("401"));
    fetchMock.mockResolvedValue({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ detail: "invalid registration code" }),
    });

    renderWithClient();
    await user.type(await screen.findByLabelText(/^email$/i), "x@y.com");
    await user.type(screen.getByLabelText(/^password$/i), "longenoughpw");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(
      await screen.findByText(/invitation link is invalid or has been used/i),
    ).toBeTruthy();
  });

  it("shows email field error on 409 (email exists)", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    mockSearchParams = new URLSearchParams("code=invitex123");
    meMock.mockRejectedValue(new Error("401"));
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: () => Promise.resolve({ detail: "email already registered" }),
    });

    renderWithClient();
    await user.type(await screen.findByLabelText(/^email$/i), "dup@y.com");
    await user.type(screen.getByLabelText(/^password$/i), "longenoughpw");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(
      await screen.findByText(/account with this email already exists/i),
    ).toBeTruthy();
  });

  it("toggles password visibility when Show/Hide button is clicked", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    mockSearchParams = new URLSearchParams("code=invitex123");
    meMock.mockRejectedValue(new Error("401"));

    renderWithClient();

    const password = await screen.findByLabelText(/^password$/i);
    expect(password.getAttribute("type")).toBe("password");

    await user.click(screen.getByRole("button", { name: /show password/i }));
    expect(password.getAttribute("type")).toBe("text");

    await user.click(screen.getByRole("button", { name: /hide password/i }));
    expect(password.getAttribute("type")).toBe("password");
  });

  it("renders loading state while /api/me is in flight", async () => {
    // Never-resolving promise simulates pending /api/me
    meMock.mockReturnValue(new Promise((_resolve) => { /* intentionally never resolves */ }));
    renderWithClient();

    expect(await screen.findByText(/^loading…$/i)).toBeTruthy();
    // No form, no banner — just the loading shell.
    expect(screen.queryByLabelText(/^email$/i)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
