# M7A Deferred Items — Design

**Date:** 2026-04-24
**Status:** Approved (user: "go")
**Parent spec:** [2026-04-21-deerflow-identity-foundation-design.md](./2026-04-21-deerflow-identity-foundation-design.md)
**Parent plan:** [2026-04-23-m7a-admin-ui.md](../plans/2026-04-23-m7a-admin-ui.md)

## Why this spec exists

M7A (admin UI) shipped A1–A6 across `feat/m7-admin-ui`. The original A3 + A4 scope contained four items that did not land:

| # | Item | Why it slipped | Cost of leaving it |
|---|---|---|---|
| 4 | `A4-rbac-matrix.spec.ts` (5 roles × 6 actions) | A4 reduced to i18n+docs only | Any future commit can silently loosen permissions and ship green |
| 2 | `create-tenant` / `create-workspace` + `PATCH`/`DELETE` for both | A3 only added member/token/user writes | Fresh `ENABLE_IDENTITY=true` deploy has no UI path to onboard a tenant |
| 1 | `react-hook-form` + `zod` schema validation | A3 used uncontrolled inputs + manual validation | No field-level errors, weak UX, schemas duplicated inline |
| 3 | i18n on dialogs/forms (A6 only did nav + `<h1>`) | A6 scoped to "high-frequency labels" | zh users hit English mid-flow on every write action |

This spec defines what ships and in what order. Each item is independently testable; checkpoints sit between them so a regression in N+1 cannot mask one in N.

## Cross-plan invariants (inherited)

From [parent plans README](../plans/README.md):

1. `ENABLE_IDENTITY=false` ⇒ zero behavior change. New routes mount inside the existing `if ENABLE_IDENTITY` gate in `app/gateway/app.py`.
2. Harness boundary unchanged — no new `app.*` imports from `backend/packages/harness/`.
3. Audit log immutability — new write endpoints MUST emit audit rows; tests assert this (Item 2).
4. Path derived from identity — N/A (no storage changes).
5. Tool whitelist default-deny — N/A (no tool changes).

## Scope

### Item 4 — RBAC matrix E2E (do first)

**File:** `frontend/tests/e2e/identity/A4-rbac-matrix.spec.ts`

**Why first:** The matrix is the regression test for everything else. Items 2 + 1 add or refactor write surfaces; landing the matrix first means each subsequent change runs against it.

**Roles tested:**

| Role | Permissions (driven via `mockIdentity` fixture) |
|---|---|
| `platform_admin` | `tenant:create`, `tenant:write`, `tenant:delete`, plus all tenant-scoped perms |
| `tenant_owner` | `tenant:write`, `workspace:create`, `workspace:write`, `workspace:delete`, `membership:invite`, `membership:remove`, `token:create`, `token:revoke`, `audit:read` |
| `workspace_admin` | `workspace:write`, `membership:invite`, `membership:remove` (within owned workspace only) |
| `member` | `tenant:read`, `workspace:read` only |
| `guest` | `tenant:read` only |

**Actions tested (6):**

1. Create tenant — `/admin/tenants` "New Tenant" button
2. Create user — `/admin/users` "New User" button
3. Create token — `/admin/tokens` "New Token" button
4. Add workspace member — `/admin/workspaces/[id]/members` "Add Member" button
5. View audit page — navigate to `/admin/audit`, assert row count > 0 OR access-denied state
6. Create workspace — `/admin/workspaces` "New Workspace" button

**Assertion per cell (one of):**

- **Allowed**: action button is `visible` AND clicking opens the dialog
- **Denied**: action button is NOT in DOM (the `<RequirePermission>` wrapper hides it). Backend 403 path is covered separately by backend tests; the matrix is purely about UI affordance.

**Implementation:**

