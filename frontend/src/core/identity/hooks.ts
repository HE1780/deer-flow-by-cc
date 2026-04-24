// frontend/src/core/identity/hooks.ts
"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useMemo } from "react";

import { identityApi } from "./api";
import { identityKeys } from "./query-keys";
import {
  type AddWorkspaceMemberPayload,
  type AuditFilters,
  type CreateMyTokenPayload,
  type CreateTenantPayload,
  type CreateTenantTokenPayload,
  type CreateUserPayload,
  type CreateWorkspacePayload,
  type IdentityError,
  type MeResponse,
  type PatchTenantPayload,
  type PatchWorkspaceMemberPayload,
  type PatchWorkspacePayload,
  type Permission,
  type RoleName,
  type UpdateMePayload,
} from "./types";

export function useIdentity() {
  const query = useQuery<MeResponse, IdentityError>({
    queryKey: identityKeys.me(),
    queryFn: identityApi.me,
    retry: false,
    staleTime: 60_000,
  });

  return {
    identity: query.data,
    isLoading: query.isLoading,
    isAuthenticated: query.isSuccess && !!query.data,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useHasPermission(perm: Permission): boolean {
  const { identity } = useIdentity();
  return useMemo(
    () => !!identity?.permissions.includes(perm),
    [identity, perm],
  );
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: identityApi.logout,
    onSettled: () => {
      qc.removeQueries({ queryKey: identityKeys.all });
    },
  });
}

// ---------------------------------------------------------------------------
// A2: admin mutations + list queries
// ---------------------------------------------------------------------------

export function useSwitchTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tenantId: number) => identityApi.switchTenant(tenantId),
    onSuccess: () => {
      // Identity cookie is re-issued server-side; re-fetch everything identity-scoped.
      void qc.invalidateQueries({ queryKey: identityKeys.all });
    },
  });
}

export function useTenants(
  params: { q?: string; offset?: number; limit?: number } = {},
) {
  return useQuery({
    queryKey: [...identityKeys.tenants(), params],
    queryFn: () => identityApi.listTenants(params),
    placeholderData: keepPreviousData,
  });
}

export function useTenant(id: number | undefined) {
  return useQuery({
    queryKey: id ? identityKeys.tenant(id) : [...identityKeys.tenants(), "disabled"],
    queryFn: () => identityApi.getTenant(id!),
    enabled: !!id,
  });
}

export function useUsers(
  tenantId: number | undefined,
  params: { q?: string; offset?: number; limit?: number } = {},
) {
  return useQuery({
    queryKey: tenantId
      ? [...identityKeys.users(tenantId), params]
      : [...identityKeys.all, "users", "disabled"],
    queryFn: () => identityApi.listUsers(tenantId!, params),
    placeholderData: keepPreviousData,
    enabled: !!tenantId,
  });
}

export function useUser(
  tenantId: number | undefined,
  userId: number | undefined,
) {
  return useQuery({
    queryKey:
      tenantId && userId
        ? identityKeys.user(tenantId, userId)
        : [...identityKeys.all, "user", "disabled"],
    queryFn: () =>
      identityApi.getUser(tenantId!, userId!),
    enabled: !!tenantId && !!userId,
  });
}

export function useWorkspaces(
  tenantId: number | undefined,
  params: { offset?: number; limit?: number } = {},
) {
  return useQuery({
    queryKey: tenantId
      ? [...identityKeys.workspaces(tenantId), params]
      : [...identityKeys.all, "workspaces", "disabled"],
    queryFn: () => identityApi.listWorkspaces(tenantId!, params),
    placeholderData: keepPreviousData,
    enabled: !!tenantId,
  });
}

export function useWorkspaceMembers(
  tenantId: number | undefined,
  wsId: number | undefined,
  params: { offset?: number; limit?: number } = {},
) {
  return useQuery({
    queryKey:
      tenantId && wsId
        ? [...identityKeys.workspaceMembers(tenantId, wsId), params]
        : [...identityKeys.all, "workspace-members", "disabled"],
    queryFn: () =>
      identityApi.listWorkspaceMembers(
        tenantId!,
        wsId!,
        params,
      ),
    placeholderData: keepPreviousData,
    enabled: !!tenantId && !!wsId,
  });
}

export function useTenantTokens(
  tenantId: number | undefined,
  params: { include_revoked?: boolean; offset?: number; limit?: number } = {},
) {
  return useQuery({
    queryKey: tenantId
      ? [...identityKeys.tokens(), tenantId, params]
      : [...identityKeys.tokens(), "disabled"],
    queryFn: () =>
      identityApi.listTenantTokens(tenantId!, params),
    placeholderData: keepPreviousData,
    enabled: !!tenantId,
  });
}

export function useAudit(
  tenantId: number | undefined,
  filters: AuditFilters,
) {
  const filterKey = JSON.stringify(filters);
  return useQuery({
    queryKey: tenantId
      ? identityKeys.audit(tenantId, filterKey)
      : [...identityKeys.all, "audit", "disabled"],
    queryFn: () => identityApi.listAudit(tenantId!, filters),
    placeholderData: keepPreviousData,
    enabled: !!tenantId,
  });
}

export function useRoles() {
  return useQuery({
    queryKey: identityKeys.roles(),
    queryFn: () => identityApi.listRoles(),
    staleTime: 5 * 60_000, // roles rarely change
  });
}

// ---------------------------------------------------------------------------
// A3: admin write mutations (create user, workspace member CRUD, token CRUD)
// ---------------------------------------------------------------------------

export function useCreateUser(tenantId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateUserPayload) => {
      if (!tenantId) throw new Error("no active tenant");
      return identityApi.createUser(tenantId, payload);
    },
    onSuccess: () => {
      if (tenantId) {
        void qc.invalidateQueries({ queryKey: identityKeys.users(tenantId) });
      }
    },
  });
}

