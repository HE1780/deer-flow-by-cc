// frontend/src/app/(admin)/admin/workspaces/[id]/page.tsx
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useState } from "react";

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
  useDeleteWorkspace,
  useHasPermission,
  useIdentity,
  useUpdateWorkspace,
  useWorkspaces,
} from "@/core/identity/hooks";

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
  const { identity } = useIdentity();
  const tid = identity?.active_tenant_id ?? undefined;
  const { data, isLoading } = useWorkspaces(tid, { limit: 200 });
  const workspace = data?.items.find((w) => w.id === wsId);

  const [renameOpen, setRenameOpen] = useState(false);
  const canUpdate = useHasPermission("workspace:update");
  const canDelete = useHasPermission("workspace:delete");
  const remove = useDeleteWorkspace(tid);

  if (isLoading) return <p className="p-6 text-muted-foreground">Loading…</p>;
  if (!workspace)
    return <p className="p-6 text-destructive">Workspace not found.</p>;

  return (
    <section className="p-6" data-testid="workspace-detail-page">
      <header className="mb-4">
        <Link
          href="/admin/workspaces"
          className="text-sm text-muted-foreground hover:underline"
        >
          ← Workspaces
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
              Rename
            </Button>
          )}
          {canDelete && (
            <InlineConfirm
              label="Delete"
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
          <dt className="text-muted-foreground">Members</dt>
          <dd>{workspace.member_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Created</dt>
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
          Manage members →
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
  const [name, setName] = useState(initialName);
  const [error, setError] = useState<string | null>(null);
  const patch = useUpdateWorkspace(tenantId, wsId);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await patch.mutateAsync({ name: name.trim() });
      onClose();
    } catch (err) {
      setError((err as Error).message || "Failed to rename workspace");
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="workspace-rename-dialog">
        <DialogHeader>
          <DialogTitle>Rename workspace</DialogTitle>
          <DialogDescription>
            The display name can be changed freely; the slug is permanent.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-3">
          <Input
            data-testid="workspace-rename-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          {error && (
            <p
              className="text-sm text-destructive"
              data-testid="workspace-rename-error"
            >
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              data-testid="workspace-rename-cancel"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="workspace-rename-submit"
              disabled={patch.isPending}
            >
              {patch.isPending ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
