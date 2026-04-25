// frontend/src/app/(admin)/admin/workspaces/page.tsx
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
import {
  useCreateWorkspace,
  useIdentity,
  useWorkspaces,
} from "@/core/identity/hooks";
import {
  type CreateWorkspaceFields,
  createWorkspaceSchema,
} from "@/core/identity/schemas";

const PAGE_SIZE = 20;

export default function WorkspacesPage() {
  return (
    <RequirePermission perm="workspace:read">
      <Inner />
    </RequirePermission>
  );
}

function Inner() {
  const { t } = useI18n();
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
        <h1 className="text-xl font-semibold">{t.admin.pages.workspacesTitle}</h1>
        <RequirePermission perm="workspace:create" fallback={null}>
          <Button
            data-testid="workspaces-new-btn"
            onClick={() => setCreateOpen(true)}
            disabled={!tid}
          >
            {t.admin.actions.newWorkspace}
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
            <TableHead>{t.admin.table.colSlug}</TableHead>
            <TableHead>{t.admin.table.colName}</TableHead>
            <TableHead>{t.admin.table.colMembers}</TableHead>
            <TableHead>{t.admin.table.colCreated}</TableHead>
            <TableHead />
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
                  {t.admin.table.details}
                </Link>
                <Link
                  href={`/admin/workspaces/${w.id}/members`}
                  className="text-sm underline"
                >
                  {t.admin.table.membersLink}
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
  const { t } = useI18n();
  const create = useCreateWorkspace(tenantId);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError,
  } = useForm<CreateWorkspaceFields>({
    resolver: zodResolver(createWorkspaceSchema),
  });

  const onSubmit = async (data: CreateWorkspaceFields) => {
    try {
      await create.mutateAsync({ slug: data.slug, name: data.name });
      onClose();
    } catch (err) {
      setError("root", {
        message: (err as Error).message || "Failed to create workspace",
      });
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="workspaces-create-dialog">
        <DialogHeader>
          <DialogTitle>{t.admin.forms.workspaceCreateTitle}</DialogTitle>
          <DialogDescription>
            {t.admin.forms.workspaceCreateDesc}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
          <div>
            <label
              className="mb-1 block text-sm font-medium"
              htmlFor="workspace-slug"
            >
              {t.admin.forms.slugLabel}
            </label>
            <Input
              id="workspace-slug"
              data-testid="workspaces-create-slug"
              {...register("slug")}
            />
            {errors.slug && (
              <p className="mt-1 text-xs text-destructive">{errors.slug.message}</p>
            )}
          </div>
          <div>
            <label
              className="mb-1 block text-sm font-medium"
              htmlFor="workspace-name"
            >
              {t.admin.forms.displayNameLabel}
            </label>
            <Input
              id="workspace-name"
              data-testid="workspaces-create-name"
              {...register("name")}
            />
            {errors.name && (
              <p className="mt-1 text-xs text-destructive">{errors.name.message}</p>
            )}
          </div>
          {errors.root && (
            <p
              className="text-sm text-destructive"
              data-testid="workspaces-create-error"
            >
              {errors.root.message}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              data-testid="workspaces-create-cancel"
            >
              {t.admin.actions.cancel}
            </Button>
            <Button
              type="submit"
              data-testid="workspaces-create-submit"
              disabled={isSubmitting}
            >
              {isSubmitting ? "Creating…" : t.admin.actions.newWorkspace}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
