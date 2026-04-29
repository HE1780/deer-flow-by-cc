# DeerFlow Documentation Index

> 📦 **2026-04-29 — 当前阶段验收**：[`SYSTEM_WHITEPAPER.md`](./SYSTEM_WHITEPAPER.md) 已交付（系统级白皮书），[`OPEN_ISSUES.md`](./OPEN_ISSUES.md) 已交付（仍未闭环议题）。所有 active plan/spec 已归档，详情见各子目录 README。

---

## 顶层文档（按重要性排序）

| Doc | 用途 |
|---|---|
| [SYSTEM_WHITEPAPER.md](./SYSTEM_WHITEPAPER.md) | **本期验收主文档** — 前端 + 后端 + 系统配置全景，含 E2E 流程、业务规则、测试矩阵 |
| [OPEN_ISSUES.md](./OPEN_ISSUES.md) | **本期收尾产出** — 仍未闭环的 13 项 open issue + 38 项部署演练 gap |
| [UPGRADE_v2.md](./UPGRADE_v2.md) | v1 → v2 升级指南（多租户身份） |
| [identity-release-checklist.md](./identity-release-checklist.md) | 发布前手工演练清单 |
| [identity-alerting.md](./identity-alerting.md) | Prometheus 告警规则样板 |
| [lessons.md](./lessons.md) | 教训记录（追加，不删除） |

---

## 子目录组织

| Directory | Purpose |
|---|---|
| [`superpowers/specs/`](./superpowers/specs/) | Design specs — 全部已归档至 `archive/`，索引见 [specs README](./superpowers/specs/README.md) |
| [`superpowers/plans/`](./superpowers/plans/) | Implementation plans — 全部已归档至 `archive/`，索引见 [plans README](./superpowers/plans/README.md) |
| [`user-guide/`](./user-guide/) | 用户使用手册（正文完成，截图待补 — 详见 [OPEN_ISSUES OI-6](./OPEN_ISSUES.md)） |
| [`pr-evidence/`](./pr-evidence/) | PR 引用的截图归档 |
| [`plans/archive/`](./plans/archive/) | 历史 plan 残留（仅 Langfuse tracing） |

**归档纪律**：
- **设计性内容**（plan/spec）closed 后 `git mv` 到 `archive/`，PR 链接历史保持鲜活
- **流程性内容**（handover、point-in-time diff 摘要）任务完成后**直接删除**——`git log` 是更新鲜的真相

---

## 锚定参考

- v2 设计不变量与 P1+ 路线图：[`superpowers/specs/archive/2026-04-21-deerflow-identity-foundation-design.md`](./superpowers/specs/archive/2026-04-21-deerflow-identity-foundation-design.md)
- 前端 / 后端开发约定：[`frontend/CLAUDE.md`](../frontend/CLAUDE.md) + [`backend/CLAUDE.md`](../backend/CLAUDE.md)
- 应用配置全貌：[`SYSTEM_WHITEPAPER.md §7`](./SYSTEM_WHITEPAPER.md)

---

## 长期未规划议题

不在 plan/spec 体系内、但在 [OPEN_ISSUES.md](./OPEN_ISSUES.md) 跟踪的方向：

- **Self-hosting epic** — docker-compose / Helm / 离线镜像 / 安装文档（下一期主线）
- **P1 RBAC 细粒度 / P2 KB / P3 SkillHub / P4 collab / P5 workflow editor** — 入口都在 identity foundation spec head matter

---

## 命名约定

- Plans / specs 用 `YYYY-MM-DD-<short-name>.md`。
- Companion plan + spec 共享 `<short-name>` 部分。
- 设计性 closed docs 用 `git mv` 到 `archive/`；流程性 closed docs 直接删除。
