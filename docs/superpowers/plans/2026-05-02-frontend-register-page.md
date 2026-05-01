# Frontend Register Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the public `/register` page that consumes backend `POST /api/auth/register`, completing the registration-code onboarding loop end-to-end.

**Architecture:** New Next.js page under `app/(public)/register/`, mirroring the existing `/login` style and conventions (raw `fetch` for auth submission, English copy, public route group). Five render phases (`loading_me / already_logged_in / no_code / ready / submitting`) gate the form. Pre-fetch `/api/me` to short-circuit logged-in users. Errors split between field-inline (422 password / 422 email / 409 email-exists) and a single top banner (404 invalid code, 410 expired, 5xx network) — no toast (Toaster is not mounted in root layout, only in `workspace/`).

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript 5.8, Tailwind 4, TanStack Query (already wired in root providers), `@testing-library/react` + Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-05-01-frontend-register-page-design.md`

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `frontend/src/core/identity/types.ts` | modify | Add `RegisterWithCodePayload` + `RegisterWithCodeResponse` types |
| `frontend/src/core/identity/api.ts` | modify | Add `identityApi.registerWithCode()` |
| `frontend/src/app/(public)/register/page.tsx` | create | Page + state machine + form |
| `frontend/tests/unit/app/register-page.test.tsx` | create | 8 vitest unit cases |
| `frontend/tests/e2e/identity/A1-register.spec.ts` | create | 1 Playwright happy-path |

`page.tsx` is one file with three internal components (`RegisterPage`, `AlreadyLoggedInBlock`, `NoCodeBlock`, `RegisterForm`) + `submitRegister()` helper. Keeping them co-located mirrors `login/page.tsx` and avoids over-decomposing a single-feature page.

---

## Branch & Commit Convention

- All work on a feature branch off `cc-main`: `feat/frontend-register-page`
- Each task ends with a commit; final task merges to `cc-main` and pushes
- Per `frontend/CLAUDE.md`: pass lint + typecheck + test before each commit

---

## Task 1: Types

**Files:**
- Modify: `frontend/src/core/identity/types.ts`

- [ ] **Step 1: Append new payload + response types**

Open `frontend/src/core/identity/types.ts`, append at the very end of the file (after the last `OrgKey*` block):

```ts
// ---------------------------------------------------------------------------
// Public registration (P1 — see docs/superpowers/specs/archive/2026-04-29-registration-code-design.md)
// ---------------------------------------------------------------------------

export interface RegisterWithCodePayload {
  code: string;
  email: string;
  password: string;
  display_name?: string;
}

export interface RegisterWithCodeResponse {
  status: "ok";
  email: string;
}
```

- [ ] **Step 2: Typecheck**

Run from `frontend/`:
```bash
pnpm typecheck
```
Expected: clean (no new errors).

- [ ] **Step 3: Commit**

```bash
git checkout -b feat/frontend-register-page
git add frontend/src/core/identity/types.ts
git commit -m "$(cat <<'EOF'
feat(identity): add RegisterWithCode types for /register page

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: API client method

**Files:**
- Modify: `frontend/src/core/identity/api.ts`

- [ ] **Step 1: Add type imports**

In `frontend/src/core/identity/api.ts`, find the existing import block from `./types` (starts with `import { ... } from "./types";`). Insert these two type names alphabetically:

```ts
  type RegisterWithCodePayload,
  type RegisterWithCodeResponse,
```

So the existing block stays alphabetized.

- [ ] **Step 2: Add the method to `identityApi`**