```ts
const matrix: Array<[Role, Action, "allow" | "deny"]> = [
  ["platform_admin", "create-tenant", "allow"],
  // ... 30 rows total, generated from a 5×6 declaration
];

for (const [role, action, expected] of matrix) {
  test(`${role} ${expected === "allow" ? "can" : "cannot"} ${action}`, async ({ page }) => {
    await mockIdentity(page, { permissions: PERMS_BY_ROLE[role] });
    await mockBackend(page); // existing fixture
    await page.goto(PAGE_FOR_ACTION[action]);
    const button = page.getByTestId(TESTID_FOR_ACTION[action]);
    if (expected === "allow") {
      await expect(button).toBeVisible();
    } else {
      await expect(button).toHaveCount(0);
    }
  });
}
```

**`data-testid` audit:** every action button gets a stable testid in this item if not already present. The buttons exist today in `tokens/page.tsx`, `users/page.tsx`, `workspaces/[id]/members/page.tsx`. The two from Item 2 (`new-tenant`, `new-workspace`) get their testids when those buttons are added.

**Pass criterion:** `pnpm test:e2e -g "rbac-matrix"` shows 30/30 green. Item 2 must keep this green after adding the two new buttons.

---

### Item 2 — `create-tenant` / `create-workspace` + `PATCH` / `DELETE`

#### 2A — Backend (`backend/app/gateway/identity/routers/admin_writes.py`)

Extend the existing module. New routes:

| Method | Path | Permission | Notes |
|---|---|---|---|
| `POST` | `/api/admin/tenants` | `tenant:create` | Body: `{slug, name}`. Slug uniqueness enforced; 409 on conflict. Platform-admin only — no tenant context. |
| `PATCH` | `/api/admin/tenants/{tid}` | `tenant:write` | Body: `{name?, settings?}`. Slug immutable. |
| `DELETE` | `/api/admin/tenants/{tid}` | `tenant:delete` | Soft-delete: sets `deleted_at`. Cascade to workspaces handled by existing M3 filter. |
| `POST` | `/api/tenants/{tid}/workspaces` | `workspace:create` | Body: `{slug, name}`. Tenant-scoped. |
| `PATCH` | `/api/tenants/{tid}/workspaces/{wid}` | `workspace:write` | Body: `{name?}`. |
| `DELETE` | `/api/tenants/{tid}/workspaces/{wid}` | `workspace:delete` | Soft-delete. |

**Cross-tenant guard:** every tenant-scoped route verifies `tid` matches `request.identity.active_tenant_id` for non-platform-admins. Mismatch → 404 (no leakage), same pattern as existing routes.

**Audit emission:** every write emits an audit row via the existing `AuditMiddleware`. Test added to `test_admin_writes.py`:

```python
@pytest.mark.parametrize("endpoint,action", [
    ("POST /api/admin/tenants", "tenant.create"),
    ("PATCH /api/admin/tenants/1", "tenant.update"),
    ("DELETE /api/admin/tenants/1", "tenant.delete"),
    # ... and the existing endpoints, parametrized in the same test
])
async def test_write_endpoints_emit_audit(...): ...
```

This back-fills audit-event verification for the existing A3 endpoints (currently untested for that aspect).

**Tests:** ~18 new tests in `test_admin_writes.py` — happy path + permission denial + cross-tenant 404 + audit emission per endpoint. StubSession pattern, no live DB.

#### 2B — Frontend

**New components:**

- `core/identity/components/CopyableSecret.tsx` — extracted from existing inline implementations in `tokens/page.tsx` and `profile/page.tsx`. One-time plaintext display + copy-to-clipboard + reveal toggle. Both pages refactored to consume it.
- `core/identity/components/ConfirmDialog.tsx` — minimal confirm modal. Used by tenant/workspace delete + existing token revoke + member remove (refactor those to consume it).

**New dialogs:**

- `app/(admin)/admin/tenants/page.tsx` — "New Tenant" button gated on `tenant:create`, opens dialog with `{slug, name}` form. Slug shown auto-derived from name with override.
- `app/(admin)/admin/tenants/[id]/page.tsx` — inline rename (pencil icon next to name) + "Delete tenant" with confirm.
- `app/(admin)/admin/workspaces/page.tsx` — "New Workspace" button gated on `workspace:create`.
- `app/(admin)/admin/workspaces/[id]/page.tsx` — inline rename + "Delete workspace" with confirm.

**API + hooks** (`core/identity/api.ts`, `core/identity/hooks.ts`):

