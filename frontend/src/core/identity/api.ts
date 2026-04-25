// frontend/src/core/identity/api.ts
import { identityFetch } from "./fetcher";
import {
  type AddWorkspaceMemberPayload,
  type AuditFilters,
  type AuditRow,
  type CreateMyTokenPayload,
  type CreateOrgKeyPayload,
  type CreateTenantPayload,
  type CreateTenantTokenPayload,
  type CreateTokenResult,
  type CreateUserPayload,
  type CreateWorkspacePayload,
  type CursorListResponse,
  type MeResponse,
  type MySessionRow,
  type MyTokenRow,
  type OffsetListResponse,
  type OrgKeyCreateResult,
  type OrgKeysResponse,
  type PatchTenantPayload,
  type PatchWorkspaceMemberPayload,
  type PatchWorkspacePayload,
  type PermissionsResponse,
  type ProvidersResponse,
  type RolesResponse,
  type SwitchTenantResponse,
  type TenantDetail,
  type TenantRow,
  type TokenRow,
  type UpdateMePayload,
  type UserRow,
  type WorkspaceMemberRow,
  type WorkspaceRow,
} from "./types";

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    // Only primitives survive URL encoding; objects would stringify to
    // "[object Object]" which silently corrupts the query. Skip them.
    if (typeof v === "string") p.set(k, v);
    else if (typeof v === "number" || typeof v === "boolean")
      p.set(k, v.toString());
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const identityApi = {
  // --- A1 surface (unchanged) ---
  me: () => identityFetch<MeResponse>("/api/me"),
  providers: () => identityFetch<ProvidersResponse>("/api/auth/providers"),
  logout: () =>
    identityFetch<{ status: string }>("/api/auth/logout", { method: "POST" }),
  refresh: () =>
    identityFetch<{ access_token: string; expires_in: number }>(
      "/api/auth/refresh",
      { method: "POST" },
    ),

  // --- A2: admin reads ---
  switchTenant: (tenantId: number) =>
    identityFetch<SwitchTenantResponse>("/api/me/switch-tenant", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId }),
    }),

  listTenants: (
    params: { q?: string; offset?: number; limit?: number } = {},
  ) =>
    identityFetch<OffsetListResponse<TenantRow>>(
      `/api/admin/tenants${qs(params)}`,
    ),
  getTenant: (id: number) =>
    identityFetch<TenantDetail>(`/api/admin/tenants/${id}`),

  listUsers: (
    tenantId: number,
    params: { q?: string; offset?: number; limit?: number } = {},
  ) =>
    identityFetch<OffsetListResponse<UserRow>>(
      `/api/tenants/${tenantId}/users${qs(params)}`,
    ),
  getUser: (tenantId: number, userId: number) =>
    identityFetch<UserRow>(`/api/tenants/${tenantId}/users/${userId}`),

  listWorkspaces: (
    tenantId: number,
    params: { offset?: number; limit?: number } = {},
  ) =>
    identityFetch<OffsetListResponse<WorkspaceRow>>(
      `/api/tenants/${tenantId}/workspaces${qs(params)}`,
    ),
  listWorkspaceMembers: (
    tenantId: number,
    wsId: number,
    params: { offset?: number; limit?: number } = {},
  ) =>
    identityFetch<OffsetListResponse<WorkspaceMemberRow>>(
      `/api/tenants/${tenantId}/workspaces/${wsId}/members${qs(params)}`,
    ),

  listTenantTokens: (
    tenantId: number,
    params: { include_revoked?: boolean; offset?: number; limit?: number } = {},
  ) =>
    identityFetch<OffsetListResponse<TokenRow>>(
      `/api/tenants/${tenantId}/tokens${qs(params)}`,
    ),

  listAudit: (tenantId: number, filters: AuditFilters = {}) =>
    identityFetch<CursorListResponse<AuditRow>>(
      `/api/tenants/${tenantId}/audit${qs(filters as Record<string, unknown>)}`,
    ),

  listRoles: () => identityFetch<RolesResponse>("/api/roles"),
  listPermissions: () =>
    identityFetch<PermissionsResponse>("/api/permissions"),

  // --- A3: admin writes ---
  createUser: (tenantId: number, payload: CreateUserPayload) =>
    identityFetch<UserRow>(`/api/tenants/${tenantId}/users`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  addWorkspaceMember: (
    tenantId: number,
    wsId: number,
    payload: AddWorkspaceMemberPayload,
  ) =>
    identityFetch<WorkspaceMemberRow>(
      `/api/tenants/${tenantId}/workspaces/${wsId}/members`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  patchWorkspaceMemberRole: (
    tenantId: number,
    wsId: number,
    userId: number,
    payload: PatchWorkspaceMemberPayload,
  ) =>
    identityFetch<WorkspaceMemberRow>(
      `/api/tenants/${tenantId}/workspaces/${wsId}/members/${userId}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
  removeWorkspaceMember: (
    tenantId: number,
    wsId: number,
    userId: number,
  ) =>
    identityFetch<void>(
      `/api/tenants/${tenantId}/workspaces/${wsId}/members/${userId}`,
      { method: "DELETE" },
    ),

  createTenantToken: (
    tenantId: number,
    payload: CreateTenantTokenPayload,
  ) =>
    identityFetch<CreateTokenResult>(`/api/tenants/${tenantId}/tokens`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  revokeTenantToken: (tenantId: number, tokenId: number) =>
    identityFetch<void>(`/api/tenants/${tenantId}/tokens/${tokenId}`, {
      method: "DELETE",
    }),

  // --- M7A item 2: tenant + workspace CRUD ---
  createTenant: (payload: CreateTenantPayload) =>
    identityFetch<TenantDetail>("/api/admin/tenants", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateTenant: (id: number, payload: PatchTenantPayload) =>
    identityFetch<TenantDetail>(`/api/admin/tenants/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteTenant: (id: number) =>
    identityFetch<void>(`/api/admin/tenants/${id}`, { method: "DELETE" }),

  createWorkspace: (tenantId: number, payload: CreateWorkspacePayload) =>
    identityFetch<WorkspaceRow>(`/api/tenants/${tenantId}/workspaces`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateWorkspace: (
    tenantId: number,
    wsId: number,
    payload: PatchWorkspacePayload,
  ) =>
    identityFetch<WorkspaceRow>(
      `/api/tenants/${tenantId}/workspaces/${wsId}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
  deleteWorkspace: (tenantId: number, wsId: number) =>
    identityFetch<void>(
      `/api/tenants/${tenantId}/workspaces/${wsId}`,
      { method: "DELETE" },
    ),

  // PATCH /api/me — update own display_name + avatar_url
  updateMe: (payload: UpdateMePayload) =>
    identityFetch<MeResponse>("/api/me", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  // --- A4: /api/me/* tokens & sessions ---
  listMyTokens: () => identityFetch<MyTokenRow[]>("/api/me/tokens"),
  createMyToken: (payload: CreateMyTokenPayload) =>
    identityFetch<CreateTokenResult>("/api/me/tokens", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  revokeMyToken: (tokenId: number) =>
    identityFetch<{ status: string }>(`/api/me/tokens/${tokenId}`, {
      method: "DELETE",
    }),
  listMySessions: () => identityFetch<MySessionRow[]>("/api/me/sessions"),
  revokeMySession: (sid: string) =>
    identityFetch<{ status: string }>(`/api/me/sessions/${sid}`, {
      method: "DELETE",
    }),

  // --- Task 5.1c: org-keys ---
  listOrgKeys: () => identityFetch<OrgKeysResponse>("/api/admin/org-keys"),
  createOrgKey: (payload: CreateOrgKeyPayload) =>
    identityFetch<OrgKeyCreateResult>("/api/admin/org-keys", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  revokeOrgKey: (keyId: number) =>
    identityFetch<{ status: string }>(`/api/admin/org-keys/${keyId}`, {
      method: "DELETE",
    }),
};