In the same file, locate `adminSetPassword` (it's the last method in the `// PATCH /api/me — update own display_name + avatar_url` block). Immediately after that method's closing brace, before the next blank line / `// --- A4` comment, add:

```ts
  // Public self-service registration via tenant_owner-issued one-time code.
  // Sets the deerflow_session cookie on success (Set-Cookie from backend).
  // Note: not used by the /register page form itself (which uses raw fetch
  // to keep the response shape inspectable for field-vs-banner error
  // routing); exported for future programmatic callers.
  registerWithCode: (payload: RegisterWithCodePayload) =>
    identityFetch<RegisterWithCodeResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
```

- [ ] **Step 3: Typecheck**

```bash
pnpm typecheck
```
Expected: clean.

- [ ] **Step 4: Lint**

```bash
pnpm lint
```
Expected: clean (or only pre-existing warnings; no new ones from the edited file).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/identity/api.ts
git commit -m "$(cat <<'EOF'
feat(identity): add identityApi.registerWithCode

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Page scaffold + no-code branch (red test first)

**Files:**
- Create: `frontend/src/app/(public)/register/page.tsx`
- Create: `frontend/tests/unit/app/register-page.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/app/register-page.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm test register-page
```
Expected: FAIL — module `@/app/(public)/register/page` does not exist.

- [ ] **Step 3: Create the page with the no-code branch only**

Create `frontend/src/app/(public)/register/page.tsx`:

```tsx
// frontend/src/app/(public)/register/page.tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import React from "react";

import { identityApi } from "@/core/identity/api";
import { identityKeys } from "@/core/identity/query-keys";
import { type MeResponse } from "@/core/identity/types";

function NoCodeBlock() {
  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-2xl font-semibold tracking-tight">Create account</h1>
      <div
        role="alert"
        className="w-full rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
      >
        Invalid invitation link — this page must be opened via the link your
        administrator sent you.
      </div>
    </main>
  );
}

function LoadingShell() {
  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col items-center justify-center gap-6 p-8">
      <p className="text-muted-foreground">Loading…</p>
    </main>
  );
}

export default function RegisterPage() {
  const params = useSearchParams();
  const router = useRouter();
  const code = params.get("code") ?? "";

  const meQuery = useQuery<MeResponse>({
    queryKey: identityKeys.me(),
    queryFn: identityApi.me,
    retry: false,
  });

  if (meQuery.isLoading) return <LoadingShell />;
  // Already-logged-in branch is added in Task 4.
  if (!code) return <NoCodeBlock />;

  // Form branch is added in Task 5.
  return <LoadingShell />;
  // (router used in later tasks; reference here to satisfy the linter)
  void router;
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pnpm test register-page
```
Expected: PASS (1 test).

- [ ] **Step 5: Typecheck + lint**

```bash
pnpm typecheck && pnpm lint
```
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/\(public\)/register/page.tsx frontend/tests/unit/app/register-page.test.tsx
git commit -m "$(cat <<'EOF'
feat(register): page scaffold with no-code branch

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Already-logged-in branch

**Files:**
- Modify: `frontend/src/app/(public)/register/page.tsx`
- Modify: `frontend/tests/unit/app/register-page.test.tsx`

- [ ] **Step 1: Append failing test**

In `frontend/tests/unit/app/register-page.test.tsx`, append a new `it` block inside the existing `describe`:

```tsx
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

    expect(
      await screen.findByText(/you are signed in as demo@example\.com/i),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /sign out/i }),
    ).toBeTruthy();
    // The form must NOT render in this state.
    expect(screen.queryByLabelText(/^password$/i)).toBeNull();
  });
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pnpm test register-page
```
Expected: NEW test fails — "you are signed in" copy not found.

- [ ] **Step 3: Implement `AlreadyLoggedInBlock` and wire the branch**

In `frontend/src/app/(public)/register/page.tsx`:

a) Add this component just below `NoCodeBlock`:

```tsx
function AlreadyLoggedInBlock({ me }: { me: MeResponse }) {
  const [signingOut, setSigningOut] = React.useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await identityApi.logout();
      // Force a full reload so cookies + react-query state are fully reset.
      // The user lands back on this same URL (with ?code=...) unauthenticated.
      window.location.reload();
    } catch {
      setSigningOut(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-2xl font-semibold tracking-tight">Create account</h1>
      <p className="text-sm text-muted-foreground">
        You are signed in as{" "}
        <span className="font-medium text-foreground">
          {me.email ?? "(unknown)"}
        </span>
        . Sign out first if you want to register a new account.
      </p>
      <button
        type="button"
        onClick={handleSignOut}
        disabled={signingOut}
        className="inline-flex w-full items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {signingOut ? "Signing out…" : "Sign out"}
      </button>
    </main>
  );
}
```

b) Replace the `// Already-logged-in branch is added in Task 4.` comment + the `if (!code)` line with:

```tsx
  if (meQuery.data?.user_id) return <AlreadyLoggedInBlock me={meQuery.data} />;
  if (!code) return <NoCodeBlock />;
```

- [ ] **Step 4: Run tests**

```bash
pnpm test register-page
```
Expected: 2/2 PASS.

- [ ] **Step 5: Typecheck + lint**

