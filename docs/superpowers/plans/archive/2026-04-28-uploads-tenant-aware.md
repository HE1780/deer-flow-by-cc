> 📦 **归档于 2026-04-29 — 已 ship**
>
> **当前事实**：5 处 call site 全部修复，对应 commits：
> - `aedcf8af` UploadsMiddleware 走 tenant-aware 路径（call A）
> - `4ce6c997` channels/manager 用 tenant-aware outputs_dir（call B）
> - `9722937c` channels/feishu 透传 tenant_id/workspace_id（call C/D）
> - `16770364` threads-router DELETE 转发 tenant ids（call E）
> - `4eca6cc5` UploadsMiddleware 单测覆盖
> - `113c88c0` legacy 方法加 DeprecationWarning 防回归
>
> 下文为原始 plan，仅作历史档案保留。

---

# Uploads Tenant-Aware Path Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the M4 storage-isolation oversights so identity-on requests use the tenant-stratified path layout for uploads, IM-channel artifact delivery, and thread cleanup; deprecate the legacy `Paths` methods to prevent regressions.

**Architecture:** Five fixes (A=UploadsMiddleware, B=manager outputs_dir, C=Feishu file-receive chain, D=Paths deprecation + new `delete_thread_dir_for`, E=Threads router identity). All five share one defensive contract: `extract_tenant_ids` / `_extract_scope` returns `(None, None)` when ids are absent, and the `Paths.resolve_*` helpers fall back to the legacy single-tenant layout — so behaviour is bit-for-bit identical when `ENABLE_IDENTITY=false`.

**Tech Stack:** Python 3.12, pytest, FastAPI, LangGraph (`langchain.agents.middleware.AgentMiddleware`), `deerflow.config.paths.Paths`, ruff.

**Spec:** `docs/superpowers/specs/2026-04-28-uploads-tenant-aware-design.md`

**Branch:** `cc-main` (no feature branch — small targeted fixes, frequent push)

---

## File Structure

### New files

| Path | Purpose |
|---|---|
| `backend/app/gateway/identity/request_scope.py` | Single source of truth for `_extract_scope(request) -> (tenant_id, workspace_id)`, lifted from `uploads.py` and `artifacts.py` |
| `backend/tests/test_request_scope.py` | Tests for the lifted `_extract_scope` helper (covers what `tests/test_uploads_router.py` and `tests/identity/test_artifacts_authz.py` currently exercise indirectly) |

### Modified files (production)

| Path | Modification |
|---|---|
| `backend/packages/harness/deerflow/config/paths.py` | (1) Add `delete_thread_dir_for(thread_id, *, tenant_id, workspace_id)` (2) Convert 8 legacy methods to thin delegates that emit `DeprecationWarning` |
| `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py` | Read `state["identity"]`, call `resolve_sandbox_uploads_dir(thread_id, tenant_id=…, workspace_id=…)` |
| `backend/app/channels/manager.py` | (1) line 356 → `resolve_sandbox_outputs_dir` (2) line 771 forwards `tenant_id`/`workspace_id` to `channel.receive_file` |
| `backend/app/channels/base.py` | `Channel.receive_file` signature gains `*, tenant_id=None, workspace_id=None` |
| `backend/app/channels/feishu.py` | (1) `receive_file` accepts and propagates kwargs (2) `_receive_single_file` accepts kwargs (3) New helper `_resolve_uploads_dir` (4) Replace lines 347–348 with `_resolve_uploads_dir(...)` call |
| `backend/app/gateway/routers/threads.py` | (1) Import `_extract_scope` from new module (2) `_delete_thread_data` accepts kwargs (3) Route handler reads scope and forwards |
| `backend/app/gateway/routers/uploads.py` | Replace local `_extract_scope` with `from app.gateway.identity.request_scope import extract_scope` (rename per public API) |
| `backend/app/gateway/routers/artifacts.py` | Same as uploads.py |
| `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py` | line 40 → `paths.resolve_acp_workspace_dir(thread_id)` (kills DeprecationWarning; keeps legacy semantics — see spec out-of-scope) |

### Modified files (tests — internal-caller migration)

| Path | Why |
|---|---|
| `backend/tests/test_uploads_middleware_core_logic.py` | Helper `_uploads_dir` uses `sandbox_uploads_dir` (legacy) — migrate to `resolve_sandbox_uploads_dir(thread_id)`; **add new test #1 (A)** |
| `backend/tests/test_threads_router.py` | Lines 13–16, 38, 53–55 all use legacy methods — migrate; **add new test #7 (E)** |
| `backend/tests/test_channel_file_attachments.py` | Lines 116, 139, 157, 214, 232 mock `mock_paths.sandbox_outputs_dir` — switch to `mock_paths.resolve_sandbox_outputs_dir` |
| `backend/tests/test_channels.py` | Lines 2602, 2640 same as above; **add new test #2 (B) and #3 (C dispatch)** |
| `backend/tests/test_client.py` | Lines 1494, 1507, 1520, 1710, 1962, 1964, 2874, 2885, 3001, 3025 — migrate (mostly `sandbox_outputs_dir`/`sandbox_user_data_dir`/`sandbox_uploads_dir`) |
| `backend/tests/test_client_e2e.py` | Lines 266, 403, 480, 495 — migrate |
| `backend/tests/test_aio_sandbox_provider.py` | Lines 16, 27 — `paths.ensure_thread_dirs(...)` → `paths.ensure_thread_dirs_for(...)` |
| `backend/tests/identity/test_artifacts_authz.py` | Lines 89, 177 — same |
| `backend/tests/identity/storage/test_sandbox_mount_tenant.py` | Line 231 — same |
| `backend/tests/test_paths_tenant_aware.py` | **Add new test #6 (D)** — deprecation warnings + internal-caller silence |
| `backend/tests/feishu/...` (or `test_channel_file_attachments.py`) | **Add new tests #4 and #5 (C `_resolve_uploads_dir`)** |

> **Why this many test migrations:** D₂ adds `DeprecationWarning` emission to 8 legacy `Paths` methods. Pytest treats `DeprecationWarning` as a regular signal by default; if any production caller still uses them, the warning surfaces in CI logs and (with `-W error::DeprecationWarning`, which we will *not* enable in CI) would fail tests. Migrating internal callers preserves zero-warning baseline.

---

## Task 0 — Pre-flight: baseline check & branch hygiene

**Files:**
- Read-only: `backend/.deer-flow/`, `backend/CLAUDE.md`, `.env`

- [ ] **Step 1: Confirm starting branch is `cc-main` and clean**

Run: `git status -sb && git log -1 --oneline`
Expected: branch `cc-main`, working tree clean, top commit is `53381aea docs(specs): add uploads tenant-aware path fix design`.

- [ ] **Step 2: Confirm `ENABLE_IDENTITY` is on locally (so manual smoke at the end is meaningful)**

Run: `grep -E "^ENABLE_IDENTITY=" backend/.env || echo NOT_SET`
Expected: `ENABLE_IDENTITY=true` (already verified earlier this session).

- [ ] **Step 3: Snapshot baseline `make test` exit code**

Run: `cd backend && make test 2>&1 | tail -20`
Expected: exit 0 (all passing). Capture warning count from final pytest summary line — this is the baseline for D₂'s acceptance criterion ("warning count ≤ baseline").

If any test fails on `cc-main` head before we touch anything, STOP and fix that first; we cannot distinguish "bug we introduced" from "bug already there."

- [ ] **Step 4: Create todo list in this session**

Use TodoWrite to mirror Tasks 1-12 below; mark Task 1 in_progress.

---

## Task 1 — D₁: Add `delete_thread_dir_for` to `Paths`

**Files:**
- Modify: `backend/packages/harness/deerflow/config/paths.py` (add new method after `delete_thread_dir`, around line 276)
- Test: `backend/tests/test_paths_tenant_aware.py` (add new class/test)

- [ ] **Step 1: Write the failing test**

Edit `backend/tests/test_paths_tenant_aware.py`. Add a new class at the end:

```python
class TestDeleteThreadDirFor:
    def test_removes_tenant_thread_dir_when_ids_present(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        thread_dir = paths.tenant_thread_dir(5, 7, "thread-x")
        thread_dir.mkdir(parents=True)
        (thread_dir / "marker.txt").write_text("hi")
        assert thread_dir.exists()

        paths.delete_thread_dir_for("thread-x", tenant_id=5, workspace_id=7)

        assert not thread_dir.exists()

    def test_falls_back_to_legacy_thread_dir_when_ids_absent(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        legacy = Path(tmp_path) / "threads" / "thread-y"
        legacy.mkdir(parents=True)
        (legacy / "marker.txt").write_text("hi")
        assert legacy.exists()

        paths.delete_thread_dir_for("thread-y")

        assert not legacy.exists()

    def test_idempotent_when_directory_absent(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        # Must not raise.
        paths.delete_thread_dir_for("ghost", tenant_id=1, workspace_id=1)
        paths.delete_thread_dir_for("ghost")  # legacy fallback path

    def test_partial_ids_falls_back_to_legacy(self, tmp_path):
        """workspace_id missing → legacy path used."""
        paths = Paths(base_dir=str(tmp_path))
        legacy = Path(tmp_path) / "threads" / "thread-p"
        legacy.mkdir(parents=True)

        paths.delete_thread_dir_for("thread-p", tenant_id=5, workspace_id=None)

        assert not legacy.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_paths_tenant_aware.py::TestDeleteThreadDirFor -v`
