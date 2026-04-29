// frontend/src/app/(admin)/admin/users/[id]/page.tsx
"use client";

import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { PermBadge } from "@/core/identity/components/PermBadge";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import {
  useAdminSetPassword,
  useAddWorkspaceMember,
  useIdentity,
  usePatchWorkspaceMemberRole,
  useUser,
  useWorkspaceMembers,
  useWorkspaces,
} from "@/core/identity/hooks";
import type { RoleName } from "@/core/identity/types";

const WORKSPACE_ROLES: RoleName[] = ["workspace_admin", "member", "viewer"];

interface Props {
  params: Promise<{ id: string }>;
}

export default function UserDetailPage({ params }: Props) {
  const { id } = use(params);
  return (
    <RequirePermission perm="membership:read">
      <Inner userId={Number(id)} />
    </RequirePermission>
  );
}

function Inner({ userId }: { userId: number }) {
  const { t } = useI18n();
  const { identity } = useIdentity();
  const tid = identity?.active_tenant_id ?? undefined;
  const { data, isLoading, isError } = useUser(tid, userId);
  const { data: workspaceData } = useWorkspaces(tid, { offset: 0, limit: 200 });
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<number>();
  const [selectedRole, setSelectedRole] = useState<RoleName>("member");

  useEffect(() => {
    if (selectedWorkspaceId) return;
    const firstWorkspace = workspaceData?.items[0];
    if (firstWorkspace) {
      setSelectedWorkspaceId(firstWorkspace.id);
    }
  }, [selectedWorkspaceId, workspaceData?.items]);

  const { data: memberData } = useWorkspaceMembers(tid, selectedWorkspaceId, {
    offset: 0,
    limit: 200,
  });
  const patchRole = usePatchWorkspaceMemberRole(tid, selectedWorkspaceId);
  const addMember = useAddWorkspaceMember(tid, selectedWorkspaceId);
  const adminSetPassword = useAdminSetPassword();
  const [resetPassword, setResetPassword] = useState("");

  const currentMemberRole = useMemo(() => {
    return memberData?.items.find((item) => item.id === userId)?.role;
  }, [memberData?.items, userId]);

  useEffect(() => {
    if (currentMemberRole) {
      setSelectedRole(currentMemberRole as RoleName);
    }
  }, [currentMemberRole]);

  /**
   * Saves selected role. Existing member uses patch; missing member uses add.
   */
  function saveWorkspaceRole() {
    if (!selectedWorkspaceId) return;
    if (currentMemberRole) {
      patchRole.mutate({ userId, role: selectedRole });
      return;
    }
    addMember.mutate({ user_id: userId, role: selectedRole });
  }

  /**
   * Allows admin to set a temporary password for the target user.
   */
  function resetUserPassword() {
    if (!data?.email || resetPassword.trim().length < 8) return;
    adminSetPassword.mutate({
      email: data.email,
      password: resetPassword.trim(),
    });
    setResetPassword("");
  }

  if (isLoading)
    return <p className="p-6 text-muted-foreground">{t.admin.table.loading}</p>;
  if (isError || !data)
    return <p className="p-6 text-destructive">User not found.</p>;
  return (
    <section className="p-6">
      <Link
        href="/admin/users"
        className="text-sm text-muted-foreground hover:underline"
      >
        {t.admin.table.backToUsers}
      </Link>
      <h1 className="mt-1 text-xl font-semibold">
        {data.display_name ?? data.email}
      </h1>
      <p className="text-sm text-muted-foreground">{data.email}</p>
      <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
        <div>
          <dt className="text-muted-foreground">{t.admin.table.colRoles}</dt>
          <dd className="flex flex-wrap gap-1">
            {data.roles.map((r) => (
              <PermBadge key={r} perm={r} />
            ))}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t.admin.table.colStatus}</dt>
          <dd>{data.status === 1 ? t.admin.table.statusActive : t.admin.table.statusDisabled}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t.admin.table.colLastLogin}</dt>
          <dd>{data.last_login_at?.slice(0, 10) ?? "—"}</dd>
        </div>
      </dl>
      <section className="mt-6 rounded-md border p-4">
        <h2 className="text-base font-medium">工作区权限配置</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-sm">
            <span>工作区</span>
            <select
              aria-label="工作区"
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={selectedWorkspaceId ?? ""}
              onChange={(event) =>
                setSelectedWorkspaceId(Number(event.target.value))
              }
            >
              {workspaceData?.items.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            <span>工作区角色</span>
            <select
              aria-label="工作区角色"
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={selectedRole}
              onChange={(event) => setSelectedRole(event.target.value as RoleName)}
            >
              {WORKSPACE_ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          当前角色：{currentMemberRole ?? "未加入该工作区"}
        </p>
        <button
          type="button"
          className="mt-3 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
          disabled={
            !selectedWorkspaceId || patchRole.isPending || addMember.isPending
          }
          onClick={saveWorkspaceRole}
        >
          保存角色
        </button>
      </section>
      <section className="mt-6 rounded-md border p-4">
        <h2 className="text-base font-medium">密码重置</h2>
        <div className="mt-3 grid gap-1 text-sm max-w-sm">
          <label htmlFor="user-reset-password">新密码</label>
          <input
            id="user-reset-password"
            aria-label="新密码"
            type="password"
            value={resetPassword}
            onChange={(event) => setResetPassword(event.target.value)}
            minLength={8}
            className="h-9 rounded-md border bg-background px-3 text-sm"
          />
        </div>
        <button
          type="button"
          className="mt-3 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
          disabled={adminSetPassword.isPending || resetPassword.trim().length < 8}
          onClick={resetUserPassword}
        >
          重置密码
        </button>
      </section>
    </section>
  );
}