```ts
identityApi.createTenant({slug, name})
identityApi.updateTenant(id, {name?, settings?})
identityApi.deleteTenant(id)
identityApi.createWorkspace(tenantId, {slug, name})
identityApi.updateWorkspace(tenantId, wsId, {name?})
identityApi.deleteWorkspace(tenantId, wsId)
```

Mutation hooks invalidate the corresponding `identityKeys.tenants()` / `identityKeys.workspaces(tid)` query.

**E2E** (`frontend/tests/e2e/identity/A3-tenant-workspace.spec.ts`, NEW):

- Create tenant happy path (platform_admin) → asserts row appears in list
- Create workspace happy path (tenant_owner)
- Rename tenant happy path
- Delete workspace with confirm
- Permission denial: `member` role does not see "New Tenant" button (also covered by Item 4 matrix; redundancy intentional for failure isolation)

**Pass criterion:**

- `pytest backend/tests/identity/test_admin_writes.py` green (existing 16 + new ~18)
- `pnpm test:e2e -g "tenant-workspace|rbac-matrix"` green
- Item 4's matrix updated to include the two new buttons; still 30/30 green

---

### Item 1 — `react-hook-form` + `zod` refactor + `PATCH /api/me`

**Deps added** (`frontend/package.json`):

```
"react-hook-form": "^7.54.0",
"@hookform/resolvers": "^3.10.0"
```

`zod` already in deps. `pnpm install` after edit.

**Schemas** (`core/identity/schemas.ts`, NEW):

```ts
export const newTokenSchema = z.object({
  name: z.string().min(1).max(64),
  expires_in_days: z.number().int().min(1).max(365).optional(),
});
export const newUserSchema = z.object({
  email: z.string().email(),
  display_name: z.string().min(1).max(128),
});
export const addMemberSchema = z.object({
  user_id: z.number().int().positive(),
  role: z.enum(["workspace_admin", "member", "guest"]),
});
export const newTenantSchema = z.object({
  slug: z.string().regex(/^[a-z0-9-]{2,64}$/),
  name: z.string().min(1).max(128),
});
export const newWorkspaceSchema = z.object({
  slug: z.string().regex(/^[a-z0-9-]{2,64}$/),
  name: z.string().min(1).max(128),
});
export const renameSchema = z.object({
  name: z.string().min(1).max(128),
});
export const profileBasicSchema = z.object({
  display_name: z.string().min(1).max(128),
  avatar_url: z.string().url().optional().or(z.literal("")),
});
```

**Dialogs refactored to `useForm` + `zodResolver`:**

- `tokens/page.tsx` — New token
- `users/page.tsx` — New user
- `workspaces/[id]/members/page.tsx` — Add member
- `tenants/page.tsx` — New tenant (from Item 2)
- `tenants/[id]/page.tsx` — Rename tenant (from Item 2)
- `workspaces/page.tsx` — New workspace (from Item 2)
- `workspaces/[id]/page.tsx` — Rename workspace (from Item 2)
- `profile/page.tsx` — Basic tab `display_name` + `avatar_url`, calls `PATCH /api/me`

**`PATCH /api/me`:** route already exists in M2 (`backend/app/gateway/identity/routers/me.py`). Verify schema matches; add `identityApi.updateMe()` + `useUpdateMe()` hook; cache invalidates `identityKeys.me()`.

**UX rules:**

- Field-level errors render inline below the input (existing `<FormMessage>` from shadcn `<Form>`)
- Submit button disabled while form is invalid OR `isSubmitting`
- Server errors (4xx body `{detail: "..."}`) render as a toast AND map to a form-level error if shape is `{detail: {field: msg}}`

**Selector stability:** existing E2E specs use `getByRole`/`getByTestId` — the refactor preserves all roles + testids. Spec runs unchanged.

**Pass criterion:**

- `pnpm check && pnpm test && pnpm test:e2e` all green
- All E2E specs from A3, A4, and A4-rbac-matrix pass without spec edits

---

### Item 3 — i18n sweep (do last)

**Files:** `frontend/src/core/i18n/locales/{en-US,zh-CN,types}.ts`