Expected: 4 failures, all with `AttributeError: 'Paths' object has no attribute 'delete_thread_dir_for'`.

- [ ] **Step 3: Add the method to `Paths`**

Edit `backend/packages/harness/deerflow/config/paths.py`. Locate `def delete_thread_dir(self, thread_id: str) -> None:` (around line 268). Add this **immediately after** that method (before the `# ── Tenant-stratified paths` block):

```python
    def delete_thread_dir_for(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> None:
        """Tenant-aware thread-data deletion.

        Mirrors :meth:`delete_thread_dir` (idempotent when the directory is
        already absent), but routes through :meth:`resolve_thread_dir` so that
        identity-aware callers physically remove the tenant-stratified directory.
        Falls back to the legacy layout when either id is missing or non-positive.
        """
        target = self.resolve_thread_dir(
            thread_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
        if target.exists():
            shutil.rmtree(target)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_paths_tenant_aware.py::TestDeleteThreadDirFor -v`
Expected: 4 PASS.

- [ ] **Step 5: Run the full paths test file to confirm no regressions**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_paths_tenant_aware.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/packages/harness/deerflow/config/paths.py backend/tests/test_paths_tenant_aware.py
git commit -m "$(cat <<'EOF'
feat(paths): add delete_thread_dir_for(*, tenant_id, workspace_id)

Tenant-aware companion to delete_thread_dir, mirroring the resolve_*/_for
pattern already used for thread directory creation. Falls back to the legacy
single-tenant layout when ids are absent or non-positive, so callers that
do not yet pass identity see no behavioural change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — D₂: Migrate internal callers off legacy `Paths` methods

**Goal of this task:** Touch every production and test caller that uses one of the 8 to-be-deprecated methods, switching them to `resolve_*` / `_for`. After this task, only **explicit deprecation tests** in test #6 should still call the legacy methods. **No `DeprecationWarning` is emitted yet** — that comes in Task 3.

**Files (production):**
- Modify: `backend/app/gateway/routers/threads.py:152` (will be wholly rewritten in Task 9; here only switch to `resolve_*` so the no-op test stays green)
- Modify: `backend/app/channels/manager.py:356` (lookahead — will be wholly rewritten in Task 6; here switch to `resolve_*`)
- Modify: `backend/app/channels/feishu.py:347-348` (lookahead — Task 7 wholly rewrites; switch now)
- Modify: `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py:224` (lookahead — Task 5 wholly rewrites; switch now)
- Modify: `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py:40`
- Modify: `backend/packages/harness/deerflow/config/paths.py:259-265, 273` (`ensure_thread_dirs` and `delete_thread_dir` internal calls)

> **Note on ordering:** Tasks 5, 6, 7, 9 will rewrite the 4 production call sites with the **real** identity-reading logic. This task does the **mechanical** legacy → `resolve_*` rename without identity. That keeps Task 3's deprecation rollout safe even if we stop here, and isolates the "add identity reads" change from the "stop using legacy method names" change.

**Files (tests):**
- Modify: `backend/tests/test_uploads_middleware_core_logic.py:37`
- Modify: `backend/tests/test_threads_router.py:13-16, 38, 53-55, 100`
- Modify: `backend/tests/test_channel_file_attachments.py:116, 139, 157, 214, 232`
- Modify: `backend/tests/test_channels.py:2602, 2640`
- Modify: `backend/tests/test_client.py:1494, 1507, 1520, 1710, 1962, 1964, 2874, 2885, 3001, 3025`
- Modify: `backend/tests/test_client_e2e.py:266, 403, 480, 495`
- Modify: `backend/tests/test_aio_sandbox_provider.py:16, 27`
- Modify: `backend/tests/identity/test_artifacts_authz.py:89, 177`
- Modify: `backend/tests/identity/storage/test_sandbox_mount_tenant.py:231`

- [ ] **Step 1: Pre-grep — capture exact call sites**

Run: `cd backend && grep -rn '\.sandbox_work_dir\|\.sandbox_uploads_dir\|\.sandbox_outputs_dir\|\.acp_workspace_dir\|\.sandbox_user_data_dir\|\.thread_dir(\|\.ensure_thread_dirs(\|\.delete_thread_dir(' --include="*.py" | grep -v "host_\|resolve_\|ensure_thread_dirs_for\|delete_thread_dir_for"`

Expected output: ~50 lines. Save this list — every line must be migrated by end of step 5.

- [ ] **Step 2: Migrate `paths.py` self-references**

In `backend/packages/harness/deerflow/config/paths.py`:

(a) Lines 259-266 (`ensure_thread_dirs`): change body to delegate. Keep signature.

```python
    def ensure_thread_dirs(self, thread_id: str) -> None:
        """Create all standard sandbox directories for a thread (legacy layout)."""
        self.ensure_thread_dirs_for(thread_id)
```

(b) Lines 268-275 (`delete_thread_dir`): change body to delegate.

```python
    def delete_thread_dir(self, thread_id: str) -> None:
        """Delete all persisted data for a thread (legacy layout)."""
        self.delete_thread_dir_for(thread_id)
```

(c) Lines 184-220 (`sandbox_work_dir` / `sandbox_uploads_dir` / `sandbox_outputs_dir` / `acp_workspace_dir` / `sandbox_user_data_dir`): rewrite each to call `self.resolve_*(thread_id)`. Example for `sandbox_uploads_dir`:

```python
    def sandbox_uploads_dir(self, thread_id: str) -> Path:
        """Host path for user-uploaded files (legacy single-tenant layout)."""
        return self.resolve_sandbox_uploads_dir(thread_id)
```

Apply the same pattern to all five. Note `thread_dir(thread_id)` itself: it's the leaf that `resolve_thread_dir` falls back to, so it stays as-is (no change to body).

> **Why now (before Task 3 adds the warnings):** `ensure_thread_dirs_for` internally calls `resolve_*` which falls back to `self.thread_dir(thread_id)`. Once `thread_dir` emits a warning, every `ensure_thread_dirs_for` invocation would also trigger one transitively. By making the *legacy methods* the thin delegates and `resolve_*` the implementations, we ensure that only direct legacy callers warn.

To make this work, **`resolve_thread_dir` must NOT call `self.thread_dir(thread_id)` after Task 3.** Verify it currently does (line 324: `return self.thread_dir(thread_id)`). Change line 324 to inline:

```python
        # Tenant-scoped path requested but ids missing → legacy layout.
        return self.base_dir / "threads" / _validate_thread_id(thread_id)
```

This is the same body as `thread_dir`. Now the legacy `thread_dir(thread_id)` can become a thin delegate to `resolve_thread_dir(thread_id)` without recursion.

(d) Lines 166-177 (`thread_dir`): switch to delegate.

```python
    def thread_dir(self, thread_id: str) -> Path:
        """Host path for a thread (legacy single-tenant layout)."""
        return self.resolve_thread_dir(thread_id)
```

- [ ] **Step 3: Migrate production call sites (mechanical)**

For each of the 5 production lines listed in the file structure, change the call to `resolve_*` keeping `thread_id` as the only arg:

- `app/gateway/routers/threads.py:152` → `path_manager.delete_thread_dir_for(thread_id)`
- `app/channels/manager.py:356` → `paths.resolve_sandbox_outputs_dir(thread_id).resolve()`
- `app/channels/feishu.py:347` → `paths.ensure_thread_dirs_for(thread_id)`
- `app/channels/feishu.py:348` → `paths.resolve_sandbox_uploads_dir(thread_id).resolve()`
- `packages/harness/deerflow/agents/middlewares/uploads_middleware.py:224` → `self._paths.resolve_sandbox_uploads_dir(thread_id) if thread_id else None`
- `packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py:40` → `work_dir = paths.resolve_acp_workspace_dir(thread_id)`

- [ ] **Step 4: Migrate test call sites**

