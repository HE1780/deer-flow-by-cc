> 📦 **归档于 2026-04-29 — 已 ship**：5 处 call site 全部修复（commits `aedcf8af`/`4ce6c997`/`9722937c`/`16770364`/`4eca6cc5`），legacy 路径方法加 `DeprecationWarning` 防回归。已知遗漏 (admin UI / OIDC 真机 / 邀请注册前端) 移交 [OPEN_ISSUES.md](../../../OPEN_ISSUES.md)。

---

# Uploads Tenant-Aware Path Fix — Design

**Date**: 2026-04-28
**Author**: Claude (with @lydoc)
**Status**: ✅ Shipped（详见上方 banner）
**Related**:
- Symptom chat: `localhost:2026/workspace/chats/53617e94-7d39-4174-96ba-de29a579da27`
- Parent epic: M4 storage isolation (commits `bcc9ccee`, `bc21a46e`, `8828c392`, `9400cc21`, `daefabd9`)
- Identity foundation spec: `2026-04-21-deerflow-identity-foundation-design.md`

---

## 1. Problem

When `ENABLE_IDENTITY=true`, `UploadsMiddleware` cannot see uploaded files. The agent receives no `<uploaded_files>` block in the prompt, so it answers "what data?" via `ask_clarification` even though the user just uploaded a file.

**Concrete reproduction (this session):**

User uploaded `财务数据.csv` to thread `53617e94-7d39-4174-96ba-de29a579da27`. The Gateway upload router wrote it to:

```
backend/.deer-flow/tenants/1/workspaces/1/threads/53617e94-…/user-data/uploads/财务数据.csv
```

`UploadsMiddleware.before_agent` looked up:

```
backend/.deer-flow/threads/53617e94-…/user-data/uploads/   ← does not exist
```

→ `historical_files = []`, no `<uploaded_files>` block, agent triggered `ask_clarification`.

## 2. Root Cause

Two divergent path APIs exist on `Paths`:

| API | Layout | Status |
|---|---|---|
| `sandbox_uploads_dir(thread_id)` | `{base}/threads/{tid}/user-data/uploads/` | legacy single-tenant |
| `resolve_sandbox_uploads_dir(thread_id, *, tenant_id, workspace_id)` | `{base}/tenants/{T}/workspaces/{W}/threads/{tid}/user-data/uploads/` when both ids are positive ints; otherwise legacy fallback | M4 tenant-aware |

M4 task 5 wired `ThreadDataMiddleware`, `SandboxMiddleware`, the Gateway uploads/artifacts routers, and `present_file_tool` to call the `resolve_*` family. **Four call sites were missed:**

| # | Location | Bug |
|---|---|---|
| **A** | `packages/harness/deerflow/agents/middlewares/uploads_middleware.py:224` | `self._paths.sandbox_uploads_dir(thread_id)` — no identity read at all |
| **B** | `app/channels/manager.py:356` | `paths.sandbox_outputs_dir(thread_id).resolve()` — same function uses `resolve_virtual_path(tenant_id=…, workspace_id=…)` on line 363, so the boundary check (line 372) misfires when ids are present |
| **C** | `app/channels/feishu.py:348` + `app/channels/manager.py:771` + `app/channels/base.py:110` | The IM file-receive chain (`Channel.receive_file → FeishuChannel.receive_file → _receive_single_file`) does not accept tenant ids; `manager._handle_chat` already has them but does not forward them |
| **E** | `app/gateway/routers/threads.py:148-152` (`_delete_thread_data`) | Calls `path_manager.delete_thread_dir(thread_id)` with no tenant ids; identity-on threads physically live under `tenants/{T}/workspaces/{W}/threads/{tid}/`, so the delete silently no-ops the legacy path and leaks the tenant directory on disk |

The legacy methods were left in place, looking superficially usable, with no warning. New callers gravitate to whichever is shorter/more familiar (the legacy one), and reviewers miss the regression because the change "looks fine."

## 3. Goals & Non-Goals

