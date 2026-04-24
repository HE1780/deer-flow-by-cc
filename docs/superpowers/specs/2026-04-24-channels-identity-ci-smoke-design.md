---
title: Channels Identity TODO + CI E2E Identity Smoke
date: 2026-04-24
status: approved
---

# Channels Identity TODO + CI E2E Identity Smoke

## Scope

Two independent deliverables:

1. **channels/manager.py identity TODO** — wire `tenant_id`/`workspace_id` from channel config through `ChannelStore` into `resolve_virtual_path`, resolving the `TODO(m5-identity)` comment at `manager.py:352`.
2. **CI E2E identity smoke workflow** — GitHub Actions job that boots Gateway with `ENABLE_IDENTITY=true` (PG + Redis), creates an API token for the bootstrap admin, and exercises the full identity pipeline end-to-end without OIDC.

---

## Part 1 — Channels Identity TODO

### Problem

`_resolve_attachments()` in `ChannelManager` calls:

```python
actual = paths.resolve_virtual_path(thread_id, virtual_path)
```

When `ENABLE_IDENTITY=true`, M4 storage routes artifact paths through tenant-stratified directories (`tenants/{tid}/workspaces/{wid}/threads/{thread_id}/user-data/outputs/`). Without `tenant_id`/`workspace_id`, the resolver falls back to the legacy flat path, so IM channel artifacts are served from the wrong location.

### Constraint

`InboundMessage` carries only a platform `user_id` string (e.g. Slack uid). IM channels authenticate via bot token, not OIDC, so there is no `Identity` object available at dispatch time.

### Design

**Source of truth**: `config.yaml` `channel_sessions.<channel>.tenant_id` / `workspace_id`. These are operator-configured integers, matching the existing `channel_sessions` config layer pattern already consumed by `_resolve_session_layer`.

**Storage**: `ChannelStore` persists `tenant_id`/`workspace_id` alongside `thread_id` in the JSON store at thread creation time. This ensures the correct values are used for the lifetime of the thread even if config changes later.

**Flag guard**: When `ENABLE_IDENTITY=false` (or values absent from config), both values are `None` and `resolve_virtual_path` falls back to the legacy flat path — zero behavior change.

### File Changes

#### `app/channels/store.py`

- `set_thread_id` gains two optional keyword args: `tenant_id: int | None = None`, `workspace_id: int | None = None`. These are written into the JSON entry alongside `thread_id`.
- New method `get_thread_mapping(channel_name, chat_id, *, topic_id) -> dict | None` returns the full entry dict (including `tenant_id`/`workspace_id`) or `None`.

JSON entry shape (backward-compatible; missing keys read as `None`):

```json
{
  "thread_id": "...",
  "user_id": "...",
  "tenant_id": 1,
  "workspace_id": 2,
  "created_at": 1700000000.0,
  "updated_at": 1700000000.0
}
```

Existing `get_thread_id` is unchanged (still returns `str | None`).

#### `app/channels/manager.py`

- `_resolve_session_layer` already returns `(channel_layer, user_layer)`. Add a helper `_resolve_channel_identity(msg) -> tuple[int | None, int | None]` that reads `tenant_id`/`workspace_id` from the channel layer (falling back to `default_session`), guards against non-int values, and returns `(None, None)` when flag is off.
- `_create_thread` calls `_resolve_channel_identity` and passes the result to `store.set_thread_id`.
- `_handle_chat` uses `store.get_thread_mapping` (instead of `get_thread_id`) to retrieve both `thread_id` and the stored `tenant_id`/`workspace_id`.
- `_resolve_attachments(thread_id, artifacts, *, tenant_id, workspace_id)` — add two keyword args, pass them through to `paths.resolve_virtual_path`.
- `_prepare_artifact_delivery` — propagates `tenant_id`/`workspace_id` to `_resolve_attachments`.
- Remove the `TODO(m5-identity)` comment block; replace with a one-line explanation.

No new imports from `app.gateway.identity.*` in `manager.py` — the flag check reads `ENABLE_IDENTITY` via `os.environ` directly (same pattern used elsewhere in channels layer). This avoids importing the identity subsystem into a module that runs whether the flag is on or off.

#### `tests/test_channels.py`

New test class `TestChannelManagerIdentity` (alongside existing `TestChannelManager`):

- `test_resolve_attachments_flag_off` — `ENABLE_IDENTITY` absent, asserts `resolve_virtual_path` called with `tenant_id=None, workspace_id=None`.
- `test_resolve_attachments_flag_on_with_config` — `ENABLE_IDENTITY=1`, channel_sessions has `tenant_id=7, workspace_id=3`, asserts `resolve_virtual_path` called with those values.
- `test_store_persists_tenant_workspace` — `ChannelStore.set_thread_id` with tenant/ws, then `get_thread_mapping` returns them.
- `test_missing_tenant_config_falls_back` — `ENABLE_IDENTITY=1` but no `tenant_id` in channel config → `resolve_virtual_path` called with `None, None`.

