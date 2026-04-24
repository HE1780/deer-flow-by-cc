// frontend/src/app/(admin)/admin/tenants/page.tsx
"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import { useTenants } from "@/core/identity/hooks";

const PAGE_SIZE = 20;

export default function TenantsPage() {
  return (
    <RequirePermission perm="tenant:read">
      <TenantsInner />
    </RequirePermission>
  );
}

function TenantsInner() {
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, isLoading, isError } = useTenants({
    q,
    offset,
    limit: PAGE_SIZE,
  });

  return (
    <section className="p-6">
      <header className="mb-4 flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold">Tenants</h1>
        <div className="flex items-center gap-2">
          <Input
            aria-label="Filter by slug"
            placeholder="Filter by slug…"
            className="w-64"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
          <RequirePermission perm="tenant:create" fallback={null}>
            <Button data-testid="tenants-new-btn" disabled>
              New Tenant
            </Button>
          </RequirePermission>
        </div>
      </header>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Slug</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Plan</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Created</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && (
            <TableRow>
              <TableCell colSpan={5} className="text-muted-foreground">
                Loading…
              </TableCell>
            </TableRow>
          )}
          {isError && (
            <TableRow>
              <TableCell colSpan={5} className="text-destructive">
                Failed to load tenants.
              </TableCell>
            </TableRow>
          )}
          {data?.items.map((t) => (
            <TableRow key={t.id}>
              <TableCell>
                <Link
                  href={`/admin/tenants/${t.id}`}
                  className="underline"
                >
                  {t.slug}
                </Link>
              </TableCell>
              <TableCell>{t.name}</TableCell>
              <TableCell>{t.plan}</TableCell>
              <TableCell>{t.status === 1 ? "active" : "disabled"}</TableCell>
              <TableCell>{t.created_at?.slice(0, 10) ?? "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <footer className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {data?.total ?? 0} total · showing {data?.total ? offset + 1 : 0}-
          {Math.min(offset + PAGE_SIZE, data?.total ?? 0)}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded-md border px-3 py-1 disabled:opacity-50"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Prev
          </button>
          <button
            type="button"
            className="rounded-md border px-3 py-1 disabled:opacity-50"
            disabled={!data || offset + PAGE_SIZE >= data.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      </footer>
    </section>
  );
}
