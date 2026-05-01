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

  // Form branch is added in Task 5.
  return <LoadingShell />;
  // (router used in later tasks; reference here to satisfy the linter)
  void router;
}
