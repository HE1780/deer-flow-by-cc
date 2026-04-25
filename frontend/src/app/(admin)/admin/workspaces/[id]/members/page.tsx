// frontend/src/app/(admin)/admin/workspaces/[id]/members/page.tsx
"use client";

import { PlusIcon } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useI18n } from "@/core/i18n/hooks";
import { InlineConfirm } from "@/core/identity/components/InlineConfirm";
import { PermBadge } from "@/core/identity/components/PermBadge";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import {
  useAddWorkspaceMember,
  useHasPermission,
  useIdentity,
  usePatchWorkspaceMemberRole,
  useRemoveWorkspaceMember,
  useWorkspaceMembers,
} from "@/core/identity/hooks";
import { type RoleName, type WorkspaceMemberRow } from "@/core/identity/types";

const PAGE_SIZE = 50;
const WORKSPACE_ROLES: RoleName[] = ["workspace_admin", "member", "viewer"];

interface Props {
  params: Promise<{ id: string }>;
}

export default function WorkspaceMembersPage({ params }: Props) {
  const { id } = use(params);
  return (
    <RequirePermission perm="membership:read">
      <Inner wsId={Number(id)} />
    </RequirePermission>
  );
}

function Inner({ wsId }: { wsId: number }) {
  const { t } = useI18n();
  const { identity } = useIdentity();
  const tid = identity?.active_tenant_id ?? undefined;
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useWorkspaceMembers(tid, wsId, {
    offset,
    limit: PAGE_SIZE,
  });

  const canInvite = useHasPermission("membership:invite");
  const canRemove = useHasPermission("membership:remove");
  const [addOpen, setAddOpen] = useState(false);

  return (
    <section className="p-6" data-testid="workspace-members-page">
      <Link
        href="/admin/workspaces"
        className="text-sm text-muted-foreground hover:underline"
      >
        {t.admin.table.backToWorkspaces}
      </Link>
      <header className="mt-1 mb-3 flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t.admin.table.colMembers}</h1>
        {canInvite && (
          <Button
            size="sm"
            onClick={() => setAddOpen(true)}
            data-testid="member-add-btn"
          >
            <PlusIcon className="size-4" /> {t.admin.actions.addMember}
          </Button>
        )}
      </header>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t.admin.table.colEmail}</TableHead>
            <TableHead>{t.admin.table.colName}</TableHead>
            <TableHead>{t.admin.table.colRole}</TableHead>
            <TableHead>{t.admin.table.colJoined}</TableHead>
            {(canInvite || canRemove) && <TableHead aria-label="actions" />}
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
          {data?.items.map((m) => (
            <MemberRow
              key={m.id}
              member={m}
              tenantId={tid}
              wsId={wsId}
              canPatch={canInvite}
              canRemove={canRemove}
            />
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

      {addOpen && tid && (
        <AddMemberDialog
          tenantId={tid}
          wsId={wsId}
          onClose={() => setAddOpen(false)}
        />
      )}
    </section>
  );
}

function MemberRow({
  member,
  tenantId,
  wsId,
  canPatch,
  canRemove,
}: {
  member: WorkspaceMemberRow;
  tenantId: number | undefined;
  wsId: number;
  canPatch: boolean;
  canRemove: boolean;
}) {
  const { t } = useI18n();
  const patch = usePatchWorkspaceMemberRole(tenantId, wsId);
  const remove = useRemoveWorkspaceMember(tenantId, wsId);

  return (
    <TableRow data-testid={`member-row-${member.id}`}>
      <TableCell>{member.email}</TableCell>
      <TableCell>{member.display_name ?? "—"}</TableCell>
      <TableCell>
        {canPatch ? (
          <Select
            value={member.role}
            onValueChange={(v) =>
              patch.mutate({ userId: member.id, role: v as RoleName })
            }
          >
            <SelectTrigger
              className="w-40"
              data-testid={`member-role-trigger-${member.id}`}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WORKSPACE_ROLES.map((r) => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <PermBadge perm={member.role} />
        )}
      </TableCell>
      <TableCell>{member.joined_at?.slice(0, 10) ?? "—"}</TableCell>
      {(canPatch || canRemove) && (
        <TableCell>
          {canRemove && (
            <InlineConfirm
              label={t.admin.actions.remove}
              onConfirm={() => remove.mutate(member.id)}
              pending={remove.isPending}
              triggerTestId={`member-remove-${member.id}`}
              confirmTestId={`member-remove-confirm-${member.id}`}
            />
          )}
        </TableCell>
      )}
    </TableRow>
  );
}

function AddMemberDialog({
  tenantId,
  wsId,
  onClose,
}: {
  tenantId: number;
  wsId: number;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [userIdRaw, setUserIdRaw] = useState("");
  const [role, setRole] = useState<RoleName>("member");
  const add = useAddWorkspaceMember(tenantId, wsId);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="member-add-dialog">
        <DialogHeader>
          <DialogTitle>{t.admin.actions.addMember}</DialogTitle>
          <DialogDescription>
            User must already be a tenant member. Enter their numeric user id —
            you can find it on the Users page.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            const userId = Number(userIdRaw);
            if (!Number.isFinite(userId) || userId <= 0) return;
            add.mutate(
              { user_id: userId, role },
              {
                onSuccess: () => {
                  onClose();
                },
              },
            );
          }}
        >
          <label className="grid gap-1 text-sm">
            <span>{t.admin.audit.filterUserId}</span>
            <Input
              type="number"
              value={userIdRaw}
              onChange={(e) => setUserIdRaw(e.target.value)}
              required
              min={1}
              data-testid="member-add-user-id"
            />
          </label>
          <label className="grid gap-1 text-sm">
            <span>{t.admin.table.colRole}</span>
            <Select
              value={role}
              onValueChange={(v) => setRole(v as RoleName)}
            >
              <SelectTrigger data-testid="member-add-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {WORKSPACE_ROLES.map((r) => (
                  <SelectItem key={r} value={r}>
                    {r}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          {add.isError && (
            <p className="text-sm text-red-600" role="alert">
              Could not add member. They might not be in this tenant yet.
            </p>
          )}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t.admin.actions.cancel}
              </Button>
            </DialogClose>
            <Button
              type="submit"
              disabled={add.isPending || !userIdRaw}
              data-testid="member-add-submit"
            >
              {add.isPending ? "Adding…" : t.admin.actions.addMember}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