**New `admin` keys:**

- `admin.dialogs.{newToken,newUser,addMember,newTenant,newWorkspace,renameTenant,renameWorkspace}.{title,description,fieldLabel.*,placeholder.*,submit}`
- `admin.validation.{required,email,url,slugFormat,tooLong,tooShort}` — wired into zod custom error map
- `admin.tables.{tenants,users,workspaces,tokens,audit}.headers.*`
- `admin.empty.{tenants,users,workspaces,tokens,audit}`
- `admin.toast.{created,updated,deleted,revoked,error}`
- `admin.profile.basic.{title,description,fieldLabel.*}` — for the new `PATCH /api/me` form

**Type-driven enforcement:** `Translations["admin"]` is a fully-typed shape. Missing keys → TS compile error in `pnpm check`. zh-CN is the source of truth for required structure.

**Wire-up:** every `<Dialog>`, `<DialogTitle>`, `<Label>`, `<Button>` literal in the admin pages routed through `useI18n()`. Hard-coded strings remaining are `data-testid` values (these are stable contracts, not user-facing).

**Custom zod error map** (`core/identity/zod-i18n.ts`, NEW): maps zod issue codes to `admin.validation.*` keys so all schema errors localize without inlining strings in `schemas.ts`.

**Pass criterion:**

- `pnpm check` green (catches missing keys via `Translations` type)
- `pnpm test:e2e` green (existing specs unaffected; selectors are role/testid-based)
- Manual spot-check: switch to zh-CN, walk through one create + one delete in `/admin/tenants`, no English leak

---

## Order, checkpoints, exit criteria

| Step | Branch | Gate before moving on |
|---|---|---|
| Item 4 | `feat/m7a-rbac-matrix` off `feat/m7-admin-ui` | `pnpm test:e2e -g "rbac-matrix"` 30/30 green |
| Item 2 | `feat/m7a-tenant-workspace-writes` off Item 4's tip | `pytest backend/tests/identity/test_admin_writes.py` green AND `pnpm test:e2e -g "tenant-workspace\|rbac-matrix"` green AND audit-emission test passes |
| Item 1 | `feat/m7a-rhf-zod` off Item 2's tip | `pnpm check && pnpm test && pnpm test:e2e` all green; backend untouched |
| Item 3 | `feat/m7a-i18n-sweep` off Item 1's tip | `pnpm check` green; `pnpm test:e2e` green |

**Final exit:** all four branches landed (locally) on `feat/m7-admin-ui`. Per `feedback_local_only_workflow`, no push, no PR ceremony — verification is local tests + visible diff.

## Out of scope

- Screenshots in any document
- `CHANGELOG.md` updates
- `frontend/CLAUDE.md` identity chapter
- Spec §8 markup updates in the parent spec
- Any change to `app/channels/manager.py` IM channel TODO
- Any change behind `ENABLE_IDENTITY=false`

If any of these become blockers, file separately.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Item 2's two new buttons land but matrix not extended → false green | Item 2 plan task explicitly includes "extend matrix to 5×6" with a checklist item; final gate re-runs matrix |
| `PATCH /api/me` route schema in M2 doesn't match what the form sends | Item 1 task 1 reads `routers/me.py`, adapts the schema, doesn't add backend code |
| zod resolver swallows server-side errors | Item 1 spec mandates `setError("root.serverError", ...)` path with toast fallback |
| zh-CN locale falls behind en-US silently | `Translations["admin"]` typed shape forces both to declare same keys |

## References

- Parent spec: `2026-04-21-deerflow-identity-foundation-design.md` §8 (REST surface), §11.2 (acceptance E1–E15)
- Parent plan: `2026-04-23-m7a-admin-ui.md` (A1–A4 task lists, especially the deferred items in A3 and A4 sections)
- Existing code: `backend/app/gateway/identity/routers/admin_writes.py`, `frontend/src/app/(admin)/admin/`, `frontend/src/core/identity/`
- Existing tests: `backend/tests/identity/test_admin_writes.py`, `frontend/tests/e2e/identity/A3-write-actions.spec.ts`