### Goals
1. Fix Web UI uploads under `ENABLE_IDENTITY=true` (the visible P1 — call site A).
2. Fix the latent IM-channel bugs (call sites B and C) before they bite production.
3. Fix the silent thread-delete leak (call site E) so identity-on tenant directories are actually removed.
4. Make every legacy `Paths` method emit `DeprecationWarning` so the next person who reaches for the wrong API is told immediately. Migrate all in-tree call sites.
5. Behavior is bit-for-bit identical for callers who pass no identity (`ENABLE_IDENTITY=false`, anonymous, or partial ids).
6. TDD coverage: 7 new unit tests, all of which fail before the fix and pass after.

### Non-Goals
- Physically deleting the legacy methods. Out-of-tree callers may exist; deprecation epic handles physical removal one release later.
- Deprecating the `host_*` family. Docker bind-mount orchestration uses these in places not yet audited; tracked separately.
- Reviewing or changing identity propagation, RBAC, audit log, or any of the M5/M6 plumbing.
- Adding tenant-awareness to Slack/Telegram channel `receive_file`. Verified neither channel overrides the base no-op (`grep receive_file` shows only `feishu.py`).
- Backward-compat shims for the new `Channel.receive_file` signature. The two new keyword-only parameters default to `None`; existing positional callers and override-free subclasses are unaffected.

## 4. Architecture

### A. UploadsMiddleware — read identity from state

**State schema gains `identity` (typed `Any` to keep the harness/app boundary clean):**

```python
class UploadsMiddlewareState(AgentState):
    uploaded_files: NotRequired[list[dict] | None]
    identity: NotRequired[Any]
```

**`before_agent` reads ids defensively (mirrors `ThreadDataMiddleware`):**

```python
from deerflow.agents.middlewares._identity import extract_tenant_ids

identity = state.get("identity") if hasattr(state, "get") else None
tenant_id, workspace_id = extract_tenant_ids(identity)
uploads_dir = (
    self._paths.resolve_sandbox_uploads_dir(
        thread_id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if thread_id
    else None
)
```

`extract_tenant_ids(None) == (None, None)`. `resolve_sandbox_uploads_dir(thread_id, tenant_id=None, workspace_id=None)` falls back to `sandbox_uploads_dir(thread_id)` via `_is_tenant_scoped`. Result: zero behaviour change for legacy callers.

### B. manager.py:356 — outputs_dir boundary check

**One-line fix.** `_resolve_attachments(thread_id, artifacts, *, tenant_id, workspace_id)` already accepts the ids and uses them on the next line for `resolve_virtual_path`. Update line 356 to match:

```python
outputs_dir = paths.resolve_sandbox_outputs_dir(
    thread_id, tenant_id=tenant_id, workspace_id=workspace_id
).resolve()
```

### C. Feishu channel — forward tenant ids end-to-end

**Base class signature** (`app/channels/base.py`, line 110):

```python
async def receive_file(
    self,
    msg: InboundMessage,
    thread_id: str,
    *,
    tenant_id: int | None = None,
    workspace_id: int | None = None,
) -> InboundMessage:
    return msg
```

**`FeishuChannel.receive_file` and `_receive_single_file`** propagate the kwargs and delegate path resolution to a new pure helper:

```python
def _resolve_uploads_dir(
    self,
    thread_id: str,
    *,
    tenant_id: int | None,
    workspace_id: int | None,
) -> Path:
    """Return the host-side uploads directory for *thread_id*, creating it on demand."""
    paths = get_paths()
    paths.ensure_thread_dirs_for(
        thread_id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    return paths.resolve_sandbox_uploads_dir(
        thread_id, tenant_id=tenant_id, workspace_id=workspace_id
    ).resolve()
```

**`manager.py:771` forwards the ids it already has** (resolved from `ChannelStore` mapping at lines 748–749):

```python
msg = (
    await channel.receive_file(
        msg, thread_id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if channel
    else msg
)
```

### D. Paths legacy methods — deprecate via thin delegation

Eight methods (in `packages/harness/deerflow/config/paths.py`) become thin delegates that emit `DeprecationWarning` and forward to the `resolve_*` / `_for` cousin:

- `thread_dir` → `resolve_thread_dir`
- `sandbox_work_dir` → `resolve_sandbox_work_dir`
- `sandbox_uploads_dir` → `resolve_sandbox_uploads_dir`
- `sandbox_outputs_dir` → `resolve_sandbox_outputs_dir`
- `acp_workspace_dir` → `resolve_acp_workspace_dir`
- `sandbox_user_data_dir` → `resolve_sandbox_user_data_dir`
- `ensure_thread_dirs` → `ensure_thread_dirs_for`
- `delete_thread_dir` → `delete_thread_dir_for` *(new method introduced for E; uses `resolve_thread_dir` internally)*

