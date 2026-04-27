# M4: Storage Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Detail level: **task-list level**. Before executing, expand each task into TDD steps by applying the pattern shown in M1.

**Goal:** Add tenant/workspace-aware paths for threads, skills, config, memory, artifacts. Update skills loader to scan the tenant-stratified tree with priority rules. Introduce config layering (global → tenant → workspace) with sensitive-field guard. All changes are **flag-gated**; `ENABLE_IDENTITY=false` keeps legacy flat paths.

**Prerequisites:** M3 merged. Branch `feat/m4-storage`.

**Spec reference:** §7 (Storage isolation), §10.2 (migration stages).

**Non-goals:** migration script itself (M7); object-storage backends; quotas; cross-workspace sharing.

---

## File Structure

### Created

```
backend/app/gateway/identity/storage/
  __init__.py
  paths.py                 # tenant_root, workspace_root, thread_path, skills_tenant_root, audit_fallback_path
  config_layers.py         # load_layered_config(global, tenant_id, workspace_id) → merged dict + cache key
  path_guard.py            # assert_within_tenant_root, safe_join, cross-tenant detection

backend/tests/identity/storage/
  __init__.py
  test_paths.py
  test_path_guard.py
  test_config_layers.py
  test_skills_loader_tenant.py
  test_sandbox_mount_tenant.py
```

### Modified

```
backend/packages/harness/deerflow/skills/loader.py
  # add tenant_id, workspace_id params; new scan order:
  #   public/  →  tenants/{tid}/custom/  →  tenants/{tid}/workspaces/{wid}/user/
  # collision policy: later-in-order wins; emit warning
  # symlink guard: realpath must stay under skills/tenants/{tid}/ root

backend/packages/harness/deerflow/agents/middlewares/thread_data.py
  # derive thread root from identity (tenant_id, workspace_id) when flag on

backend/packages/harness/deerflow/sandbox/local/*.py
backend/packages/harness/deerflow/community/aio_sandbox/*.py
  # update host-side mount point generation to use tenant/workspace path

backend/app/gateway/routers/artifacts.py  # verify thread belongs to identity tenant/workspace
backend/app/gateway/routers/uploads.py    # same

backend/app/gateway/identity/settings.py  # add DEER_FLOW_HOME default, sensitive field list

backend/app/gateway/identity/db.py        # no change; referenced for audit fallback writer (M6)

config/identity.yaml.example              # sensitive_global_only fields list

backend/CLAUDE.md
```

---

## Task 1: Path utilities

**Functions (in `storage/paths.py`):**

```python
def deerflow_home() -> Path: ...                         # $DEER_FLOW_HOME or backend/.deer-flow
def tenant_root(tenant_id: int) -> Path: ...
def workspace_root(tenant_id: int, workspace_id: int) -> Path: ...
def thread_path(tenant_id: int, workspace_id: int, thread_id: str) -> Path: ...
def skills_public_root() -> Path: ...
def skills_tenant_custom_root(tenant_id: int) -> Path: ...
def skills_workspace_user_root(tenant_id: int, workspace_id: int) -> Path: ...
def user_memory_path(tenant_id: int, user_id: int) -> Path: ...
def audit_fallback_path(date_yyyymmdd: str) -> Path: ...
def audit_archive_path(tenant_id: int, yyyy_mm: str) -> Path: ...
def tenant_shared_root(tenant_id: int) -> Path: ...
def migration_report_path(ts: str) -> Path: ...
def migration_lock_path() -> Path: ...
```

Each function must:
- assert `tenant_id` positive (defensive)
- return an absolute Path
- NOT create the directory (caller creates)

Tests: verify paths match spec §7.1 / §7.2 layout exactly. No I/O.

---

## Task 2: Path guard

```python
# storage/path_guard.py
def assert_within_tenant_root(p: Path, tenant_id: int) -> None:
    """Raise PathEscapeError if p.resolve() is not inside tenant_root(tenant_id)."""

def safe_join(root: Path, *segments: str) -> Path:
    """Join + normalise + assert result is inside root. Rejects '..' and absolute paths."""

def assert_symlink_parent_safe(symlink: Path, allowed_root: Path) -> None:
    """For skills loader: reject symlinks whose realpath leaves the tenant's skills subtree."""
```

Tests: `..` traversal blocked; absolute-path injection blocked; valid symlinks pass; symlinks pointing outside allowed_root rejected.

---

## Task 3: Skills loader tenant-aware

Modify `backend/packages/harness/deerflow/skills/loader.py`:

Current (from main):
```python
def load_skills(skills_path: Path | None = None, use_config: bool = True, enabled_only: bool = False) -> list[Skill]:
    ...
    for category in ["public", "custom"]:
        ...
```

New:
```python
def load_skills(
    skills_path: Path | None = None,
    *,
    use_config: bool = True,
    enabled_only: bool = False,
    tenant_id: int | None = None,
    workspace_id: int | None = None,
) -> list[Skill]:
    """
    Scan priority (later-in-order wins on name collision):
      1. skills_path/public/
      2. skills_path/tenants/{tenant_id}/custom/            (if tenant_id)
      3. skills_path/tenants/{tenant_id}/workspaces/{workspace_id}/user/  (if both)
    When tenant_id is None (legacy mode, flag off), scan only:
      1. skills_path/public/
      2. skills_path/custom/
      3. skills_path/user/
    """
```

Harness boundary: loader lives in `packages/harness/`, must not import `app.*`. tenant_id/workspace_id are passed explicitly by the caller (Gateway router + `ThreadDataMiddleware`).

