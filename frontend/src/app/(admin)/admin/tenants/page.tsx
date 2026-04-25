// frontend/src/app/(admin)/admin/tenants/page.tsx
"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";

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
import { useI18n } from "@/core/i18n/hooks";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import { useCreateTenant, useTenants } from "@/core/identity/hooks";
import {
  type CreateTenantFields,
  createTenantSchema,
} from "@/core/identity/schemas";

const PAGE_SIZE = 20;

export default function TenantsPage() {
  return (
    <RequirePermission perm="tenant:read">
      <TenantsInner />
    </RequirePermission>
  );
}

function TenantsInner() {
  const { t } = useI18n();
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
        <h1 className="text-xl font-semibold">{t.admin.pages.tenantsTitle}</h1>
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
              {t.admin.actions.newTenant}
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
            <TableHead>{t.admin.table.colSlug}</TableHead>
            <TableHead>{t.admin.table.colName}</TableHead>
            <TableHead>{t.admin.table.colPlan}</TableHead>
            <TableHead>{t.admin.table.colStatus}</TableHead>
            <TableHead>{t.admin.table.colCreated}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && (
            <TableRow>
              <TableCell colSpan={5} className="text-muted-foreground">
                {t.admin.table.loading}
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
          {data?.items.map((tenant) => (
            <TableRow key={tenant.id}>
              <TableCell>
                <Link
                  href={`/admin/tenants/${tenant.id}`}
                  className="underline"
                >
                  {tenant.slug}
                </Link>
              </TableCell>
              <TableCell>{tenant.name}</TableCell>
              <TableCell>{tenant.plan}</TableCell>
              <TableCell>
                {tenant.status === 1
                  ? t.admin.table.statusActive
                  : t.admin.table.statusDisabled}
              </TableCell>
              <TableCell>{tenant.created_at?.slice(0, 10) ?? "—"}</TableCell>
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
            {t.admin.table.prev}
          </button>
          <button
            type="button"
            className="rounded-md border px-3 py-1 disabled:opacity-50"
            disabled={!data || offset + PAGE_SIZE >= data.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            {t.admin.table.next}
          </button>
        </div>
      </footer>
    </section>
  );
}

function CreateTenantDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const create = useCreateTenant();
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError,
  } = useForm<CreateTenantFields>({ resolver: zodResolver(createTenantSchema) });

  const onSubmit = async (data: CreateTenantFields) => {
    try {
      await create.mutateAsync({ slug: data.slug, name: data.name });
      onClose();
    } catch (err) {
      setError("root", {
        message: (err as Error).message || "Failed to create tenant",
      });
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="tenants-create-dialog">
        <DialogHeader>
          <DialogTitle>{t.admin.forms.tenantCreateTitle}</DialogTitle>
          <DialogDescription>
            {t.admin.forms.tenantCreateDesc}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
          <div>
            <label className="mb-1 block text-sm font-medium" htmlFor="tenant-slug">
              {t.admin.forms.slugLabel}
            </label>
            <Input
              id="tenant-slug"
              data-testid="tenants-create-slug"
              placeholder="acme"
              {...register("slug")}
            />
            {errors.slug ? (
              <p className="mt-1 text-xs text-destructive">{errors.slug.message}</p>
            ) : (
              <p className="mt-1 text-xs text-muted-foreground">
                {t.admin.forms.slugHint}
              </p>
            )}
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium" htmlFor="tenant-name">
              {t.admin.forms.displayNameLabel}
            </label>
            <Input
              id="tenant-name"
              data-testid="tenants-create-name"
              placeholder="Acme Inc"
              {...register("name")}
            />
            {errors.name && (
              <p className="mt-1 text-xs text-destructive">{errors.name.message}</p>
            )}
          </div>
          {errors.root && (
            <p className="text-sm text-destructive" data-testid="tenants-create-error">
              {errors.root.message}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              data-testid="tenants-create-cancel"
            >
              {t.admin.actions.cancel}
            </Button>
            <Button
              type="submit"
              data-testid="tenants-create-submit"
              disabled={isSubmitting}
            >
              {isSubmitting ? "Creating…" : t.admin.actions.newTenant}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