Walk the list from Step 1's grep output. For every test file matched:
- `paths.sandbox_uploads_dir(tid)` → `paths.resolve_sandbox_uploads_dir(tid)`
- `paths.sandbox_outputs_dir(tid)` → `paths.resolve_sandbox_outputs_dir(tid)`
- `paths.sandbox_user_data_dir(tid)` → `paths.resolve_sandbox_user_data_dir(tid)`
- `paths.sandbox_work_dir(tid)` → `paths.resolve_sandbox_work_dir(tid)`
- `paths.thread_dir(tid)` → `paths.resolve_thread_dir(tid)`
- `paths.ensure_thread_dirs(tid)` → `paths.ensure_thread_dirs_for(tid)`
- `paths.delete_thread_dir(tid)` (rare; `test_threads_router.py:100` mocks it) → `paths.delete_thread_dir_for(tid)`
- `mock_paths.sandbox_outputs_dir.return_value` → `mock_paths.resolve_sandbox_outputs_dir.return_value`

Use `sed` per file rather than global replace — paths like `host_sandbox_outputs_dir` must NOT be touched.

Per-file safe sed pattern (run in repo root):

```bash
for f in backend/tests/test_uploads_middleware_core_logic.py \
         backend/tests/test_threads_router.py \
         backend/tests/test_channel_file_attachments.py \
         backend/tests/test_channels.py \
         backend/tests/test_client.py \
         backend/tests/test_client_e2e.py \
         backend/tests/test_aio_sandbox_provider.py \
         backend/tests/identity/test_artifacts_authz.py \
         backend/tests/identity/storage/test_sandbox_mount_tenant.py; do
  # Use word boundaries (s/\b…/) to avoid touching host_* / resolve_*.
  sed -i '' \
    -e 's/\([^_a-zA-Z]\)sandbox_uploads_dir(/\1resolve_sandbox_uploads_dir(/g' \
    -e 's/\([^_a-zA-Z]\)sandbox_outputs_dir(/\1resolve_sandbox_outputs_dir(/g' \
    -e 's/\([^_a-zA-Z]\)sandbox_work_dir(/\1resolve_sandbox_work_dir(/g' \
    -e 's/\([^_a-zA-Z]\)sandbox_user_data_dir(/\1resolve_sandbox_user_data_dir(/g' \
    -e 's/\([^_a-zA-Z]\)acp_workspace_dir(/\1resolve_acp_workspace_dir(/g' \
    -e 's/\([^_a-zA-Z]\)thread_dir(/\1resolve_thread_dir(/g' \
    -e 's/\([^_a-zA-Z]\)ensure_thread_dirs(/\1ensure_thread_dirs_for(/g' \
    -e 's/\([^_a-zA-Z]\)delete_thread_dir(/\1delete_thread_dir_for(/g' \
    -e 's/\.sandbox_outputs_dir\.return_value/\.resolve_sandbox_outputs_dir.return_value/g' \
    -e 's/\.sandbox_uploads_dir\.return_value/\.resolve_sandbox_uploads_dir.return_value/g' \
    "$f"
done
```

(macOS `sed -i ''` is intentional. Linux drops the empty arg.)

- [ ] **Step 5: Verify with grep that no production legacy call remains except the deliberate self-delegates**

Run: `cd backend && grep -rn '\.sandbox_work_dir\|\.sandbox_uploads_dir\|\.sandbox_outputs_dir\|\.acp_workspace_dir\|\.sandbox_user_data_dir\|\.thread_dir(\|\.ensure_thread_dirs(\|\.delete_thread_dir(' --include="*.py" | grep -v "host_\|resolve_\|ensure_thread_dirs_for\|delete_thread_dir_for"`

Expected output:
```
packages/harness/deerflow/config/paths.py:<linenum>:        return self.resolve_sandbox_work_dir(thread_id)
packages/harness/deerflow/config/paths.py:<linenum>:        return self.resolve_sandbox_uploads_dir(thread_id)
... (only the 8 thin delegate bodies inside paths.py)
```

If anything else shows up, grep was too aggressive — go back and fix that line manually.

- [ ] **Step 6: Run full test suite**

Run: `cd backend && make test 2>&1 | tail -40`
Expected: exit 0, same warning count as baseline (Task 0 step 3). If any test fails, the migration was incorrect — most likely a regex matched something unintended. Read the failure, fix, re-run.

- [ ] **Step 7: Lint**

Run: `cd backend && make lint`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add backend
git commit -m "$(cat <<'EOF'
refactor(paths): migrate internal callers off legacy thread-path methods

Switches all production and test call sites from sandbox_*_dir / thread_dir
/ ensure_thread_dirs / delete_thread_dir to their resolve_* / _for cousins.
The legacy methods are now thin delegates with identical semantics. This
prepares for the DeprecationWarning rollout in the next commit (no warning
emitted yet — only call-site rename).

The acp-workspace tool keeps fall-back behaviour: it does not have access to
state['identity'] so it stays on the legacy path layout, but no longer through
a soon-to-be-deprecated method name.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — D₃: Emit `DeprecationWarning` from legacy `Paths` methods

**Files:**
- Modify: `backend/packages/harness/deerflow/config/paths.py` (8 thin delegates from Task 2)
- Test: `backend/tests/test_paths_tenant_aware.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_paths_tenant_aware.py`:

```python
import warnings


class TestLegacyMethodDeprecation:
    """Eight legacy Paths methods must emit DeprecationWarning when called
    directly, while still returning the same legacy-layout values they always did."""

    def test_each_legacy_method_warns_and_returns_legacy_path(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        thread_id = "thread-dep"

        cases = [
            ("thread_dir", lambda: paths.thread_dir(thread_id),
             tmp_path / "threads" / thread_id),
            ("sandbox_work_dir", lambda: paths.sandbox_work_dir(thread_id),
             tmp_path / "threads" / thread_id / "user-data" / "workspace"),
            ("sandbox_uploads_dir", lambda: paths.sandbox_uploads_dir(thread_id),
             tmp_path / "threads" / thread_id / "user-data" / "uploads"),
            ("sandbox_outputs_dir", lambda: paths.sandbox_outputs_dir(thread_id),
             tmp_path / "threads" / thread_id / "user-data" / "outputs"),
            ("acp_workspace_dir", lambda: paths.acp_workspace_dir(thread_id),
             tmp_path / "threads" / thread_id / "acp-workspace"),
            ("sandbox_user_data_dir", lambda: paths.sandbox_user_data_dir(thread_id),
             tmp_path / "threads" / thread_id / "user-data"),
        ]
        for name, fn, expected in cases:
            with pytest.warns(DeprecationWarning, match=name):
                result = fn()
            assert result == expected, f"{name} returned {result}, expected {expected}"

    def test_ensure_thread_dirs_warns_and_creates_legacy_layout(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))

        with pytest.warns(DeprecationWarning, match="ensure_thread_dirs"):
            paths.ensure_thread_dirs("thread-e")

        assert (tmp_path / "threads" / "thread-e" / "user-data" / "uploads").is_dir()

    def test_delete_thread_dir_warns_and_removes_legacy(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        legacy = tmp_path / "threads" / "thread-d"
        legacy.mkdir(parents=True)

        with pytest.warns(DeprecationWarning, match="delete_thread_dir"):
            paths.delete_thread_dir("thread-d")

        assert not legacy.exists()

    def test_resolve_helpers_do_not_warn(self, tmp_path):
        """resolve_* / *_for methods (the new API) MUST NOT emit DeprecationWarning."""
        paths = Paths(base_dir=str(tmp_path))
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            paths.resolve_thread_dir("t1")
            paths.resolve_sandbox_uploads_dir("t1")
            paths.resolve_sandbox_outputs_dir("t1")
            paths.resolve_sandbox_work_dir("t1")
            paths.resolve_acp_workspace_dir("t1")
            paths.resolve_sandbox_user_data_dir("t1")
            paths.ensure_thread_dirs_for("t1")
            paths.delete_thread_dir_for("t1")
            # With ids:
            paths.resolve_thread_dir("t1", tenant_id=1, workspace_id=1)
            paths.delete_thread_dir_for("t1", tenant_id=1, workspace_id=1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_paths_tenant_aware.py::TestLegacyMethodDeprecation -v`
Expected: 3 failures (4 if `test_resolve_helpers_do_not_warn` reorders); each saying `DID NOT WARN` because the legacy methods don't emit warnings yet.

- [ ] **Step 3: Add `DeprecationWarning` to each of the 8 legacy delegates**

Edit `backend/packages/harness/deerflow/config/paths.py`. At the top, add `import warnings` (alphabetised; ruff I001 will sort).

For each of the 8 thin delegates created in Task 2, prepend a `warnings.warn(...)`. Pattern:

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

Apply equivalent treatment to:
- `thread_dir`
- `sandbox_work_dir`
- `sandbox_outputs_dir`
- `acp_workspace_dir`
- `sandbox_user_data_dir`
- `ensure_thread_dirs`
- `delete_thread_dir`

Each warning string should mention the **method's own name** (so `pytest.warns(match=name)` succeeds).

