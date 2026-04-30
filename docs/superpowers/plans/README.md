# Implementation Plans Index

> 📦 **2026-04-29 — 全部归档收尾**
>
> 当前阶段所有已编写的 implementation plan 均已 `git mv` 到 [`archive/`](./archive/)。仍未闭环的开放议题（含未启动的 plan）统一归集到 [`docs/OPEN_ISSUES.md`](../../OPEN_ISSUES.md)，已交付的功能总览见 [`docs/SYSTEM_WHITEPAPER.md`](../../SYSTEM_WHITEPAPER.md)。
>
> 本 README 保留作目录索引；下一期开新 plan 时仍按 `YYYY-MM-DD-<short-name>.md` 命名直接落到本目录即可。

---

## 命名约定

- 一个 plan = 一个可发布范围。文件名：`YYYY-MM-DD-<short-name>.md`。
- 关闭后 `git mv` 到 `archive/`（不删除），保留 PR 链接历史。
- 对应的 design 在同名 [`../specs/`](../specs/) 中，归档目录镜像。

## 归档总览

`archive/` 当前共 21 个 plan，分两批：

### 批次 A — P0 identity foundation（M1-M7）

2026-04-28 在 P0 闭环时一次性归档：

| Plan | 已交付 |
|---|---|
| [m1-schema-bootstrap-feature-flag](./archive/2026-04-21-m1-schema-bootstrap-feature-flag.md) | identity schema + Alembic + ORM + bootstrap + `ENABLE_IDENTITY` |
| [m2-authentication](./archive/2026-04-21-m2-authentication.md) | OIDC + JWT + API tokens + Redis sessions + lockout + `/auth/*` + `/me` |
| [m3-rbac-middleware](./archive/2026-04-21-m3-rbac-middleware.md) | `@requires` + tenant auto-filter + roles/perms 读 |
| [m4-storage-isolation](./archive/2026-04-21-m4-storage-isolation.md) | tenant 路径 + skills 加载 + 三层 config + sandbox + artifacts authz |
| [m5-langgraph-identity-guardrail](./archive/2026-04-21-m5-langgraph-identity-guardrail.md) | HMAC 头 + IdentityMiddleware + GuardrailMiddleware + subagent 继承 |
| [m6-audit](./archive/2026-04-21-m6-audit.md) | AuditMiddleware + 异步 batch writer + JSONL fallback + 查询/导出 + 保留 + immutability |
| [m7-admin-ui-migration-release](./archive/2026-04-21-m7-admin-ui-migration-release.md) | 14 admin 页 + Playwright + 迁移 + 多副本锁 + metrics |
| [m7a-admin-ui](./archive/2026-04-23-m7a-admin-ui.md) + [-A2](./archive/2026-04-23-m7a-admin-ui-A2.md) | Admin shell + 只读页 |
| [m7a-deferred-items](./archive/2026-04-24-m7a-deferred-items.md) | RBAC 矩阵 E2E、creates、zod、i18n |
| [agent-fix-i18n](./archive/2026-04-25-agent-fix-i18n.md) | agent_name 注入 + i18n 基线 |
| [channels-identity-ci-smoke](./archive/2026-04-25-channels-identity-ci-smoke.md) | channels 多租户 + CI smoke |
| [skill-mgmt-v2-remaining](./archive/2026-04-25-skill-mgmt-v2-remaining.md) | thread skill bind/unbind + badge UI + admin tabs |
| [identity-langgraph-passthrough-bug](./archive/2026-04-27-identity-langgraph-passthrough-bug.md) | P0 fix: HMAC bypass; default `/api/langgraph-compat` |

### 批次 B — 验收阶段归档（2026-04-29）

| Plan | 状态（核对当前代码） |
|---|---|
| [agent-skill-version-pin](./archive/2026-04-25-agent-skill-version-pin.md) | ✅ 已 ship — manifest 解析 + version pin + `org_key_env` |
| [custom-agent-edit-page](./archive/2026-04-27-custom-agent-edit-page.md) | ✅ 已 ship — edit page + `GET /api/tool-groups` + tri-state helper |
| [llm-event-loop-closed](./archive/2026-04-28-llm-event-loop-closed.md) | ✅ Gateway mode 已 ship；Standard mode → [OPEN_ISSUES OI-3](../../OPEN_ISSUES.md) |
| [loop-detection-orphan-tool-msg](./archive/2026-04-28-loop-detection-orphan-tool-msg.md) | ✅ hard_stop 已 ship；warning → [OPEN_ISSUES OI-1](../../OPEN_ISSUES.md) |
| [session-refresh-interceptor](./archive/2026-04-28-session-refresh-interceptor.md) | ✅ 已 ship — 9 vitest 全绿 |
| [uploads-tenant-aware](./archive/2026-04-28-uploads-tenant-aware.md) | ✅ 已 ship — 5 处 call site 全部修复 |
| [user-guide-implementation](./archive/2026-04-27-user-guide-implementation.md) | 🟡 正文完成 / 截图待补 → [OPEN_ISSUES OI-6](../../OPEN_ISSUES.md) |
| [registration-code](./archive/2026-04-29-registration-code.md) | ✅ 已 ship — admin 三件套 + 公开 /register + workspace_member role；merged e7235070 |

---

## 跨 plan 不变量（identity 启用时永远成立）

1. **`ENABLE_IDENTITY=false` 行为零变化**。守卫：[backend/tests/identity/test_feature_flag_offline.py](../../../backend/tests/identity/test_feature_flag_offline.py)。
2. **Harness 边界**：`backend/packages/harness/deerflow/` 不能 `import app.*`。守卫：[backend/tests/test_harness_boundary.py](../../../backend/tests/test_harness_boundary.py)。
3. **审计日志不可变**：DB GRANT 拒绝对 `identity.audit_logs` 的 UPDATE/DELETE。
4. **路径不可越界**：业务代码不直接拼路径，全部走 [storage/paths.py](../../../backend/app/gateway/identity/storage/paths.py)。
5. **工具权限白名单**：`TOOL_PERMISSION_MAP` + MCP 声明的 `required_permission` 是唯一允许路径，未登记的工具默认拒绝。
