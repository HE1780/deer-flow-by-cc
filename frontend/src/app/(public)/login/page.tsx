// frontend/src/app/(public)/login/page.tsx
"use client";

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";

import { identityApi } from "@/core/identity/api";
import { identityKeys } from "@/core/identity/query-keys";
import { type AuthProvider } from "@/core/identity/types";

const ERROR_MESSAGES: Record<string, string> = {
  oidc_callback_failed:
    "Sign-in via OIDC failed. Please try again or choose another provider.",
  no_membership:
    "Your account has no tenant membership yet. Contact your administrator.",
};

function PasswordLoginForm({ next }: { next: string | null }) {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(
          (body as { detail?: string }).detail ?? `Login failed (${res.status})`,
        );
        return;
      }
      window.location.href = next ?? "/admin/tenants";
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
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
          placeholder="admin@example.com"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="password" className="text-sm font-medium">
          Password
        </label>
        <input
          id="password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="••••••••"
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={loading}
        className="inline-flex w-full items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {loading ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  const searchParams = useSearchParams();
  const error = searchParams.get("error");
  const next = searchParams.get("next");

  const { data, isLoading, isError } = useQuery({
    queryKey: identityKeys.providers(),
    queryFn: identityApi.providers,
  });

  const providers: AuthProvider[] = data?.providers ?? [];

  const hrefFor = (id: string) =>
    `/api/auth/oidc/${id}/login${next ? `?next=${encodeURIComponent(next)}` : ""}`;

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>

      {error && ERROR_MESSAGES[error] && (
        <div
          role="alert"
          className="w-full rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
        >
          {ERROR_MESSAGES[error]}
        </div>
      )}

      {isLoading && <p className="text-muted-foreground">Loading providers…</p>}
      {isError && (
        <p className="text-sm text-destructive">
          Could not reach the auth service.
        </p>
      )}

      {/* OIDC provider buttons */}
      {providers.length > 0 && (
        <ul className="flex w-full flex-col gap-2">
          {providers.map((p) => (
            <li key={p.id}>
              <a
                href={hrefFor(p.id)}
                className="inline-flex w-full items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent"
              >
                Continue with {p.display_name}
              </a>
            </li>
          ))}
        </ul>
      )}

      {/* Password login — shown when no OIDC providers configured */}
      {!isLoading && !isError && providers.length === 0 && (
        <PasswordLoginForm next={next} />
      )}
    </main>
  );
}
