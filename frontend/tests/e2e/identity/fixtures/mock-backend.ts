// frontend/tests/e2e/identity/fixtures/mock-backend.ts
import { type Page, type Route } from "@playwright/test";

import type {
  AuditRow,
  CursorListResponse,
  OffsetListResponse,
  RoleRow,
  TenantDetail,
  TenantRow,
  TokenRow,
  UserRow,
  WorkspaceMemberRow,
  WorkspaceRow,
} from "@/core/identity/types";

export interface MockIdentityOptions {
  authenticated?: boolean;
  permissions?: string[];
  tenants?: Array<{ id: number; slug: string; name: string }>;
  workspaces?: Array<{ id: number; slug: string; name: string }>;
  providers?: Array<{
    id: string;
    display_name: string;
    icon_url: string | null;
  }>;
}

const DEFAULT_PROVIDERS = [
  { id: "okta", display_name: "Okta", icon_url: null },
  { id: "keycloak", display_name: "Keycloak", icon_url: null },
];

export async function mockIdentity(
  page: Page,
  opts: MockIdentityOptions = {},
): Promise<void> {
  const providers = opts.providers ?? DEFAULT_PROVIDERS;
  const authenticated = opts.authenticated ?? false;

  await page.route("**/api/auth/providers", (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ providers }),
    }),
  );

  await page.route("**/api/me", (route: Route) => {
    if (!authenticated) return route.fulfill({ status: 401, body: "" });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: 42,
        email: "demo@deerflow.local",
        display_name: "Demo",
        avatar_url: null,
        active_tenant_id: 1,
        tenants: opts.tenants ?? [{ id: 1, slug: "default", name: "Default" }],
        workspaces: opts.workspaces ?? [
          { id: 7, slug: "main", name: "Main" },
        ],
        permissions: opts.permissions ?? ["tenant:read", "workspace:read"],
        roles: { "tenant:1": ["tenant_owner"] },
      }),
    });
  });

  await page.route("**/api/auth/logout", (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok" }),
    }),
  );

  if (authenticated) {
    await page.context().addCookies([
      {
        name: "deerflow_session",
        value: "fake-cookie-value-for-middleware-check",
        url: "http://localhost:3000",
        httpOnly: true,
      },
    ]);
  }
}

// ---------------------------------------------------------------------------
// A2 admin-read route mocks — opt-in per spec via mockAdmin(page, opts).
// ---------------------------------------------------------------------------

export interface MockAdminOptions {
  tenants?: OffsetListResponse<TenantRow>;
  tenantDetail?: Record<number, TenantDetail>;
  users?: OffsetListResponse<UserRow>;
  userDetail?: Record<number, UserRow>;
  workspaces?: OffsetListResponse<WorkspaceRow>;
  workspaceMembers?: Record<number, OffsetListResponse<WorkspaceMemberRow>>;
  tokens?: OffsetListResponse<TokenRow>;
  audit?: CursorListResponse<AuditRow>;
  auditPage2?: CursorListResponse<AuditRow>; // served when ?cursor= is set
  roles?: { roles: RoleRow[] };
}

export async function mockAdmin(
  page: Page,
  opts: MockAdminOptions = {},
): Promise<void> {
  // /api/admin/tenants/{id} — register BEFORE the list route so the regex
  // beats the wildcard.
  await page.route(/\/api\/admin\/tenants\/(\d+)/, (route: Route) => {
    const id = Number(
      (/\/tenants\/(\d+)/.exec(route
        .request()
        .url()))?.[1] ?? 0,
    );
    const detail = opts.tenantDetail?.[id];
    return route.fulfill(
      detail
        ? {
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(detail),
          }
        : { status: 404, body: "" },
    );
  });

  await page.route("**/api/admin/tenants*", (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(opts.tenants ?? { items: [], total: 0 }),
    }),
  );

  // /api/tenants/{tid}/users/{uid} — register before the list route.
  await page.route(
    /\/api\/tenants\/(\d+)\/users\/(\d+)/,
    (route: Route) => {
      const uid = Number(
        (/\/users\/(\d+)/.exec(route
          .request()
          .url()))?.[1] ?? 0,
      );
      const detail = opts.userDetail?.[uid];
      return route.fulfill(
        detail
          ? {
              status: 200,
              contentType: "application/json",
              body: JSON.stringify(detail),
            }
          : { status: 404, body: "" },
      );
    },
  );

  await page.route(/\/api\/tenants\/(\d+)\/users(\?|$)/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(opts.users ?? { items: [], total: 0 }),
    }),
  );

  await page.route(
    /\/api\/tenants\/(\d+)\/workspaces\/(\d+)\/members/,
    (route: Route) => {
      const wid = Number(
        (/\/workspaces\/(\d+)\/members/.exec(route
          .request()
          .url()))?.[1] ?? 0,
      );
      const data = opts.workspaceMembers?.[wid] ?? { items: [], total: 0 };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(data),
      });
    },
  );

  await page.route(
    /\/api\/tenants\/(\d+)\/workspaces(\?|$)/,
    (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(opts.workspaces ?? { items: [], total: 0 }),
      }),
  );

  await page.route(/\/api\/tenants\/(\d+)\/tokens/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(opts.tokens ?? { items: [], total: 0 }),
    }),
  );

  await page.route(/\/api\/tenants\/(\d+)\/audit/, (route: Route) => {
    const hasCursor = route.request().url().includes("cursor=");
    const payload =
      hasCursor && opts.auditPage2
        ? opts.auditPage2
        : (opts.audit ?? { items: [], next_cursor: null });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });

  await page.route("**/api/roles", (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(opts.roles ?? { roles: [] }),
    }),
  );
}