export function useAddWorkspaceMember(
  tenantId: number | undefined,
  wsId: number | undefined,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: AddWorkspaceMemberPayload) => {
      if (!tenantId || !wsId) throw new Error("missing tenant or workspace");
      return identityApi.addWorkspaceMember(tenantId, wsId, payload);
    },
    onSuccess: () => {
      if (tenantId && wsId) {
        void qc.invalidateQueries({
          queryKey: identityKeys.workspaceMembers(tenantId, wsId),
        });
        void qc.invalidateQueries({
          queryKey: identityKeys.workspaces(tenantId),
        });
      }
    },
  });
}

export function usePatchWorkspaceMemberRole(
  tenantId: number | undefined,
  wsId: number | undefined,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      userId,
      role,
    }: {
      userId: number;
      role: RoleName;
    }) => {
      if (!tenantId || !wsId) throw new Error("missing tenant or workspace");
      return identityApi.patchWorkspaceMemberRole(tenantId, wsId, userId, {
        role,
      } satisfies PatchWorkspaceMemberPayload);
    },
    onSuccess: () => {
      if (tenantId && wsId) {
        void qc.invalidateQueries({
          queryKey: identityKeys.workspaceMembers(tenantId, wsId),
        });
      }
    },
  });
}

export function useRemoveWorkspaceMember(
  tenantId: number | undefined,
  wsId: number | undefined,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) => {
      if (!tenantId || !wsId) throw new Error("missing tenant or workspace");
      return identityApi.removeWorkspaceMember(tenantId, wsId, userId);
    },
    onSuccess: () => {
      if (tenantId && wsId) {
        void qc.invalidateQueries({
          queryKey: identityKeys.workspaceMembers(tenantId, wsId),
        });
        void qc.invalidateQueries({
          queryKey: identityKeys.workspaces(tenantId),
        });
      }
    },
  });
}

export function useCreateTenantToken(tenantId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateTenantTokenPayload) => {
      if (!tenantId) throw new Error("no active tenant");
      return identityApi.createTenantToken(tenantId, payload);
    },
    onSuccess: () => {
      if (tenantId) {
        void qc.invalidateQueries({ queryKey: identityKeys.tokens() });
      }
    },
  });
}

export function useRevokeTenantToken(tenantId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tokenId: number) => {
      if (!tenantId) throw new Error("no active tenant");
      return identityApi.revokeTenantToken(tenantId, tokenId);
    },
    onSuccess: () => {
      if (tenantId) {
        void qc.invalidateQueries({ queryKey: identityKeys.tokens() });
      }
    },
  });
}

// ---------------------------------------------------------------------------
// A4: /api/me/{tokens,sessions} for the Profile page
// ---------------------------------------------------------------------------

export function useMyTokens(enabled = true) {
  return useQuery({
    queryKey: identityKeys.myTokens(),
    queryFn: () => identityApi.listMyTokens(),
    enabled,
  });
}

export function useCreateMyToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateMyTokenPayload) =>
      identityApi.createMyToken(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: identityKeys.myTokens() });
    },
  });
}

export function useRevokeMyToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tokenId: number) => identityApi.revokeMyToken(tokenId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: identityKeys.myTokens() });
    },
  });
}

export function useMySessions(enabled = true) {
  return useQuery({
    queryKey: identityKeys.mySessions(),
    queryFn: () => identityApi.listMySessions(),
    enabled,
  });
}

export function useRevokeMySession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sid: string) => identityApi.revokeMySession(sid),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: identityKeys.mySessions() });
    },
  });
}

// ---------------------------------------------------------------------------
// M7A item 2: tenant + workspace CRUD hooks
// ---------------------------------------------------------------------------

export function useCreateTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateTenantPayload) =>
      identityApi.createTenant(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: identityKeys.tenants() });
    },
  });
}

export function useUpdateTenant(id: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: PatchTenantPayload) => {
      if (!id) throw new Error("no tenant id");
      return identityApi.updateTenant(id, payload);
    },
    onSuccess: () => {
      if (id) {
        void qc.invalidateQueries({ queryKey: identityKeys.tenant(id) });
        void qc.invalidateQueries({ queryKey: identityKeys.tenants() });
      }
    },
  });
}

export function useDeleteTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => identityApi.deleteTenant(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: identityKeys.tenants() });
    },
  });
}

export function useCreateWorkspace(tenantId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateWorkspacePayload) => {
      if (!tenantId) throw new Error("no active tenant");
      return identityApi.createWorkspace(tenantId, payload);
    },
    onSuccess: () => {
      if (tenantId) {
        void qc.invalidateQueries({
          queryKey: identityKeys.workspaces(tenantId),
        });
      }
    },
  });
}

export function useUpdateWorkspace(
  tenantId: number | undefined,
  wsId: number | undefined,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: PatchWorkspacePayload) => {
      if (!tenantId || !wsId) throw new Error("missing tenant or workspace");
      return identityApi.updateWorkspace(tenantId, wsId, payload);
    },
    onSuccess: () => {
      if (tenantId) {
        void qc.invalidateQueries({
          queryKey: identityKeys.workspaces(tenantId),
        });
      }
    },
  });
}

export function useDeleteWorkspace(tenantId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (wsId: number) => {
      if (!tenantId) throw new Error("no active tenant");
      return identityApi.deleteWorkspace(tenantId, wsId);
    },
    onSuccess: () => {
      if (tenantId) {
        void qc.invalidateQueries({
          queryKey: identityKeys.workspaces(tenantId),
        });
      }
    },
  });
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: UpdateMePayload) => identityApi.updateMe(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: identityKeys.me() });
    },
  });
}