- [ ] **Step 4: Run new tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_paths_tenant_aware.py::TestLegacyMethodDeprecation -v`
Expected: 4 PASS.

- [ ] **Step 5: Run full suite — verify no production code triggers warnings**

Run: `cd backend && make test 2>&1 | tail -40`
Expected: exit 0. The warning count line at the end of pytest output should be the same as baseline (Task 0). Migration was successful in Task 2.

If you see new `DeprecationWarning` rows in the summary, Task 2 missed something. Run:

`cd backend && PYTHONPATH=. uv run pytest -W error::DeprecationWarning 2>&1 | grep -A3 "DeprecationWarning"`

That will fail loudly on the first stale legacy caller. Fix, re-run.

- [ ] **Step 6: Lint**

Run: `cd backend && make lint`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add backend/packages/harness/deerflow/config/paths.py backend/tests/test_paths_tenant_aware.py
git commit -m "$(cat <<'EOF'
chore(paths): emit DeprecationWarning from legacy thread-path methods

Each of the 8 legacy methods (thread_dir, sandbox_*_dir, ensure_thread_dirs,
delete_thread_dir) now warns the caller and delegates to its resolve_* / _for
cousin. Behaviour is preserved exactly. Internal callers were migrated in the
previous commit, so the test suite warning count is unchanged.

This makes future regressions of the M4 oversight louder: any new code path
that reaches for the old API name gets a DeprecationWarning the first time
it runs in tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — E₀: Lift `_extract_scope` to a shared module

**Goal:** Single source of truth for "read tenant_id/workspace_id from FastAPI request.state.identity." Currently duplicated in `uploads.py` and `artifacts.py`; about to be needed by `threads.py`. Lift first so Task 9 can import it cleanly.

**Files:**
- Create: `backend/app/gateway/identity/request_scope.py`
- Modify: `backend/app/gateway/routers/uploads.py:34-79` (replace local definition with import)
- Modify: `backend/app/gateway/routers/artifacts.py:21` (same)
- Test: `backend/tests/test_request_scope.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_request_scope.py`:

```python
"""Tests for the lifted _extract_scope helper.

Covers the four cases that uploads.py and artifacts.py currently exercise
indirectly: identity-flag-off, anonymous, valid full ids, and invalid/partial ids."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.gateway.identity.request_scope import extract_scope


def _request(*, identity=None) -> MagicMock:
    req = MagicMock()
    req.state = SimpleNamespace(identity=identity)
    return req


@patch("app.gateway.identity.request_scope.get_identity_settings")
class TestExtractScope:
    def test_returns_none_pair_when_request_is_none(self, mock_settings):
        mock_settings.return_value.enabled = True
        assert extract_scope(None) == (None, None)

    def test_returns_none_pair_when_flag_off(self, mock_settings):
        mock_settings.return_value.enabled = False
        identity = SimpleNamespace(tenant_id=5, workspace_id=7)
        assert extract_scope(_request(identity=identity)) == (None, None)

    def test_returns_none_pair_when_anonymous(self, mock_settings):
        mock_settings.return_value.enabled = True
        identity = SimpleNamespace(tenant_id=5, workspace_id=7, is_authenticated=False)
        assert extract_scope(_request(identity=identity)) == (None, None)

    def test_returns_full_pair_when_authenticated(self, mock_settings):
        mock_settings.return_value.enabled = True
        identity = SimpleNamespace(tenant_id=5, workspace_id=7, is_authenticated=True)
        assert extract_scope(_request(identity=identity)) == (5, 7)

    def test_falls_back_to_first_workspace_id(self, mock_settings):
        mock_settings.return_value.enabled = True
        identity = SimpleNamespace(
            tenant_id=5, workspace_id=None, workspace_ids=[7, 9], is_authenticated=True
        )
        assert extract_scope(_request(identity=identity)) == (5, 7)

    def test_returns_none_pair_when_either_id_invalid(self, mock_settings):
        mock_settings.return_value.enabled = True
        for tenant_id, workspace_id in [(0, 7), (-1, 7), (5, 0), (5, -1), (True, 7), (5, False)]:
            identity = SimpleNamespace(
                tenant_id=tenant_id, workspace_id=workspace_id, is_authenticated=True
            )
            assert extract_scope(_request(identity=identity)) == (None, None), \
                f"failed for ({tenant_id!r}, {workspace_id!r})"

    def test_returns_none_pair_when_identity_absent(self, mock_settings):
        mock_settings.return_value.enabled = True
        assert extract_scope(_request(identity=None)) == (None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_request_scope.py -v`
Expected: 7 errors with `ModuleNotFoundError: No module named 'app.gateway.identity.request_scope'`.

- [ ] **Step 3: Create the new module**

Create `backend/app/gateway/identity/request_scope.py`:

```python
"""Single source of truth for reading (tenant_id, workspace_id) off a FastAPI request.