// ---------------------------------------------------------------------------
// A3 admin-write + A4 me-tokens/sessions route mocks. Each call records the
// last request body so tests can assert payloads. Pass `{ ok: false }` to make
// a route return 4xx.
// ---------------------------------------------------------------------------

export interface MockWritesRecorder {
  createUser: { body: unknown }[];
  addMember: { body: unknown }[];
  patchMember: { body: unknown }[];
  removeMember: { url: string }[];
  createTenantToken: { body: unknown }[];
  revokeTenantToken: { url: string }[];
  createMyToken: { body: unknown }[];
  revokeMyToken: { url: string }[];
  revokeMySession: { url: string }[];
  createTenant: { body: unknown }[];
  updateTenant: { body: unknown; url: string }[];
  deleteTenant: { url: string }[];
  createWorkspace: { body: unknown }[];
  updateWorkspace: { body: unknown; url: string }[];
  deleteWorkspace: { url: string }[];
}

export interface MockWritesOptions {
  failCreateUser?: boolean;
  myTokens?: Array<{
    id: number;
    name: string;
    prefix: string;
    scopes: string[];
    workspace_id: number | null;
    created_at: string | null;
    expires_at: string | null;
    last_used_at: string | null;
  }>;
  mySessions?: Array<{
    sid: string;
    created_at: string | null;
    ip: string | null;
    user_agent: string | null;
  }>;
}

