# Implementation Plans Index

This directory tracks **active** implementation plans. Closed plans live under [`archive/`](./archive/).

Conventions:

- One plan = one shippable scope. Filename pattern: `YYYY-MM-DD-<short-name>.md`.
- A plan moves to `archive/` when its goal is shipped (and any deferred sub-tasks are explicitly recorded as such).
- The corresponding design lives in [`../specs/`](../specs/); same naming convention with archive mirror.

---

## Active plans

| Plan | Scope | Status | Spec |
|---|---|---|---|
| [2026-04-25-agent-skill-version-pin](./2026-04-25-agent-skill-version-pin.md) | `name@version` skill pinning + `manifest.yaml` parser, auto-merge tool_groups + env at agent build | **open · actionable** — depends on agent-fix-i18n (shipped); not started | [skill-agent-i18n-design](../specs/archive/2026-04-25-skill-agent-i18n-design.md) (shared) |
| [2026-04-27-custom-agent-edit-page](./2026-04-27-custom-agent-edit-page.md) | Backend agent CRUD + tool-groups endpoint + frontend edit form | **open · actionable** — 2026-04-28 复核确认前端 UI/hook/i18n/test 全部未落地，backend 仅缺 `GET /api/tool-groups`；TDD-level plan ~10 个 task，预计 2-4h agentic | [custom-agent-edit-page-design](../specs/2026-04-27-custom-agent-edit-page-design.md) |
| [2026-04-27-user-guide-implementation](./2026-04-27-user-guide-implementation.md) | 9-chapter end-user manual under `docs/user-guide/` with happy-path verification | **open · 内容完成 · 仅缺截图** — 9 章 + README ~599 行已实质完成；剩余仅 10+ 张截图补全 + 01-06 章 UI 改动后回访复核 | [user-guide-design](../specs/2026-04-27-user-guide-design.md) |

Long-term / parking lot (no plan, but tracked elsewhere):

- **Self-hosting epic** — docker-compose / Helm / offline images / install docs. No plan file yet; the next major epic. See memory `project_self_hosted_positioning.md`.
- **P1 bug: LoopDetectionMiddleware orphan ToolMessage** — spec at [`../specs/2026-04-27-loop-detection-orphan-tool-msg.md`](../specs/2026-04-27-loop-detection-orphan-tool-msg.md); plan to be written. spec 末尾"实施指引"块已给出文件:行号坐标 + 30 行编码 + 50 行测试的工作量估算，下一个写 plan 的工程师可直接拾取。

---

## Archived plans (P0 identity foundation + follow-up)

All under [`archive/`](./archive/). Archived 2026-04-28 once `M1-M7` and the M7A follow-on items shipped on `main`.

| Plan | Shipped scope |
|---|---|
| [m1-schema-bootstrap-feature-flag](./archive/2026-04-21-m1-schema-bootstrap-feature-flag.md) | Identity schema + Alembic + ORM + bootstrap + `ENABLE_IDENTITY` flag + pg/redis compose + CI |
| [m2-authentication](./archive/2026-04-21-m2-authentication.md) | OIDC + internal JWT + API tokens + Redis sessions + login lockout + `/auth/*` + `/me` |
| [m3-rbac-middleware](./archive/2026-04-21-m3-rbac-middleware.md) | `@requires` decorator + tenant auto-filter + horizontal-access matrix + roles/perms reads |
| [m4-storage-isolation](./archive/2026-04-21-m4-storage-isolation.md) | Tenant/workspace paths + tenant-aware skills loader + 3-layer config merge + sandbox + artifacts authz |
| [m5-langgraph-identity-guardrail](./archive/2026-04-21-m5-langgraph-identity-guardrail.md) | HMAC identity headers Gateway→LangGraph + IdentityMiddleware + GuardrailMiddleware + subagent inheritance |
| [m6-audit](./archive/2026-04-21-m6-audit.md) | AuditMiddleware + async batch writer + JSONL fallback + query/export + retention + immutability GRANT |
| [m7-admin-ui-migration-release](./archive/2026-04-21-m7-admin-ui-migration-release.md) | 14 admin pages + Playwright E2E + migration script + multi-replica bootstrap lock + metrics + release guide |
| [m7a-admin-ui](./archive/2026-04-23-m7a-admin-ui.md) + [-A2](./archive/2026-04-23-m7a-admin-ui-A2.md) | Admin shell + read-only pages (A1 + A2 sub-PRs) |
| [m7a-deferred-items](./archive/2026-04-24-m7a-deferred-items.md) | M7A deferred follow-ups (RBAC matrix E2E, creates, zod, i18n) — 53/53 steps shipped |
| [agent-fix-i18n](./archive/2026-04-25-agent-fix-i18n.md) | Agent name configurable injection + i18n baseline |
| [channels-identity-ci-smoke](./archive/2026-04-25-channels-identity-ci-smoke.md) | Channels tenant/workspace threading + CI smoke workflow |
| [skill-mgmt-v2-remaining](./archive/2026-04-25-skill-mgmt-v2-remaining.md) | Thread skill bind/unbind endpoints + badge UI + admin tabs |
| [identity-langgraph-passthrough-bug](./archive/2026-04-27-identity-langgraph-passthrough-bug.md) | P0 fix: HMAC bypass via direct LangGraph; default frontend to `/api/langgraph-compat`; Tasks 4–5 deferred to self-host epic |

---

## Cross-plan invariants (load-bearing for any plan touching identity)

These invariants MUST hold across the lifetime of `ENABLE_IDENTITY=true`; regressing one is a hard failure:

1. **`ENABLE_IDENTITY=false` ⇒ zero behavior change from pre-M1 main.** Regression guard: `backend/tests/identity/test_feature_flag_offline.py`.
2. **Harness boundary.** No code in `backend/packages/harness/deerflow/` imports from `app.*`. Enforced by `backend/tests/test_harness_boundary.py`.
3. **Audit log immutability.** DB GRANT denies UPDATE/DELETE on `identity.audit_logs`.
4. **Identity-derived paths.** No business code computes a storage path from untrusted user input; must go through `app/gateway/identity/storage/paths.py`.
5. **Tool permission whitelist.** `TOOL_PERMISSION_MAP` + MCP-declared permissions are the only allow paths; unknown tools default-deny.