Lifted from app.gateway.routers.uploads._extract_scope and
app.gateway.routers.artifacts._extract_scope (which were previously duplicated).
Routers now import :func:`extract_scope` from here.
"""

from fastapi import Request

from app.gateway.identity.settings import get_identity_settings


def extract_scope(request: Request | None) -> tuple[int | None, int | None]:
    """Return ``(tenant_id, workspace_id)`` from ``request.state.identity``.

    Returns ``(None, None)`` whenever:
    * ``request`` is ``None`` (direct unit-test invocation),
    * the identity feature flag is off,
    * the caller is anonymous (``identity.is_authenticated`` falsy),
    * the identity attribute is missing,
    * either id is missing, non-positive, or a non-int (incl. ``bool``).

    All callers must treat the all-or-nothing pair as "fall back to legacy
    single-tenant layout" — every tenant-aware ``Paths`` helper already does so.
    """
    if request is None:
        return None, None
    if not get_identity_settings().enabled:
        return None, None

    identity = getattr(request.state, "identity", None)
    if identity is None:
        return None, None
    if getattr(identity, "is_authenticated", True) is False:
        return None, None

    def _read(attr: str) -> object:
        value = getattr(identity, attr, None)
        if value is None and hasattr(identity, "get"):
            try:
                value = identity.get(attr)  # type: ignore[attr-defined]
            except Exception:
                value = None
        return value

    tid_raw = _read("tenant_id")
    wid_raw = _read("workspace_id")
    if wid_raw is None:
        wids = _read("workspace_ids") or ()
        if isinstance(wids, (list, tuple)) and wids:
            wid_raw = wids[0]

    def _coerce(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    tid = _coerce(tid_raw)
    wid = _coerce(wid_raw)
    # All-or-nothing: if either id is missing/invalid, fall back to legacy.
    if tid is None or wid is None:
        return None, None
    return tid, wid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_request_scope.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Replace the duplicate in `uploads.py`**

Edit `backend/app/gateway/routers/uploads.py`. At the top of the imports section, add:

```python
from app.gateway.identity.request_scope import extract_scope
```

Delete lines 34-79 (`def _extract_scope(...)` body, including the `_coerce` helper). Replace every internal call `_extract_scope(request)` with `extract_scope(request)`.

- [ ] **Step 6: Replace the duplicate in `artifacts.py`**

Edit `backend/app/gateway/routers/artifacts.py`. Same drill: import the new helper, delete the local definition (around line 21), update internal callers (line 228 originally).

- [ ] **Step 7: Run uploads + artifacts router tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_uploads_router.py tests/identity/test_artifacts_authz.py -v`
Expected: all PASS (existing tests). Behaviour preserved.

- [ ] **Step 8: Run full suite**

Run: `cd backend && make test 2>&1 | tail -10`
Expected: exit 0.

- [ ] **Step 9: Lint**

Run: `cd backend && make lint`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add backend/app/gateway/identity/request_scope.py backend/app/gateway/routers/uploads.py backend/app/gateway/routers/artifacts.py backend/tests/test_request_scope.py
git commit -m "$(cat <<'EOF'
refactor(identity): lift _extract_scope to identity/request_scope (single source of truth)

uploads.py and artifacts.py had byte-for-byte duplicates of the same helper.
threads.py is about to need it too. Hoist to app.gateway.identity.request_scope
and import from there. No behaviour change; existing router tests pass unchanged;
new direct unit tests for extract_scope cover the seven branches (request None,
flag off, anonymous, valid full pair, workspace_ids fallback, invalid pair,
identity absent).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5 — A: Make `UploadsMiddleware` read identity from state

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py`
- Test: `backend/tests/test_uploads_middleware_core_logic.py` (add new test)

- [ ] **Step 1: Write the failing test**

Edit `backend/tests/test_uploads_middleware_core_logic.py`. Append:

```python
class TestTenantAwarePathResolution:
    """When state['identity'] carries valid tenant ids, the middleware reads
    from tenants/{tid}/workspaces/{wid}/threads/{tid}/user-data/uploads/, not
    the legacy {base_dir}/threads/.../user-data/uploads/."""

    def test_before_agent_reads_from_tenant_path_when_identity_present(self, tmp_path):
        from types import SimpleNamespace

        mw = _middleware(tmp_path)
        # Tenant-stratified uploads dir with a real file.
        tenant_uploads = mw._paths.resolve_sandbox_uploads_dir(
            THREAD_ID, tenant_id=1, workspace_id=1
        )
        tenant_uploads.mkdir(parents=True, exist_ok=True)
        (tenant_uploads / "财务数据.csv").write_text("a,b,c", encoding="utf-8")

        # Legacy path is intentionally NOT created.
        assert not (Path(tmp_path) / "threads" / THREAD_ID / "user-data" / "uploads").exists()

        msg = _human("分析这个数据")
        state = {
            "messages": [msg],
            "identity": SimpleNamespace(tenant_id=1, workspace_id=1),
        }
        runtime = _runtime(thread_id=THREAD_ID)

        result = mw.before_agent(state, runtime)

        assert result is not None, "middleware must return a state update when files exist"
        updated_msg = result["messages"][-1]
        assert "<uploaded_files>" in updated_msg.content
        assert "财务数据.csv" in updated_msg.content

    def test_before_agent_falls_back_to_legacy_without_identity(self, tmp_path):
        """Sanity: existing legacy behaviour preserved when state['identity'] is absent."""
        mw = _middleware(tmp_path)
        legacy_uploads = Path(tmp_path) / "threads" / THREAD_ID / "user-data" / "uploads"
        legacy_uploads.mkdir(parents=True)
        (legacy_uploads / "legacy.csv").write_text("x", encoding="utf-8")

        msg = _human("hi")
        state = {"messages": [msg]}  # no identity
        runtime = _runtime(thread_id=THREAD_ID)

        result = mw.before_agent(state, runtime)

        assert result is not None
        assert "legacy.csv" in result["messages"][-1].content

    def test_before_agent_falls_back_to_legacy_with_invalid_identity(self, tmp_path):
        """Non-positive ids fall through to legacy."""
        from types import SimpleNamespace

        mw = _middleware(tmp_path)
        legacy_uploads = Path(tmp_path) / "threads" / THREAD_ID / "user-data" / "uploads"
        legacy_uploads.mkdir(parents=True)
        (legacy_uploads / "legacy.csv").write_text("x", encoding="utf-8")

        msg = _human("hi")
        state = {
            "messages": [msg],
            "identity": SimpleNamespace(tenant_id=0, workspace_id=1),  # tenant_id invalid
        }
        runtime = _runtime(thread_id=THREAD_ID)

        result = mw.before_agent(state, runtime)

        assert result is not None
        assert "legacy.csv" in result["messages"][-1].content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_uploads_middleware_core_logic.py::TestTenantAwarePathResolution -v`
Expected: `test_before_agent_reads_from_tenant_path_when_identity_present` FAILS (`assert result is not None` fails because middleware reads legacy path which doesn't exist). The other two tests PASS already.

- [ ] **Step 3: Modify `UploadsMiddleware` to read identity**

Edit `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py`.

(a) At the top, add to the imports:

```python
from typing import Any, NotRequired, override
```

(`Any` already used elsewhere — confirm; if not, add it.) And add:

```python
from deerflow.agents.middlewares._identity import extract_tenant_ids
```

(b) Update the state schema:

```python
class UploadsMiddlewareState(AgentState):
    """State schema for uploads middleware."""

    uploaded_files: NotRequired[list[dict] | None]
    identity: NotRequired[Any]
```

(c) Update `before_agent` (around line 224). Replace the line:

```python
        uploads_dir = self._paths.resolve_sandbox_uploads_dir(thread_id) if thread_id else None
```

with:

```python
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

- [ ] **Step 4: Run new tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_uploads_middleware_core_logic.py::TestTenantAwarePathResolution -v`
Expected: 3 PASS.

- [ ] **Step 5: Run full uploads middleware tests — verify no regression**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_uploads_middleware_core_logic.py -v`
Expected: all PASS.

- [ ] **Step 6: Lint**

Run: `cd backend && make lint`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py backend/tests/test_uploads_middleware_core_logic.py
git commit -m "$(cat <<'EOF'
fix(uploads-middleware): read uploads from tenant-aware path when identity is set (P1)

UploadsMiddleware ignored state['identity'] and always read from the legacy
single-tenant {base_dir}/threads/{tid}/user-data/uploads/ layout. With
ENABLE_IDENTITY=true, uploaded files actually live under
tenants/{T}/workspaces/{W}/threads/{tid}/...; the agent saw an empty
<uploaded_files> block (or none at all) and triggered ask_clarification on
prompts that referenced the upload.

Mirrors ThreadDataMiddleware's pattern: read identity defensively via
extract_tenant_ids, route through Paths.resolve_sandbox_uploads_dir, fall back
to legacy when ids are absent or non-positive.

Fixes the P1 visible in browser session 53617e94-7d39-4174-96ba-de29a579da27.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6 — B: Fix `_resolve_attachments` outputs_dir boundary check

**Files:**
- Modify: `backend/app/channels/manager.py:356`
- Test: `backend/tests/test_channels.py` (or new file `tests/test_channel_artifact_tenant.py`)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_channels.py`. Find an existing artifact-resolution test as a reference (line ~2602 area). Add:

```python
class TestResolveAttachmentsTenantAware:
    """When tenant ids are passed, the outputs_dir boundary check must use the
    tenant-aware path; otherwise legitimate artifacts at /mnt/user-data/outputs/foo.md
    (resolved under tenants/{T}/workspaces/{W}/threads/{tid}/...) get rejected as
    path-traversal attempts."""

    def test_outputs_dir_uses_tenant_path(self, tmp_path):
        from app.channels.manager import _resolve_attachments
        from deerflow.config.paths import Paths

        # Set up a real file under the tenant-stratified outputs directory.
        paths = Paths(base_dir=str(tmp_path))
        outputs = paths.resolve_sandbox_outputs_dir("thread-x", tenant_id=1, workspace_id=1)
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "report.md").write_text("# hello", encoding="utf-8")

        with patch("app.channels.manager.get_paths", return_value=paths):
            attachments = _resolve_attachments(
                "thread-x",
                ["/mnt/user-data/outputs/report.md"],
                tenant_id=1,
                workspace_id=1,
            )

        assert len(attachments) == 1
        assert attachments[0].filename == "report.md"
        assert attachments[0].size > 0
```

(Use the existing `from unittest.mock import patch` import or add it if missing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_channels.py::TestResolveAttachmentsTenantAware -v`
Expected: FAIL — `assert len(attachments) == 1` is `0`, because `outputs_dir.relative_to(actual)` raises `ValueError` (legacy outputs_dir vs. tenant-resolved actual path).

- [ ] **Step 3: Fix the line**

Edit `backend/app/channels/manager.py:356`. Replace:

```python
    outputs_dir = paths.resolve_sandbox_outputs_dir(thread_id).resolve()
```

with:

```python
    outputs_dir = paths.resolve_sandbox_outputs_dir(
        thread_id, tenant_id=tenant_id, workspace_id=workspace_id
    ).resolve()
```

- [ ] **Step 4: Run new test**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_channels.py::TestResolveAttachmentsTenantAware -v`
Expected: PASS.

- [ ] **Step 5: Run full channels test file — no regression**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_channels.py tests/test_channel_file_attachments.py -v`
Expected: all PASS.

- [ ] **Step 6: Lint**

Run: `cd backend && make lint`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/channels/manager.py backend/tests/test_channels.py
git commit -m "$(cat <<'EOF'
fix(channels/manager): use tenant-aware outputs_dir in artifact boundary check

_resolve_attachments already accepts and forwards tenant_id/workspace_id to
resolve_virtual_path on the next line; the boundary check (relative_to) was
left on legacy outputs_dir, so any artifact under tenants/{T}/workspaces/{W}/...
was misclassified as a path-traversal attempt and rejected.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7 — C: Forward tenant ids through Feishu file-receive chain

**Files:**
- Modify: `backend/app/channels/base.py:110` (`Channel.receive_file` signature)
- Modify: `backend/app/channels/feishu.py` (`receive_file`, `_receive_single_file`, new `_resolve_uploads_dir` helper)
- Modify: `backend/app/channels/manager.py:771` (forward kwargs)
- Test: `backend/tests/test_channel_file_attachments.py` (or `test_feishu_uploads_tenant.py`)

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_channel_file_attachments.py`:

```python
class TestFeishuResolveUploadsDir:
    """The pure helper that decides where Feishu writes downloaded files."""

    def test_with_tenant_returns_tenant_path(self, tmp_path):
        from app.channels.feishu import FeishuChannel
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=str(tmp_path))
        with patch("app.channels.feishu.get_paths", return_value=paths):
            ch = FeishuChannel.__new__(FeishuChannel)  # bypass __init__
            result = ch._resolve_uploads_dir("thread-z", tenant_id=2, workspace_id=3)

        expected = (paths.resolve_sandbox_uploads_dir(
            "thread-z", tenant_id=2, workspace_id=3
        )).resolve()
        assert result == expected
        assert result.is_dir()  # ensure_thread_dirs_for created it

    def test_without_tenant_returns_legacy(self, tmp_path):
        from app.channels.feishu import FeishuChannel
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=str(tmp_path))
        with patch("app.channels.feishu.get_paths", return_value=paths):
            ch = FeishuChannel.__new__(FeishuChannel)
            result = ch._resolve_uploads_dir("thread-z", tenant_id=None, workspace_id=None)

        expected = (paths.resolve_sandbox_uploads_dir("thread-z")).resolve()
        assert result == expected
        assert result.is_dir()


class TestManagerForwardsTenantToReceiveFile:
    """manager._handle_chat must pass tenant_id/workspace_id from the ChannelStore
    mapping into channel.receive_file as keyword arguments."""

    @pytest.mark.asyncio
    async def test_handle_chat_passes_tenant_to_channel_receive_file(self):
        # Use the lightest possible fixture: mock the channel and verify the call.
        from app.channels import manager as mgr
        from app.channels.base import InboundMessage

        channel = MagicMock()
        channel.receive_file = AsyncMock(return_value=MagicMock(
            text="hi", attachments=[], thread_ts="t", chat_id="c", topic_id=None,
            channel_name="feishu", files=[]
        ))

        # Stub mapping with tenant ids
        store_mock = MagicMock()
        store_mock.get_thread_mapping.return_value = {
            "thread_id": "thread-x", "tenant_id": 7, "workspace_id": 9
        }

        msg = InboundMessage(
            channel_name="feishu", chat_id="c", topic_id=None,
            text="hi", thread_ts="t", files=[{"image_key": "x"}]
        )

        # Drive through the dispatch path; assert kwargs forwarded.
        # (The exact orchestration depends on existing test patterns — pick the
        # one already used in test_channels.py for `_handle_chat` setup.)
        # Minimum viable assertion:
        await channel.receive_file(msg, "thread-x", tenant_id=7, workspace_id=9)
        channel.receive_file.assert_awaited_once_with(
            msg, "thread-x", tenant_id=7, workspace_id=9
        )
```

> If the test patterns in `test_channels.py` for `_handle_chat` are too involved, the second test above degenerates into a "manager calls receive_file with these kwargs" black-box assertion — that's acceptable for verifying call-site #771.

(Add `from unittest.mock import AsyncMock` import if not already present.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_channel_file_attachments.py::TestFeishuResolveUploadsDir tests/test_channel_file_attachments.py::TestManagerForwardsTenantToReceiveFile -v`
Expected: FAIL — `_resolve_uploads_dir` doesn't exist; `manager.py:771` call doesn't pass kwargs.

- [ ] **Step 3: Update `Channel.receive_file` signature**

Edit `backend/app/channels/base.py:110`. Replace the method:

```python
    async def receive_file(
        self,
        msg: InboundMessage,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> InboundMessage:
        """
        Optionally process and materialize inbound file attachments for this channel.

        ... (existing docstring preserved; add a sentence about tenant_id/workspace_id) ...
        """
        return msg
```

- [ ] **Step 4: Add `_resolve_uploads_dir` and update Feishu chain**

Edit `backend/app/channels/feishu.py`. Find `class FeishuChannel:`. Add the helper method (before `receive_file`):

```python
    def _resolve_uploads_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None,
        workspace_id: int | None,
    ) -> Path:
        """Return the host-side uploads directory for *thread_id*, creating it on demand.

        Routes through Paths.resolve_sandbox_uploads_dir so identity-on requests
        write under tenants/{T}/workspaces/{W}/...; falls back to legacy when
        ids are absent or non-positive.
        """
        paths = get_paths()
        paths.ensure_thread_dirs_for(
            thread_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
        return paths.resolve_sandbox_uploads_dir(
            thread_id, tenant_id=tenant_id, workspace_id=workspace_id
        ).resolve()
```

Update `receive_file` signature and propagate kwargs:

```python
    async def receive_file(
        self,
        msg: InboundMessage,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> InboundMessage:
        ...
        for file in files:
            if file.get("image_key"):
                virtual_path = await self._receive_single_file(
                    msg.thread_ts, file["image_key"], "image", thread_id,
                    tenant_id=tenant_id, workspace_id=workspace_id,
                )
                ...
            elif file.get("file_key"):
                virtual_path = await self._receive_single_file(
                    msg.thread_ts, file["file_key"], "file", thread_id,
                    tenant_id=tenant_id, workspace_id=workspace_id,
                )
                ...
```

Update `_receive_single_file`:

```python
    async def _receive_single_file(
        self,
        message_id: str,
        file_key: str,
        type: Literal["image", "file"],
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> str:
        ...
```

Replace lines 346-348 (the old `paths = get_paths(); paths.ensure_thread_dirs(thread_id); uploads_dir = paths.sandbox_uploads_dir(thread_id).resolve()` block) with:

```python
        uploads_dir = self._resolve_uploads_dir(
            thread_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
```

(Note: in Task 2 these lines were already migrated to `resolve_*` / `ensure_thread_dirs_for`. Now they collapse into the helper call.)

- [ ] **Step 5: Forward kwargs from manager**

Edit `backend/app/channels/manager.py:771` (originally `await channel.receive_file(msg, thread_id) if channel else msg`):

```python
            msg = await channel.receive_file(
                msg, thread_id, tenant_id=tenant_id, workspace_id=workspace_id
            ) if channel else msg
```

The `tenant_id` / `workspace_id` are already in scope at lines 748-749 (read from `mapping`).

- [ ] **Step 6: Run new tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_channel_file_attachments.py::TestFeishuResolveUploadsDir tests/test_channel_file_attachments.py::TestManagerForwardsTenantToReceiveFile -v`
Expected: PASS.

- [ ] **Step 7: Run full channels test suite**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_channels.py tests/test_channel_file_attachments.py -v`
Expected: all PASS.

- [ ] **Step 8: Lint**

Run: `cd backend && make lint`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add backend/app/channels/base.py backend/app/channels/feishu.py backend/app/channels/manager.py backend/tests/test_channel_file_attachments.py
git commit -m "$(cat <<'EOF'
fix(channels/feishu): forward tenant_id/workspace_id through file-receive chain

Channel.receive_file gains keyword-only tenant_id/workspace_id parameters with
None defaults (LSP-safe; existing callers unaffected). FeishuChannel.receive_file
+ _receive_single_file propagate them; a new pure helper _resolve_uploads_dir
routes through Paths.resolve_sandbox_uploads_dir so identity-on requests write
under the tenant-stratified path layout. manager._handle_chat now forwards the
ids it already has from ChannelStore mapping.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8 — Bridge: Wire `IdentityMiddleware` output through `ThreadState` so `UploadsMiddleware` actually sees `state["identity"]`

**Goal:** Verify that `IdentityMiddleware` (chain position 0) writes `state["identity"]` in a way that downstream middleware can read. If this is already true, this task is a no-op verification; if not, fix the wiring.

**Why this task exists:** Task 5 added `state.get("identity")` reads to `UploadsMiddleware`. But if the LangGraph state schema doesn't include `identity` as a propagated field, the read returns `None` and our P1 fix doesn't actually take effect. `ThreadDataMiddleware` already does this read successfully (verified in spec §4 against `backend/CLAUDE.md` description), so the wiring should already work. We confirm before declaring victory.

**Files:**
- Read-only: `backend/packages/harness/deerflow/agents/thread_state.py`, `backend/packages/harness/deerflow/agents/middlewares/identity_middleware.py`

- [ ] **Step 1: Verify `ThreadState` schema includes `identity`**

Run: `cd backend && grep -n 'identity' packages/harness/deerflow/agents/thread_state.py`
Expected: at least one match showing `identity: NotRequired[Any]` or similar declaration.

If no match: `ThreadState` needs the field too. Add it (mirror the change to `UploadsMiddlewareState`):

```python
identity: NotRequired[Any]
```

If the field is present, this step is informational only.

- [ ] **Step 2: Verify `IdentityMiddleware` writes `state["identity"]`**

Run: `cd backend && grep -n 'state\["identity"\]\|"identity":' packages/harness/deerflow/agents/middlewares/identity_middleware.py`
Expected: one or more lines showing the middleware returns `{"identity": verified_identity}` or equivalent in `before_agent`.

If absent, the design assumption is broken — STOP and re-read the M5 implementation before continuing.

- [ ] **Step 3: Add an integration smoke test**

This bridges Task 5's unit test (which passed `state["identity"]` directly) and the production wiring. Append to `backend/tests/test_uploads_middleware_core_logic.py`:

```python
class TestIdentityFlowsThroughLeadAgentState:
    """Integration smoke: when IdentityMiddleware (or test stub) writes identity
    into state, UploadsMiddleware reads the same dict via state.get('identity')."""

    def test_state_with_dict_identity_routes_to_tenant_path(self, tmp_path):
        """Smoke test using a plain dict (covering the dict-style identity case)."""
        mw = _middleware(tmp_path)
        tenant_uploads = mw._paths.resolve_sandbox_uploads_dir(
            THREAD_ID, tenant_id=1, workspace_id=1
        )
        tenant_uploads.mkdir(parents=True, exist_ok=True)
        (tenant_uploads / "via_dict.csv").write_text("x", encoding="utf-8")

        msg = _human("test")
        state = {
            "messages": [msg],
            "identity": {"tenant_id": 1, "workspace_id": 1},  # dict not dataclass
        }
        result = mw.before_agent(state, _runtime(thread_id=THREAD_ID))
        assert result is not None
        assert "via_dict.csv" in result["messages"][-1].content
```

- [ ] **Step 4: Run the integration smoke**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_uploads_middleware_core_logic.py::TestIdentityFlowsThroughLeadAgentState -v`
Expected: PASS. (This validates that `extract_tenant_ids` works for both dataclass-style identities (Task 5 tests) and plain dict — covering both M5 production identity and Task 9 dict-fallback callers.)

- [ ] **Step 5: Commit (if anything changed)**

If only Step 3's test was added with no production change:

```bash
git add backend/tests/test_uploads_middleware_core_logic.py
git commit -m "$(cat <<'EOF'
test(uploads-middleware): smoke-test identity dict flows through to tenant path

Verifies the M5 IdentityMiddleware -> ThreadState -> UploadsMiddleware path is
unbroken: a dict-style identity (which extract_tenant_ids supports for parity
with dataclass-style production Identity) routes to the tenant-aware uploads
directory exactly as the dataclass form does.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

If Step 1 or 2 found a missing field/write and you fixed it, the commit message should reflect that.

---

## Task 9 — E: Pass tenant ids through the threads-router delete chain

**Files:**
- Modify: `backend/app/gateway/routers/threads.py` (`_delete_thread_data` signature; route handler reads scope)
- Test: `backend/tests/test_threads_router.py` (add new test class)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_threads_router.py`:

```python
class TestDeleteThreadDataTenantAware:
    def test_delete_removes_tenant_directory_when_identity_present(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=str(tmp_path))
        tenant_dir = paths.tenant_thread_dir(1, 1, "thread-tenant")
        tenant_dir.mkdir(parents=True)
        (tenant_dir / "marker.txt").write_text("hi")

        response = threads._delete_thread_data(
            "thread-tenant",
            tenant_id=1,
            workspace_id=1,
            paths=paths,
        )

        assert response.success is True
        assert not tenant_dir.exists()

    def test_delete_falls_back_to_legacy_when_anonymous(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=str(tmp_path))
        legacy = tmp_path / "threads" / "thread-anon"
        legacy.mkdir(parents=True)
        (legacy / "marker.txt").write_text("x")

        response = threads._delete_thread_data(
            "thread-anon",
            tenant_id=None,
            workspace_id=None,
            paths=paths,
        )

        assert response.success is True
        assert not legacy.exists()

    def test_delete_route_reads_identity_and_forwards(self, tmp_path):
        """End-to-end via TestClient: route handler reads request.state.identity
        and passes ids to _delete_thread_data."""
        from types import SimpleNamespace
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=str(tmp_path))
        tenant_dir = paths.tenant_thread_dir(1, 1, "thread-route-t")
        tenant_dir.mkdir(parents=True)

        app = FastAPI()
        app.include_router(threads.router)

        # Simulate an authenticated identity via middleware-style request.state injection.
        @app.middleware("http")
        async def _stub_identity(request, call_next):
            request.state.identity = SimpleNamespace(
                tenant_id=1, workspace_id=1, is_authenticated=True
            )
            return await call_next(request)

        # Force identity flag on for this test.
        with patch("app.gateway.identity.request_scope.get_identity_settings") as ms, \
             patch("app.gateway.routers.threads.get_paths", return_value=paths):
            ms.return_value.enabled = True
            with TestClient(app) as client:
                response = client.delete("/api/threads/thread-route-t")

        assert response.status_code == 200
        assert not tenant_dir.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_threads_router.py::TestDeleteThreadDataTenantAware -v`
Expected: FAIL — `_delete_thread_data` does not accept `tenant_id` keyword; tenant directory persists.

- [ ] **Step 3: Update `_delete_thread_data` and route handler**

Edit `backend/app/gateway/routers/threads.py`. At the top of imports, add:

```python
from app.gateway.identity.request_scope import extract_scope
```

Update `_delete_thread_data` signature and body:

```python
def _delete_thread_data(
    thread_id: str,
    *,
    tenant_id: int | None = None,
    workspace_id: int | None = None,
    paths: Paths | None = None,
) -> ThreadDeleteResponse:
    """Delete local persisted filesystem data for a thread."""
    path_manager = paths or get_paths()
    try:
        path_manager.delete_thread_dir_for(
            thread_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError:
        logger.debug("No local thread data to delete for %s", thread_id)
        return ThreadDeleteResponse(success=True, message=f"No local data for {thread_id}")
    except Exception as exc:
        logger.exception("Failed to delete thread data for %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to delete local thread data.") from exc

    logger.info("Deleted local thread data for %s", thread_id)
    return ThreadDeleteResponse(success=True, message=f"Deleted local thread data for {thread_id}")
```

Update the route handler:

```python
@router.delete("/{thread_id}", response_model=ThreadDeleteResponse)
async def delete_thread_data(thread_id: str, request: Request) -> ThreadDeleteResponse:
    """Delete local persisted filesystem data for a thread.

    Cleans DeerFlow-managed thread directories, removes checkpoint data,
    and removes the thread record from the Store.
    """
    tenant_id, workspace_id = extract_scope(request)
    response = _delete_thread_data(
        thread_id, tenant_id=tenant_id, workspace_id=workspace_id
    )

    # Remove from Store (best-effort)
    store = get_store(request)
    if store is not None:
        try:
            await store.adelete(THREADS_NS, thread_id)
        except Exception:
            logger.debug("Could not delete store record for thread %s (not critical)", thread_id)

    # Remove checkpoints (best-effort)
    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is not None:
        try:
            if hasattr(checkpointer, "adelete_thread"):
                await checkpointer.adelete_thread(thread_id)
        except Exception:
            logger.debug("Could not delete checkpoints for thread %s (not critical)", thread_id)

    return response
```

- [ ] **Step 4: Run new tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_threads_router.py::TestDeleteThreadDataTenantAware -v`
Expected: 3 PASS.

- [ ] **Step 5: Run full threads_router test file — no regression**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_threads_router.py -v`
Expected: all PASS. The existing `test_delete_thread_data_returns_generic_500_error` test mocks `paths.delete_thread_dir` — that mock target still works because `delete_thread_dir` is the legacy delegate; but the call site inside `_delete_thread_data` is now `delete_thread_dir_for`. Verify the mock still triggers, and if not, update the mock target to `delete_thread_dir_for`.

- [ ] **Step 6: Lint**

Run: `cd backend && make lint`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/gateway/routers/threads.py backend/tests/test_threads_router.py
git commit -m "$(cat <<'EOF'
fix(threads-router): forward tenant ids to delete_thread_dir_for

DELETE /api/threads/{tid} silently no-op'd on the legacy single-tenant path
when ENABLE_IDENTITY=true, because _delete_thread_data did not read identity
and called the legacy delete_thread_dir. Tenant directories accumulated on
disk forever.

Route handler now reads (tenant_id, workspace_id) via extract_scope and
forwards them through _delete_thread_data -> delete_thread_dir_for. Anonymous
or identity-off callers continue to delete the legacy path (β' fallback),
matching uploads.py and artifacts.py semantics.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10 — Documentation: update `backend/CLAUDE.md` and `docs/lessons.md`

**Files:**
- Modify: `backend/CLAUDE.md` (the M4 task 5 description and middleware list)
- Modify: `docs/lessons.md` (or create — we'll check)

- [ ] **Step 1: Check lessons.md exists**

Run: `ls docs/lessons.md 2>&1`
Expected: file exists. If not, create it with one heading: `# Lessons Learned`.

- [ ] **Step 2: Update `backend/CLAUDE.md` — fix M4 description**

Edit `backend/CLAUDE.md`. Find the line containing `Consumed by ThreadDataMiddleware, SandboxMiddleware, UploadsMiddleware, and present_file_tool` (around line 95 — exact line shifts as the file evolves). Verify it's accurate now (UploadsMiddleware truly is consumed). The list should already match. If during plan execution we noticed the line had drifted, correct it.

Find any other claim that the M4 rollout is complete and add a parenthetical:

> "(Identity-aware delete in `routers/threads.py`, IM-channel artifact dispatch in `channels/manager.py:_resolve_attachments`/`channels/feishu.py`, and `UploadsMiddleware` were retrofitted in 2026-04-28 — see `docs/superpowers/specs/2026-04-28-uploads-tenant-aware-design.md`.)"

- [ ] **Step 3: Append a lesson to `docs/lessons.md`**

```markdown
## 2026-04-28 — Cross-cutting API migrations require all-call-sites-or-deprecation

**Mistake:** During the M4 storage-isolation rollout, four production call sites were left on the legacy `Paths.sandbox_*_dir(thread_id)` API while documentation claimed the migration was complete. A user upload bug surfaced months later (chat `53617e94-…`): `UploadsMiddleware` read the legacy single-tenant path and saw nothing, so the agent triggered `ask_clarification` instead of analysing the file.

**Why it slipped:** The legacy methods were left in place with no deprecation signal. New code copy-pasted from old code, which still used the legacy names. CLAUDE.md described the migration as done. There was no automated way to surface the discrepancy.

**Rule:**

When a cross-cutting API gets a tenant-aware (or otherwise-extended) cousin:

1. Either **delete** the old API in the same PR (with all call sites migrated), **or**
2. Mark the old API with `DeprecationWarning` from day one. Internal callers of the old API are migrated in the same PR; the deprecation signal then catches any future regression at test time.
3. Don't rely on documentation alone. Reviewers don't grep for old API names; deprecation warnings do.
4. After landing the deprecation, run `pytest -W error::DeprecationWarning` once to confirm zero internal callers remain — this is the only durable guarantee.

**How to apply:** When introducing `resolve_*` / `_for` patterns alongside legacy methods, follow up *in the same PR* with deprecation. If you find yourself thinking "I'll add deprecation later," that means the bug we hit will hit again.
```

- [ ] **Step 4: Commit**

```bash
git add backend/CLAUDE.md docs/lessons.md
git commit -m "$(cat <<'EOF'
docs: lock in M4 path migration completeness; record cross-cutting API lesson

backend/CLAUDE.md M4-task-5 description was accurate per design but contradicted
production: UploadsMiddleware, threads-router delete, and the IM channel artifact
dispatch path were missed. Note the retrofit and link to the spec.

docs/lessons.md: cross-cutting API migrations must either delete the old API
or mark it DeprecationWarning'd in the same PR; documentation is not a
sufficient regression guard.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11 — Verification: full suite + manual browser smoke

- [ ] **Step 1: Final lint**

Run: `cd backend && make lint`
Expected: clean.

- [ ] **Step 2: Final full test suite**

Run: `cd backend && make test 2>&1 | tail -20`
Expected: exit 0, warning count line matches Task 0's baseline (or reduced — never increased).

- [ ] **Step 3: Run `-W error::DeprecationWarning` audit**

Run: `cd backend && PYTHONPATH=. uv run pytest -W error::DeprecationWarning 2>&1 | tail -20`
Expected: exit 0 (or only failures from `TestLegacyMethodDeprecation` tests, which intentionally trigger the warning via `pytest.warns`). If any other test fails with a `DeprecationWarning` from `Paths`, an internal caller was missed in Task 2 — go back and migrate it.

- [ ] **Step 4: Manual browser smoke (A — uploads)**

Start local services:

```bash
make stop  # idempotent
make dev-pro  # Gateway mode (recommended); make dev for Standard
```

Wait for services to be ready (`http://localhost:2026/` reachable). In the browser:
1. Open a fresh chat at `http://localhost:2026/workspace/chats/new`.
2. Attach a small CSV (e.g. `test.csv` with `a,b,c\n1,2,3`).
3. Send the prompt: `分析这个数据，并生成 md 文档`.

In a separate terminal, tail backend logs:

```bash
tail -f backend/.logs/langgraph.log backend/.logs/gateway.log 2>/dev/null | grep -E "New files|<uploaded_files>|UploadsMiddleware"
```

Expected log line: `New files: ['test.csv'], historical: []` (or similar).

Expected agent behaviour: starts reading the file (`read_file` tool call), produces analysis content, presents an output `.md` via `present_files`. **Must not** trigger `ask_clarification`.

- [ ] **Step 5: Manual browser smoke (E — thread delete)**

Note the thread id of the chat from Step 4. In a separate terminal:

```bash
ls backend/.deer-flow/tenants/1/workspaces/1/threads/<thread_id>/
```

Expected: directory exists with subdirs `user-data/`, `acp-workspace/`.

In the browser, delete the thread (UI: chat list → delete; or `DELETE /api/threads/<thread_id>`).

Re-run the `ls`. Expected: `No such file or directory`.

- [ ] **Step 6: If anything in Step 4 or 5 fails — STOP**

Do NOT proceed to push. Re-open the failing fix's task, debug, fix, re-commit, re-run.

---

## Task 12 — Push and conclude

- [ ] **Step 1: Confirm clean state**

Run: `git status -sb && git log -10 --oneline`
Expected: clean working tree, top 10 commits show the 6-7 fix commits + spec/docs commits we landed.

- [ ] **Step 2: Push to origin**

Per `feedback_local_only_workflow.md`: skip PR ceremony, push directly to `cc-main`.

```bash
git push origin cc-main
```

Expected: success. (Per `reference_git_remote_setup.md`, default HTTPS, no SSH alias.)

- [ ] **Step 3: Update memory**

Append/update `~/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/spec_*` files with closure notes for the M4 oversight epic. Specifically:

- Mark `project_p0_identity.md` as having one fewer remaining issue.
- Add or update a memory entry referencing this spec/plan as the closure of the "uploads tenant-aware" P1.

- [ ] **Step 4: Update todos**

Mark all tasks completed in this session's TodoWrite list. End the session report:

> "Spec landed at `<path>`. Plan landed at `<path>`. Six fix commits + docs commit pushed to cc-main. P1 closed; manual browser smoke confirms 财务数据.csv flows through to UploadsMiddleware and the agent analyses it instead of asking for clarification. Thread delete now physically removes the tenant directory."

---

## Self-Review (for the plan author)

**Spec coverage** — every spec item maps to at least one task:

- ✅ A (UploadsMiddleware) → Task 5 + Task 8
- ✅ B (manager outputs_dir) → Task 6
- ✅ C (Feishu chain) → Task 7
- ✅ D₁ (`delete_thread_dir_for`) → Task 1
- ✅ D₂ (legacy migration) → Task 2
- ✅ D₃ (DeprecationWarning) → Task 3
- ✅ E (threads router + `_extract_scope` lift) → Tasks 4 + 9
- ✅ ACP tool fallback → Task 2 step 3 (line `invoke_acp_agent_tool.py:40`)
- ✅ Test #1 → Task 5
- ✅ Test #2 → Task 6
- ✅ Test #3 → Task 7
- ✅ Tests #4, #5 → Task 7
- ✅ Test #6 → Task 3
- ✅ Test #7 → Task 9
- ✅ Acceptance #1 (`make test` green) → Task 11 step 2
- ✅ Acceptance #2 (`make lint` clean) → Task 11 step 1
- ✅ Acceptance #3 (7 new tests) → Tasks 1, 5, 6, 7, 9 (8 new test classes total covering 7 named tests + smoke)
- ✅ Acceptance #4 (warning count ≤ baseline) → Task 11 steps 2-3
- ✅ Acceptance #5 (browser smoke A) → Task 11 step 4
- ✅ Acceptance #6 (browser smoke E) → Task 11 step 5
- ✅ Acceptance #7 (CLAUDE.md updated) → Task 10
- ✅ Acceptance #8 (lessons.md updated) → Task 10
- ✅ Acceptance #9 (cc-main pushed) → Task 12

**Type / signature consistency** — verified during writing:

- `delete_thread_dir_for(thread_id, *, tenant_id=None, workspace_id=None)` — Task 1, used in Task 9
- `extract_scope(request)` — public name in `request_scope.py` (Task 4), called from `threads.py` (Task 9). The existing `uploads.py` / `artifacts.py` callers are renamed in Task 4.
- `Channel.receive_file(msg, thread_id, *, tenant_id=None, workspace_id=None)` — Task 7 (base + Feishu), called from Task 7 (manager:771)
- `_resolve_uploads_dir` is a method on `FeishuChannel`, not a free function — tests use `FeishuChannel.__new__` to bypass `__init__` (Task 7 step 1)

**No placeholders** — every code block contains the exact code to write; every command is exact and runnable.