export async function mockWrites(
  page: Page,
  opts: MockWritesOptions = {},
): Promise<MockWritesRecorder> {
  const rec: MockWritesRecorder = {
    createUser: [],
    addMember: [],
    patchMember: [],
    removeMember: [],
    createTenantToken: [],
    revokeTenantToken: [],
    createMyToken: [],
    revokeMyToken: [],
    revokeMySession: [],
    createTenant: [],
    updateTenant: [],
    deleteTenant: [],
    createWorkspace: [],
    updateWorkspace: [],
    deleteWorkspace: [],
  };

  await page.route(
    /\/api\/tenants\/(\d+)\/users$/,
    async (route: Route) => {
      const req = route.request();
      if (req.method() === "POST") {
        const body = req.postDataJSON?.() ?? null;
        rec.createUser.push({ body });
        if (opts.failCreateUser) {
          return route.fulfill({
            status: 409,
            contentType: "application/json",
            body: JSON.stringify({ detail: "already a member" }),
          });
        }
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: 999,
            email: (body as { email?: string } | null)?.email ?? "x@y.com",
            display_name: null,
            avatar_url: null,
            status: 1,
            last_login_at: null,
          }),
        });
      }
      return route.fallback();
    },
  );

  await page.route(
    /\/api\/tenants\/(\d+)\/workspaces\/(\d+)\/members\/(\d+)$/,
    async (route: Route) => {
      const req = route.request();
      if (req.method() === "PATCH") {
        const body = req.postDataJSON?.() ?? null;
        rec.patchMember.push({ body });
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: 11,
            email: "b@b.com",
            display_name: "Bob",
            avatar_url: null,
            status: 1,
            role: (body as { role?: string } | null)?.role ?? "member",
            joined_at: null,
          }),
        });
      }
      if (req.method() === "DELETE") {
        rec.removeMember.push({ url: req.url() });
        return route.fulfill({ status: 204, body: "" });
      }
      return route.fallback();
    },
  );

  await page.route(
    /\/api\/tenants\/(\d+)\/workspaces\/(\d+)\/members$/,
    async (route: Route) => {
      const req = route.request();
      if (req.method() === "POST") {
        const body = req.postDataJSON?.() ?? null;
        rec.addMember.push({ body });
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: (body as { user_id?: number } | null)?.user_id ?? 11,
            email: "b@b.com",
            display_name: "Bob",
            avatar_url: null,
            status: 1,
            role: (body as { role?: string } | null)?.role ?? "member",
            joined_at: null,
          }),
        });
      }
      return route.fallback();
    },
  );

  await page.route(
    /\/api\/tenants\/(\d+)\/tokens\/(\d+)$/,
    async (route: Route) => {
      const req = route.request();
      if (req.method() === "DELETE") {
        rec.revokeTenantToken.push({ url: req.url() });
        return route.fulfill({ status: 204, body: "" });
      }
      return route.fallback();
    },
  );
  await page.route(
    /\/api\/tenants\/(\d+)\/tokens$/,
    async (route: Route) => {
      const req = route.request();
      if (req.method() === "POST") {
        const body = req.postDataJSON?.() ?? null;
        rec.createTenantToken.push({ body });
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: 200,
            plaintext: "dft_PLAINTEXT_ONLY_ONCE_xyz",
            prefix: "dft_PLAINTEX",
          }),
        });
      }
      return route.fallback();
    },
  );

  await page.route(/\/api\/me\/tokens(\/(\d+))?$/, async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const idMatch = /\/tokens\/(\d+)$/.exec(url);
    if (req.method() === "GET" && !idMatch) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(opts.myTokens ?? []),
      });
    }
    if (req.method() === "POST" && !idMatch) {
      const body = req.postDataJSON?.() ?? null;
      rec.createMyToken.push({ body });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 300,
          plaintext: "dft_MY_PLAINTEXT_abc",
          prefix: "dft_MY_PLAIN",
        }),
      });
    }
    if (req.method() === "DELETE" && idMatch) {
      rec.revokeMyToken.push({ url });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "revoked" }),
      });
    }
    return route.fallback();
  });

  await page.route(
    /\/api\/me\/sessions(\/[A-Za-z0-9_-]+)?$/,
    async (route: Route) => {
      const req = route.request();
      const url = req.url();
      const sidMatch = /\/sessions\/([A-Za-z0-9_-]+)$/.exec(url);
      if (req.method() === "GET" && !sidMatch) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(opts.mySessions ?? []),
        });
      }
      if (req.method() === "DELETE" && sidMatch) {
        rec.revokeMySession.push({ url });
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ status: "revoked" }),
        });
      }
      return route.fallback();
    },
  );

  const getJson = (route: Route) => {
    try {
      return (route.request().postDataJSON() as unknown) ?? null;
    } catch {
      return null;
    }
  };

  // /api/admin/tenants/{id} — PATCH rename, DELETE soft-delete
  await page.route(
    /\/api\/admin\/tenants\/(\d+)$/,
    async (route: Route) => {
      const req = route.request();
      const url = req.url();
      const id = Number((/\/tenants\/(\d+)$/.exec(url))?.[1] ?? 0);
      if (req.method() === "PATCH") {
        const body = getJson(route);
        rec.updateTenant.push({ body, url });
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id,
            slug: "acme",
            name: (body as { name?: string } | null)?.name ?? "Acme",
            plan: "free",
            status: 1,
            created_at: null,
            member_count: 0,
            workspace_count: 0,
          }),
        });
      }
      if (req.method() === "DELETE") {
        rec.deleteTenant.push({ url });
        return route.fulfill({ status: 204, body: "" });
      }
      return route.fallback();
    },
  );

  // /api/admin/tenants — POST create
  await page.route(
    /\/api\/admin\/tenants(\?|$)/,
    async (route: Route) => {
      const req = route.request();
      if (req.method() === "POST") {
        const body = getJson(route);
        rec.createTenant.push({ body });
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: 99,
            slug: (body as { slug?: string } | null)?.slug ?? "new",
            name: (body as { name?: string } | null)?.name ?? "New",
            plan: "free",
            status: 1,
            created_at: null,
          }),
        });
      }
      return route.fallback();
    },
  );

  // /api/tenants/{tid}/workspaces/{wid} — PATCH rename, DELETE
  await page.route(
    /\/api\/tenants\/(\d+)\/workspaces\/(\d+)$/,
    async (route: Route) => {
      const req = route.request();
      const url = req.url();
      const wid = Number((/\/workspaces\/(\d+)$/.exec(url))?.[1] ?? 0);
      if (req.method() === "PATCH") {
        const body = getJson(route);
        rec.updateWorkspace.push({ body, url });
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: wid,
            tenant_id: 1,
            slug: "main",
            name: (body as { name?: string } | null)?.name ?? "Main",
            description: null,
            created_at: null,
            member_count: 0,
          }),
        });
      }
      if (req.method() === "DELETE") {
        rec.deleteWorkspace.push({ url });
        return route.fulfill({ status: 204, body: "" });
      }
      return route.fallback();
    },
  );

  // /api/tenants/{tid}/workspaces — POST create (catches ?limit= etc via (\?|$))
  await page.route(
    /\/api\/tenants\/(\d+)\/workspaces(\?|$)/,
    async (route: Route) => {
      const req = route.request();
      if (req.method() === "POST") {
        const body = getJson(route);
        rec.createWorkspace.push({ body });
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: 88,
            tenant_id: 1,
            slug: (body as { slug?: string } | null)?.slug ?? "new",
            name: (body as { name?: string } | null)?.name ?? "New",
            description: null,
            created_at: null,
            member_count: 0,
          }),
        });
      }
      return route.fallback();
    },
  );

  return rec;
}
