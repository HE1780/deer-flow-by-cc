# DeerFlow 开放议题清单

> **状态**：当前系统验收阶段独立产出
> **基线 commit**：`d6497326`（cc-main，2026-04-29）
> **撰写依据**：基于代码事实（`grep`/`find` 实地核对），凡过程文档与代码不一致一律以代码为准
> **配套文档**：[SYSTEM_WHITEPAPER.md](SYSTEM_WHITEPAPER.md)（已交付的功能总览）

本文档**只**收录**当前**仍未闭环的议题。已 ship 的事项不在此处出现，过期描述已剔除（见文末"已剔除条目"）。

---

## 目录

- [P1 — 阻塞或显著影响生产](#p1--阻塞或显著影响生产)
- [P2 — 体验/完整度（不阻塞）](#p2--体验完整度不阻塞)
- [P3 — 增强 / 部署演练](#p3--增强--部署演练)
- [验收 gap 清单（38 项手工演练）](#验收-gap-清单38-项手工演练)
- [已剔除条目（核对后确认已闭环）](#已剔除条目核对后确认已闭环)

---

## P1 — 阻塞或显著影响生产

### OI-1 LoopDetectionMiddleware **warning 路径**注入 HumanMessage 导致线程永久损坏

**当前事实**（核验源：[backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py](backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py)）：
- **hard_stop 路径**已修：line 508-516 通过 `RemoveMessage(id=m.id)` 清孤儿 ToolMessage，对应 spec `2026-04-27-loop-detection-orphan-tool-msg.md` 已闭环。
- **warning 路径**仍未修：line 373-380 直接在工具调用循环中间注入 `HumanMessage(content=warning)`，破坏 `AIMessage(tool_calls) → ToolMessage(result)` 配对。

**症状**：MiniMax M2.7 等严格 provider 在历史含 warning 注入的 thread 上发起下一轮调用时，返回 `400 "tool call result does not follow tool call (2013)"`，**线程永久损坏**。已实证：thread `336b7fce-...`（[docs/lessons.md](lessons.md) 2026-04-28 完整复盘）。

**触发条件**：`warn_threshold=3` < 重复工具调用次数 < `hard_limit=5`。一旦命中，warning 路径不做任何消息清理。

**待讨论**：
1. 方案 A：把 warning 合并到下一轮 system prompt 而非作为独立 message。
2. 方案 B：保留 HumanMessage 但用 `RemovableMessage` 在下一轮 LLM 调用前清理。
3. 方案 C：warning 触发后给 thread 打"已 warn"标记，阻止后续运行（最保守）。

**影响域**：所有使用严格 provider（MiniMax/Anthropic）+ 长内容生成的 thread。

---

### OI-2 LLMErrorHandlingMiddleware 静默吞错

**当前事实**（核验源：[backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py](backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py)）：
- 当 LLM 返回 400/网络错误时，middleware 捕获异常 → 返回 user-facing fallback message → Run 标记为 `success`。
- **未写 audit critical log**，上层无法感知线程已损坏。

**症状**：用户看到模糊的"模型出错了"提示，运维侧无任何告警；OI-1 里"线程永久损坏"的诊断也是事后翻日志才能定位。

**待讨论**：
1. 加 `logger.critical("LLM error silenced after %d attempts ...", ..., exc_info=exc)`（design 已写于 spec `2026-04-28-llm-event-loop-closed-design.md` §4.5，Task 8/9 描述清晰）。
2. 把 `llm.error.silenced` 加进 audit `KNOWN_ACTIONS` + `KEY_CRITICAL_ACTIONS`。
3. 区分协议错误（400 类）与临时性错误（网络/限流）：前者不静默，向上抛出；后者保留 fallback。

**影响域**：所有走 `LLMErrorHandlingMiddleware` 的 LLM 调用（即所有 agent 运行）。

---

### OI-3 Standard mode 下 LLM `Event loop is closed` bug 未修

**当前事实**（核验源：[backend/CLAUDE.md](../backend/CLAUDE.md) Runtime Modes 段 + [backend/packages/harness/deerflow/runtime/main_loop.py](backend/packages/harness/deerflow/runtime/main_loop.py) 已存在）：
- **Gateway mode 已修**（commit `c769a210`）：`set_main_loop` + `submit_to_main_loop` 复用 Uvicorn 主 loop。
- **Standard mode 仍存在**：memory updater 与 subagent executor 仍走 ephemeral `asyncio.run`，会触发 [langchain-ai/langchain#35783](https://github.com/langchain-ai/langchain/issues/35783) 的 cached httpx-client 跨 loop bug。
- 已在 `backend/CLAUDE.md` 文档化为已知限制：**生产推荐 Gateway mode**。

**待讨论**：
1. 接受现状（已文档化），并把 Standard mode 在 README 标注为"开发/调试用"。
2. 给 LangGraph Server 加自定义 lifespan hook 注入 main loop（侵入性大，不确定 LangGraph 是否允许）。
3. 让 memory updater / subagent executor 在 Standard mode 下通过 langgraph-sdk HTTP 调回 LangGraph 而非直接调 LLM（绕过本地 ephemeral loop）。

**影响域**：仅 `make dev` 启动模式 + 启用 memory 或 subagent 的对话第 2 轮起。生产用 `make dev-pro` / `make up-pro` 不受影响。

---

## P2 — 体验 / 完整度（不阻塞）

### OI-4 注册码注册（registration-code）— ✅ 后端已 ship（2026-04-30）

**当前事实**：
- 设计：[docs/superpowers/specs/2026-04-29-registration-code-design.md](superpowers/specs/2026-04-29-registration-code-design.md)
- Plan：[docs/superpowers/plans/2026-04-29-registration-code.md](superpowers/plans/2026-04-29-registration-code.md)
- 实施：merged into cc-main as `e7235070`（23 commits，173 测试绿）
- 行为契约见 [backend/CLAUDE.md](../backend/CLAUDE.md) "Registration code flow" 小节

**仍待办**（不阻塞 P0/P1）：
- 前端注册页面（输入码 + email + password 表单）
- email 通知（注册码链接当前由 admin OOB 分发）
- skill publish 审核机制（启用后再放开 `skill:publish` 给 `workspace_member`）
- existing user 升级 `workspace_member`（本期只对未来扫码注册的人生效）

**已知 tech debt**（review 阶段记录）：
- `set_password` 和 `create_user` 仍用默认 bcrypt cost（应读 `settings.bcrypt_cost`）
- `_EMAIL_RE` 已抽到 `validators.EMAIL_RE` 共享模块；其它 router 如有重复 regex 可复用

---

### OI-5 同名 skill (public vs custom) 前端 UI 无法清晰区分

**当前事实**（核验源：skill 加载逻辑见 [`packages/harness/deerflow/skills/`](../backend/packages/harness/deerflow/skills/)；冲突修复历史在 git log 中可查 `git log --grep "skill name conflict"`）：
- **后端已修**：配置层用组合键 `{category}:{name}`，API 支持 `category` 参数。
- **前端未补**：UI 无 category badge，用户在 skill 库看不出哪个是 public、哪个是 custom；同名时容易误装载错误 skill。

**待讨论**：
1. 在 skill 卡片加 badge 显示 `public` / `custom` / `user`。
2. 上传 skill 时检查与 public 同名并警告。
3. 后端 `POST /api/skills/install` 直接拒绝与 public 同名（最保守）。

**影响域**：低频出现，但一旦撞名很难调试。

---

### OI-6 用户使用手册缺截图

**当前事实**（核验源：`ls docs/user-guide/`）：
- **正文已完成**：9 章 + README，约 599 行（[docs/user-guide/](user-guide/)）。
- **截图全缺**：[docs/user-guide/images/](user-guide/images/) 目录为空（仅 `.gitkeep` 占位）。

**剩余工作**：
1. 补 10+ 张截图（`01-login-page.png`、`01-workspace-home.png`、`02-new-thread.png` 等，文件名清单见 [user-guide-implementation plan](superpowers/plans/archive/2026-04-27-user-guide-implementation.md)）。
2. 复核 01-06 章准确性：写于 admin nav 改造前，UI 可能已变；07-08 章已确认与当前 admin 路由一致。
3. 删除/修订 09 章中已过时的"已知限制"：
   - 「`/admin/tenants/{id}` 是占位页」**已过时**（页面 207 行真页面）
   - 「`/admin/users/{id}` 是占位页」**已过时**（页面 205 行真页面）
   - 「`/admin/workspaces/{id}/members` 完整度待验证」**已过时**（已 ship）
   - 「audit fallback.jsonl 路径异常致 gateway 启动失败」**待复核**：fallback.py 已使用 asyncio.Lock 串行化 + rotate-then-read，旧文档描述的"被错误创建为目录"问题可能已不再现。

**待讨论**：是否本期完成截图收尾，还是留到下一个文档迭代（用户体验影响小）。

---

### OI-7 Workspace 切换 / auth gate 未在生产路由生效

**当前事实**：
- `frontend/src/app/api/auth/[...all]/` 是 better-auth 转发器，已配置但未在生产路由启用（见 [SYSTEM_WHITEPAPER.md](SYSTEM_WHITEPAPER.md) §3.6）。
- workspace 切换在多 workspace 用户场景下的 401 拦截 + 自动重新激活当前 tenant 流程未端到端验证。

**待讨论**：
1. better-auth 是否准备启用？如否，删除 `frontend/src/server/better-auth/config.ts` + route handler 减少混淆。
2. 多 tenant 用户切换 workspace 时的 token 刷新链路是否完整？设计假设 `/api/me/switch-tenant` 后 cookie 会被替换，但缺少专门 E2E 测试。

---

## P3 — 增强 / 部署演练

### OI-8 OIDC 真实 IdP 端到端验证未完成

**当前事实**（核验源：[docs/identity-release-checklist.md](identity-release-checklist.md)）：
- 代码层完整：PKCE + state + nonce + Redis 反重放（`auth/oidc.py`）。
- 单元测试有：`backend/tests/identity/auth/test_identity_factory.py`、`test_oidc.py`。
- **真实 IdP 烟雾测试 3 项未跑**：Okta / Azure AD / Keycloak 各一次完整 round-trip。
- CI 烟雾通过签发 RS256 JWT 直接绕过 OIDC，未触达 IdP（[.github/workflows/identity-e2e-smoke.yml](.github/workflows/identity-e2e-smoke.yml)）。

**风险**：首批生产用户用真实 IdP 部署时可能遇到 redirect_uri / claim mapping / scope 不匹配。

**待讨论**：是否在 self-hosting epic 阶段安排一次三个 IdP 的演练？

---

### OI-9 Langfuse tracing 集成

**当前事实**：
- 设计完整：[docs/plans/archive/2026-04-01-langfuse-tracing.md](plans/archive/2026-04-01-langfuse-tracing.md)（4 个 task：配置解析、callback factory、依赖、回归测试）。
- **未实施**。

**影响域**：可观测性增强，不阻塞核心流程。Prometheus `/metrics`（M7-C 已 ship）已覆盖 5 项 identity 指标，但 LLM 调用链路追踪缺位。

**待讨论**：是否纳入下一个可观测性迭代？还是改用 LangSmith / OpenTelemetry？

---

### OI-10 Path B 多租户迁移脚本的实装完整度复核

**当前事实**：
- 入口存在：`scripts/migrate_to_multitenant.py`（Makefile 暴露 `make identity-migrate-{dry,apply,rollback}`）。
- 设计完整：planner / executor / rollback / report / lock 五件套（见 [SYSTEM_WHITEPAPER.md](SYSTEM_WHITEPAPER.md) §3.1.7）。
- **未实操跑过 1000-thread 演练**（release checklist 38 项未勾选项之一）。
- **未端到端验证 rollback**。

**已知风险**：fallback.jsonl 路径异常时 gateway 启动可能失败（OI-6 第 4 条已复核：可能已修，但未端到端验证）。

**待讨论**：
1. self-hosting epic 阶段是否安排一次正式的迁移演练（含 rollback drill）？
2. 是否需要给迁移加 dry-run 报告的人类可读 summary 文件（当前是 JSON）？

---

### OI-11 多副本 bootstrap advisory lock 真机演练未跑

**当前事实**：
- 代码已实现：[backend/app/gateway/identity/bootstrap_lock.py](../backend/app/gateway/identity/bootstrap_lock.py) `bootstrap_with_advisory_lock` 用 `pg_advisory_lock(hashtext('deerflow_bootstrap'))`。
- 失败降级路径已写：锁获取失败 → 降级到 pre-M7 路径并打 WARN 日志。
- **未在双副本同时启动场景下验证**（release checklist "Both replicas should reach `Listening on ...` within 10 s"）。

**待讨论**：是否在 K8s staging 上跑一次 2 副本同时滚动重启演练？

---

### OI-12 Docker 与 K8s 部署演练 gap

**当前事实**（核验源：release checklist 未勾选项）：
- `docker compose up`（dev）+ identity on 流程未端到端验证。
- `./scripts/deploy.sh`（prod）+ identity on 流程未端到端验证。
- K8s 双副本 + ingress 部署演练未跑。

**待讨论**：self-hosting epic 阶段把这三种部署形态纳入正式发布前 checklist。

---

### OI-13 标志切换（identity on/off）回归演练未跑

**当前事实**：
- 代码层 `ENABLE_IDENTITY=false` 完全惰性已由 `tests/identity/test_feature_flag_offline.py` 单测保证。
- **完整切换演练**未跑：staging 上 on→off→on 一遍，确认线程持久化兼容性、`/api/auth/*` 404、`/metrics` 404、legacy 路由回到 v1 行为。

**待讨论**：是否在下一期发布前演练一次？

---

## 验收 gap 清单（38 项手工演练）

完整清单见 [docs/identity-release-checklist.md](identity-release-checklist.md) 中的 `- [ ]` 项。按主题归类：

| 主题 | 未勾选项数 | 主要内容 |
|---|---|---|
| 测试覆盖 / CI | 5 | identity/* 80% 覆盖率、ENABLE_IDENTITY=false 守卫、CHANGELOG/UPGRADE_v2 终稿 |
| OIDC 真实 IdP | 3 | Okta、Azure AD、Keycloak 各一轮端到端（OI-8） |
| 多租户迁移 | 5 | dry → apply → 重跑幂等 → 五个抽样 → rollback（OI-10） |
| 多副本 bootstrap | 3 | 双副本同时启动 + advisory lock 验证（OI-11） |
| 部署形态 | 3 | docker compose dev / prod / K8s（OI-12） |
| 标志切换 | 5 | on→off→on 完整回归（OI-13） |
| 审计端到端 | 4 | 空数据查询 / CSV 导出 / PG 离线 fallback / backfill |
| Prometheus | 3 | `/metrics` 抓取 / 告警规则 / Grafana 面板 |
| 综合冒烟 | 7 | 真实 IdP + 各部署形态联动 |

**讨论方向**：以上 38 项不是代码 bug，是部署/发布流程缺位。建议把 release-checklist 拆成两组：
1. **必跑（阻塞 v2 发布）**：标志守卫、OIDC 至少一个 IdP、迁移 dry+apply、单副本 bootstrap、docker compose prod。
2. **强烈建议（提示）**：其余 28 项放到后续滚动验证。

---

## 已剔除条目（核对后确认已闭环）

以下议题在过程文档里曾出现为"未实施 / TODO / open"，但**经代码核对已确认 ship**，不再属于 open issue：

| 议题 | 核对依据 | 状态 |
|---|---|---|
| Session refresh 401 拦截器 | [frontend/src/core/identity/fetcher.ts](frontend/src/core/identity/fetcher.ts) line 41-128，commit `d6497326` | ✅ 已 ship |
| LLM event-loop main_loop helper（Gateway mode） | [backend/packages/harness/deerflow/runtime/main_loop.py](backend/packages/harness/deerflow/runtime/main_loop.py) 存在；commit `c769a210` | ✅ 已 ship（Standard mode 见 OI-3） |
| LoopDetectionMiddleware **hard_stop** 孤儿 ToolMessage | loop_detection_middleware.py line 508-516 `RemoveMessage` 已加 | ✅ 已 ship（warning 路径见 OI-1） |
| Custom-agent edit page UI + `GET /api/tool-groups` | [frontend/src/app/workspace/agents/[agent_name]/edit/page.tsx](../frontend/src/app/workspace/agents/%5Bagent_name%5D/edit/page.tsx) + agents.py line 123 | ✅ 已 ship |
| Skill `name@version` pin + manifest.yaml | [backend/packages/harness/deerflow/skills/manifest.py](../backend/packages/harness/deerflow/skills/manifest.py) 存在 | ✅ 已 ship |
| Uploads tenant-aware 5 处 call site | commits `aedcf8af`/`4ce6c997`/`9722937c`/`16770364`/`4eca6cc5` | ✅ 已 ship |
| Workspace/outputs 双目录假死循环 | commits `b62d35bc` + `d67e0e13`，spec 已 close | ✅ 已 ship |
| Password login + admin set_password | [backend/app/gateway/identity/routers/auth.py](../backend/app/gateway/identity/routers/auth.py) line 192/253 | ✅ 已 ship |
| `/admin/tenants/[id]`、`/admin/users/[id]` 占位页 | 实测各 200+ 行真实页面，非 stub | ✅ 已非 stub |
| `/admin/workspaces/[id]/members` 完整度 | 已合并 PR，目录存在功能可用 | ✅ 已 ship |
| Channels 多租户路径透传 | commits `4ce6c997`/`9722937c` | ✅ 已 ship |
| 14 个 admin 页 (M7-A) | `frontend/src/app/(admin)/admin/` 11 个目录全部 ship | ✅ 已 ship |
| identity-langgraph passthrough P0 bug | 已修，`/api/langgraph-compat` 已默认（见 SYSTEM_WHITEPAPER §1.3） | ✅ 已 ship |

---

## 复核日志

- 2026-04-29：基于 commit `d6497326` 全量重核，剔除 13 项过时 open（见上表），保留 13 项真实 open（OI-1 ~ OI-13）+ 38 项验收 gap。
- 核验方法：`git log` + `find` + `grep -n` 实地查代码，过程文档与实地不一致一律以代码为准。
- 配套白皮书 [SYSTEM_WHITEPAPER.md](SYSTEM_WHITEPAPER.md) 同基线产出，可联合评审。