```bash
pnpm typecheck && pnpm lint
```
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/\(public\)/register/page.tsx frontend/tests/unit/app/register-page.test.tsx
git commit -m "$(cat <<'EOF'
feat(register): already-logged-in branch with sign-out

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Form + happy path

**Files:**
- Modify: `frontend/src/app/(public)/register/page.tsx`
- Modify: `frontend/tests/unit/app/register-page.test.tsx`

- [ ] **Step 1: Append failing test for happy path**

In `frontend/tests/unit/app/register-page.test.tsx`, add a `fetch` mock at module level (just below the `meMock` setup, before `function renderWithClient`):

```tsx
const fetchMock = vi.fn();
beforeAll(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  fetchMock.mockReset();
});
```

Also add `beforeAll, afterEach` to the imports from `vitest`:

```tsx
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
```

Then append this `it` block inside the `describe`:

```tsx
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
```

Add `@testing-library/user-event` to `package.json` if not already present:

```bash
cd frontend && pnpm list @testing-library/user-event 2>&1 | head -5
```

If absent (no version line printed), install:
```bash
pnpm add -D @testing-library/user-event
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pnpm test register-page
```
Expected: the new test fails — form not rendered, button not found.

- [ ] **Step 3: Implement `submitRegister` helper + `RegisterForm`**

In `frontend/src/app/(public)/register/page.tsx`, add right after the `import` block (before `function NoCodeBlock`):

```tsx
type SubmitOutcome =
  | { ok: true }
  | { ok: false; kind: "field"; field: "email" | "password"; msg: string }
  | { ok: false; kind: "banner"; msg: string };

interface RegisterPayload {
  code: string;
  email: string;
  password: string;
  display_name?: string;
}

async function submitRegister(payload: RegisterPayload): Promise<SubmitOutcome> {
  let res: Response;
  try {
    res = await fetch("/api/auth/register", {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    return {
      ok: false,
      kind: "banner",
      msg: "Could not reach the registration service. Please try again later.",
    };
  }
  if (res.ok) return { ok: true };

  const body = await res.json().catch(() => ({}));
  const detail = (body as { detail?: unknown }).detail;
  const detailStr = typeof detail === "string" ? detail.toLowerCase() : "";

  if (res.status === 422) {
    if (detailStr.includes("password")) {
      return {
        ok: false,
        kind: "field",
        field: "password",
        msg: "Password must be at least 8 characters",
      };
    }
    if (detailStr.includes("email")) {
      return {
        ok: false,
        kind: "field",
        field: "email",
        msg: "Please enter a valid email address",
      };
    }
    return { ok: false, kind: "field", field: "email", msg: "Invalid input" };
  }
  if (res.status === 404) {
    return {
      ok: false,
      kind: "banner",
      msg: "This invitation link is invalid or has been used.",
    };
  }
  if (res.status === 410) {
    return {
      ok: false,
      kind: "banner",
      msg: "This invitation link has expired. Please request a new one.",
    };
  }
  if (res.status === 409) {
    return {
      ok: false,
      kind: "field",
      field: "email",
      msg: "An account with this email already exists",
    };
  }
  return {
    ok: false,
    kind: "banner",
    msg: `Registration failed (${res.status}), please try again later`,
  };
}
```

Then append the form component below `AlreadyLoggedInBlock`:

```tsx
function RegisterForm({
  code,
  onSuccess,
}: {
  code: string;
  onSuccess: () => void;
}) {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [bannerError, setBannerError] = React.useState<string | null>(null);
  const [emailError, setEmailError] = React.useState<string | null>(null);
  const [passwordError, setPasswordError] = React.useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setBannerError(null);
    setEmailError(null);
    setPasswordError(null);
    const outcome = await submitRegister({
      code,
      email,
      password,
      display_name: displayName.trim() || undefined,
    });
    setSubmitting(false);
    if (outcome.ok) {
      onSuccess();
      return;
    }
    if (outcome.kind === "banner") setBannerError(outcome.msg);
    else if (outcome.field === "email") setEmailError(outcome.msg);
    else setPasswordError(outcome.msg);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-2xl font-semibold tracking-tight">Create account</h1>

      {bannerError && (
        <div
          role="alert"
          className="w-full rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
        >
          {bannerError}
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex w-full flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="email" className="text-sm font-medium">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder="you@example.com"
          />
          {emailError && (
            <p role="alert" className="text-sm text-destructive">
              {emailError}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="password" className="text-sm font-medium">
            Password
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              required
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 pr-16 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="At least 8 characters"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground hover:text-foreground"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
          {passwordError && (
            <p role="alert" className="text-sm text-destructive">
              {passwordError}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="display_name" className="text-sm font-medium">
            Display name <span className="text-muted-foreground">(optional)</span>
          </label>
          <input
            id="display_name"
            type="text"
            autoComplete="nickname"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder="defaults to email prefix"
          />
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex w-full items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
    </main>
  );
}
```

