// frontend/src/app/(admin)/admin/layout.tsx
"use client";

import Link from "next/link";
import { type ReactNode } from "react";

import { AdminSidebar } from "@/core/identity/components/AdminSidebar";
import { TenantSwitcher } from "@/core/identity/components/TenantSwitcher";

function LogoutButton() {
  return (
    <button
      onClick={async () => {
        await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
        window.location.href = "/login";
      }}
      className="inline-flex h-8 items-center rounded-md border px-3 text-sm hover:bg-accent"
    >
      Sign out
    </button>
  );
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background">
      <aside className="w-56 border-r bg-muted/30">
        <Link
          href="/admin/profile"
          className="block border-b px-4 py-3 text-lg font-semibold tracking-tight"
        >
          系统管理
        </Link>
        <AdminSidebar />
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="flex h-14 items-center justify-between gap-4 border-b px-6">
          <Link
            href="/workspace"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-sm hover:bg-accent"
          >
            ← Workspace
          </Link>
          <div className="flex items-center gap-4">
            <TenantSwitcher />
            <LogoutButton />
          </div>
        </header>
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
