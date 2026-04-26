# M7A Deferred Items — Implementation Plan

> **实施状态（2026-04-27 复核）：** ✅ 全部 53 个 Step 已落地。
> - **Item 4 RBAC matrix E2E：** `tenants-new-btn` / `workspaces-new-btn` testid + audit `<RequirePermission>` + `A4-rbac-matrix.spec.ts` 全部已建。
> - **Item 2 create+rename+delete：** [admin_writes.py](../../../backend/app/gateway/identity/routers/admin_writes.py) 6 个写端点（`create_tenant` / `update_tenant` / `delete_tenant` / `create_workspace` / `update_workspace` / `delete_workspace`）+ audit 测试全部已加。
> - **Item 1 react-hook-form + zod：** [schemas.ts](../../../frontend/src/core/identity/schemas.ts)、[zod-i18n.ts](../../../frontend/src/core/identity/zod-i18n.ts) 已建；admin 写表单全部使用 `useForm` + `zodResolver`；[me.py:106 patch_me](../../../backend/app/gateway/identity/routers/me.py#L106) 已加。
> - **Item 3 i18n sweep：** admin 命名空间 + en-US/zh-CN locale 已扩展，admin 页面英文字面量已替换为 `useI18n()` 键。
> - **组件命名差异：** 计划里的 `<ConfirmDialog>` 实际以 [`InlineConfirm.tsx`](../../../frontend/src/core/identity/components/InlineConfirm.tsx) 名称落地，功能等价（被 tenants/[id]、workspaces/[id]、tokens、org-keys 引用）。
> - **手工验证项：** Playwright matrix / write spec 是否在本地稳定运行需要人工执行；本次复核仅核对了源代码存在性。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the four deferred M7A items — RBAC matrix E2E, tenant/workspace create+rename+delete, react-hook-form+zod refactor with `PATCH /api/me`, and i18n sweep — onto `main` with all gates green.

**Architecture:** Sequential, in spec order (4 → 2 → 1 → 3). Each item is a single commit (or 2: backend+frontend) and a green gate. No new feature branch — work on `main` per `feedback_local_only_workflow`. The matrix lands first so it acts as the regression test for items 2 and 1.

**Tech Stack:** Next.js 15 App Router · TanStack Query · Playwright · shadcn/ui · FastAPI · SQLAlchemy 2.0 · pytest · `react-hook-form@^7.54` + `@hookform/resolvers@^3.10` + `zod@^3.24`

**Spec:** [`docs/superpowers/specs/2026-04-24-m7a-deferred-items-design.md`](../specs/2026-04-24-m7a-deferred-items-design.md)

---

## File map

| Path | Status | Owner item |
|---|---|---|
| `frontend/tests/e2e/identity/A4-rbac-matrix.spec.ts` | NEW | 4 |
| `frontend/src/app/(admin)/admin/tenants/page.tsx` | MODIFY (add `tenants-new-btn` testid + dialog) | 2, 1 |
| `frontend/src/app/(admin)/admin/tenants/[id]/page.tsx` | MODIFY (rename + delete) | 2, 1 |
| `frontend/src/app/(admin)/admin/workspaces/page.tsx` | MODIFY (add `workspaces-new-btn` + dialog) | 2, 1 |
| `frontend/src/app/(admin)/admin/workspaces/[id]/page.tsx` | MODIFY (rename + delete) | 2, 1 |
| `frontend/src/core/identity/components/CopyableSecret.tsx` | NEW | 2 |
| `frontend/src/core/identity/components/ConfirmDialog.tsx` | NEW | 2 |
| `frontend/src/core/identity/api.ts` | MODIFY (6 new wrappers + updateMe) | 2, 1 |
| `frontend/src/core/identity/hooks.ts` | MODIFY (6 mutation hooks + useUpdateMe) | 2, 1 |
| `frontend/src/core/identity/types.ts` | MODIFY (CreateTenantBody etc.) | 2 |
| `frontend/src/core/identity/schemas.ts` | NEW (zod schemas) | 1 |
| `frontend/src/core/identity/zod-i18n.ts` | NEW (custom error map) | 3 |
| `frontend/src/core/i18n/locales/types.ts` | MODIFY (admin namespace expansion) | 3 |
| `frontend/src/core/i18n/locales/en-US.ts` | MODIFY | 3 |
| `frontend/src/core/i18n/locales/zh-CN.ts` | MODIFY | 3 |
| `frontend/tests/e2e/identity/A3-tenant-workspace.spec.ts` | NEW | 2 |
| `backend/app/gateway/identity/routers/admin_writes.py` | MODIFY (+6 routes) | 2 |
| `backend/tests/identity/test_admin_writes.py` | MODIFY (+18 tests, +audit param test) | 2 |

---

## Item 4 — RBAC matrix E2E

### Task 1: Add `tenants-new-btn` and `workspaces-new-btn` testids

**Files:**
- Modify: `frontend/src/app/(admin)/admin/tenants/page.tsx`
- Modify: `frontend/src/app/(admin)/admin/workspaces/page.tsx`

**Why:** Item 4's matrix needs a stable selector for these buttons. Item 2 will wire the dialogs onto these buttons; for now they exist as no-op buttons gated by `<RequirePermission>` so the matrix can assert visibility per role.

- [x] **Step 1: Read current `tenants/page.tsx`**

```bash
cat frontend/src/app/\(admin\)/admin/tenants/page.tsx
```

- [x] **Step 2: Add gated New Tenant button to tenants page**

In `tenants/page.tsx`, add this near the page title (mirror the pattern from `tokens/page.tsx:80-86`):

```tsx
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import { Button } from "@/components/ui/button";

// ...inside the page header:
<RequirePermission perm="tenant:create">
  <Button data-testid="tenants-new-btn" disabled>
    New Tenant
  </Button>
</RequirePermission>
```

`disabled` is intentional — Item 2 wires the click handler. The matrix only asserts visibility.

- [x] **Step 3: Same for workspaces/page.tsx with `workspace:create` perm**

```tsx
<RequirePermission perm="workspace:create">
  <Button data-testid="workspaces-new-btn" disabled>
    New Workspace
  </Button>
</RequirePermission>
```

- [x] **Step 4: Type-check**

Run: `cd frontend && pnpm check`
Expected: PASS (no new errors).

- [x] **Step 5: Commit**

```bash
git add frontend/src/app/\(admin\)/admin/tenants/page.tsx frontend/src/app/\(admin\)/admin/workspaces/page.tsx
git commit -m "feat(identity-ui): add tenants-new-btn + workspaces-new-btn placeholders for RBAC matrix"
```

### Task 2: Audit page — assert authenticated render via testid

**Files:**
- Modify: `frontend/src/app/(admin)/admin/audit/page.tsx`

**Why:** Item 4's matrix needs a "view audit" assertion. The simplest cell semantic: gate the page wrapper on `audit:read`. If the role lacks the perm, render an `audit-denied` empty state. The matrix asserts `audit-page` testid for allowed roles, `audit-denied` for denied.

- [x] **Step 1: Read audit page header section**

```bash
grep -n "data-testid\|audit-page\|RequirePermission\|audit:read" frontend/src/app/\(admin\)/admin/audit/page.tsx | head
```

- [x] **Step 2: Wrap page body in `<RequirePermission perm="audit:read">` with `audit-denied` fallback**

If `audit-page` testid already exists, leave it. Wrap as:

```tsx
<RequirePermission
  perm="audit:read"
  fallback={
    <section className="p-6" data-testid="audit-denied">
      <p className="text-muted-foreground">
        You do not have permission to view audit logs.
      </p>
    </section>
  }
>
  {/* existing audit page body, must include data-testid="audit-page" on its root */}
</RequirePermission>
```

- [x] **Step 3: Type-check + commit**

```bash
cd frontend && pnpm check && cd .. && \
git add frontend/src/app/\(admin\)/admin/audit/page.tsx && \
git commit -m "feat(identity-ui): gate audit page with audit:read + audit-denied fallback"
```

### Task 3: Write the matrix spec (failing first)

**Files:**
- Create: `frontend/tests/e2e/identity/A4-rbac-matrix.spec.ts`

- [x] **Step 1: Write the spec file**

```ts
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
    "membership:invite",
    "membership:remove",
    "token:create",
    "token:revoke",
    "audit:read",
  ],
  tenant_owner: [
    "tenant:read",
    "tenant:write",
    "workspace:read",
    "workspace:create",
    "workspace:write",
    "workspace:delete",
    "membership:invite",
    "membership:remove",
    "token:create",
    "token:revoke",
    "audit:read",
  ],
  workspace_admin: [
    "tenant:read",
    "workspace:read",
    "workspace:write",
    "membership:invite",
    "membership:remove",
  ],
  member: ["tenant:read", "workspace:read"],
  guest: ["tenant:read"],
};

interface Cell {
  page: string;
  testId: string;
  /** When set, navigation requires mockAdmin scaffolding (workspace member page needs id=7). */
  needsAdmin?: boolean;
}

const ACTION: Record<Action, Cell> = {
  "create-tenant": {
    page: "/admin/tenants",
    testId: "tenants-new-btn",
    needsAdmin: true,
  },
  "create-user": {
    page: "/admin/users",
    testId: "users-new-btn",
    needsAdmin: true,
  },
  "create-token": {
    page: "/admin/tokens",
    testId: "tokens-new-btn",
    needsAdmin: true,
  },
  "add-workspace-member": {
    page: "/admin/workspaces/7/members",
    testId: "member-add-btn",
    needsAdmin: true,
  },
  "view-audit": {
    page: "/admin/audit",
    testId: "audit-page",
    needsAdmin: true,
  },
  "create-workspace": {
    page: "/admin/workspaces",
    testId: "workspaces-new-btn",
    needsAdmin: true,
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

  // workspace_admin — only workspace-scoped writes
  ["workspace_admin", "create-tenant", "deny"],
  ["workspace_admin", "create-user", "deny"],
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

  // guest — read-only
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

      const cell = ACTION[action];
      if (cell.needsAdmin) {
        await mockAdmin(page, {
          tenants: { items: [], total: 0 },
          users: { items: [], total: 0 },
          workspaces: { items: [], total: 0 },
          tokens: { items: [], total: 0 },
          workspaceMembers: { 7: { items: [], total: 0 } },
          audit: { items: [], next_cursor: null },
        });
      }

      await page.goto(cell.page);

      if (action === "view-audit") {
        // view-audit allow vs deny is page-body vs fallback, not a button.
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
```

- [x] **Step 2: Run the spec — expect failures only on the cells that depend on Task 1/2 having shipped (none should fail)**

Run: `cd frontend && pnpm test:e2e -g "rbac-matrix" --reporter=list`

Expected: 30/30 pass. If anything fails, the failing cell points to a missing testid or a perm gate not wired — fix the page, re-run.

- [x] **Step 3: Commit**

```bash
git add frontend/tests/e2e/identity/A4-rbac-matrix.spec.ts
git commit -m "test(identity-ui): RBAC matrix 5 roles x 6 actions (M7A item 4)"
```

---

## Item 2 — create/PATCH/DELETE for tenants + workspaces

### Task 4: Backend — extend `admin_writes.py` with tenant create/patch/delete

**Files:**
- Modify: `backend/app/gateway/identity/routers/admin_writes.py`
- Modify: `backend/tests/identity/test_admin_writes.py`

- [x] **Step 1: Read existing module to mirror its style**

```bash
sed -n '1,80p' backend/app/gateway/identity/routers/admin_writes.py
```

- [x] **Step 2: Write failing tests first**

Append to `backend/tests/identity/test_admin_writes.py`:

```python
# --- Tenant CRUD (Item 2) ---

async def test_create_tenant_requires_platform_perm(client_no_perm):
    r = await client_no_perm.post(
        "/api/admin/tenants", json={"slug": "acme", "name": "Acme"}
    )
    assert r.status_code == 403


async def test_create_tenant_happy_path(client_platform_admin, db_session):
    r = await client_platform_admin.post(
        "/api/admin/tenants", json={"slug": "acme", "name": "Acme"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "acme"
    assert body["id"] > 0


async def test_create_tenant_slug_conflict_returns_409(
    client_platform_admin, existing_tenant
):
    r = await client_platform_admin.post(
        "/api/admin/tenants",
        json={"slug": existing_tenant.slug, "name": "dup"},
    )
    assert r.status_code == 409


async def test_patch_tenant_updates_name(
    client_tenant_owner, existing_tenant
):
    r = await client_tenant_owner.patch(
        f"/api/admin/tenants/{existing_tenant.id}",
        json={"name": "Renamed"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"


async def test_patch_tenant_cross_tenant_returns_404(
    client_tenant_owner, other_tenant
):
    r = await client_tenant_owner.patch(
        f"/api/admin/tenants/{other_tenant.id}", json={"name": "x"}
    )
    assert r.status_code == 404


async def test_delete_tenant_soft_deletes(
    client_platform_admin, existing_tenant, db_session
):
    r = await client_platform_admin.delete(
        f"/api/admin/tenants/{existing_tenant.id}"
    )
    assert r.status_code == 204
    db_session.expire_all()
    refreshed = db_session.get(Tenant, existing_tenant.id)
    assert refreshed.deleted_at is not None
```

Mirror the same 6 tests for workspaces (`POST /api/tenants/{tid}/workspaces`, `PATCH`, `DELETE`).

- [x] **Step 3: Run failing**

Run: `cd backend && pytest tests/identity/test_admin_writes.py -k "create_tenant or patch_tenant or delete_tenant or create_workspace or patch_workspace or delete_workspace" -x`

Expected: FAIL with "404 not found" / route missing.

- [x] **Step 4: Implement the 6 routes**

Add to `admin_writes.py`:

```python
class CreateTenantBody(BaseModel):
    slug: constr(regex=r"^[a-z0-9-]{2,64}$")
    name: constr(min_length=1, max_length=128)


class UpdateTenantBody(BaseModel):
    name: Optional[constr(min_length=1, max_length=128)] = None
    settings: Optional[dict] = None


@router.post("/api/admin/tenants", status_code=201)
@requires("tenant:create")
async def create_tenant(request: Request, body: CreateTenantBody):
    db = request.state.db
    if db.query(Tenant).filter_by(slug=body.slug).first():
        raise HTTPException(status_code=409, detail="slug taken")
    tenant = Tenant(slug=body.slug, name=body.name)
    db.add(tenant)
    db.commit()
    return TenantOut.from_orm(tenant)


@router.patch("/api/admin/tenants/{tid}")
@requires("tenant:write")
async def update_tenant(request: Request, tid: int, body: UpdateTenantBody):
    db = request.state.db
    tenant = _get_tenant_or_404(request, tid)
    if body.name is not None:
        tenant.name = body.name
    if body.settings is not None:
        tenant.settings = body.settings
    db.commit()
    return TenantOut.from_orm(tenant)


@router.delete("/api/admin/tenants/{tid}", status_code=204)
@requires("tenant:delete")
async def delete_tenant(request: Request, tid: int):
    db = request.state.db
    tenant = _get_tenant_or_404(request, tid)
    tenant.deleted_at = datetime.utcnow()
    db.commit()
```

`_get_tenant_or_404` checks `request.identity.is_platform_admin` OR `tid == request.identity.active_tenant_id`; otherwise 404.

Mirror for workspaces with `workspace:create` / `workspace:write` / `workspace:delete` and tenant-scoped path.

- [x] **Step 5: Run tests passing**

Run: `cd backend && pytest tests/identity/test_admin_writes.py -x`
Expected: PASS (existing 16 + new 12).

- [x] **Step 6: Commit**

```bash
git add backend/app/gateway/identity/routers/admin_writes.py backend/tests/identity/test_admin_writes.py
git commit -m "feat(identity): tenant + workspace CRUD endpoints (M7A item 2 backend)"
```

### Task 5: Backend — audit emission test

**Files:**
- Modify: `backend/tests/identity/test_admin_writes.py`

- [x] **Step 1: Add parametrized audit test**

```python
@pytest.mark.parametrize(
    "method,path,body,action_name",
    [
        ("POST", "/api/admin/tenants", {"slug": "z", "name": "Z"}, "tenant.create"),
        ("PATCH", "/api/admin/tenants/{tid}", {"name": "y"}, "tenant.update"),
        ("DELETE", "/api/admin/tenants/{tid}", None, "tenant.delete"),
        ("POST", "/api/tenants/{tid}/workspaces", {"slug": "w", "name": "W"}, "workspace.create"),
        ("PATCH", "/api/tenants/{tid}/workspaces/{wid}", {"name": "x"}, "workspace.update"),
        ("DELETE", "/api/tenants/{tid}/workspaces/{wid}", None, "workspace.delete"),
        # Backfill existing endpoints
        ("POST", "/api/tenants/{tid}/users", {"email": "n@a.b", "display_name": "n"}, "user.create"),
        ("POST", "/api/tenants/{tid}/tokens", {"name": "t"}, "token.create"),
        ("POST", "/api/tenants/{tid}/workspaces/{wid}/members", {"user_id": 2, "role": "member"}, "membership.invite"),
        ("DELETE", "/api/tenants/{tid}/workspaces/{wid}/members/{uid}", None, "membership.remove"),
    ],
)
async def test_write_endpoints_emit_audit(
    client_platform_admin, db_session, audit_collector,
    method, path, body, action_name,
    seeded_tenant, seeded_workspace, seeded_user,
):
    formatted = path.format(
        tid=seeded_tenant.id, wid=seeded_workspace.id, uid=seeded_user.id
    )
    r = await client_platform_admin.request(method, formatted, json=body)
    assert r.status_code in (200, 201, 204)
    rows = audit_collector.flush()
    assert any(row.action == action_name for row in rows), (
        f"no audit row for {action_name}; got {[r.action for r in rows]}"
    )
```

`audit_collector` is a pytest fixture that snapshots `AuditMiddleware`'s buffer; if it doesn't exist yet, add it next to the existing `client_*` fixtures in `tests/identity/conftest.py`. Pattern:

```python
@pytest.fixture
def audit_collector(monkeypatch):
    rows: list[AuditEvent] = []
    from app.gateway.identity.audit import middleware as audit_mw
    original = audit_mw._buffer.append
    monkeypatch.setattr(audit_mw._buffer, "append", lambda e: (rows.append(e), original(e)))
    return SimpleNamespace(flush=lambda: rows[:])
```

If the actual audit buffer API differs, adapt — read `app/gateway/identity/audit/middleware.py` first.

- [x] **Step 2: Run, then iterate until green**

Run: `cd backend && pytest tests/identity/test_admin_writes.py::test_write_endpoints_emit_audit -x -v`
Expected: 10/10 PASS.

- [x] **Step 3: Commit**

```bash
git add backend/tests/identity/test_admin_writes.py backend/tests/identity/conftest.py
git commit -m "test(identity): audit emission for all write endpoints (M7A item 2)"
```

### Task 6: Frontend — `<CopyableSecret>` and `<ConfirmDialog>` components

**Files:**
- Create: `frontend/src/core/identity/components/CopyableSecret.tsx`
- Create: `frontend/src/core/identity/components/ConfirmDialog.tsx`

- [x] **Step 1: Read existing inline copy logic in `tokens/page.tsx`**

```bash
sed -n '280,330p' frontend/src/app/\(admin\)/admin/tokens/page.tsx
```

- [x] **Step 2: Write `CopyableSecret`**

```tsx
// frontend/src/core/identity/components/CopyableSecret.tsx
"use client";

import { Eye, EyeOff, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

interface Props {
  value: string;
  testIdPrefix?: string;
}

export function CopyableSecret({ value, testIdPrefix = "secret" }: Props) {
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-md border bg-muted px-3 py-2 font-mono text-sm">
      <span className="flex-1 break-all" data-testid={`${testIdPrefix}-value`}>
        {revealed ? value : "•".repeat(Math.min(value.length, 32))}
      </span>
      <Button
        type="button"
        size="icon"
        variant="ghost"
        onClick={() => setRevealed((v) => !v)}
        data-testid={`${testIdPrefix}-toggle`}
      >
        {revealed ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </Button>
      <Button
        type="button"
        size="icon"
        variant="ghost"
        data-testid={`${testIdPrefix}-copy`}
        onClick={async () => {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        <Copy className="size-4" />
      </Button>
      {copied && <span className="text-xs text-muted-foreground">Copied</span>}
    </div>
  );
}
```

- [x] **Step 3: Write `ConfirmDialog`**

```tsx
// frontend/src/core/identity/components/ConfirmDialog.tsx
"use client";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

interface Props {
  trigger: React.ReactNode;
  title: string;
  description?: string;
  confirmLabel?: string;
  onConfirm: () => void | Promise<void>;
  testIdPrefix: string;
  destructive?: boolean;
}

export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel = "Confirm",
  onConfirm,
  testIdPrefix,
  destructive = true,
}: Props) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild data-testid={`${testIdPrefix}-trigger`}>
        {trigger}
      </AlertDialogTrigger>
      <AlertDialogContent data-testid={`${testIdPrefix}-dialog`}>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description && (
            <AlertDialogDescription>{description}</AlertDialogDescription>
          )}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel data-testid={`${testIdPrefix}-cancel`}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction asChild>
            <Button
              variant={destructive ? "destructive" : "default"}
              onClick={onConfirm}
              data-testid={`${testIdPrefix}-confirm`}
            >
              {confirmLabel}
            </Button>
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
```

If `alert-dialog` shadcn component is missing, scaffold it: `cd frontend && pnpm dlx shadcn@latest add alert-dialog`.

- [x] **Step 4: Refactor `tokens/page.tsx` and `profile/page.tsx` to consume `CopyableSecret`**

Replace the inline `<input value={plaintext} readonly>` + manual copy button with `<CopyableSecret value={plaintext} testIdPrefix="token-plaintext" />`. Preserve the `token-plaintext-value` and `token-copy-btn` testids by passing `testIdPrefix="token-plaintext"`.

If existing E2E uses `token-copy-btn` exactly, also accept that prefix transition: keep the original testids by passing `testIdPrefix="token-plaintext"` so `token-plaintext-copy` exists; then update the existing `A3-write-actions.spec.ts` selector (or add an alias). Verify by running the spec.

- [x] **Step 5: Type-check + commit**

```bash
cd frontend && pnpm check && cd .. && \
git add frontend/src/core/identity/components/CopyableSecret.tsx frontend/src/core/identity/components/ConfirmDialog.tsx frontend/src/app/\(admin\)/admin/tokens/page.tsx frontend/src/app/\(admin\)/admin/profile/page.tsx && \
git commit -m "refactor(identity-ui): extract CopyableSecret + ConfirmDialog (M7A item 2)"
```

### Task 7: Frontend — wrappers + hooks for tenant/workspace CRUD

**Files:**
- Modify: `frontend/src/core/identity/types.ts`
- Modify: `frontend/src/core/identity/api.ts`
- Modify: `frontend/src/core/identity/hooks.ts`

- [x] **Step 1: Add types**

In `types.ts`:

```ts
export interface CreateTenantBody { slug: string; name: string; }
export interface UpdateTenantBody { name?: string; settings?: Record<string, unknown>; }
export interface CreateWorkspaceBody { slug: string; name: string; }
export interface UpdateWorkspaceBody { name?: string; }
export interface UpdateMeBody { display_name?: string; avatar_url?: string | null; }
```

- [x] **Step 2: Add API wrappers**

In `api.ts`:

```ts
createTenant: (body: CreateTenantBody) =>
  identityFetch<TenantDetail>("/api/admin/tenants", { method: "POST", body }),
updateTenant: (id: number, body: UpdateTenantBody) =>
  identityFetch<TenantDetail>(`/api/admin/tenants/${id}`, { method: "PATCH", body }),
deleteTenant: (id: number) =>
  identityFetch<void>(`/api/admin/tenants/${id}`, { method: "DELETE" }),
createWorkspace: (tid: number, body: CreateWorkspaceBody) =>
  identityFetch<WorkspaceRow>(`/api/tenants/${tid}/workspaces`, { method: "POST", body }),
updateWorkspace: (tid: number, wid: number, body: UpdateWorkspaceBody) =>
  identityFetch<WorkspaceRow>(`/api/tenants/${tid}/workspaces/${wid}`, { method: "PATCH", body }),
deleteWorkspace: (tid: number, wid: number) =>
  identityFetch<void>(`/api/tenants/${tid}/workspaces/${wid}`, { method: "DELETE" }),
updateMe: (body: UpdateMeBody) =>
  identityFetch<MeResponse>("/api/me", { method: "PATCH", body }),
```

- [x] **Step 3: Add hooks (mutations + invalidations)**

In `hooks.ts`, mirror the existing `useCreateUser` pattern. Each mutation invalidates the relevant cache key:

```ts
export function useCreateTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: identityApi.createTenant,
    onSuccess: () => qc.invalidateQueries({ queryKey: identityKeys.tenants() }),
  });
}
// ... useUpdateTenant, useDeleteTenant, useCreateWorkspace, useUpdateWorkspace, useDeleteWorkspace, useUpdateMe
```

`useUpdateMe` invalidates `identityKeys.me()`.

- [x] **Step 4: Type-check + commit**

```bash
cd frontend && pnpm check && cd .. && \
git add frontend/src/core/identity/{api,hooks,types}.ts && \
git commit -m "feat(identity-ui): API + hooks for tenant/workspace CRUD + updateMe (M7A item 2)"
```

### Task 8: Frontend — wire dialogs onto the `tenants-new-btn` and `workspaces-new-btn` placeholders + rename/delete on detail pages

**Files:**
- Modify: `frontend/src/app/(admin)/admin/tenants/page.tsx`
- Modify: `frontend/src/app/(admin)/admin/tenants/[id]/page.tsx`
- Modify: `frontend/src/app/(admin)/admin/workspaces/page.tsx`
- Modify: `frontend/src/app/(admin)/admin/workspaces/[id]/page.tsx`

- [x] **Step 1: Wire New Tenant dialog**

Replace the placeholder `disabled` Button in `tenants/page.tsx` with a `<Dialog>` whose trigger is the `tenants-new-btn` Button (no longer disabled). Form has `slug` + `name` fields with `data-testid="tenants-create-{slug,name,submit}"`. Submit calls `useCreateTenant().mutateAsync(...)`, closes on success.

(Validation here is uncontrolled inputs + manual `required`. Item 1 will refactor to rhf+zod.)

- [x] **Step 2: Wire rename + delete on `tenants/[id]/page.tsx`**

Add a pencil-icon Button next to the tenant name; click opens a small inline dialog with one `name` field calling `useUpdateTenant`. Add a `<ConfirmDialog>` for delete calling `useDeleteTenant`, then `router.push("/admin/tenants")` on success.

- [x] **Step 3: Mirror for workspaces (page + detail)**

`workspaces/[id]/page.tsx` may not exist yet — if not, create a minimal detail page that renders the workspace name + Members link + the rename/delete affordances. Otherwise modify in place.

- [x] **Step 4: Type-check + run RBAC matrix to confirm nothing regressed**

```bash
cd frontend && pnpm check
pnpm test:e2e -g "rbac-matrix" --reporter=list
```

Expected: 30/30 PASS still.

- [x] **Step 5: Commit**

```bash
git add frontend/src/app/\(admin\)/admin/tenants frontend/src/app/\(admin\)/admin/workspaces && \
git commit -m "feat(identity-ui): tenant + workspace create/rename/delete dialogs (M7A item 2)"
```

### Task 9: E2E happy paths for tenant/workspace writes

**Files:**
- Create: `frontend/tests/e2e/identity/A3-tenant-workspace.spec.ts`

- [x] **Step 1: Write spec**

Cover:
1. `platform_admin` creates a tenant — fill slug+name in dialog, submit, mock returns 201, assert toast + invalidation triggered (network call observed).
2. `tenant_owner` creates a workspace.
3. `tenant_owner` renames a tenant.
4. `tenant_owner` deletes a workspace via confirm — assert second click on confirm fires DELETE.
5. `member` does NOT see `tenants-new-btn` (cross-check against matrix; intentional redundancy).

Use `mockAdmin` fixture; intercept the new POST/PATCH/DELETE routes and assert request bodies.

- [x] **Step 2: Run + commit**

```bash
cd frontend && pnpm test:e2e -g "tenant-workspace|rbac-matrix" --reporter=list
git add frontend/tests/e2e/identity/A3-tenant-workspace.spec.ts && \
git commit -m "test(identity-ui): E2E for tenant/workspace CRUD (M7A item 2)"
```

---

## Item 1 — `react-hook-form` + `zod` refactor + `PATCH /api/me`

### Task 10: Add deps + zod schema module

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/src/core/identity/schemas.ts`

- [x] **Step 1: Install**

```bash
cd frontend && pnpm add react-hook-form @hookform/resolvers
```

- [x] **Step 2: Write `schemas.ts`** (full module from spec §"Item 1 → Schemas")

- [x] **Step 3: Verify `<Form>` shadcn primitives exist**

```bash
ls frontend/src/components/ui/form.tsx 2>/dev/null || (cd frontend && pnpm dlx shadcn@latest add form)
```

- [x] **Step 4: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/core/identity/schemas.ts frontend/src/components/ui/form.tsx 2>/dev/null
git commit -m "chore(identity-ui): add react-hook-form + zod schemas module (M7A item 1)"
```

### Task 11: Refactor each dialog to `useForm` + `zodResolver`

**Files:**
- Modify: 8 dialog locations (see spec §"Dialogs refactored")

- [x] **Step 1: Refactor `tokens/page.tsx` New-token dialog**

Replace the `useState`-driven inputs + onClick handler with:

```tsx
const form = useForm<z.infer<typeof newTokenSchema>>({
  resolver: zodResolver(newTokenSchema),
  defaultValues: { name: "", expires_in_days: undefined },
});
const create = useCreateToken();
const onSubmit = form.handleSubmit(async (values) => {
  const result = await create.mutateAsync(values);
  setPlaintext(result.plaintext);
});
return (
  <Form {...form}>
    <form onSubmit={onSubmit}>
      <FormField name="name" control={form.control} render={({ field }) => (
        <FormItem>
          <FormLabel>Name</FormLabel>
          <FormControl><Input data-testid="token-name-input" {...field} /></FormControl>
          <FormMessage />
        </FormItem>
      )} />
      {/* ... */}
      <Button type="submit" data-testid="token-submit-btn" disabled={!form.formState.isValid || form.formState.isSubmitting}>
        Create
      </Button>
    </form>
  </Form>
);
```

PRESERVE every existing testid. Run `pnpm test:e2e -g "A3-write-actions"` after each refactor to confirm no selector breakage.

- [x] **Step 2: Same for `users/page.tsx`, `members/page.tsx`, `tenants/page.tsx`, `tenants/[id]/page.tsx`, `workspaces/page.tsx`, `workspaces/[id]/page.tsx`**

After EACH file: `pnpm test:e2e -g "A3-|rbac-matrix"` green before moving to the next.

- [x] **Step 3: Wire `PATCH /api/me` in `profile/page.tsx` Basic tab**

Use `profileBasicSchema`, `useUpdateMe()`. Render success toast on save. Add testids `profile-basic-{display-name,avatar-url,submit}`.

- [x] **Step 4: Verify schema route matches backend**

```bash
sed -n '1,80p' backend/app/gateway/identity/routers/me.py | grep -A 20 "patch\|PATCH\|update_me"
```

If the backend `PATCH /api/me` schema differs (e.g. only accepts `display_name` not `avatar_url`), narrow `profileBasicSchema` to match. Don't add backend code in this item.

- [x] **Step 5: Full gate**

```bash
cd frontend && pnpm check && pnpm test && pnpm test:e2e --reporter=list
```

Expected: all green.

- [x] **Step 6: Commit**

```bash
git add frontend/src/app/\(admin\)/admin frontend/src/core/identity && \
git commit -m "refactor(identity-ui): rhf + zod for all admin dialogs + PATCH /api/me wiring (M7A item 1)"
```

---

## Item 3 — i18n sweep

### Task 12: Expand `admin` namespace type + locale files

**Files:**
- Modify: `frontend/src/core/i18n/locales/types.ts`
- Modify: `frontend/src/core/i18n/locales/en-US.ts`
- Modify: `frontend/src/core/i18n/locales/zh-CN.ts`
- Create: `frontend/src/core/identity/zod-i18n.ts`

- [x] **Step 1: Add namespace structure to `types.ts`**

Extend the `admin` field with `dialogs`, `validation`, `tables`, `empty`, `toast`, `profile.basic` sub-shapes per spec §"New `admin` keys". Make every leaf `string`.

- [x] **Step 2: Fill en-US.ts and zh-CN.ts**

For zh-CN, prefer concise Mandarin matching v1 product copy in `frontend/src/components/landing/` for terminology consistency.

- [x] **Step 3: Wire zod-i18n custom error map**

```ts
// frontend/src/core/identity/zod-i18n.ts
import { z } from "zod";

import { type Translations } from "@/core/i18n/locales/types";

export function makeZodErrorMap(t: Translations["admin"]["validation"]): z.ZodErrorMap {
  return (issue, ctx) => {
    switch (issue.code) {
      case z.ZodIssueCode.invalid_type:
        return { message: t.required };
      case z.ZodIssueCode.invalid_string:
        if (issue.validation === "email") return { message: t.email };
        if (issue.validation === "url") return { message: t.url };
        if (issue.validation === "regex") return { message: t.slugFormat };
        return { message: ctx.defaultError };
      case z.ZodIssueCode.too_small:
        return { message: t.tooShort };
      case z.ZodIssueCode.too_big:
        return { message: t.tooLong };
      default:
        return { message: ctx.defaultError };
    }
  };
}
```

In a top-level provider (or in each form's `useEffect`), `z.setErrorMap(makeZodErrorMap(t))`.

- [x] **Step 4: Replace remaining English literals in admin pages with `useI18n()` keys**

Sweep every page under `app/(admin)/admin/`. Check with:

```bash
grep -nE '"[A-Z][a-z]+( [a-z]+){1,3}"' frontend/src/app/\(admin\)/admin --include='*.tsx' -r | grep -v "data-testid\|className\|aria-"
```

Treat each match as a candidate; replace if it's user-facing.

- [x] **Step 5: Type-check (catches missing zh keys)**

```bash
cd frontend && pnpm check
```

Expected: PASS — TS errors mean a key exists in en-US but not zh-CN (or vice versa).

- [x] **Step 6: Manual smoke (optional but recommended)**

```bash
cd frontend && pnpm dev
```

Switch language to zh-CN, walk through `/admin/tenants` create + delete, confirm no English leak.

- [x] **Step 7: Final gate + commit**

```bash
cd frontend && pnpm check && pnpm test:e2e --reporter=list
git add frontend/src/core/i18n frontend/src/core/identity/zod-i18n.ts frontend/src/app/\(admin\)/admin && \
git commit -m "i18n(identity-ui): full admin dialog/form/validation sweep zh + en (M7A item 3)"
```

---

## Self-review

**Spec coverage:**
- §Item 4 → Tasks 1-3 ✔
- §Item 2 backend → Tasks 4-5 ✔ (incl. audit emission)
- §Item 2 frontend → Tasks 6-9 ✔ (CopyableSecret, ConfirmDialog, hooks, dialogs, E2E)
- §Item 1 → Tasks 10-11 ✔ (deps, schemas, refactor, PATCH /api/me)
- §Item 3 → Task 12 ✔ (i18n + zod-i18n + sweep)

**Placeholder scan:** No "TBD" / "implement later". Audit-collector fixture has an "if API differs, adapt" — mitigated by "read source first" instruction. Acceptable: backend audit middleware internals aren't fully readable from this plan and the engineer needs to verify shape.

**Type consistency:** `CreateTenantBody`, `useCreateTenant`, `identityKeys.tenants()` all consistent across Tasks 4/7/8. `audit-page` and `audit-denied` testids consistent between Task 2 and Task 3.

**Selector-stability risk:** Task 6 changes `token-plaintext-value` / `token-copy-btn` selectors via `<CopyableSecret testIdPrefix="token-plaintext">`. The existing testids become `token-plaintext-value` (already matches) and `token-plaintext-copy` (was `token-copy-btn`). Mitigation: Task 6 Step 4 explicitly says update the existing E2E spec selector or accept the new prefix.