All tests mock `paths.resolve_virtual_path` (no filesystem needed).

---

## Part 2 — CI E2E Identity Smoke

### Goal

A GitHub Actions job that runs on every push to `main` and on PRs touching `backend/**`, proving that `ENABLE_IDENTITY=true` Gateway starts correctly, authenticates a request, and records an audit event — end-to-end, no mocks, no OIDC required.

### Auth Strategy

The bootstrap admin user has no password (OIDC-only login). To avoid OIDC in CI:

1. Bootstrap creates the platform_admin user (via `DEERFLOW_BOOTSTRAP_ADMIN_EMAIL`).
2. The smoke test calls `POST /api/me/tokens` using a **JWT issued directly** by a helper script (`scripts/ci/issue_bootstrap_token.py`) that reads the private key from disk and mints a short-lived JWT for the admin user — same RS256 path as the real auth flow, just without the OIDC dance.
3. That JWT is used as `Authorization: Bearer <jwt>` to call `POST /api/me/tokens` → gets an API token.
4. API token used for all subsequent calls (`Authorization: Bearer dft_...`).

This exercises: JWT middleware → identity resolution → RBAC → API token creation → `/api/me` → audit event.

### Files

#### `.github/workflows/identity-e2e-smoke.yml`

New workflow. Trigger: `push` to `main` + `pull_request` on `backend/**` or the workflow file itself.

Services: `postgres:16-alpine` + `redis:7-alpine` (same config as `backend-identity-tests`).

Steps:
1. Checkout, Python 3.12, uv
2. `uv sync --group dev`
3. `alembic upgrade head`
4. `make identity-keys` (generate RS256 keypair)
5. `python -m app.gateway.identity.cli bootstrap`
6. Start Gateway: `uvicorn app.gateway.app:app --port 8001 &`
7. Wait for `GET /health` → 200 (poll with `curl --retry 10 --retry-connrefused --retry-delay 1`)
8. `python scripts/ci/identity_smoke_test.py`
9. Kill uvicorn

Env vars passed to all steps:
```
ENABLE_IDENTITY: "true"
DEERFLOW_DATABASE_URL: postgresql+asyncpg://deerflow:deerflow@localhost:5432/deerflow
DEERFLOW_REDIS_URL: redis://localhost:6379/0
DEERFLOW_BOOTSTRAP_ADMIN_EMAIL: admin@smoke.test
DEERFLOW_INTERNAL_SIGNING_KEY: smoke-test-signing-key-32chars!!
```

#### `scripts/ci/identity_smoke_test.py`

Single-file script, no pytest, pure stdlib + `httpx` (already a dev dep).

```
Assertions (in order):
1. GET  /health                              → 200
2. POST /api/me/tokens  (JWT auth)           → 201, body has "plaintext" starting "dft_"
3. GET  /api/me         (API token auth)     → 200, body has user_id + tenant_id (non-null)
4. GET  /api/tenants/{tid}/audit (API token) → 200, items non-empty (audit middleware fired)
5. Print "smoke: all assertions passed" and exit 0
```

Exit 1 on any assertion failure, printing the failing response body.

#### `scripts/ci/issue_bootstrap_token.py`

Helper that mints a short-lived JWT (60s TTL) for the bootstrap admin email, using the private key at the path returned by `get_identity_settings().jwt_private_key_path`. Outputs the raw JWT to stdout. Used by `identity_smoke_test.py` via `subprocess.check_output`.

No new dependencies — uses `python-jose` (already in dev deps; fall back to `PyJWT` if absent). Implementation checks which is available at import time.

---

## Cross-cutting invariants preserved

- `ENABLE_IDENTITY=false` → `_resolve_attachments` called with `tenant_id=None, workspace_id=None` → legacy path unchanged. Verified by `test_resolve_attachments_flag_off`.
- `test_feature_flag_offline.py` must stay green — no new identity imports in the channels module path.
- Harness boundary (`test_harness_boundary.py`) unaffected — all changes are in `app.*`.

---

## Non-goals

- Multi-tenant IM (different tenants per user within one channel) — spec §8.7 non-goal.
- Real Okta/Azure/Keycloak login in CI — manual runbook in `docs/identity-release-checklist.md`.
- K8s deployment verification — manual runbook only.
- 1000-thread migration rehearsal — manual runbook only.
