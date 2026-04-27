# M7: Admin UI + Migration Script + Release Implementation Plan

> **For agentic workers:** Detail level: **task-list level**. Expand to TDD per step when executing. M7 is large and splits naturally into three PRs (UI, migration, release) — recommended to land sequentially.

**Goal:** Ship the 14 admin pages, the one-shot `migrate_to_multitenant.py` script, and the release note / upgrade guide. After M7, a clean deployment of `ENABLE_IDENTITY=true` delivers the full P0 experience end-to-end.

**Prerequisites:** M1-M6 merged. Three parallel branches allowed: `feat/m7-admin-ui`, `feat/m7-migration`, `feat/m7-release`.

**Spec reference:** §8 (Admin UI), §10.2-10.10 (Migration + release).

**Non-goals:** Dashboard charts; three-app frontend split; i18n platform; email invite; custom role editor.

---

## Part A: Admin UI (branch `feat/m7-admin-ui`)

### File Structure

```
frontend/src/app/
  (public)/
    login/page.tsx
    logout/page.tsx
    auth/oidc/[provider]/callback/page.tsx
  (admin)/
    admin/
      layout.tsx                # sidebar with perm-guarded nav
      tenants/
        page.tsx                # list
        [id]/page.tsx           # detail
      users/
        page.tsx
        [id]/page.tsx
      roles/
        page.tsx                # read-only list
      workspaces/
        page.tsx
        [id]/members/page.tsx
      tokens/
        page.tsx
      audit/
        page.tsx
      profile/
        page.tsx

frontend/src/core/identity/
  hooks.ts                      # useIdentity, useSwitchTenant, useHasPermission
  components.tsx                # <RequirePermission>, <SessionExpiredModal>, <TenantSwitcher>
  api.ts                        # me, tenants, users, roles, workspaces, tokens, audit wrappers

frontend/middleware.ts          # /admin/* guard → redirect /login when no session
frontend/e2e/identity/          # Playwright scenarios E1-E15 from spec §11.2
```

### Tasks

1. **Login page** — OIDC provider buttons (fetched from `/api/auth/providers`), `?error=` banner. UX: match spec §8.6.
2. **Session-expired modal** — global component listening for 401 responses.
3. **Admin layout + guard** — sidebar with perm-filtered items, `middleware.ts` redirect when no cookie.
4. **Tenants list + detail pages** — platform_admin only.
5. **Users list + detail** — tenant-scoped; create-user form (direct creation since email invite is v1.1).
6. **Roles list (read-only)** — render 5 builtins grouped by scope.
7. **Workspaces list + members** — add/remove members with role dropdown.
8. **API Tokens page** — list + create modal (plaintext shown once, copy button). Revoke action.
9. **Audit page** — virtual-scrolled table using TanStack + server-side pagination; filter bar; detail drawer.
10. **Profile page** — tabs: basic info / my tokens / my sessions.
11. **Tenant switcher** — top-bar dropdown when user belongs to 2+ tenants.
12. **Playwright E2E suite** — scenarios E1-E15 from spec §11.2.
13. **i18n** — zh + en via Next.js route segments or cookie-based locale.
14. **Docs** — update `frontend/README.md`, add screenshots to `docs/superpowers/`.

Each page uses `useIdentity()` + `<RequirePermission>`, falls back to 403 UI when lacking perm (never silent).

Tests: Playwright E2E + React Testing Library unit tests for guards.

### PR A checklist

- All 14 routes exist and authenticate correctly
- `middleware.ts` redirects unauthenticated access
- Playwright CI job green
- Screenshots in PR description

---

## Part B: Migration script (branch `feat/m7-migration`)

### File Structure

```
scripts/migrate_to_multitenant.py
scripts/tests/test_migrate_to_multitenant.py
backend/app/gateway/identity/migration/
  planner.py          # enumerate source paths, build plan
  executor.py         # apply moves, create symlinks
  rollback.py         # reverse apply
  report.py           # JSON report writer
```

### Tasks

1. **CLI skeleton** — argparse with `--dry-run`, `--apply`, `--tenant-slug default`.
2. **Pre-check** — PG/Redis reachable, `identity` schema present, default tenant/ws exist, `$DEER_FLOW_HOME` writable, no existing `migration_lock`.
3. **Enumeration** — walk `backend/.deer-flow/threads/*`, `skills/custom/*`, `skills/user/*`; build map source→target.
4. **Plan printer** — human-readable + machine-parseable JSON.
5. **Executor** — `mv` (rename, not copy) each item; create symlink old→new; write per-item audit event; fsync report after each batch of 50.
6. **Symlink guard** — for skills, symlinks must point inside `skills/tenants/{tid}/` subtree (reuse §7.2 guard from M4).
7. **Post-check** — symlink readability, byte-count parity, sample-thread can be opened.
8. **Rollback** — reverse: remove symlinks, `mv` new→old; cleans lock.
9. **Idempotency** — re-running after partial success skips already-migrated items; lock file coordinates.
10. **Tests** — fixtures that scaffold fake `threads/*` + `skills/custom/*`; assert after apply the new tree matches expected; assert rollback restores original.

