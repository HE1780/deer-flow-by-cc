# DeerFlow v2 Upgrade Guide

> 📌 **2026-04-29 验收复核**：本指南内容仍然准确反映当前代码事实。若干部署演练 gap（OIDC 真机、1000-thread 迁移、双副本 bootstrap、各部署形态）尚未完成，详见 [OPEN_ISSUES.md OI-8 ~ OI-13](./OPEN_ISSUES.md) + [identity-release-checklist.md](./identity-release-checklist.md) 的 38 项未勾选项。Spec 锚点已归档到 [`superpowers/specs/archive/2026-04-21-deerflow-identity-foundation-design.md`](./superpowers/specs/archive/2026-04-21-deerflow-identity-foundation-design.md)。

---

This guide documents the upgrade path from DeerFlow v1.x (single-tenant) to
v2.0 (multi-tenant identity foundation). Spec reference:
[`docs/superpowers/specs/archive/2026-04-21-deerflow-identity-foundation-design.md`](./superpowers/specs/archive/2026-04-21-deerflow-identity-foundation-design.md),
sections §10.2 and §10.10.

## TL;DR

* **Keeping v1 behaviour**: leave `ENABLE_IDENTITY=false` (default). No
  database changes required. The identity subsystem is inert and all
  existing code paths are preserved, enforced by the regression guard
  `backend/tests/identity/test_feature_flag_offline.py`.
* **Turning identity on**: follow Path A (greenfield) or Path B (migration)
  below. The flip is intended to be a **one-way** operation for an
  installation that commits to multi-tenancy.

## Breaking vs. non-breaking changes

**Non-breaking (ENABLE_IDENTITY=false)**

* No DB connection attempted.
* No middleware registered (`IdentityMiddleware`, `AuditMiddleware`,
  `IdentityGuardrailMiddleware` — all absent).
* Auth / audit / admin routes are not mounted; `/api/*` routes behave
  identically to v1.x.
* Gateway lifespan does not open Redis.
* Legacy thread storage at `backend/.deer-flow/threads/<id>` continues to work.

**Breaking (ENABLE_IDENTITY=true)**

* Every `/api/*` call now resolves an identity (cookie or `Authorization`
  header). Unauthenticated requests get 401 from `@requires(...)`.
* Thread / skill / memory filesystem paths move under
  `$DEER_FLOW_HOME/tenants/{tid}/...` (see §7.1). Legacy flat paths only
  resolve via forwarder symlinks left by the migration script.
* `POST /api/threads/{id}/uploads` requires `workspace_id` context and
  enforces `assert_within_tenant_root`.
* `GET /api/artifacts/...` returns 403 on cross-tenant path attempts
  instead of 404.
* OIDC provider config (`config/identity.yaml`) becomes a runtime
  dependency; without at least one provider, login is impossible.
* Prometheus endpoint `/metrics` is exposed. Ensure your scrape config
  and network policy are ready.

## Path A — greenfield (no existing data to migrate)

For new deployments or dev environments.

1. Copy config template:
   ```bash
   cp config/identity.yaml.example config/identity.yaml
   # fill in your Okta / Azure AD / Keycloak credentials
   ```
2. Generate the RS256 keypair:
   ```bash
   make identity-keys
   ```
3. Set env vars (example, see `backend/app/gateway/identity/settings.py`
   for the full list):
   ```bash
   export ENABLE_IDENTITY=true
   export DEERFLOW_DATABASE_URL=postgresql+asyncpg://user:pw@host/deerflow
   export DEERFLOW_REDIS_URL=redis://host:6379/0
   export DEERFLOW_BOOTSTRAP_ADMIN_EMAIL=ops@example.com
   export DEERFLOW_INTERNAL_SIGNING_KEY=$(openssl rand -hex 32)
   ```
4. Apply schema + seed:
   ```bash
   make db-upgrade
   make identity-bootstrap
   ```
5. Start the gateway:
   ```bash
   make gateway
   ```
6. Visit `/api/auth/oidc/{provider}/login`. After the OIDC callback the
   bootstrap admin has `platform_admin` + `tenant_owner(default)` +
   `workspace_admin(default)`.

## Path B — migration from v1 (existing on-disk data)

For production installations upgrading in place.

### B.1 Prepare a rollback point

1. **Snapshot `$DEER_FLOW_HOME`** (filesystem snapshot, LVM / zfs, or
   `tar -czf`). Until step B.4 completes you should be able to revert
   to the snapshot in under a minute.
2. Commit to a pinned DeerFlow version on disk (no in-place `pip install`
   or `uv sync` during the migration window).
3. Drain LangGraph runs — the migration acquires a file lock at
   `$DEER_FLOW_HOME/_system/migration.lock` and a PG advisory lock
   (`deerflow_migration`) and will refuse to start concurrently.

