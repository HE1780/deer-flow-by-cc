# Design Specs Index

This directory tracks **active** design specs. Closed specs live under [`archive/`](./archive/).

A spec is the design artifact a [`plan`](../plans/) consumes. Most specs and plans are 1:1; some specs (the P0 identity foundation) span multiple plans.

---

## Active specs

| Spec | Scope | Status | Companion plan |
|---|---|---|---|
| [2026-04-21-deerflow-identity-foundation-design](./2026-04-21-deerflow-identity-foundation-design.md) | Multi-tenant identity, RBAC, storage isolation, LangGraph guardrail, audit. **Anchor doc for v2 enterprise identity.** | **kept · long-term reference** — P0 (M1-M7) shipped; remains the source of truth for v2 invariants and the entry point for P1 (fine-grained RBAC), P2 (KB), P3 (SkillHub), P4 (collab), P5 (workflow editor) | M1-M7 plans (all archived) |
| [2026-04-27-custom-agent-edit-page-design](./2026-04-27-custom-agent-edit-page-design.md) | Agent edit form + tool-groups endpoint design | **open · actionable** — implementation plan exists, work not started | [custom-agent-edit-page](../plans/2026-04-27-custom-agent-edit-page.md) |
| [2026-04-27-loop-detection-orphan-tool-msg](./2026-04-27-loop-detection-orphan-tool-msg.md) | P1 bug: `LoopDetectionMiddleware.hard_stop` clears `tool_calls` but leaves orphan `ToolMessage` history → MiniMax/Anthropic 400 on next call | **open · actionable** — P1 bug; fix deferred behind self-hosting epic | _none yet_ |
| [2026-04-27-user-guide-design](./2026-04-27-user-guide-design.md) | 9-chapter user guide structure + role definitions + TOC | **open · in-progress** | [user-guide-implementation](../plans/2026-04-27-user-guide-implementation.md) |

---

## Archived specs

All under [`archive/`](./archive/). Archived 2026-04-28 alongside their companion plans.

| Spec | Companion plan |
|---|---|
| [channels-identity-ci-smoke-design](./archive/2026-04-24-channels-identity-ci-smoke-design.md) | [channels-identity-ci-smoke](../plans/archive/2026-04-25-channels-identity-ci-smoke.md) |
| [m7a-deferred-items-design](./archive/2026-04-24-m7a-deferred-items-design.md) | [m7a-deferred-items](../plans/archive/2026-04-24-m7a-deferred-items.md) |
| [skill-agent-i18n-design](./archive/2026-04-25-skill-agent-i18n-design.md) | [agent-fix-i18n](../plans/archive/2026-04-25-agent-fix-i18n.md) (closed) + [agent-skill-version-pin](../plans/2026-04-25-agent-skill-version-pin.md) (still active) |
| [skill-mgmt-v2-complete-design](./archive/2026-04-25-skill-mgmt-v2-complete-design.md) | [skill-mgmt-v2-remaining](../plans/archive/2026-04-25-skill-mgmt-v2-remaining.md) |
| [p0-original-scope-audit](./archive/2026-04-27-p0-original-scope-audit.md) | _no plan — retrospective audit doc_ |
| [skill-slash-prefix-display](./archive/2026-04-27-skill-slash-prefix-display.md) | _no plan — shipped via `feat(skills): show "/skill-name" badge"` commits_ |
