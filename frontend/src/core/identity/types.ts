// frontend/src/core/identity/types.ts

export type Permission = string; // e.g. "tenant:read", "workspace:write"

export type RoleName =
  | "platform_admin"
  | "tenant_owner"
  | "workspace_admin"
  | "member"
  | "viewer";

// /api/me response shape (matches backend MeResponse in routers/me.py).
export interface MeResponse {
  user_id: number;
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
  active_tenant_id: number | null;
  tenants: Array<{ id: number; slug: string; name: string }>;
  workspaces: Array<{ id: number; slug: string; name: string }>;
  permissions: Permission[];
  // roles is a map keyed by scope: {"platform":[...], "tenant:1":[...], "workspace:7":[...]}
  roles: Record<string, RoleName[]>;
}

export interface AuthProvider {
  id: string;
  display_name: string;
  icon_url: string | null;
}

export interface ProvidersResponse {
  providers: AuthProvider[];
}

export type IdentityError =
  | { kind: "unauthenticated" }
  | { kind: "forbidden"; missing?: Permission }
  | { kind: "network"; status: number; message: string };

// ---------------------------------------------------------------------------
// A2 admin read shapes — mirror backend response JSON exactly.
// Sources:
//   - app/gateway/identity/routers/admin.py (tenants/users/workspaces/tokens)
//   - app/gateway/identity/routers/roles.py (/api/roles, /api/permissions)
//   - app/gateway/identity/audit/api.py    (/api/tenants/{tid}/audit)
// ---------------------------------------------------------------------------

export interface TenantRow {
  id: number;
  slug: string;
  name: string;
  plan: string;
  status: number;
  created_at: string | null;
}

export interface TenantDetail extends TenantRow {
  member_count: number;
  workspace_count: number;
}

export interface UserRow {
  id: number;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  status: number;
  last_login_at: string | null;
  roles: string[];
}

export interface WorkspaceRow {
  id: number;
  tenant_id: number;
  slug: string;
  name: string;
  description: string | null;
  created_at: string | null;
  member_count: number;
}

export interface WorkspaceMemberRow {
  id: number; // user id
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  status: number;
  role: string; // role_key
  joined_at: string | null;
}

export interface TokenRow {
  id: number;
  tenant_id: number;
  user_id: number;
  workspace_id: number | null;
  name: string;
  prefix: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
}

// Audit row shape from app/gateway/identity/audit/api.py::_row_to_dict
export interface AuditRow {
  id: number;
  created_at: string | null;
  tenant_id: number | null;
  user_id: number | null;
  workspace_id: number | null;
  thread_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  ip: string | null;
  user_agent: string | null;
  result: "success" | "failure";
  error_code: string | null;
  duration_ms: number | null;
  metadata: Record<string, unknown>;
}

export interface OffsetListResponse<T> {
  items: T[];
  total: number;
}

export interface CursorListResponse<T> {
  items: T[];
  next_cursor: string | null;
}

// Role row shape (matches backend /api/roles — no id, no permissions array).
export interface RoleRow {
  role_key: string;
  scope: "platform" | "tenant" | "workspace";
  is_builtin: boolean;
  display_name: string | null;
  description: string | null;
}

export interface RolesResponse {
  roles: RoleRow[];
}

// Permission row shape (matches backend /api/permissions — no id).
export interface PermissionRow {
  tag: string;
  scope: "platform" | "tenant" | "workspace";
  description: string | null;
}

export interface PermissionsResponse {
  permissions: PermissionRow[];
}

export interface AuditFilters {
  action?: string;
  user_id?: number;
  resource_type?: string;
  result?: "success" | "failure";
  date_from?: string;
  date_to?: string;
  cursor?: string;
  limit?: number;
}

export interface SwitchTenantResponse {
  access_token: string;
  expires_in: number;
}

// ---------------------------------------------------------------------------
// A3 admin write payloads — mirror backend admin_writes.py.
// ---------------------------------------------------------------------------

export interface CreateUserPayload {
  email: string;
  display_name?: string;
  initial_password?: string;
}

export interface AddWorkspaceMemberPayload {
  user_id: number;
  role: RoleName;
}

export interface PatchWorkspaceMemberPayload {
  role: RoleName;
}

export interface CreateTenantTokenPayload {
  name: string;
  scopes: string[];
  user_id: number;
  workspace_id?: number | null;
  expires_at?: string | null;
}

export interface CreateTokenResult {
  id: number;
  plaintext: string; // shown ONCE — never re-served by the backend
  prefix: string;
}

// /api/me/tokens (per-user tokens — distinct from /api/tenants/{tid}/tokens which lists tenant-wide)
export interface MyTokenRow {
  id: number;
  name: string;
  prefix: string;
  scopes: string[];
  workspace_id: number | null;
  created_at: string | null;
  expires_at: string | null;
  last_used_at: string | null;
}

export interface CreateMyTokenPayload {
  name: string;
  scopes: string[];
  workspace_id?: number | null;
  expires_at?: string | null;
}

// /api/me/sessions
export interface MySessionRow {
  sid: string;
  created_at: string | null;
  ip: string | null;
  user_agent: string | null;
}

// ---------------------------------------------------------------------------
// M7A item 2: tenant + workspace CRUD
// ---------------------------------------------------------------------------

export interface CreateTenantPayload {
  slug: string;
  name: string;
}

export interface PatchTenantPayload {
  name: string;
}

export interface CreateWorkspacePayload {
  slug: string;
  name: string;
}

export interface PatchWorkspacePayload {
  name: string;
}

export interface UpdateMePayload {
  display_name?: string | null;
  avatar_url?: string | null;
}

export interface ChangePasswordPayload {
  old_password: string;
  new_password: string;
}

export interface AdminSetPasswordPayload {
  email: string;
  password: string;
}

// ---------------------------------------------------------------------------
// Task 5.1c: Org API key management
// ---------------------------------------------------------------------------

export interface OrgKeyRow {
  id: number;
  prefix: string;
  name: string;
  created_at: string | null;
  expires_at: string | null;
  no_expiry: boolean;
  auto_rotate_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface OrgKeyCreateResult extends OrgKeyRow {
  plaintext: string; // shown ONCE — never re-served
}

export interface OrgKeysResponse {
  keys: OrgKeyRow[];
}

export interface CreateOrgKeyPayload {
  name: string;
  no_expiry: boolean;
  expires_in_days?: number | null;
  allowed_skills?: string[];
}

// ---------------------------------------------------------------------------
// Public registration (P1 — see docs/superpowers/specs/archive/2026-04-29-registration-code-design.md)
// ---------------------------------------------------------------------------

export interface RegisterWithCodePayload {
  code: string;
  email: string;
  password: string;
  display_name?: string;
}

export interface RegisterWithCodeResponse {
  status: "ok";
  email: string;
}