### B.2 Bring up identity (read-only mode)

Follow steps A.1–A.4 above (OIDC config, keypair, DB upgrade, bootstrap),
but DO NOT flip `ENABLE_IDENTITY=true` for the user-facing replicas yet —
leave at least one gateway replica on the flag-off config so end-users
continue hitting v1 paths while you rehearse.

### B.3 Rehearse the migration (dry run)

```bash
make identity-migrate-dry
```

The dry-run writes a plan + report to
`$DEER_FLOW_HOME/_system/migration_report_<ts>.json` and never mutates
the filesystem. Read the report, sanity-check item counts (threads,
tenant-custom skills, workspace-user skills), and keep it for diffing
after the real apply.

### B.4 Apply the migration

```bash
make identity-migrate-apply
```

The executor:
* takes both locks
* renames each `backend/.deer-flow/threads/<id>` →
  `$DEER_FLOW_HOME/tenants/{tid}/workspaces/{wid}/threads/<id>`
* drops a symlink at the old path so legacy callers transparently follow
* verifies byte-count parity per item
* routes audit events (`system.migration.item.moved`) through the M6
  fallback JSONL at `$DEER_FLOW_HOME/_audit/fallback.jsonl`; the batch
  writer back-fills them at the next gateway boot.

**Rehearsal tip:** run the pair of commands on a non-prod clone with at
least 100 threads of real-shaped data. Confirm the second `apply`
invocation reports `moved: 0, skipped: N, failed: 0` (idempotency).

### B.5 Flip the flag

On all gateway replicas, set `ENABLE_IDENTITY=true` and restart. The
first replica to finish its lifespan takes the `deerflow_bootstrap`
advisory lock (see `bootstrap_lock.py`) and runs the seed; the rest
wait for it to finish, then observe the already-committed state and
return instantly — no `UniqueViolation` races.

At this point `/metrics` begins to expose `identity_*` counters; wire
your Prometheus and Grafana per `docs/identity-alerting.md`.

### B.6 Exercise the rollback drill

Keep the migration report file from step B.4. To roll back storage:

```bash
make identity-migrate-rollback REPORT=$DEER_FLOW_HOME/_system/migration_report_<ts>.json
```

This reverses the moves and removes the forwarder symlinks. **After
rollback**, set `ENABLE_IDENTITY=false` and restart — the gateway
reverts to flag-off behaviour and the legacy `threads/<id>` tree is
accessible again.

Rollback is idempotent: running it twice restores the tree once and
then no-ops.

## Upgrading from v2.0 to a later v2.x

After the identity flag has been flipped once, subsequent upgrades are
regular Alembic migrations:

```bash
make db-upgrade
```

The `bootstrap_with_advisory_lock` wrapper is always in place from v2.0
onwards, so multi-replica rolling restarts are safe without additional
operator action.

## Troubleshooting

| Symptom | Probable cause | Fix |
|---|---|---|
| Gateway exits with "DB pre-check failed" on boot | `DEERFLOW_DATABASE_URL` wrong or PG unreachable | Validate `psql $URL`; confirm `identity` schema exists (`make db-upgrade`). |
| `/api/auth/oidc/foo/login` returns 404 | `config/identity.yaml` missing provider `foo` | Add the provider block; restart gateway. |
| Migration script exits with code 3 | another run is holding the file or PG lock | Check `$DEER_FLOW_HOME/_system/migration.lock` for a live PID; also run `SELECT * FROM pg_locks WHERE locktype='advisory'`. |
| Unexpected 401s after flip | session cookie from flag-off era | `/api/auth/logout` or clear the `deerflow_session` cookie; re-login through OIDC. |
| `audit_queue_depth` pinned at 10000 | PG outage; writer is at queue_max | Check PG; failed events are in `$DEER_FLOW_HOME/_audit/fallback.jsonl` and backfill once PG recovers. |

## Migration invariants

Across every milestone and the release wrapper above, these MUST hold:

1. **`ENABLE_IDENTITY=false` ⇒ zero behavior change from pre-M1 main.**
2. **Harness boundary.** No code in `backend/packages/harness/deerflow/`
   imports from `app.*` (enforced by `tests/test_harness_boundary.py`).
3. **Audit log immutability.** DB GRANT denies UPDATE/DELETE on
   `identity.audit_logs` from the app role (M6 migration `0003`).
4. **Path derived from identity.** No business code computes a storage
   path from untrusted user input; all routes go through `storage/paths.py`.
5. **Tool permission whitelist.** `TOOL_PERMISSION_MAP` + MCP-declared
   permissions are the only paths to allow a tool; unknown tools
   default-deny.

Regressing any of these is a hard failure — revert the change rather
than patching the invariant.