### PR B checklist

- `--dry-run` never writes
- `--apply` produces report + audit events
- K8s multi-replica safety: advisory lock (PG `pg_advisory_lock(hashtext('deerflow_migration'))`) prevents concurrent runs
- Rollback unit tests green
- Real-data rehearsal (at least 100 threads) documented in PR description

---

## Part C: Release (branch `feat/m7-release`)

### Tasks

1. **Bootstrap multi-replica safety** — add PG advisory lock around `bootstrap()` so two gateway replicas don't race on seed inserts (spec §13 risk item).
2. **Metrics export** — prometheus counters for `identity_login_total`, `identity_authz_denied_total`, `identity_session_active`, `audit_queue_depth`, `audit_write_failures_total`.
3. **Alerting docs** — sample Grafana alert rules for login failure spike / audit queue depth.
4. **Upgrade guide** — `docs/UPGRADE_v2.md` with A/B paths from spec §10.10.
5. **Release notes** — `CHANGELOG.md` entry with breaking/non-breaking split.
6. **CLAUDE.md finalisation** — full identity subsystem map across all 7 milestones.
7. **Manual verification runbook** — `docs/identity-release-checklist.md` covering spec §11.7:
   - Okta real login
   - Azure AD real login
   - Keycloak real login
   - Full migration rehearsal with 1000+ threads
   - docker-compose and K8s deployment
   - Rollback drill (flag on → flag off → legacy thread access)
8. **End-to-end smoke** — GitHub Actions workflow that:
   - Spins up PG+Redis
   - Runs alembic upgrade
   - Starts gateway with flag=true
   - Plays through OIDC mock IdP login
   - Creates a thread via API
   - Asserts audit event visible
   - Shuts down

### PR C checklist

- CHANGELOG entry accurate
- Upgrade guide peer-reviewed
- Release checklist exercised once on staging
- All prior milestone CI green on `main` after merge

---

## M7 Self-review vs spec §8/§10

- §8.1 route group separation (public/app/admin) — Part A
- §8.2 nav guards — Part A tasks 3, 11
- §8.3 14 pages — Part A tasks 1-10
- §8.4 REST endpoints — consumed by Part A (must already exist from M2-M6 plus a handful of read-only admin/user endpoints added opportunistically in this part)
- §8.5 tech stack choice — no new libs beyond what repo already has (shadcn/ui, TanStack)
- §8.6 space/empty states + first boot — Part A + Part C bootstrap hardening
- §8.7 exclusions respected
- §10.2 stages 0-4 — Part B script + Part C release
- §10.3 script contract — Part B tasks 1-9
- §10.4 bootstrap hardening — Part C task 1
- §10.7 rollback — Part B task 8 + Part C task 7
- §10.8 metrics + alerts — Part C tasks 2-3
- §10.10 upgrade guide — Part C task 4

## Sequencing

Recommended order (sequential, not parallel, for PR review sanity):

1. Part B (migration) — small, mostly Python, low dep surface
2. Part C (release) — hardens bootstrap + adds metrics (prereq for prod rollout)
3. Part A (admin UI) — largest; lands last so it can consume all finalised APIs

If team capacity allows parallel frontend+backend, Parts A and B can run in parallel; Part C merges after both.

## Global acceptance (all 7 milestones)

After M7 ships (spec §15 checklist):

- [ ] Alembic migration creates `identity` schema with 11 tables + seed
- [ ] `make dev` with flag=false: functionally identical to v1.x (CI green)
- [ ] `make dev` with flag=true: OIDC login end-to-end
- [ ] Migration script dry-run + apply on 100+ threads
- [ ] 14 admin pages accessible
- [ ] 5-role × core-action RBAC matrix green
- [ ] Guardrail upgrade: tool denies land in audit
- [ ] Cross-tenant access yields 403 + audit event
- [ ] Rollback drill: flag=true → flag=false → legacy threads still openable
- [ ] Real Okta, Azure AD, Keycloak each passed one login
- [ ] CI green for all identity jobs; identity coverage ≥ 80%
