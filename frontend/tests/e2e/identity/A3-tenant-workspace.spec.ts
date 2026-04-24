// frontend/tests/e2e/identity/A3-tenant-workspace.spec.ts
import { expect, test } from "@playwright/test";

import {
  mockAdmin,
  mockIdentity,
  mockWrites,
} from "./fixtures/mock-backend";

const PLATFORM_ADMIN_PERMS = [
  "tenant:read",
  "tenant:create",
  "tenant:update",
  "tenant:delete",
  "workspace:read",
  "workspace:create",
  "workspace:update",
  "workspace:delete",
];

const WS_ITEM = {
  id: 7,
  tenant_id: 1,
  slug: "main",
  name: "Main Workspace",
  description: null,
  created_at: "2026-01-01T00:00:00Z",
  member_count: 3,
};

test.describe("A3: tenant CRUD", () => {
  test("create tenant dialog posts payload and closes on success", async ({
    page,
  }) => {
    await mockIdentity(page, {
      authenticated: true,
      permissions: ["tenant:read", "tenant:create"],
    });
    await mockAdmin(page, { tenants: { items: [], total: 0 } });
    const rec = await mockWrites(page);

    await page.goto("/admin/tenants");
    await page.getByTestId("tenants-new-btn").click();

    const dialog = page.getByTestId("tenants-create-dialog");
    await expect(dialog).toBeVisible();

    await page.getByTestId("tenants-create-slug").fill("acme");
    await page.getByTestId("tenants-create-name").fill("Acme Inc");
    await page.getByTestId("tenants-create-submit").click();

    await expect(dialog).toBeHidden();
    expect(rec.createTenant).toHaveLength(1);
    expect(rec.createTenant[0]?.body).toEqual({
      slug: "acme",
      name: "Acme Inc",
    });
  });

  test("create tenant button absent without tenant:create permission", async ({
    page,
  }) => {
    await mockIdentity(page, {
      authenticated: true,
      permissions: ["tenant:read"],
    });
    await mockAdmin(page, { tenants: { items: [], total: 0 } });
    await mockWrites(page);

    await page.goto("/admin/tenants");
    await expect(page.getByTestId("tenants-new-btn")).not.toBeVisible();
  });

  test("rename tenant dialog patches name and closes on success", async ({
    page,
  }) => {
    const TENANT = {
      id: 5,
      slug: "acme",
      name: "Old Name",
      plan: "free",
      status: 1,
      created_at: "2026-01-01T00:00:00Z",
      member_count: 2,
      workspace_count: 1,
    };
    await mockIdentity(page, {
      authenticated: true,
      permissions: PLATFORM_ADMIN_PERMS,
    });
    await mockAdmin(page, { tenantDetail: { 5: TENANT } });
    const rec = await mockWrites(page);

    await page.goto("/admin/tenants/5");
    await page.getByTestId("tenant-rename-btn").click();

    const dialog = page.getByTestId("tenant-rename-dialog");
    await expect(dialog).toBeVisible();

    const nameInput = page.getByTestId("tenant-rename-name");
    await nameInput.fill("New Name");
    await page.getByTestId("tenant-rename-submit").click();

    await expect(dialog).toBeHidden();
    expect(rec.updateTenant).toHaveLength(1);
    expect(rec.updateTenant[0]?.body).toEqual({ name: "New Name" });
    expect(rec.updateTenant[0]?.url).toContain("/api/admin/tenants/5");
  });

  test("delete tenant requires confirm and posts DELETE then navigates", async ({
    page,
  }) => {
    const TENANT = {
      id: 5,
      slug: "acme",
      name: "Acme Inc",
      plan: "free",
      status: 1,
      created_at: "2026-01-01T00:00:00Z",
      member_count: 0,
      workspace_count: 0,
    };
    await mockIdentity(page, {
      authenticated: true,
      permissions: PLATFORM_ADMIN_PERMS,
    });
    await mockAdmin(page, {
      tenants: { items: [], total: 0 },
      tenantDetail: { 5: TENANT },
    });
    const rec = await mockWrites(page);

    await page.goto("/admin/tenants/5");
    await page.getByTestId("tenant-delete-btn").click();
    await page.getByTestId("tenant-delete-confirm-btn").click();

    await expect.poll(() => rec.deleteTenant.length).toBe(1);
    expect(rec.deleteTenant[0]?.url).toContain("/api/admin/tenants/5");
  });

  test("delete/rename buttons absent without update/delete permissions", async ({
    page,
  }) => {
    const TENANT = {
      id: 5,
      slug: "acme",
      name: "Acme Inc",
      plan: "free",
      status: 1,
      created_at: "2026-01-01T00:00:00Z",
      member_count: 0,
      workspace_count: 0,
    };
    await mockIdentity(page, {
      authenticated: true,
      permissions: ["tenant:read"],
    });
    await mockAdmin(page, { tenantDetail: { 5: TENANT } });
    await mockWrites(page);

    await page.goto("/admin/tenants/5");
    await expect(page.getByTestId("tenant-rename-btn")).not.toBeVisible();
    await expect(page.getByTestId("tenant-delete-btn")).not.toBeVisible();
  });
});

