// frontend/src/app/(public)/register/page.tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import React from "react";

import { identityApi } from "@/core/identity/api";
import { identityKeys } from "@/core/identity/query-keys";
import { type MeResponse } from "@/core/identity/types";

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
  if (meQuery.data?.user_id) return <AlreadyLoggedInBlock me={meQuery.data} />;
  if (!code) return <NoCodeBlock />;

  return <RegisterForm code={code} onSuccess={() => router.push("/")} />;
}
