// frontend/tests/e2e/identity/A4-rbac-matrix.spec.ts
import { expect, test } from "@playwright/test";

import { mockAdmin, mockIdentity } from "./fixtures/mock-backend";

type Role =
  | "platform_admin"
  | "tenant_owner"
  | "workspace_admin"
  | "member"
  | "guest";

type Action =
  | "create-tenant"
  | "create-user"
  | "create-token"
  | "add-workspace-member"
  | "view-audit"
  | "create-workspace";

const PERMS_BY_ROLE: Record<Role, string[]> = {
  platform_admin: [
    "tenant:read",
    "tenant:create",
    "tenant:write",
    "tenant:delete",
    "workspace:read",
    "workspace:create",
    "workspace:write",
    "workspace:delete",
    "membership:read",
    "membership:invite",
    "membership:remove",
    "token:read",
    "token:create",
    "token:revoke",
    "user:read",
    "user:create",
    "audit:read",
  ],
  tenant_owner: [
    "tenant:read",
    "tenant:write",
    "workspace:read",
    "workspace:create",
    "workspace:write",
    "workspace:delete",
    "membership:read",
    "membership:invite",
    "membership:remove",
    "token:read",
    "token:create",
    "token:revoke",
    "user:read",
    "user:create",
    "audit:read",
  ],
  workspace_admin: [
    "tenant:read",
    "workspace:read",
    "workspace:write",
    "membership:read",
    "membership:invite",
    "membership:remove",
  ],
  member: ["tenant:read", "workspace:read", "user:read"],
  guest: ["tenant:read"],
};

interface Cell {
  page: string;
  testId: string;
}

const ACTION: Record<Action, Cell> = {
  "create-tenant": {
    page: "/admin/tenants",
    testId: "tenants-new-btn",
  },
  "create-user": {
    page: "/admin/users",
    testId: "users-new-btn",
  },
  "create-token": {
    page: "/admin/tokens",
    testId: "tokens-new-btn",
  },
  "add-workspace-member": {
    page: "/admin/workspaces/7/members",
    testId: "member-add-btn",
  },
  "view-audit": {
    page: "/admin/audit",
    testId: "audit-page",
  },
  "create-workspace": {
    page: "/admin/workspaces",
    testId: "workspaces-new-btn",
  },
};

const MATRIX: Array<[Role, Action, "allow" | "deny"]> = [
  // platform_admin — everything allowed
  ["platform_admin", "create-tenant", "allow"],
  ["platform_admin", "create-user", "allow"],
  ["platform_admin", "create-token", "allow"],
  ["platform_admin", "add-workspace-member", "allow"],
  ["platform_admin", "view-audit", "allow"],
  ["platform_admin", "create-workspace", "allow"],

  // tenant_owner — everything except create-tenant (platform-only)
  ["tenant_owner", "create-tenant", "deny"],
  ["tenant_owner", "create-user", "allow"],
  ["tenant_owner", "create-token", "allow"],
  ["tenant_owner", "add-workspace-member", "allow"],
  ["tenant_owner", "view-audit", "allow"],
  ["tenant_owner", "create-workspace", "allow"],

  // workspace_admin — workspace-scoped writes. create-user lights up because
  // the current UI gates "users-new-btn" on membership:invite, which is the
  // same perm that lets them add workspace members. Tighten perm split if
  // tenant-level user creation should stop at tenant_owner.
  ["workspace_admin", "create-tenant", "deny"],
  ["workspace_admin", "create-user", "allow"],
  ["workspace_admin", "create-token", "deny"],
  ["workspace_admin", "add-workspace-member", "allow"],
  ["workspace_admin", "view-audit", "deny"],
  ["workspace_admin", "create-workspace", "deny"],

  // member — read-only
  ["member", "create-tenant", "deny"],
  ["member", "create-user", "deny"],
  ["member", "create-token", "deny"],
  ["member", "add-workspace-member", "deny"],
  ["member", "view-audit", "deny"],
  ["member", "create-workspace", "deny"],

  // guest — read-only, tenant-level only
  ["guest", "create-tenant", "deny"],
  ["guest", "create-user", "deny"],
  ["guest", "create-token", "deny"],
  ["guest", "add-workspace-member", "deny"],
  ["guest", "view-audit", "deny"],
  ["guest", "create-workspace", "deny"],
];

test.describe("rbac-matrix: 5 roles × 6 actions", () => {
  for (const [role, action, expected] of MATRIX) {
    test(`${role} ${expected === "allow" ? "can" : "cannot"} ${action}`, async ({
      page,
    }) => {
      await mockIdentity(page, {
        authenticated: true,
        permissions: PERMS_BY_ROLE[role],
      });
      await mockAdmin(page, {
        tenants: { items: [], total: 0 },
        users: { items: [], total: 0 },
        workspaces: { items: [], total: 0 },
        tokens: { items: [], total: 0 },
        workspaceMembers: { 7: { items: [], total: 0 } },
        audit: { items: [], next_cursor: null },
      });

      const cell = ACTION[action];
      await page.goto(cell.page);

      if (action === "view-audit") {
        if (expected === "allow") {
          await expect(page.getByTestId("audit-page")).toBeVisible();
        } else {
          await expect(page.getByTestId("audit-denied")).toBeVisible();
        }
        return;
      }

      const button = page.getByTestId(cell.testId);
      if (expected === "allow") {
        await expect(button).toBeVisible();
      } else {
        await expect(button).toHaveCount(0);
      }
    });
  }
});