Pattern:

```python
def sandbox_uploads_dir(self, thread_id: str) -> Path:
    """DEPRECATED: use ``resolve_sandbox_uploads_dir`` instead."""
    warnings.warn(
        "Paths.sandbox_uploads_dir() is deprecated; use "
        "resolve_sandbox_uploads_dir(thread_id, tenant_id=..., workspace_id=...) "
        "(it falls back to the legacy layout when ids are absent).",
        DeprecationWarning,
        stacklevel=2,
    )
    return self.resolve_sandbox_uploads_dir(thread_id)
```

`ensure_thread_dirs` similarly delegates to `ensure_thread_dirs_for(thread_id)`. `ensure_thread_dirs_for` already uses only `resolve_*` helpers, so the legacy shim is the *only* place that emits a warning — no internal warning loops.

**Behavioural invariant preserved**: `resolve_*(thread_id, tenant_id=None, workspace_id=None)` returns exactly what `legacy_*(thread_id)` would have returned. Verified by inspecting `_is_tenant_scoped` (rejects `None`, non-int, bool, non-positive) and `resolve_thread_dir` (returns `self.thread_dir(thread_id)` on fallback).

### E. Threads router — read identity, pass tenant ids to `delete_thread_dir`

**The problem with the current code path** (`app/gateway/routers/threads.py:148-164`):

```python
def _delete_thread_data(thread_id: str, paths: Paths | None = None) -> ThreadDeleteResponse:
    path_manager = paths or get_paths()
    path_manager.delete_thread_dir(thread_id)        # legacy path only
```

`delete_thread_dir` itself calls `self.thread_dir(thread_id)` (line 273 of `paths.py`) — also legacy. With `ENABLE_IDENTITY=true`, the actual data lives at `tenants/{T}/workspaces/{W}/threads/{tid}/`, so the call is effectively a silent no-op and tenant directories accumulate forever.

