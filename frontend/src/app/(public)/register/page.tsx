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
