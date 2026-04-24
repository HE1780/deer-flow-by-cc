// frontend/src/app/(admin)/admin/workspaces/page.tsx
"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  useCreateWorkspace,
  useIdentity,
  useWorkspaces,
} from "@/core/identity/hooks";

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
  const [createOpen, setCreateOpen] = useState(false);
  const { data, isLoading } = useWorkspaces(tid, {
    offset,
    limit: PAGE_SIZE,
  });
  return (
    <section className="p-6" data-testid="workspaces-page">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Workspaces</h1>
        <RequirePermission perm="workspace:create" fallback={null}>
          <Button
            data-testid="workspaces-new-btn"
            onClick={() => setCreateOpen(true)}
            disabled={!tid}
          >
            New Workspace
          </Button>
        </RequirePermission>
      </header>
      {createOpen && tid && (
        <CreateWorkspaceDialog
          tenantId={tid}
          onClose={() => setCreateOpen(false)}
        />
      )}
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
              <TableCell className="flex gap-3">
                <Link
                  href={`/admin/workspaces/${w.id}`}
                  className="text-sm underline"
                >
                  Details →
                </Link>
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

function CreateWorkspaceDialog({
  tenantId,
  onClose,
}: {
  tenantId: number;
  onClose: () => void;
}) {
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useCreateWorkspace(tenantId);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await create.mutateAsync({ slug: slug.trim(), name: name.trim() });
      onClose();
    } catch (err) {
      setError((err as Error).message || "Failed to create workspace");
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="workspaces-create-dialog">
        <DialogHeader>
          <DialogTitle>New workspace</DialogTitle>
          <DialogDescription>
            The slug is scoped to the current tenant and permanent.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-3">
          <div>
            <label
              className="mb-1 block text-sm font-medium"
              htmlFor="workspace-slug"
            >
              Slug
            </label>
            <Input
              id="workspace-slug"
              data-testid="workspaces-create-slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              pattern="^[a-z0-9-]{2,64}$"
              required
            />
          </div>
          <div>
            <label
              className="mb-1 block text-sm font-medium"
              htmlFor="workspace-name"
            >
              Display name
            </label>
            <Input
              id="workspace-name"
              data-testid="workspaces-create-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          {error && (
            <p
              className="text-sm text-destructive"
              data-testid="workspaces-create-error"
            >
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              data-testid="workspaces-create-cancel"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="workspaces-create-submit"
              disabled={create.isPending}
            >
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