**Fix shape** (depends on D's new `delete_thread_dir_for`):

1. **Use `delete_thread_dir_for(thread_id, *, tenant_id, workspace_id)`** added in part D₁. It uses `resolve_thread_dir(...)` (which falls back to legacy when ids are absent).

2. **Update `_delete_thread_data` to accept tenant ids** and forward them:

```python
def _delete_thread_data(
    thread_id: str,
    *,
    tenant_id: int | None = None,
    workspace_id: int | None = None,
    paths: Paths | None = None,
) -> ThreadDeleteResponse:
    path_manager = paths or get_paths()
    path_manager.delete_thread_dir_for(
        thread_id, tenant_id=tenant_id, workspace_id=workspace_id
    )
```

3. **`delete_thread_data` route handler reads identity** via the lifted `_extract_scope`:

```python
@router.delete("/{thread_id}", response_model=ThreadDeleteResponse)
async def delete_thread_data(thread_id: str, request: Request) -> ThreadDeleteResponse:
    tenant_id, workspace_id = _extract_scope(request)
    response = _delete_thread_data(
        thread_id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    ...
```

The `_extract_scope` helper currently exists in **two duplicate copies**: `uploads.py:34-79` and `artifacts.py:21`. To avoid further duplication when `threads.py` joins the party, **lift it to `app/gateway/identity/request_scope.py`** (single source of truth). Update all three routers (`uploads.py`, `artifacts.py`, `threads.py`) to import from the new module. This is a minor mechanical refactor — same logic, existing tests of `uploads.py` and `artifacts.py` continue to pass without modification.

**Anonymous semantics (β')**: when identity is on but the caller is anonymous (or the ids are absent / non-positive), `_extract_scope` returns `(None, None)` and `delete_thread_dir_for` falls back to `delete_thread_dir` semantics on the legacy path. **This matches `uploads.py` exactly — no new asymmetry.**

If future RBAC hardening wants to deny anonymous deletes, that's a router-wide policy change, applied to *all* threads routes uniformly (out of scope here).

## 5. Data Flow

### Before (broken with `ENABLE_IDENTITY=true`)

```
HumanMessage (additional_kwargs.files = [{filename: "财务数据.csv"}])
  ↓
IdentityMiddleware     → state["identity"] = VerifiedIdentity(tenant_id=1, workspace_id=1, ...)
ThreadDataMiddleware   → uses tenant path ✓
SandboxMiddleware      → uses tenant path ✓
UploadsMiddleware      → ✗ ignores state["identity"]; reads legacy {base}/threads/.../uploads/
  ↓
no <uploaded_files> block
  ↓
agent: ask_clarification("which data?")
```

### After

```
HumanMessage (additional_kwargs.files = [...])
  ↓
IdentityMiddleware     → state["identity"] = VerifiedIdentity(tenant_id=1, workspace_id=1, ...)
ThreadDataMiddleware   → tenant path
SandboxMiddleware      → tenant path
UploadsMiddleware      → reads tenant path; injects <uploaded_files> with file outline
  ↓
agent: read_file("/mnt/user-data/uploads/财务数据.csv") → analysis → present_files
```

Identity-off flow is unchanged: every middleware (including new uploads code path) sees `extract_tenant_ids → (None, None)` and falls back to legacy.

### Thread delete (call site E)

**Before**:

```
DELETE /api/threads/{tid}  (identity on)
  ↓
delete_thread_data(thread_id, request)
  ↓
_delete_thread_data(thread_id)            # ✗ does not read identity
  ↓
paths.delete_thread_dir(thread_id)        # legacy path
  ↓
shutil.rmtree({base}/threads/{tid}/)      # path does not exist → silent no-op
                                            # tenant dir leaks on disk
```

**After**:

```
DELETE /api/threads/{tid}  (identity on)
  ↓
delete_thread_data(thread_id, request)
  ↓
tenant_id, workspace_id = _extract_scope(request)   # ← reads request.state.identity
  ↓
_delete_thread_data(thread_id, tenant_id=1, workspace_id=1)
  ↓
paths.delete_thread_dir_for(thread_id, tenant_id=1, workspace_id=1)
  ↓
shutil.rmtree({base}/tenants/1/workspaces/1/threads/{tid}/)   # ✓ tenant dir removed
```

Anonymous / identity-off flow continues to remove the legacy path (or no-op if it doesn't exist) — no regression.

## 6. Error Handling Matrix

| Scenario | Pre-fix | Post-fix | Change |
|---|---|---|---|
| Identity flag off | legacy path | legacy path | none |
| Identity on, anonymous caller | legacy path (identity not on state) | legacy path | none |
| Identity on, complete `(tenant=1, workspace=1)` | **legacy path → bug** | **tenant path** | **fix** |
| Identity on, partial (`tenant=None`) | legacy path | legacy path | none |
| Identity on, non-positive (`tenant=0` / `tenant=-1`) | legacy path | legacy path (`_is_tenant_scoped` rejects) | none |
| Identity on, bool (`tenant=True`) | legacy path | legacy path (`_is_tenant_scoped` rejects bool) | none |
| `thread_id` missing | `uploads_dir = None` | `uploads_dir = None` | none |
| Caller invokes `paths.sandbox_uploads_dir(...)` | silent legacy path | `DeprecationWarning` + legacy path | warn (no behavioural change) |
| `DELETE /api/threads/{tid}` with identity on, full ids | **silently no-ops legacy path; tenant dir leaks** | physically removes tenant dir | **fix** |
| `DELETE /api/threads/{tid}` with identity on, anonymous | legacy path no-op | legacy path no-op (β' fallback) | none |
| `DELETE /api/threads/{tid}` with identity off | legacy path delete | legacy path delete | none |

The new identity read piggybacks on the existing `_is_tenant_scoped` gate. **No new failure modes are introduced.**

## 7. Testing

Seven new unit tests, mapped to call sites:

| # | File | Name | Covers |
|---|---|---|---|
| 1 | `tests/test_uploads_middleware_core_logic.py` | `test_before_agent_reads_from_tenant_path_when_identity_present` | A |
| 2 | `tests/test_channels.py` (or `test_channel_artifact_tenant.py`) | `test_resolve_attachments_outputs_dir_uses_tenant_path` | B |
| 3 | `tests/test_channels.py` | `test_handle_chat_passes_tenant_to_channel_receive_file` | C (manager.py:771 dispatch) |
| 4 | feishu test file | `test_feishu_resolve_uploads_dir_with_tenant_returns_tenant_path` | C (`_resolve_uploads_dir` pure helper, with ids) |
| 5 | feishu test file | `test_feishu_resolve_uploads_dir_without_tenant_returns_legacy` | C (fallback) |
| 6 | `tests/test_paths.py` | `test_legacy_path_methods_emit_deprecation_warning` + `test_internal_resolve_callers_do_not_warn` (one file, parameterised) | D |
| 7 | `tests/test_threads_router.py` (or `test_threads_delete_tenant.py`) | `test_delete_thread_data_removes_tenant_directory_when_identity_present` + `test_delete_thread_data_falls_back_to_legacy_when_anonymous` | E |

Tests #4 and #5 deliberately bypass the lark SDK by isolating the helper — see Q4 in the brainstorming session.

Existing `test_uploads_middleware_core_logic.py` cases use `_runtime(thread_id="thread-abc123")` with no identity. They will continue to exercise the legacy fallback path unchanged.

## 8. Implementation Order

One PR, six commits, each independently revertible:

1. **D₁** — `feat(paths): add delete_thread_dir_for(thread_id, *, tenant_id, workspace_id)` *(introduces the missing tenant-aware delete method that E depends on; bundled with D for atomicity)*
2. **D₂** — `chore(paths): deprecate legacy thread-path methods, delegate to resolve_*` *(infra audit; full test suite must stay green; after this commit lands, the only `DeprecationWarning` emissions during `make test` should come from tests that intentionally exercise the legacy methods — i.e. test #6 itself; all production code paths migrated to `resolve_*` / `_for`)*
3. **A** — `fix(uploads-middleware): read uploads from tenant-aware path when identity is set (P1)`
4. **B** — `fix(channels/manager): use tenant-aware outputs_dir in artifact boundary check`
5. **C** — `fix(channels/feishu): forward tenant_id/workspace_id through file-receive chain`
6. **E** — `fix(threads-router): pass tenant ids to delete_thread_dir; lift _extract_scope to identity/request_scope` *(also updates uploads.py and artifacts.py to import from the new shared module)*

Then docs:

7. `docs(specs): record M4 oversight + remediation` (this file lands separately; CLAUDE.md and lessons.md updated)

## 9. Acceptance Criteria

- [ ] `make test` (full backend suite) is green.
- [ ] `make lint` is clean.
- [ ] All 7 new tests pass.
- [ ] Total `DeprecationWarning` count emitted by `make test` is `≤` baseline (i.e. all internal callers were migrated to `resolve_*` / `_for`).
- [ ] Manual browser smoke (A): open a fresh chat, upload a `.csv`, send "分析这个数据"; backend logs show `New files: ['<filename>'], historical: []`; agent responds with file analysis (not `ask_clarification`).
- [ ] Manual browser smoke (E): create a thread on identity-on, then `DELETE /api/threads/{tid}`; verify `tenants/{T}/workspaces/{W}/threads/{tid}/` is physically removed.
- [ ] `backend/CLAUDE.md` line ~95 ("Consumed by ThreadDataMiddleware, SandboxMiddleware, UploadsMiddleware, and present_file_tool") corrected to reflect the *now-true* state.
- [ ] `docs/lessons.md` records: when changing a cross-cutting API (path resolution, state schema), grep the entire codebase for the old API and migrate every call site **in the same PR** — leaving both APIs available without deprecation guarantees future regressions.
- [ ] Branch `cc-main` pushed.

## 10. Out of Scope

| Item | Why deferred |
|---|---|
| Physically delete legacy `Paths` methods | One release of deprecation warning before removal |
| Deprecate `host_*` family | Docker bind-mount audit pending; not on the P1 path |
| Slack / Telegram tenant forwarding | Neither overrides `Channel.receive_file`; no write path exists |
| Re-audit Skills / Memory tenant-awareness | M4 task 5 already covers them per `backend/CLAUDE.md` (and visible via grep); not in scope here |
| Audit log signal "uploads-middleware blind to files" | The 6 new tests are sufficient regression coverage |
