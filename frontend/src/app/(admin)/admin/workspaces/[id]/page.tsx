// frontend/src/app/(admin)/admin/workspaces/[id]/page.tsx
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
import { useI18n } from "@/core/i18n/hooks";
import { InlineConfirm } from "@/core/identity/components/InlineConfirm";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import {
  useDeleteWorkspace,
  useHasPermission,
  useIdentity,
  useUpdateWorkspace,
  useWorkspaces,
} from "@/core/identity/hooks";
import {
  type RenameWorkspaceFields,
  renameWorkspaceSchema,
} from "@/core/identity/schemas";

interface Props {
  params: Promise<{ id: string }>;
}

export default function WorkspaceDetailPage({ params }: Props) {
  const { id } = use(params);
  const wsId = Number(id);
  return (
    <RequirePermission perm="workspace:read">
      <Inner wsId={wsId} />
    </RequirePermission>
  );
}

function Inner({ wsId }: { wsId: number }) {
  const router = useRouter();
  const { t } = useI18n();
  const { identity } = useIdentity();
  const tid = identity?.active_tenant_id ?? undefined;
  const { data, isLoading } = useWorkspaces(tid, { limit: 200 });
  const workspace = data?.items.find((w) => w.id === wsId);

  const [renameOpen, setRenameOpen] = useState(false);
  const canUpdate = useHasPermission("workspace:update");
  const canDelete = useHasPermission("workspace:delete");
  const remove = useDeleteWorkspace(tid);

  if (isLoading) return <p className="p-6 text-muted-foreground">{t.admin.table.loading}</p>;
  if (!workspace)
    return <p className="p-6 text-destructive">Workspace not found.</p>;

  return (
    <section className="p-6" data-testid="workspace-detail-page">
      <header className="mb-4">
        <Link
          href="/admin/workspaces"
          className="text-sm text-muted-foreground hover:underline"
        >
          {t.admin.table.backToWorkspaces}
        </Link>
        <div className="mt-1 flex items-center gap-2">
          <h1 className="text-xl font-semibold">{workspace.name}</h1>
          {canUpdate && (
            <Button
              size="sm"
              variant="ghost"
              data-testid="workspace-rename-btn"
              onClick={() => setRenameOpen(true)}
            >
              {t.admin.actions.rename}
            </Button>
          )}
          {canDelete && (
            <InlineConfirm
              label={t.admin.actions.delete}
              onConfirm={async () => {
                await remove.mutateAsync(workspace.id);
                router.push("/admin/workspaces");
              }}
              pending={remove.isPending}
              triggerTestId="workspace-delete-btn"
              confirmTestId="workspace-delete-confirm-btn"
            />
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          <code>/{workspace.slug}</code> · #{workspace.id}
        </p>
      </header>
      <dl className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <dt className="text-muted-foreground">{t.admin.table.colMembers}</dt>
          <dd>{workspace.member_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t.admin.table.colCreated}</dt>
          <dd>{workspace.created_at?.slice(0, 10) ?? "—"}</dd>
        </div>
        {workspace.description && (
          <div className="col-span-2">
            <dt className="text-muted-foreground">Description</dt>
            <dd>{workspace.description}</dd>
          </div>
        )}
      </dl>
      <div className="mt-4">
        <Link
          href={`/admin/workspaces/${workspace.id}/members`}
          className="text-sm underline"
        >
          {t.admin.table.manageMembers}
        </Link>
      </div>
      {renameOpen && tid && (
        <RenameWorkspaceDialog
          tenantId={tid}
          wsId={workspace.id}
          initialName={workspace.name}
          onClose={() => setRenameOpen(false)}
        />
      )}
    </section>
  );
}

function RenameWorkspaceDialog({
  tenantId,
  wsId,
  initialName,
  onClose,
}: {
  tenantId: number;
  wsId: number;
  initialName: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const patch = useUpdateWorkspace(tenantId, wsId);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError,
  } = useForm<RenameWorkspaceFields>({
    resolver: zodResolver(renameWorkspaceSchema),
    defaultValues: { name: initialName },
  });

  const onSubmit = async (data: RenameWorkspaceFields) => {
    try {
      await patch.mutateAsync({ name: data.name.trim() });
      onClose();
    } catch (err) {
      setError("root", {
        message: (err as Error).message || "Failed to rename workspace",
      });
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="workspace-rename-dialog">
        <DialogHeader>
          <DialogTitle>{t.admin.forms.workspaceRenameTitle}</DialogTitle>
          <DialogDescription>
            {t.admin.forms.workspaceRenameDesc}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
          <Input
            data-testid="workspace-rename-name"
            {...register("name")}
          />
          {errors.root && (
            <p
              className="text-sm text-destructive"
              data-testid="workspace-rename-error"
            >
              {errors.root.message}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              data-testid="workspace-rename-cancel"
            >
              {t.admin.actions.cancel}
            </Button>
            <Button
              type="submit"
              data-testid="workspace-rename-submit"
              disabled={isSubmitting}
            >
              {isSubmitting ? "Saving…" : t.admin.actions.save}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