`extensions_config.json` lookup also splits: one global file (backward compat) + optional `tenants/{tid}/extensions_config.json`. Merge by union of enabled skill names; tenant file overrides `false` flags but cannot re-enable a disabled-by-global skill.

Tests (integration, fs fixture):
- Flat legacy layout still works when tenant_id=None
- Stratified layout respects priority (workspace user skill with same name as public wins)
- Collision warning logged
- Symlink from tenant custom to path outside tenants/{tid}/ → skipped with warning
- `followlinks=True` still functional for in-scope symlinks

---

## Task 4: Config layering

```python
# storage/config_layers.py
SENSITIVE_GLOBAL_ONLY = frozenset({
    # model provider keys — never allowed in tenant/workspace layers
    "models[*].api_key",
    "models[*].endpoint",
    # sandbox provisioner credentials
    "sandbox.provisioner.api_key",
    # others populated from config/identity.yaml.example
})

def load_layered_config(
    global_path: Path,
    tenant_id: int | None,
    workspace_id: int | None,
    *,
    deerflow_home: Path,
) -> tuple[dict, str]:
    """Return (merged_dict, cache_key). cache_key = f'{tid}:{wid}' or 'global'."""

def merge_config(global_cfg: dict, tenant_cfg: dict | None, workspace_cfg: dict | None) -> dict:
    """Deep merge; lists replaced whole; raises SensitiveFieldViolation if a lower layer
    attempts to set any SENSITIVE_GLOBAL_ONLY path."""
```

Tests:
- global-only config returns global dict + cache_key="global"
- tenant override on non-sensitive key merges correctly
- workspace override on top of tenant on top of global
- tenant attempts to set `models[0].api_key` → `SensitiveFieldViolation`
- list-merge semantics documented by example

Redis cache entry: key `config:merged:{tid}:{wid}`, TTL 5min, invalidated on tenant/workspace config mtime change (hook into existing mtime check).

---

## Task 5: ThreadData middleware path change

Modify `backend/packages/harness/deerflow/agents/middlewares/thread_data.py`:

- Current: constructs host path at `backend/.deer-flow/threads/{thread_id}`
- New: if `state.get("identity") and identity.tenant_id and identity.workspace_id`, use `thread_path(tid, wid, thread_id)`; else fall back to legacy path
- Sandbox virtual path `/mnt/user-data/{workspace,uploads,outputs}` unchanged

Add test that with identity present the host path is tenant-aware; without identity the legacy path is preserved (flag-off regression).

LangGraph-side identity is set by the middleware in M5. In M4 we add the consumer side (ThreadData reads state["identity"]), but `state["identity"]` is only populated when M5 ships. To avoid a dead code path during M4 validation, add a temporary fixture-driven unit test that injects a fake identity into state and confirms path resolution.

---

## Task 6: Sandbox host-mount update

Modify local and Docker sandbox providers under `packages/harness/deerflow/sandbox/local/` and `packages/harness/deerflow/community/aio_sandbox/`:

- Host path passed to bind mount or file operations must resolve through `thread_path(...)` when identity is in scope
- Virtual path mapping unchanged (`/mnt/user-data`, `/mnt/skills`, `/mnt/acp-workspace`)
- `mount` / `/proc/self/mountinfo` leakage: verify `is_relative_to(tenant_root)` holds; no tenant id exposed in mount-point name (the sandbox sees the path rewritten to `/mnt/user-data` only)

Tests: `test_sandbox_mount_tenant.py`:
- With identity → bind-mount source is `tenants/{tid}/workspaces/{wid}/threads/{tid}/user-data/workspace`
- Without identity → legacy `backend/.deer-flow/threads/{tid}/user-data/workspace`
- In-sandbox `ls /mnt/` shows no tenant names
- Cross-tenant sibling path cannot be accessed from inside sandbox (negative test via `../../tenants/OTHER_TID/...` command in bash tool → rejected by virtual-path translator)

---

## Task 7: Artifacts / uploads authz

Modify `app/gateway/routers/artifacts.py` and `.../uploads.py`:

- Extract `thread_id` from path
- Look up thread → tenant_id/workspace_id (metadata table comes later; for M4 the loader derives tenant/ws from the filesystem ancestors of the host path)
- If extracted tenant/ws ≠ identity's → 403 + queue `authz.path.denied` audit event
- Pure read-only business logic unchanged

When flag off → middleware short-circuits → legacy behavior preserved.

Tests:
- Cross-tenant artifact GET → 403
- Same-tenant GET → 200
- Flag off → artifact still returned without identity check (regression guard)

---

## Task 8: Directory bootstrap helper

Script `backend/scripts/ensure_tenant_dirs.py` (or Makefile target):

```
make identity-dirs TENANT_ID=1 WORKSPACE_ID=1
```

Creates the expected tree with `0700` permissions. Used by M7 migration and by manual tenant provisioning.

---

## Task 9: Docs + PR

- Update `CLAUDE.md` Skills System + Sandbox sections to reference new layout.
- Update root `README.md` "Enterprise Identity" section with `DEER_FLOW_HOME` guidance.
- Push branch, open PR.

## Self-review vs spec §7

- §7.1 file paths — Task 1 matches.
- §7.2 skills loader — Task 3 matches; symlink guard Task 2.
- §7.3 config layering — Task 4; sensitive-field guard covered.
- §7.4 memory + artifacts — Task 7.
- §7.5 migration — deferred to M7, noted.
- §7.6 non-goals — respected.
- §7.7 invariants (path derived from identity; symlink scope; config down-sink only; rollback-safe) — Tasks 1-7.
