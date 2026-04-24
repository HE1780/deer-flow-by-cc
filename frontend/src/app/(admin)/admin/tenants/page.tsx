// frontend/src/app/(admin)/admin/tenants/page.tsx
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
import { useCreateTenant, useTenants } from "@/core/identity/hooks";

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
  const [createOpen, setCreateOpen] = useState(false);
  const { data, isLoading, isError } = useTenants({
    q,
    offset,
    limit: PAGE_SIZE,
  });

  return (
    <section className="p-6" data-testid="tenants-page">
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
            <Button
              data-testid="tenants-new-btn"
              onClick={() => setCreateOpen(true)}
            >
              New Tenant
            </Button>
          </RequirePermission>
        </div>
      </header>

      {createOpen && (
        <CreateTenantDialog onClose={() => setCreateOpen(false)} />
      )}

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

function CreateTenantDialog({ onClose }: { onClose: () => void }) {
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useCreateTenant();

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await create.mutateAsync({ slug: slug.trim(), name: name.trim() });
      onClose();
    } catch (err) {
      const msg = (err as Error).message || "Failed to create tenant";
      setError(msg);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="tenants-create-dialog">
        <DialogHeader>
          <DialogTitle>New tenant</DialogTitle>
          <DialogDescription>
            Platform admins can create a new tenant. The slug is permanent —
            choose carefully.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-3">
          <div>
            <label className="mb-1 block text-sm font-medium" htmlFor="tenant-slug">
              Slug
            </label>
            <Input
              id="tenant-slug"
              data-testid="tenants-create-slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="acme"
              pattern="^[a-z0-9-]{2,64}$"
              required
            />
            <p className="mt-1 text-xs text-muted-foreground">
              2–64 chars, lowercase letters, digits, or dashes.
            </p>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium" htmlFor="tenant-name">
              Display name
            </label>
            <Input
              id="tenant-name"
              data-testid="tenants-create-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Acme Inc"
              required
            />
          </div>
          {error && (
            <p className="text-sm text-destructive" data-testid="tenants-create-error">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              data-testid="tenants-create-cancel"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="tenants-create-submit"
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
