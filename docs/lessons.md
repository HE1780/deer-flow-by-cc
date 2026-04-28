# Lessons Learned

A running log of mistakes and discoveries that should shape future work.
Recent entries first.

---

## 2026-04-28 — Cross-cutting API migrations require all-call-sites-or-deprecation

**Mistake:** During the M4 storage-isolation rollout, five production call
sites were left on the legacy `Paths.sandbox_*_dir(thread_id)` /
`thread_dir` / `ensure_thread_dirs` / `delete_thread_dir` API while
documentation claimed the migration was complete. A user upload bug
surfaced months later (chat `53617e94-7d39-4174-96ba-de29a579da27`):
`UploadsMiddleware` read the legacy single-tenant path and saw nothing,
so the agent triggered `ask_clarification` instead of analysing the
uploaded CSV.

**Why it slipped:**

1. The legacy methods were left in place with no deprecation signal.
2. New code copy-pasted from old code, which still used the legacy names.
3. `backend/CLAUDE.md` described the migration as done.
4. There was no automated way to surface the discrepancy.

**Sibling latent bugs uncovered while fixing it:**

* `app/channels/manager.py:_resolve_attachments` was mixing tenant-aware
  path resolution with a legacy-path boundary check — so any IM-channel
  artifact under `tenants/{T}/...` got falsely rejected as a path-traversal
  attempt.
* `app/channels/feishu.py` ignored tenant ids the manager already had,
  so Feishu uploads written under `ENABLE_IDENTITY=true` landed in the
  wrong directory.
* `app/gateway/routers/threads.py:_delete_thread_data` silently no-op'd
  on the legacy path for identity-on threads, leaking tenant directories
  on disk forever.
* `packages/harness/deerflow/sandbox/tools.py:204` and
  `tools/builtins/invoke_acp_agent_tool.py:40` still used legacy methods.

**Rule:**

When a cross-cutting API gets a tenant-aware (or otherwise-extended) cousin:

1. Either **delete** the old API in the same PR (with all call sites
   migrated), **or**
2. Mark the old API with `DeprecationWarning` from day one. Internal
   callers of the old API are migrated in the same PR; the deprecation
   signal then catches any future regression at test time.
3. Don't rely on documentation alone. Reviewers don't grep for old API
   names; deprecation warnings do.
4. After landing the deprecation, run
   `pytest -W error::DeprecationWarning` once to confirm zero internal
   callers remain — this is the only durable guarantee.

**How to apply:** When introducing `resolve_*` / `_for` patterns alongside
legacy methods, follow up *in the same PR* with deprecation. If you find
yourself thinking "I'll add deprecation later," that means the bug we hit
will hit again. Use `grep -rn '\.legacy_method_name(' --include="*.py"`
to audit every call site before considering the migration done — and run
that grep against both `packages/` and `app/` (a single `--include` flag
plus `\|`-alternation easily masks one of them).

**Related artefacts:**

* Spec: [`docs/superpowers/specs/2026-04-28-uploads-tenant-aware-design.md`](superpowers/specs/2026-04-28-uploads-tenant-aware-design.md)
* Plan: [`docs/superpowers/plans/2026-04-28-uploads-tenant-aware.md`](superpowers/plans/2026-04-28-uploads-tenant-aware.md)
* Memory: `feedback_cross_cutting_api_migration.md`