Then in `RegisterPage`, replace the trailing `return <LoadingShell />;` + `void router;` with:

```tsx
  return <RegisterForm code={code} onSuccess={() => router.push("/")} />;
```

- [ ] **Step 4: Run tests to verify happy path passes**

```bash
pnpm test register-page
```
Expected: 3/3 PASS.

- [ ] **Step 5: Typecheck + lint**

```bash
pnpm typecheck && pnpm lint
```
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/\(public\)/register/page.tsx frontend/tests/unit/app/register-page.test.tsx frontend/package.json frontend/pnpm-lock.yaml
git commit -m "$(cat <<'EOF'
feat(register): form + happy-path submission

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(If `pnpm-lock.yaml` was not modified — i.e. user-event was already installed — drop it from the `add`.)

---

## Task 6: Error-state tests (422 password, 404, 409)

**Files:**
- Modify: `frontend/tests/unit/app/register-page.test.tsx`

- [ ] **Step 1: Add three failing-then-passing tests**

In the existing `describe`, append:

```tsx
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
```

- [ ] **Step 2: Run tests**

```bash
pnpm test register-page
```
Expected: 6/6 PASS (all error routing already implemented in Task 5).

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/unit/app/register-page.test.tsx
git commit -m "$(cat <<'EOF'
test(register): cover 422 password / 404 / 409 error routing

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Show/hide password test

**Files:**
- Modify: `frontend/tests/unit/app/register-page.test.tsx`

- [ ] **Step 1: Append test**

```tsx
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
```

- [ ] **Step 2: Run tests**

```bash
pnpm test register-page
```
Expected: 7/7 PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/unit/app/register-page.test.tsx
git commit -m "$(cat <<'EOF'
test(register): cover password show/hide toggle

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Loading state test (8th vitest case from spec)

**Files:**
- Modify: `frontend/tests/unit/app/register-page.test.tsx`

- [ ] **Step 1: Append test**

```tsx
  it("renders loading state while /api/me is in flight", async () => {
    // Never-resolving promise simulates pending /api/me
    meMock.mockReturnValue(new Promise(() => {}));
    renderWithClient();

    expect(await screen.findByText(/^loading…$/i)).toBeTruthy();
    // No form, no banner — just the loading shell.
    expect(screen.queryByLabelText(/^email$/i)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
```

- [ ] **Step 2: Run tests**

```bash
pnpm test register-page
```
Expected: 8/8 PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/unit/app/register-page.test.tsx
git commit -m "$(cat <<'EOF'
test(register): cover loading_me phase

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Playwright E2E happy path

**Files:**
- Create: `frontend/tests/e2e/identity/A1-register.spec.ts`

- [ ] **Step 1: Write the spec**

```ts
// frontend/tests/e2e/identity/A1-register.spec.ts
import { expect, test, type Route } from "@playwright/test";

import { mockIdentity } from "./fixtures/mock-backend";

test.describe("A1: register page", () => {
  test("happy path: filling form posts /api/auth/register and lands on /", async ({
    page,
  }) => {
    // Unauthenticated /api/me + providers + logout already mocked here.
    await mockIdentity(page, { authenticated: false });

    let registerCalls = 0;
    await page.route("**/api/auth/register", (route: Route) => {
      registerCalls += 1;
      const body = route.request().postDataJSON() as {
        code?: string;
        email?: string;
        password?: string;
      };
      expect(body.code).toBe("test12345abcdef");
      expect(body.email).toBe("new@example.com");
      expect(body.password).toBe("longenoughpw");
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok", email: "new@example.com" }),
      });
    });

    // Mock the post-success destination so we don't trigger real /api/me etc.
    await page.route("**/", (route: Route) => {
      if (route.request().resourceType() !== "document") return route.continue();
      return route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body><h1 id='landed'>landed</h1></body></html>",
      });
    });

    await page.goto("/register?code=test12345abcdef");

    await page.getByLabel(/^email$/i).fill("new@example.com");
    await page.getByLabel(/^password$/i).fill("longenoughpw");
    await page.getByRole("button", { name: /create account/i }).click();

    await page.waitForURL("**/");
    expect(registerCalls).toBe(1);
  });

  test("shows red banner when URL has no code", async ({ page }) => {
    await mockIdentity(page, { authenticated: false });
    await page.goto("/register");
    await expect(
      page.getByRole("alert").filter({ hasText: /invalid invitation link/i }),
    ).toBeVisible();
  });
});
```

