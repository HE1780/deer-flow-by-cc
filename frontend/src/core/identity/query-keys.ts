// frontend/src/core/identity/query-keys.ts

export const identityKeys = {
  all: ["identity"] as const,
  me: () => [...identityKeys.all, "me"] as const,
  providers: () => [...identityKeys.all, "providers"] as const,
  tenants: () => [...identityKeys.all, "tenants"] as const,
  tenant: (id: number) => [...identityKeys.all, "tenants", id] as const,
  users: (tenantId: number) =>
    [...identityKeys.all, "tenants", tenantId, "users"] as const,
  user: (tenantId: number, userId: number) =>
    [...identityKeys.all, "tenants", tenantId, "users", userId] as const,
  workspaces: (tenantId: number) =>
    [...identityKeys.all, "tenants", tenantId, "workspaces"] as const,
  workspaceMembers: (tenantId: number, wsId: number) =>
    [
      ...identityKeys.all,
      "tenants",
      tenantId,
      "workspaces",
      wsId,
      "members",
    ] as const,
  tokens: () => [...identityKeys.all, "tokens"] as const,
  myTokens: () => [...identityKeys.all, "me", "tokens"] as const,
  mySessions: () => [...identityKeys.all, "me", "sessions"] as const,
  audit: (tenantId: number, filters: string) =>
    [...identityKeys.all, "audit", tenantId, filters] as const,
  roles: () => [...identityKeys.all, "roles"] as const,
  orgKeys: () => [...identityKeys.all, "org-keys"] as const,
};
