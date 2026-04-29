// frontend/src/app/(admin)/admin/roles/page.tsx
"use client";

import { useI18n } from "@/core/i18n/hooks";
import { useRoles } from "@/core/identity/hooks";
import type { RoleRow } from "@/core/identity/types";

const roleDisplayNameZhMap: Record<string, string> = {
  platform_admin: "平台管理员",
  tenant_owner: "租户所有者",
  workspace_admin: "工作区管理员",
  member: "成员",
  viewer: "只读成员",
};

const roleDescriptionZhMap: Record<string, string> = {
  platform_admin: "拥有平台全部管理权限。",
  tenant_owner: "拥有租户内全部管理权限。",
  workspace_admin: "拥有工作区管理权限，可管理成员和配置。",
  member: "可在工作区内正常协作与操作。",
  viewer: "仅可查看内容，不可修改。",
};

/**
 * Resolves role text for rendering and forces Chinese labels for known built-in roles.
 */
function resolveRoleText(role: RoleRow) {
  return {
    displayName: roleDisplayNameZhMap[role.role_key] ?? role.display_name ?? role.role_key,
    description: roleDescriptionZhMap[role.role_key] ?? role.description,
  };
}

/**
 * Renders the admin roles catalog grouped by permission scope.
 */
export default function RolesPage() {
  const { locale, t } = useI18n();
  const { data, isLoading } = useRoles();
  const scopeLabels = {
    platform: t.admin.pages.rolesScopePlatform,
    tenant: t.admin.pages.rolesScopeTenant,
    workspace: t.admin.pages.rolesScopeWorkspace,
  } as const;

  if (isLoading)
    return (
      <section className="p-6 text-muted-foreground" role="status">
        {t.admin.table.loading}
      </section>
    );

  const grouped = new Map<string, RoleRow[]>();
  (data?.roles ?? []).forEach((r) => {
    const arr = grouped.get(r.scope) ?? [];
    arr.push(r);
    grouped.set(r.scope, arr);
  });
  return (
    <section className="p-6">
      <h1 className="mb-4 text-xl font-semibold">{t.admin.pages.rolesTitle}</h1>
      {(["platform", "tenant", "workspace"] as const).map((scope) => (
        <div key={scope} className="mb-6">
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted-foreground">
            {scopeLabels[scope]}
          </h2>
          <ul className="space-y-3">
            {(grouped.get(scope) ?? []).map((r) => (
              <li key={r.role_key} className="rounded-md border p-3">
                <p className="font-medium">{resolveRoleText(r).displayName}</p>
                <p className="text-xs text-muted-foreground">
                  {locale === "zh-CN" ? (
                    <span>角色标识：{resolveRoleText(r).displayName}</span>
                  ) : (
                    <code>{r.role_key}</code>
                  )}
                  {r.is_builtin && (
                    <span className="ml-2">· {t.admin.pages.rolesBuiltinTag}</span>
                  )}
                </p>
                {resolveRoleText(r).description && (
                  <p className="mt-1 text-sm text-muted-foreground">
                    {resolveRoleText(r).description}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
