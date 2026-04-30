# Design Specs Index

> 📦 **2026-04-29 — 全部归档收尾**
>
> 当前阶段所有 design spec 均已 `git mv` 到 [`archive/`](./archive/)。仍未闭环的开放议题统一归集到 [`docs/OPEN_ISSUES.md`](../../OPEN_ISSUES.md)，已交付的功能总览见 [`docs/SYSTEM_WHITEPAPER.md`](../../SYSTEM_WHITEPAPER.md)。
>
> 本 README 保留作目录索引；下一期开新 spec 时仍按 `YYYY-MM-DD-<short-name>.md` 命名直接落到本目录即可。

---

## 命名约定

- 一个 spec ≈ 一个 [plan](../plans/) 的设计输入。文件名 `YYYY-MM-DD-<short-name>.md`。
- 多数 spec 与 plan 1:1；P0 identity foundation 是个例外，跨多个 plan。
- 关闭后 `git mv` 到 `archive/`（不删除）。

## 归档总览

`archive/` 当前共 16 个 spec，分两批：

### 批次 A — 2026-04-28 与 P0 一同归档

| Spec | Companion plan |
|---|---|
| [channels-identity-ci-smoke-design](./archive/2026-04-24-channels-identity-ci-smoke-design.md) | [channels-identity-ci-smoke](../plans/archive/2026-04-25-channels-identity-ci-smoke.md) |
| [m7a-deferred-items-design](./archive/2026-04-24-m7a-deferred-items-design.md) | [m7a-deferred-items](../plans/archive/2026-04-24-m7a-deferred-items.md) |
| [skill-agent-i18n-design](./archive/2026-04-25-skill-agent-i18n-design.md) | [agent-fix-i18n](../plans/archive/2026-04-25-agent-fix-i18n.md) + [agent-skill-version-pin](../plans/archive/2026-04-25-agent-skill-version-pin.md) |
| [skill-mgmt-v2-complete-design](./archive/2026-04-25-skill-mgmt-v2-complete-design.md) | [skill-mgmt-v2-remaining](../plans/archive/2026-04-25-skill-mgmt-v2-remaining.md) |
| [p0-original-scope-audit](./archive/2026-04-27-p0-original-scope-audit.md) | _retrospective audit_ |
| [skill-slash-prefix-display](./archive/2026-04-27-skill-slash-prefix-display.md) | _no plan_ |

### 批次 B — 2026-04-29 验收阶段归档

| Spec | 当前事实 |
|---|---|
| [deerflow-identity-foundation-design](./archive/2026-04-21-deerflow-identity-foundation-design.md) | ✅ P0 已 ship · 长期参考（v2 不变量 + P1+ 路线图） |
| [custom-agent-edit-page-design](./archive/2026-04-27-custom-agent-edit-page-design.md) | ✅ 已 ship |
| [loop-detection-orphan-tool-msg](./archive/2026-04-27-loop-detection-orphan-tool-msg.md) | ✅ hard_stop 已 ship；warning → [OPEN_ISSUES OI-1](../../OPEN_ISSUES.md) |
| [user-guide-design](./archive/2026-04-27-user-guide-design.md) | 🟡 正文完成 / 截图缺 → [OPEN_ISSUES OI-6](../../OPEN_ISSUES.md) |
| [llm-event-loop-closed-design](./archive/2026-04-28-llm-event-loop-closed-design.md) | ✅ Gateway mode 已 ship；Standard mode → [OPEN_ISSUES OI-3](../../OPEN_ISSUES.md) |
| [llm-event-loop-closed-rootcause](./archive/2026-04-28-llm-event-loop-closed-rootcause.md) | 根因报告，作为历史档案 |
| [uploads-tenant-aware-design](./archive/2026-04-28-uploads-tenant-aware-design.md) | ✅ 已 ship |
| [workspace-outputs-dual-dir-loop](./archive/2026-04-28-workspace-outputs-dual-dir-loop.md) | ✅ 已 ship |
| [session-refresh-interceptor-design](./archive/2026-04-28-session-refresh-interceptor-design.md) | ✅ 已 ship |
| [registration-code-design](./archive/2026-04-29-registration-code-design.md) | ✅ 已 ship — merged e7235070 |
