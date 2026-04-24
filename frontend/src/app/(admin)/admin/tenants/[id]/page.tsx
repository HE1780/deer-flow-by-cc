// frontend/src/app/(admin)/admin/tenants/[id]/page.tsx
"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useState } from "react";
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
import { InlineConfirm } from "@/core/identity/components/InlineConfirm";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import {
  useDeleteTenant,
  useHasPermission,
  useTenant,
  useUpdateTenant,
} from "@/core/identity/hooks";
import {
  type RenameTenantFields,
  renameTenantSchema,
} from "@/core/identity/schemas";

interface Props {
  params: Promise<{ id: string }>;
}

export default function TenantDetailPage({ params }: Props) {
  const { id } = use(params);
  const tenantId = Number(id);
  return (
    <RequirePermission perm="tenant:read">
      <Inner id={tenantId} />
    </RequirePermission>
  );
}

function Inner({ id }: { id: number }) {
  const router = useRouter();
  const { data, isLoading, isError } = useTenant(id);
  const [renameOpen, setRenameOpen] = useState(false);
  const canUpdate = useHasPermission("tenant:update");
  const canDelete = useHasPermission("tenant:delete");
  const remove = useDeleteTenant();

  if (isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (isError || !data)
    return <p className="p-6 text-destructive">Tenant not found.</p>;

  return (
    <section className="p-6" data-testid="tenant-detail-page">
      <header className="mb-4">
        <Link
          href="/admin/tenants"
          className="text-sm text-muted-foreground hover:underline"
        >
          ← Tenants
        </Link>
        <div className="mt-1 flex items-center gap-2">
          <h1 className="text-xl font-semibold">{data.name}</h1>
          {canUpdate && (
            <Button
              size="sm"
              variant="ghost"
              data-testid="tenant-rename-btn"
              onClick={() => setRenameOpen(true)}
            >
              Rename
            </Button>
          )}
          {canDelete && (
            <InlineConfirm
              label="Delete"
              onConfirm={async () => {
                await remove.mutateAsync(data.id);
                router.push("/admin/tenants");
              }}
              pending={remove.isPending}
              triggerTestId="tenant-delete-btn"
              confirmTestId="tenant-delete-confirm-btn"
            />
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          <code>/{data.slug}</code> · #{data.id}
        </p>
      </header>
      <dl className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <dt className="text-muted-foreground">Plan</dt>
          <dd>{data.plan}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Status</dt>
          <dd>{data.status === 1 ? "active" : "disabled"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Workspaces</dt>
          <dd>{data.workspace_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Members</dt>
          <dd>{data.member_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Created</dt>
          <dd>{data.created_at?.slice(0, 10) ?? "—"}</dd>
        </div>
      </dl>
      {renameOpen && (
        <RenameTenantDialog
          tenantId={data.id}
          initialName={data.name}
          onClose={() => setRenameOpen(false)}
        />
      )}
    </section>
  );
}

function RenameTenantDialog({
  tenantId,
  initialName,
  onClose,
}: {
  tenantId: number;
  initialName: string;
  onClose: () => void;
}) {
  const patch = useUpdateTenant(tenantId);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError,
  } = useForm<RenameTenantFields>({
    resolver: zodResolver(renameTenantSchema),
    defaultValues: { name: initialName },
  });

  const onSubmit = async (data: RenameTenantFields) => {
    try {
      await patch.mutateAsync({ name: data.name.trim() });
      onClose();
    } catch (err) {
      setError("root", {
        message: (err as Error).message || "Failed to rename tenant",
      });
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="tenant-rename-dialog">
        <DialogHeader>
          <DialogTitle>Rename tenant</DialogTitle>
          <DialogDescription>
            The display name can be changed freely; the slug is permanent.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
          <Input
            data-testid="tenant-rename-name"
            {...register("name")}
          />
          {errors.root && (
            <p
              className="text-sm text-destructive"
              data-testid="tenant-rename-error"
            >
              {errors.root.message}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              data-testid="tenant-rename-cancel"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="tenant-rename-submit"
              disabled={isSubmitting}
            >
              {isSubmitting ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
