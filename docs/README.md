# DeerFlow Documentation Index

Top-level entry point for project documentation. Last reorganized 2026-04-28 after
the P0 identity foundation reached its closure milestone.

---

## How docs are organized

| Directory | Purpose |
|---|---|
| [`superpowers/specs/`](./superpowers/specs/) | Design specs (load-bearing references) — see [specs README](./superpowers/specs/README.md) |
| [`superpowers/plans/`](./superpowers/plans/) | Implementation plans (one per shippable scope) — see [plans README](./superpowers/plans/README.md) |
| [`superpowers/handovers/`](./superpowers/handovers/) | Cross-session handover notes |
| [`user-guide/`](./user-guide/) | End-user manual (work-in-progress, see [user-guide/README](./user-guide/README.md)) |
| [`pr-evidence/`](./pr-evidence/) | Screenshots / artifacts referenced from PRs |
| [`plans/`](./plans/) | Legacy plans dir (predates `superpowers/plans/`); kept only because Langfuse plan moved to its own archive |
| [`archive/`](./archive/) | Obsolete top-level docs (point-in-time change summaries, superseded fixes) |

Closed plans/specs always live in a sibling `archive/` next to their active siblings, never deleted.

---

## Active reference docs (top-level)

| Doc | Purpose |
|---|---|
| [UPGRADE_v2.md](./UPGRADE_v2.md) | v1 → v2 upgrade guide (multi-tenant identity rollout). Anchor for any deployment migrating off the legacy single-tenant tree. |
| [identity-release-checklist.md](./identity-release-checklist.md) | Manual runbook to exercise on staging before promoting v2 to production. Spec §11.7. |
| [identity-alerting.md](./identity-alerting.md) | Sample Prometheus alert rules for the identity subsystem (`GET /metrics`). |

Anchor design doc: [`superpowers/specs/2026-04-21-deerflow-identity-foundation-design.md`](./superpowers/specs/2026-04-21-deerflow-identity-foundation-design.md) — the v2 invariants, data model, RBAC scheme, and the P1+ roadmap entry points all live there.

---

## Where work-in-progress lives

- **Active plans:** [`superpowers/plans/`](./superpowers/plans/) (only 3 right now: agent skill version pin, custom-agent edit page, user-guide).
- **Active specs:** [`superpowers/specs/`](./superpowers/specs/) (4 active including the identity anchor doc).
- **Long-term parking lot** (no plan file yet, tracked in memory):
  - **Self-hosting epic** — docker-compose / Helm / offline images / install docs. Next major epic.
  - **P1 RBAC fine-grain, P2 KB, P3 SkillHub, P4 collab, P5 workflow editor** — entries listed in the identity-foundation spec head matter.

---

## Naming conventions

- Plans / specs use `YYYY-MM-DD-<short-name>.md`.
- Companion plan + spec share the `<short-name>` portion when 1:1.
- Closed docs are `git mv`'d to `archive/` rather than deleted, so links from past PRs and commit messages stay alive.