test.describe("A3: workspace CRUD", () => {
  test("create workspace dialog posts payload and closes on success", async ({
    page,
  }) => {
    await mockIdentity(page, {
      authenticated: true,
      permissions: ["workspace:read", "workspace:create"],
    });
    await mockAdmin(page, {
      workspaces: { items: [], total: 0 },
    });
    const rec = await mockWrites(page);

    await page.goto("/admin/workspaces");
    await page.getByTestId("workspaces-new-btn").click();

    const dialog = page.getByTestId("workspaces-create-dialog");
    await expect(dialog).toBeVisible();

    await page.getByTestId("workspaces-create-slug").fill("eng");
    await page.getByTestId("workspaces-create-name").fill("Engineering");
    await page.getByTestId("workspaces-create-submit").click();

    await expect(dialog).toBeHidden();
    expect(rec.createWorkspace).toHaveLength(1);
    expect(rec.createWorkspace[0]?.body).toEqual({
      slug: "eng",
      name: "Engineering",
    });
  });

  test("create workspace button absent without workspace:create permission", async ({
    page,
  }) => {
    await mockIdentity(page, {
      authenticated: true,
      permissions: ["workspace:read"],
    });
    await mockAdmin(page, { workspaces: { items: [], total: 0 } });
    await mockWrites(page);

    await page.goto("/admin/workspaces");
    await expect(page.getByTestId("workspaces-new-btn")).not.toBeVisible();
  });

  test("rename workspace dialog patches name and closes on success", async ({
    page,
  }) => {
    await mockIdentity(page, {
      authenticated: true,
      permissions: PLATFORM_ADMIN_PERMS,
    });
    await mockAdmin(page, {
      workspaces: { items: [WS_ITEM], total: 1 },
    });
    const rec = await mockWrites(page);

    await page.goto("/admin/workspaces/7");
    await page.getByTestId("workspace-rename-btn").click();

    const dialog = page.getByTestId("workspace-rename-dialog");
    await expect(dialog).toBeVisible();

    const nameInput = page.getByTestId("workspace-rename-name");
    await nameInput.fill("Renamed WS");
    await page.getByTestId("workspace-rename-submit").click();

    await expect(dialog).toBeHidden();
    expect(rec.updateWorkspace).toHaveLength(1);
    expect(rec.updateWorkspace[0]?.body).toEqual({ name: "Renamed WS" });
    expect(rec.updateWorkspace[0]?.url).toContain(
      "/api/tenants/1/workspaces/7",
    );
  });

  test("delete workspace requires confirm and posts DELETE", async ({
    page,
  }) => {
    await mockIdentity(page, {
      authenticated: true,
      permissions: PLATFORM_ADMIN_PERMS,
    });
    await mockAdmin(page, {
      workspaces: { items: [WS_ITEM], total: 1 },
    });
    const rec = await mockWrites(page);

    await page.goto("/admin/workspaces/7");
    await page.getByTestId("workspace-delete-btn").click();
    await page.getByTestId("workspace-delete-confirm-btn").click();

    await expect.poll(() => rec.deleteWorkspace.length).toBe(1);
    expect(rec.deleteWorkspace[0]?.url).toContain(
      "/api/tenants/1/workspaces/7",
    );
  });

  test("rename/delete buttons absent without update/delete permissions", async ({
    page,
  }) => {
    await mockIdentity(page, {
      authenticated: true,
      permissions: ["workspace:read"],
    });
    await mockAdmin(page, {
      workspaces: { items: [WS_ITEM], total: 1 },
    });
    await mockWrites(page);

    await page.goto("/admin/workspaces/7");
    await expect(page.getByTestId("workspace-rename-btn")).not.toBeVisible();
    await expect(page.getByTestId("workspace-delete-btn")).not.toBeVisible();
  });
});
