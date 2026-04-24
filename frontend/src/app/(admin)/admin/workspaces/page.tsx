// frontend/src/app/(admin)/admin/workspaces/page.tsx
"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import { useIdentity, useWorkspaces } from "@/core/identity/hooks";

const PAGE_SIZE = 20;

export default function WorkspacesPage() {
  return (
    <RequirePermission perm="workspace:read">
      <Inner />
    </RequirePermission>
  );
}

function Inner() {
  const { identity } = useIdentity();
  const tid = identity?.active_tenant_id ?? undefined;
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useWorkspaces(tid, {
    offset,
    limit: PAGE_SIZE,
  });
  return (
    <section className="p-6">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Workspaces</h1>
        <RequirePermission perm="workspace:create" fallback={null}>
          <Button data-testid="workspaces-new-btn" disabled>
            New Workspace
          </Button>
        </RequirePermission>
      </header>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Slug</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Members</TableHead>
            <TableHead>Created</TableHead>
            <TableHead />
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
          {data?.items.map((w) => (
            <TableRow key={w.id}>
              <TableCell className="font-mono text-xs">{w.slug}</TableCell>
              <TableCell>{w.name}</TableCell>
              <TableCell>{w.member_count}</TableCell>
              <TableCell>{w.created_at?.slice(0, 10) ?? "—"}</TableCell>
              <TableCell>
                <Link
                  href={`/admin/workspaces/${w.id}/members`}
                  className="text-sm underline"
                >
                  Members →
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <footer className="mt-4 flex gap-2 text-sm">
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
      </footer>
    </section>
  );
}