- [ ] **Step 2: Run e2e**

```bash
cd frontend && pnpm test:e2e -- A1-register
```
Expected: 2/2 PASS.

(If this is the first e2e run on a clean checkout it will need `pnpm exec playwright install chromium`; the playwright config already builds + serves.)

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/identity/A1-register.spec.ts
git commit -m "$(cat <<'EOF'
test(register): playwright happy-path + no-code banner e2e

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Final verification + merge to cc-main

- [ ] **Step 1: Full local check**

```bash
cd frontend && pnpm check && pnpm test
```
Expected: lint clean, typecheck clean, all unit tests pass.

- [ ] **Step 2: Build (catches Next.js / RSC compile errors that lint misses)**

```bash
pnpm build
```
Expected: build succeeds.

- [ ] **Step 3: Manual smoke (optional but recommended)**

```bash
pnpm dev
```

Open `http://localhost:3110/register?code=fakecode123`. Confirm:
- Form renders, all three inputs visible, Show/Hide button toggles password type
- Submit fails (real backend not in mock) — banner appears
- Open `/register` (no code) — red banner, no form

Stop dev server.

- [ ] **Step 4: Merge to `cc-main` and push**

```bash
git checkout cc-main
git merge --no-ff feat/frontend-register-page -m "merge: frontend register page (8 vitest + 2 playwright)"
git push origin cc-main
```

- [ ] **Step 5: Archive the spec**

```bash
git mv docs/superpowers/specs/2026-05-01-frontend-register-page-design.md docs/superpowers/specs/archive/
git mv docs/superpowers/plans/2026-05-02-frontend-register-page.md docs/superpowers/plans/archive/
git commit -m "docs(register): archive shipped spec + plan"
git push origin cc-main
```

- [ ] **Step 6: Update memo**

Update `memo/memo.md` "Top 3 待办" by removing the register page item if present, and add a short "✅ 已闭环" line referencing the merge commit.

---

## Self-Review Notes

**Spec coverage check (against `2026-05-01-frontend-register-page-design.md`):**

- §3 main path → Task 5 (form + happy path) + Task 9 (e2e)
- §3 no-code branch → Task 3 (page scaffold) + Task 9 e2e case 2
- §3 already-logged-in branch → Task 4
- §3 422 password → Task 6 case 1
- §3 422 email → covered by error-routing code in Task 5; not a separate test (low ROI; same code path as 422 password)
- §3 404 → Task 6 case 2
- §3 410 → covered by code in Task 5; no separate test (same banner code path as 404 — adequate coverage)
- §3 409 email → Task 6 case 3
- §3 5xx → covered by code in Task 5 (banner); no separate test
- §5 state machine → exercised across Tasks 3, 4, 5, 8
- §6 raw fetch (not identityFetch) → enforced in Task 5 step 3
- §7 error routing → Task 5 step 3
- §8 form UX details → Task 5 step 3 (full markup including show/hide), Task 7 toggle test
- §10.1 8 vitest cases → Tasks 3, 4, 5, 6 (×3), 7, 8 = 8 ✓
- §10.2 1 e2e happy path → Task 9 (one test; second test for no-code banner is a bonus, kept because it's near-zero cost)

**Placeholder scan:** None of the steps contain "TODO", "TBD", "appropriate", "as needed". Every code block is complete.

**Type consistency:** `RegisterWithCodePayload` (Task 1) is exported from `types.ts` and consumed by `api.ts` (Task 2). The page itself uses a local `RegisterPayload` interface (Task 5) instead — this is intentional, because the page submits via raw `fetch`, not via the typed `identityApi` method, and the local type avoids the page importing a domain type just to immediately stringify it. Names match across all tasks.
