# DeerFlow 系统白皮书

> **状态**：当前系统验收提交
> **范围**：前端 + 后端 + 系统配置（基于代码事实，2026-04-29 cc-main 分支）
> **撰写依据**：仓库实际源码与配置文件，独立于 `docs/plans/`、`docs/superpowers/specs/`、`memo/` 等上层文档
> **基线 commit**：`d6497326 Merge feat/session-refresh-interceptor`

---

## 目录

1. [产品定位与系统拓扑](#1-产品定位与系统拓扑)
2. [整体架构](#2-整体架构)
3. [功能描述（按子系统）](#3-功能描述按子系统)
4. [E2E 流程图](#4-e2e-流程图)
5. [业务规则与不变量](#5-业务规则与不变量)
6. [测试点矩阵](#6-测试点矩阵)
7. [系统配置与部署](#7-系统配置与部署)
8. [验收清单](#8-验收清单)

---

## 1. 产品定位与系统拓扑

### 1.1 产品定位

DeerFlow 是一个基于 LangGraph 的开源 AI 超级智能体（super-agent）系统，面向**自托管/私有化部署**场景。系统以单一"主智能体（lead_agent）+ 子智能体委派"为执行内核，叠加沙箱执行、持久记忆、技能（skills）扩展、MCP 工具集成、IM 通道桥接，构成一个可在企业内部独立运行的 AI 工作台。

### 1.2 进程拓扑

| 进程 | 端口 | 角色 |
|---|---|---|
| **Nginx** | 2026 | 统一反代入口，按路径分发 |
| **Frontend** (Next.js) | 3110 | Web UI（聊天、Admin、Workspace） |
| **Gateway API** (FastAPI) | 8100 | REST API：模型、MCP、技能、记忆、上传、线程、artifacts、agents、suggestions、channels、identity |
| **LangGraph Server** | 2024 | Agent 运行时（Standard 模式独立进程） |
| **Provisioner** | 8002 | K8s/Docker 沙箱供应器（仅在沙箱配置为 provisioner 模式时启动） |
| **PostgreSQL** | 5432 | identity 子系统数据库（启用 `ENABLE_IDENTITY` 时） |
| **Redis** | 6379 | 会话、锁定、PKCE/state、权限缓存 |

### 1.3 两种运行模式

代码层面通过 `make dev`（Standard）和 `make dev-pro`（Gateway 模式，实验性）区分：
- **Standard**：4 进程，LangGraph Server 独立处理 agent 执行
- **Gateway**：3 进程，agent 运行时嵌入 Gateway（`packages/harness/deerflow/runtime/`），无 LangGraph Server，`/api/langgraph/*` 在 nginx 处通过 envsubst 改写为指向 Gateway

---

## 2. 整体架构

### 2.1 后端代码分层（强制依赖方向）

```
backend/
├── packages/harness/deerflow/      # 可发布的 agent 框架（import: deerflow.*）
│   ├── agents/                     # lead_agent、middleware 链、memory、ThreadState
│   ├── sandbox/                    # 抽象沙箱接口 + LocalSandboxProvider + tools
│   ├── subagents/                  # 子智能体执行池（scheduler×3 + execution×3）
│   ├── tools/builtins/             # present_files、ask_clarification、view_image
│   ├── community/                  # tavily/jina_ai/firecrawl/aio_sandbox/image_search
│   ├── mcp/                        # MCP MultiServerMCPClient + 缓存（mtime 失效）
│   ├── models/                     # 模型工厂 + vLLM provider
│   ├── skills/                     # SKILL.md 加载、安装、租户分层
│   ├── reflection/                 # 字符串路径 → 模块/类解析
│   ├── runtime/                    # Gateway 模式：RunManager + run_agent + StreamBridge
│   ├── identity_propagation.py     # M5 HMAC 签名/校验（与 app/ 同源契约）
│   └── client.py                   # DeerFlowClient（嵌入式入口，与 Gateway 响应同形）
│
└── app/                            # 应用层（import: app.*）
    ├── gateway/                    # FastAPI 应用
    │   ├── app.py                  # create_app + lifespan
    │   ├── routers/                # 13 个业务 router
    │   └── identity/               # M1-M7：auth/RBAC/audit/storage/migration/metrics
    └── channels/                   # 飞书/Slack/Telegram 集成
```

**依赖红线**：`app.* → deerflow.*` 允许；`deerflow.* → app.*` 禁止。由 [backend/tests/test_harness_boundary.py](backend/tests/test_harness_boundary.py) 在 CI 中强制执行。

### 2.2 前端代码分层

```
frontend/src/
├── app/                            # Next.js 16 App Router
│   ├── (public)/                   # login、logout、auth/oidc/[provider]/callback
│   ├── (admin)/admin/              # tenants、users、workspaces、roles、audit、profile、tokens、models、skills、org-keys
│   ├── workspace/                  # chats、agents、skills（核心工作台）
│   ├── api/auth/[...all]/          # better-auth 转发器（已配置未启用）
│   └── api/memory/                 # 记忆代理
│
├── core/                           # 业务逻辑（22 个子模块）
│   ├── identity/                   # 验收重点：api、fetcher、hooks、types、schemas
│   ├── threads/                    # 线程 CRUD + 流式聊天 hooks
│   ├── api/                        # LangGraph SDK 单例 + stream-mode 控制
│   ├── artifacts/、agents/、skills/、memory/、messages/、mcp/...
│
├── components/
│   ├── ui/、ai-elements/           # shadcn + Vercel AI SDK 自动生成
│   └── workspace/                  # chats、agents、artifacts、citations、messages、settings
```

### 2.3 中间件链（lead_agent，最终顺序）

定义于 `packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py::build_lead_runtime_middlewares` 与 `agents/lead_agent/agent.py::_build_middlewares`：

| # | 中间件 | 启用条件 | 职责 |
|---|---|---|---|
| 0 | IdentityMiddleware | 设置了 `DEERFLOW_INTERNAL_SIGNING_KEY` | 校验 Gateway 注入的 HMAC 头，写 `state["identity"]` |
| 1 | ThreadDataMiddleware | 始终 | 创建 per-thread 目录树（含租户分层） |
| 2 | UploadsMiddleware | 始终 | 跟踪并注入新上传文件到对话 |
| 3 | SandboxMiddleware | 始终 | 获取沙箱、写 `sandbox_id` 到 state |
| 4 | DanglingToolCallMiddleware | 始终 | 为孤儿 AIMessage tool_calls 注入占位 ToolMessage |
| 5 | LLMErrorHandlingMiddleware | 始终 | 把模型调用失败转为 assistant-facing 错误 |
| 6 | IdentityGuardrailMiddleware | 同 #0 | RBAC 工具授权（白名单 + `TOOL_PERMISSION_MAP`） |
| 7 | GuardrailMiddleware（OAP） | `guardrails.enabled` | 可插拔策略 provider |
| 8 | SandboxAuditMiddleware | 始终 | 沙箱命令安全审计 |
| 9 | ToolErrorHandlingMiddleware | 始终 | 工具异常转 ToolMessage |
| 10 | SummarizationMiddleware | `summarization.enabled` | 上下文压缩 |
| 11 | TodoListMiddleware | `is_plan_mode` | `write_todos` 工具 |
| 12 | TokenUsageMiddleware | `token_usage.enabled` | 记录 token 消耗 |
| 13 | TitleMiddleware | 始终 | 首轮后自动生成 thread title |
| 14 | MemoryMiddleware | `memory.enabled` | 队列异步更新记忆 |
| 15 | ViewImageMiddleware | 模型 `supports_vision` | 注入图像 base64 |
| 16 | DeferredToolFilterMiddleware | 始终 | 延迟工具 schema 隐藏 |
| 17 | SubagentLimitMiddleware | `subagent_enabled` | 截断超额 task 调用（≤3 并发） |
| 18 | LoopDetectionMiddleware | 始终 | 检测重复 tool-call 循环，hard-stop 强制收尾 |
| 19 | ClarificationMiddleware | 始终（必须最后） | 拦截 `ask_clarification`，`Command(goto=END)` 中断 |

### 2.4 数据流

```
用户输入
  → frontend hooks (core/threads/hooks.ts)
  → LangGraph SDK 流式发起 run
  → nginx /api/langgraph/* → LangGraph Server（或 Gateway 嵌入运行时）
  → lead_agent middleware 链（19 层）
  → 流事件返回 (values | messages-tuple | custom)
  → frontend 解析并渲染（消息、artifacts、todos、tool calls）
```

---

## 3. 功能描述（按子系统）

### 3.1 Identity 身份子系统（M1-M7）

由 `ENABLE_IDENTITY` 环境变量门控，关闭时整个子系统惰性，无 DB 连接、无中间件注册。

#### 3.1.1 数据模型（11 张表，schema=`identity`）

| 表 | 关键字段 | 说明 |
|---|---|---|
| tenants | id, slug(unique), name, plan, status, owner_id, expires_at | 租户 |
| users | id, email(unique), display_name, oidc_subject, oidc_provider, password_hash, last_login_ip | 全局用户 |
| memberships | user_id, tenant_id, status | 用户-租户成员关系 |
| workspaces | id, tenant_id(FK), slug, name, unique(tenant_id, slug) | 工作区 |
| permissions | id, tag(unique), scope, description | 权限定义 |
| roles | id, role_key, scope, is_builtin, unique(role_key, scope) | 角色 |
| role_permissions | role_id, permission_id | 角色-权限 |
| user_roles | id(PK), user_id, tenant_id(nullable), role_id | tenant_id=NULL 表示平台级 |
| workspace_members | user_id, workspace_id, role_id | workspace 成员 |
| api_tokens | id, user_id, token_hash(bcrypt), scope, expires_at | `dft_*` API token |
| audit_logs | id, tenant_id, user_id, action, resource_*, ip, metadata(JSONB), created_at | 审计日志 |

**Alembic 迁移**：[backend/alembic/versions/](backend/alembic/versions/) 共 5 个版本，最新 `20260425_0005_skill_registry_org_api_keys.py`。

#### 3.1.2 认证流程（M2）

- **算法**：JWT RS256，密钥默认在 `$DEER_FLOW_HOME/_system/jwt_{private,public}.pem`（0600/0644）
- **Cookie**：`deerflow_session`（HttpOnly，Prod 环境 Secure，SameSite=Lax）
- **Refresh token**：仅服务端 Redis，明文不出网
- **OIDC**：PKCE + state + nonce 反重放，state/nonce 存 Redis
- **登录锁定**：按 `(IP, email)` 维度，参数走 `DEERFLOW_LOGIN_LOCKOUT_*`
- **Refresh endpoint**：`POST /api/auth/refresh`，从（可能已过期）的 token 中取 `sid`，到 Redis 验会话存活后重发 access token

#### 3.1.3 RBAC（M3）

- 装饰器 `@requires(tag, scope)` 来自 [backend/app/gateway/identity/rbac/decorator.py](backend/app/gateway/identity/rbac/decorator.py)
- scope ∈ `{platform, tenant, workspace}`
- 决策树：未认证 → 401；认证但无权限 → 403；scope 越权 → 403
- 路径参数自动提取：`tid`/`tenant_id`、`wid`/`workspace_id`/`ws_id`
- **JWT 模式**：权限放声明里，无需 Redis 查表
- **API token 模式**：`PermissionCache`（Redis，TTL 300s）

#### 3.1.4 租户隔离（M3 + M4）

- **数据层**（M3）：`install_auto_filter(sessionmaker)` 注册 SQLAlchemy `do_orm_execute` + `before_flush` 监听器
  - 所有继承 `TenantScoped` 的模型 SELECT 自动 `WHERE tenant_id = ?`
  - 所有继承 `WorkspaceScoped` 的模型 SELECT 自动 `WHERE workspace_id IN (...)`
  - 跨租户 INSERT/UPDATE 抛 `PermissionDeniedError`
  - 平台管理员绕过；维护脚本用 `with_platform_privilege()` 显式 opt-out
- **存储层**（M4）：`$DEER_FLOW_HOME/tenants/{tid}/workspaces/{wid}/threads/{thread_id}/user-data/{workspace,uploads,outputs}`
  - 13 个路径辅助函数定义于 [backend/app/gateway/identity/storage/paths.py](backend/app/gateway/identity/storage/paths.py)
  - `assert_within_tenant_root` / `safe_join` / `assert_symlink_parent_safe` 三道护栏
  - Gateway router（artifacts、uploads、threads.delete）通过 `extract_scope(request)` 拿 scope，越权统一返 `403 "Access denied"`（不泄漏租户 id）

#### 3.1.5 LangGraph 身份传播（M5）

由 `DEERFLOW_INTERNAL_SIGNING_KEY` 门控（与 `ENABLE_IDENTITY` 解耦）。

- **签名**：HMAC-SHA256 over `"{uid}|{tid}|{wid}|{perms_sorted}|{ts}"`
- **HTTP 头**：`X-Deerflow-User-Id`、`-Tenant-Id`、`-Workspace-Id`、`-Permissions`、`-Session-Id`、`-Identity-Ts`、`-Identity-Sig`
- **注入**：`app/gateway/services._inject_identity_headers` 在 `start_run()` 时塞进 `config["configurable"]["headers"]`
- **校验**：harness 侧 `IdentityMiddleware`（中间件链 #0），写 `VerifiedIdentity` 到 `state["identity"]`
- **重放窗口**：默认 300s（`DEERFLOW_HMAC_SKEW_SEC`）
- **Subagent 继承**：父 agent 的 `state["identity"]` 直接透传，子 agent IdentityMiddleware 检测到已有值不覆写

#### 3.1.6 审计管道（M6）

完整管道 6 个文件 + 1 个 Alembic 权限收紧：

| 组件 | 路径 | 职责 |
|---|---|---|
| events.py | `audit/events.py` | `AuditEvent` 数据类 + `KNOWN_ACTIONS` + `KEY_CRITICAL_ACTIONS` |
| redact.py | `audit/redact.py` | 密码/token/secret 字段 → `***`；命令截断 500 字符；`write_file` 仅留 path+size |
| fallback.py | `audit/fallback.py` | JSONL 落盘（PG 故障兜底），`asyncio.Lock` 串行化，rotate-then-read |
| writer.py | `audit/writer.py` | `AuditBatchWriter`：flush=1.0s, batch=500, queue_max=10000；critical 同步插入；非 critical 满则丢 |
| middleware.py | `audit/middleware.py` | 最外层 HTTP 中间件，跳过 `/api/me`、`/health`、`/docs`、`/internal/*`、`/api/langgraph` |
| api.py | `audit/api.py` | `GET /api/tenants/{tid}/audit`（cursor 分页，默认 7 天/最大 90 天）、`/export`（CSV，100k 行上限）、`/api/admin/audit`（跨租户，需 `audit:read.all`） |
| retention.py | `audit/retention.py` | 每日 cron：(tid, yyyy-mm) 分组归档 >90 天到 `.gz`，同事务删除 |
| 0003 迁移 | alembic 0003 | REVOKE UPDATE/DELETE on `audit_logs` from `deerflow`；GRANT DELETE to `deerflow_retention` |

#### 3.1.7 多租户迁移（M7-B）

CLI：`scripts/migrate_to_multitenant.py`（`make identity-migrate-{dry,apply,rollback}`）

- planner → executor → rollback → report 四件套
- 双锁：`fcntl.LOCK_EX | LOCK_NB` 文件锁 + PG `pg_try_advisory_lock(hashtext('deerflow_migration'))`
- 迁移完成后留下 forwarder symlink，重跑幂等
- Skill symlink 用 `assert_symlink_parent_safe` 防止跨租户逃逸
- 退出码：0/1/2/3/4 分别对应成功/预检失败/参数错/锁冲突/项目失败

#### 3.1.8 Release Hardening（M7-C）

- **Bootstrap 锁**：`bootstrap_with_advisory_lock(engine, ...)`，K8s 多副本 rolling 不会撞 idempotent seed
- **Prometheus 指标**：`GET /metrics`（依赖标志开关）
  - 计数：`identity_login_total{result}`、`identity_authz_denied_total`、`audit_write_failures_total`
  - 仪表：`identity_session_active`（SCAN Redis）、`audit_queue_depth`
- **CI 烟雾测试**：[.github/workflows/identity-e2e-smoke.yml](.github/workflows/identity-e2e-smoke.yml)，绕过 OIDC，直接为 bootstrap admin 签 RS256 JWT

### 3.2 Agent 运行时（lead_agent）

- **入口**：`make_lead_agent(config: RunnableConfig)`，注册在 [backend/langgraph.json](backend/langgraph.json)
- **状态**：`ThreadState` 扩展 `AgentState`，新增 `sandbox`、`thread_data`、`title`、`artifacts`、`todos`、`uploaded_files`、`viewed_images`
- **工具组装**：`get_available_tools(groups, include_mcp, model_name, subagent_enabled)` 合并：
  1. config.yaml 定义的工具（reflection 解析）
  2. MCP 工具（lazy + mtime 缓存）
  3. 内建工具（`present_files`、`ask_clarification`、`view_image`）
  4. `task` 子智能体工具（如启用）
- **运行时配置**（`config.configurable`）：`thinking_enabled`、`model_name`、`is_plan_mode`、`subagent_enabled`

### 3.3 子智能体（Subagents）

- **内建**：`general-purpose`（除 `task` 外全部工具）、`bash`（命令专家）
- **执行池**：`_scheduler_pool=3` + `_execution_pool=3`
- **并发上限**：`MAX_CONCURRENT_SUBAGENTS=3`，由 `SubagentLimitMiddleware` 在 `after_model` 截断
- **超时**：15 分钟
- **流程**：`task()` → `SubagentExecutor` → 后台线程 → 5s 轮询 → SSE 事件
- **事件**：`task_started` / `task_running` / `task_completed` / `task_failed` / `task_timed_out`

### 3.4 沙箱（Sandbox）

- **抽象接口**：`Sandbox`（`execute_command` / `read_file` / `write_file` / `list_dir`）
- **Provider 模式**：`SandboxProvider`（`acquire` / `get` / `release`）
- **实现**：
  - `LocalSandboxProvider`（单例，本地文件系统，路径映射）
  - `AioSandboxProvider`（社区，Docker 容器隔离）
  - K8s/Provisioner 模式（端口 8002）
- **虚拟路径**：
  - Agent 视角：`/mnt/user-data/{workspace,uploads,outputs}`、`/mnt/skills`
  - 物理（租户分层）：`$DEER_FLOW_HOME/tenants/{tid}/workspaces/{wid}/threads/{thread_id}/user-data/...`
- **沙箱工具**：`bash`、`ls`、`read_file`、`write_file`、`str_replace`
- **str_replace 锁**：作用域 `(sandbox.id, path)`，避免独立沙箱因相同虚拟路径相互阻塞

### 3.5 Skills 技能系统

- **位置**：`skills/{public,custom}/`
- **格式**：目录 + `SKILL.md`（YAML frontmatter：name、description、license、allowed-tools）
- **多租户加载顺序**（later wins）：
  1. `skills/public/`（跨租户共享）
  2. `tenants/{tid}/custom/`（租户私有）
  3. `tenants/{tid}/workspaces/{wid}/user/`（workspace 私有）
- **租户级 disable-only 语义**：租户配置只能禁用全局已启用的技能，不能再启用全局禁用的（防止策略放松）
- **安装**：`POST /api/skills/install` 解压 `.skill` 到 custom/

### 3.6 MCP（Model Context Protocol）

- 基于 `langchain-mcp-adapters` `MultiServerMCPClient`
- **传输**：stdio（命令）、SSE、HTTP
- **OAuth**：HTTP/SSE 支持 `client_credentials` + `refresh_token`，自动注入 Authorization
- **延迟初始化** + **mtime 缓存失效**
- 配置文件：`extensions_config.json`，运行时由 `PUT /api/mcp/config` 写入

### 3.7 IM Channels

支持飞书、Slack、Telegram。

- **MessageBus**：异步 pub/sub，inbound 队列 → outbound 回调
- **Store**：JSON 持久化 `channel:chat[:topic]` → `{thread_id, tenant_id, workspace_id, user_id}`
- **Manager**：路由命令、`client.threads.create()` 起线程、`client.runs.{wait,stream}` 收结果
- **飞书特殊**：`runs.stream(["messages-tuple", "values"])` 流式累积 AI 文本，单条 card `PATCH` 原地更新
- **命令**：`/new`、`/status`、`/models`、`/memory`、`/help`

### 3.8 内存（Memory）

- **存储**：`backend/.deer-flow/memory.json`
- **结构**：用户上下文（workContext、personalContext、topOfMind）+ 历史（recentMonths、earlierContext、longTermBackground）+ 离散事实（id、content、category、confidence、createdAt、source）
- **流程**：
  1. `MemoryMiddleware` 过滤消息（用户输入 + 最终 AI 响应）入队
  2. 队列 30s 防抖批处理，per-thread 去重
  3. 后台线程调 LLM 抽取上下文 + 事实
  4. 原子写入（temp + rename），缓存失效，去重重复事实
  5. 下轮注入 top 15 facts + context 进 `<memory>` 标签

### 3.9 前端 Identity 模块（验收重点）

#### 3.9.1 [frontend/src/core/identity/fetcher.ts](frontend/src/core/identity/fetcher.ts) — 401 拦截器（本次验收核心）

```typescript
// 关键不变量
let pendingRefresh: Promise<boolean> | null = null;  // singleflight slot
type InternalInit = RequestInit & { _skipRefreshOn401?: boolean };
```

**identityFetch 行为**：
1. 默认带 `credentials: "include"`、`accept: application/json`，body 存在则补 `content-type`
2. **401 处理**：
   - 若 `_skipRefreshOn401` 为 true（refresh 调用本身或 retry）→ 触发 `emitSessionExpired()` + 抛 `IdentityFetchError({kind:"unauthenticated"})`
   - 否则 → `await refreshSession()`（singleflight）
   - refresh 成功 → 单次重试（`_skipRefreshOn401: true`）
   - refresh 失败 → 同上，触发 session expired
3. **403 处理**：尝试解析 `detail.missing` 权限，抛 `IdentityFetchError({kind:"forbidden", missing})`
4. **其他非 2xx**：抛 `IdentityFetchError({kind:"network", status, message})`

**refreshSession singleflight**（[fetcher.ts:41-53](frontend/src/core/identity/fetcher.ts#L41-L53)）：
- `pendingRefresh` 存活期间所有并发 401 共享同一 Promise
- 任意 throw 都被 `.catch(() => false)` 吞，`finally` 清空 slot
- 只有内部 `_refreshSessionForIdentityApi` 导出别名供 `identityApi.refresh` 复用，外部无法直接触发

**Session expired 监听器**：
- `onSessionExpired(fn)` 注册，`emitSessionExpired()` 单次去重广播
- `consumeSessionExpired()` 重置标志，`resetSessionExpiredListeners()` 清表（测试用）

#### 3.9.2 [identityApi](frontend/src/core/identity/api.ts) — 后端契约面

40+ 个 API 函数全部走 `identityFetch`，分组：
- **A1（认证）**：`me`、`providers`、`logout`、`refresh`
- **A2（admin 读）**：`switchTenant`、`listTenants`、`getTenant`、`listUsers`、`getUser`、`listWorkspaces`、`listWorkspaceMembers`、`listTenantTokens`、`listAudit`、`listRoles`、`listPermissions`
- **A3（admin 写）**：`createUser`、`addWorkspaceMember`、`patchWorkspaceMemberRole`、`removeWorkspaceMember`、`createTenantToken`、`revokeTenantToken`
- **租户/Workspace CRUD**（M7A）：`createTenant`、`updateTenant`、`deleteTenant`、`createWorkspace`、`updateWorkspace`、`deleteWorkspace`
- **个人**：`updateMe`、`changePassword`、`adminSetPassword`
- **A4（me/* 自助）**：`listMyTokens`、`createMyToken`、`revokeMyToken`、`listMySessions`、`revokeMySession`
- **组织密钥**（5.1c）：`listOrgKeys`、`createOrgKey`、`revokeOrgKey`

#### 3.9.3 [hooks.ts](frontend/src/core/identity/hooks.ts) — TanStack Query 封装

40+ 个 React Query hooks：
- 列表查询统一 `keepPreviousData`（cursor 分页友好）
- mutation 全部在成功后 `queryClient.invalidateQueries({ queryKey: identityKeys.xxx() })`
- 角色列表 `staleTime: 5min`（变更频率低）
- `useIdentity()` 是单一身份事实源，`useHasPermission(perm)` 基于其结果

### 3.10 前端管理后台（Admin）

| 路由 | 功能 | 后端契约 |
|---|---|---|
| `/admin` | 仪表盘 | — |
| `/admin/tenants` | 租户列表 + 创建 | `GET/POST /api/admin/tenants` |
| `/admin/tenants/[id]` | 租户详情 + 编辑 + 删除 | `GET/PATCH/DELETE /api/admin/tenants/{id}` |
| `/admin/users` | 用户列表 | `GET /api/tenants/{tid}/users` |
| `/admin/users/[id]` | 用户详情（admin 设密、编辑） | `GET /api/tenants/{tid}/users/{uid}`、`POST /api/auth/set-password` |
| `/admin/workspaces` | workspace 列表 | `GET /api/tenants/{tid}/workspaces` |
| `/admin/workspaces/[id]/members` | workspace 成员管理 | `POST/PATCH/DELETE /api/tenants/{tid}/workspaces/{wid}/members[/{uid}]` |
| `/admin/roles` | 角色 + 权限只读视图 | `GET /api/roles`、`/api/permissions` |
| `/admin/audit` | 审计日志查询 | `GET /api/tenants/{tid}/audit?cursor=...` |
| `/admin/profile` | 个人资料 + 修改密码 + my tokens + my sessions | `PATCH /api/me`、`POST /api/me/password`、`/api/me/tokens`、`/api/me/sessions` |
| `/admin/tokens` | 租户级 API token | `/api/tenants/{tid}/tokens` |
| `/admin/org-keys` | 组织级 API 密钥 | `/api/admin/org-keys` |
| `/admin/models` | 模型列表 | `/api/models` |
| `/admin/skills` | 技能开关 | `/api/skills` |

### 3.11 前端工作台（Workspace）

| 路由 | 功能 |
|---|---|
| `/workspace/chats` | 聊天列表（`POST /api/threads/search` 排序 by `updated_at` desc） |
| `/workspace/chats/[thread_id]` | 主聊天界面（流式消息、artifacts、todos、tool calls） |
| `/workspace/agents` | 自定义 agent 列表 |
| `/workspace/agents/new` | 创建 agent |
| `/workspace/agents/[name]/edit` | 编辑 agent |
| `/workspace/agents/[name]/chats/[thread_id]` | agent 特定聊天 |
| `/workspace/skills` | 技能列表 |

### 3.12 Gateway API 业务路由（非 identity）

| Router | 端点 | 功能 |
|---|---|---|
| `/api/models` | GET/POST/PUT/DELETE | 模型 CRUD |
| `/api/mcp/config` | GET/PUT | MCP 服务器配置（写 extensions_config.json） |
| `/api/skills` | GET/PUT/POST `/install` | 技能列表、启停、安装 |
| `/api/memory` | GET/POST `/reload`、GET `/config`、`/status` | 全局记忆 |
| `/api/threads/{id}/uploads` | POST/GET `/list`/DELETE `/{filename}` | 多文件上传 + PDF/PPT/Excel/Word 自动转 markdown（markitdown） |
| `/api/threads/{id}` | DELETE/POST/PATCH/GET、`/search`、`/state`、`/history` | LangGraph 兼容线程 CRUD（详见 §4.3） |
| `/api/threads/{id}/artifacts/{path}` | GET | artifact 提供（HTML/SVG 强制 download 防 XSS） |
| `/api/agents` | GET/POST/PUT/DELETE | 自定义 agent CRUD（per-agent soul/prompt） |
| `/api/threads/{id}/suggestions` | POST | LLM 生成 follow-up 建议 |
| `/api/channels` | GET/POST | IM 通道状态、重启 |
| `/api/runs` | POST | 无状态运行（stream/wait） |
| `/api/threads/{id}/runs` | POST | LangGraph 兼容运行 stream/cancel |
| `/api/assistants` | — | LangGraph Platform 兼容存根 |

### 3.13 前端 → 后端代理（next.config.js）

[frontend/next.config.js](frontend/next.config.js) 决定前端 API 路径如何映射到后端。三层 rewrite：

1. `/api/langgraph/*` → `http://127.0.0.1:2024`（或 `DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL`）
2. `/api/langgraph-compat/:path*` → `${gateway}/api/:path*`（兼容层）
3. `/api/agents/:path*`、`/api/skills/:path*`、`/api/:path*` catch-all → `${gateway}/api/:path*`（依赖 `DEER_FLOW_INTERNAL_GATEWAY_BASE_URL`）

设置 `NEXT_PUBLIC_BACKEND_BASE_URL` / `NEXT_PUBLIC_LANGGRAPH_BASE_URL` 可禁用 rewrite，让浏览器直连后端（开发场景）。

---

## 4. E2E 流程图

### 4.1 OIDC 登录 + 会话刷新（关键链路）

```
[Browser]                  [Frontend (3110)]              [Nginx (2026)]              [Gateway (8100)]              [IdP]              [Redis]              [Postgres]
   │                              │                              │                              │                       │                    │                         │
   │ GET /login                   │                              │                              │                       │                    │                         │
   ├─────────────────────────────▶│                              │                              │                       │                    │                         │
   │                              │ render LoginPage             │                              │                       │                    │                         │
   │                              │                              │                              │                       │                    │                         │
   │ Click "OIDC: okta"           │                              │                              │                       │                    │                         │
   ├─────────────────────────────▶│                              │                              │                       │                    │                         │
   │ GET /api/auth/oidc/okta/login│                              │                              │                       │                    │                         │
   ├──────────────────────────────┴─────────────────────────────▶│ /api/auth/oidc/okta/login   │                       │                    │                         │
   │                                                             ├─────────────────────────────▶│ generate state+PKCE   │                    │                         │
   │                                                             │                              ├─────────────────────────────────────────────▶ store state, nonce      │
   │                                                             │                              ◀──── 302 redirect to IdP authorize URL ────│                         │
   │ ◀──────────────────── 302 ───────────────────────────────────────────────────────────────────────────────────────────│                  │                         │
   │                                                                                                                       │                  │                         │
   ├──────────────────── login at IdP ───────────────────────────────────────────────────────────────────────────────────▶│                  │                         │
   │ ◀────────── 302 with code+state to /api/auth/oidc/okta/callback ──────────────────────────────────────────────────────│                  │                         │
   │                              │                              │                              │                       │                    │                         │
   │ GET /callback?code=...       │                              │                              │                       │                    │                         │
   ├──────────────────────────────┴─────────────────────────────▶│ /api/auth/oidc/okta/callback│                       │                    │                         │
   │                                                             ├─────────────────────────────▶│ verify state+nonce    │                    │                         │
   │                                                             │                              ├─────────────────────────────────────────────▶ pop state                │
   │                                                             │                              ├──── exchange code for tokens ──────────────▶│                         │
   │                                                             │                              │                       │                    │                         │
   │                                                             │                              ├──── upsert user, resolve tenant ────────────────────────────────────▶│
   │                                                             │                              ├──── create session record ─────────────────▶│ SETEX sid -> sess       │
   │                                                             │                              │                       │                    │                         │
   │ ◀── 302 with Set-Cookie: deerflow_session=<RS256-JWT> ─────│                              │                       │                    │                         │
   │                              │                              │                              │                       │                    │                         │
   │ ----  时间流逝，access token 过期（默认 ~ 30 min）  ----    │                              │                       │                    │                         │
   │                              │                              │                              │                       │                    │                         │
   │ User clicks "Users" page     │                              │                              │                       │                    │                         │
   ├─────────────────────────────▶│                              │                              │                       │                    │                         │
   │                              │ identityApi.listUsers()      │                              │                       │                    │                         │
   │                              │ → identityFetch GET /api/tenants/1/users                    │                       │                    │                         │
   │                              ├─────────────────────────────▶│ ────────────────────────────▶│ verify_access_token   │                    │                         │
   │                              │                              │                              │  → ExpiredError       │                    │                         │
   │                              │ ◀──────────── 401 ──────────────────────────────────────────│                       │                    │                         │
   │                              │                              │                              │                       │                    │                         │
   │                              │ refreshSession() singleflight│                              │                       │                    │                         │
   │                              │ POST /api/auth/refresh       │                              │                       │                    │                         │
   │                              ├─────────────────────────────▶│─────────────────────────────▶│ extract sid           │                    │                         │
   │                              │                              │                              ├─────────────────────────────────────────────▶ GET sid (still valid)   │
   │                              │                              │                              │ issue new access tok  │                    │                         │
   │                              │ ◀── Set-Cookie: deerflow_session=<新JWT> + 200 ────────────│                       │                    │                         │
   │                              │                              │                              │                       │                    │                         │
   │                              │ retry GET /api/tenants/1/users                              │                       │                    │                         │
   │                              │ (with _skipRefreshOn401: true)                              │                       │                    │                         │
   │                              ├─────────────────────────────▶│ ────────────────────────────▶│ verify (now valid)    │                    │                         │
   │                              │ ◀──────────── 200 + user list ──────────────────────────────│                       │                    │                         │
   │                              │                              │                              │                       │                    │                         │
   │ render user list              │                              │                              │                       │                    │                         │
   │ ◀────────────────────────────│                              │                              │                       │                    │                         │
```

**并发 401 处理**：当 5 个 React Query hook 同时发起请求并都拿到 401 时，5 个调用都会 `await refreshSession()`，但 `pendingRefresh` slot 保证只有 1 个 POST `/api/auth/refresh` 真正发出，其他 4 个共享同一 Promise 结果。Refresh 完成 → slot 清空，5 个调用各自重试一次。

**Refresh 失败路径**：refresh 接口返 401（sid 已撤销/过期）→ pendingRefresh resolve 为 `false` → 各调用各自 `emitSessionExpired()`（监听器侧用 `sessionExpiredPending` 标志去重，仅触发一次模态） → 抛 `IdentityFetchError({kind:"unauthenticated"})` → 上层路由跳 `/login`。

### 4.2 用户对话（流式聊天）

```
[Browser]              [Frontend]                   [Nginx]                   [LangGraph (2024) / Gateway runtime]                [Sandbox]
   │                       │                            │                                  │                                          │
   │ Type "帮我写一份白皮书" │                            │                                  │                                          │
   ├──────────────────────▶│                            │                                  │                                          │
   │                       │ useSubmitThread()          │                                  │                                          │
   │                       │   ↓                         │                                  │                                          │
   │                       │ getAPIClient().runs.stream(│                                  │                                          │
   │                       │   thread_id,               │                                  │                                          │
   │                       │   "lead_agent",            │                                  │                                          │
   │                       │   { input: { messages },   │                                  │                                          │
   │                       │     stream_mode: ["values",│                                  │                                          │
   │                       │       "messages-tuple",    │                                  │                                          │
   │                       │       "custom"] }          │                                  │                                          │
   │                       ├────────────────────────────▶│ /api/langgraph/threads/{id}/runs/stream                                    │
   │                       │                            ├─────────────────────────────────▶│ start run                               │
   │                       │                            │                                  │                                          │
   │                       │                            │                                  │ middleware chain (#0-19):              │
   │                       │                            │                                  │   IdentityMiddleware: verify HMAC      │
   │                       │                            │                                  │   ThreadDataMiddleware: mkdir thread   │
   │                       │                            │                                  │   SandboxMiddleware: acquire ─────────▶│ acquire(thread_id, tid, wid)
   │                       │                            │                                  │                                          │
   │                       │                            │                                  │ LLM call (with system prompt)          │
   │                       │                            │                                  │   → tool_calls: [bash, write_file]    │
   │                       │                            │                                  │                                          │
   │                       │                            │                                  │ IdentityGuardrailMiddleware: check perm│
   │                       │                            │                                  │ tools execute ─────────────────────────▶│ execute_command, write_file
   │                       │                            │                                  │                                       ◀─│ outputs
   │                       │                            │                                  │                                          │
   │                       │ ◀── SSE: messages-tuple (delta AI text) ────────────────────│                                          │
   │                       │ ◀── SSE: messages-tuple (delta) ──────────────────────────│                                          │
   │                       │ ◀── SSE: messages-tuple (tool_call: bash) ────────────────│                                          │
   │                       │ ◀── SSE: messages-tuple (tool_result) ────────────────────│                                          │
   │                       │ ◀── SSE: values (artifacts updated) ──────────────────────│                                          │
   │                       │ ◀── SSE: end (with usage) ────────────────────────────────│                                          │
   │                       │                            │                                  │                                          │
   │                       │ TitleMiddleware (after first complete exchange)              │                                          │
   │                       │   → POST /api/threads/{id}/state with {title}                │                                          │
   │                       │ MemoryMiddleware: enqueue (debounced 30s)                    │                                          │
   │                       │                            │                                  │                                          │
   │ render messages,      │                            │                                  │                                          │
   │ artifacts panel,      │                            │                                  │                                          │
   │ tool call cards       │                            │                                  │                                          │
   ◀───────────────────────│                            │                                  │                                          │
```

**关键点**：
- 三种 stream_mode：`values` 全状态快照（artifacts/todos）、`messages-tuple` 增量消息（per-id 拼接）、`custom` 自定义事件
- AI 文本去重：`values` 模式不再重发已通过 `messages-tuple` 投递的文本，避免双交付
- 失败回滚：模型/工具异常 → `LLMErrorHandlingMiddleware` / `ToolErrorHandlingMiddleware` 转化为 ToolMessage 继续运行

### 4.3 线程列表（含懒迁移）

[backend/app/gateway/routers/threads.py](backend/app/gateway/routers/threads.py) `search_threads` 三段式：

1. **Phase 1 — Store 快路径**：`store.asearch(threads_ns, limit=10000)` 拿元数据
2. **Phase 2 — Checkpointer 补全**：迭代 checkpointer 找出未在 Store 的线程（如直接由 LangGraph Server 创建的），写入 Store（懒迁移），下次 search 跳过 Phase 2
3. **Phase 3 — 过滤 + 排序 + 分页**：metadata 过滤 → status 过滤 → 按 `updated_at desc` → offset/limit

**身份隔离**：`_thread_scope_namespace(request)` 在 identity 启用 + 已认证时返回 `("threads", "tenant:{tid}", "workspace:{wid}", "user:{uid}")`，否则回落到 `("threads",)`。当命名空间已隔离时，Phase 2 跳过 checkpointer 扫描（避免跨用户列举）。

`_ensure_scoped_thread_access` 在所有需要单线程操作的 endpoint（state/history/patch/delete）入口先做存在性检查，越权直接 404（不暴露存在性）。

### 4.4 文件上传（含 PDF 转 Markdown）

```
Browser → POST /api/threads/{id}/uploads (multipart)
       → nginx → Gateway uploads.py
       → extract_scope(request) 拿 (tid, wid)
       → 校验路径在 tenant_root 内（assert_within_tenant_root）
       → 拒绝目录输入（all-or-nothing）
       → 落盘到 $DEER_FLOW_HOME/tenants/{tid}/workspaces/{wid}/threads/{id}/user-data/uploads/
       → 检测 PDF/PPT/Excel/Word → markitdown 单 worker 转换为 .md（同 active loop 复用）
       → 200 { "files": [...] }
```

下次 agent 运行时 `UploadsMiddleware` 注入文件清单进系统提示。

### 4.5 IM 通道收发（飞书示例）

```
飞书用户消息
  → 飞书回调 → channels/feishu.py.on_message()
  → MessageBus.publish_inbound(InboundMessage)
  → ChannelManager._dispatch_loop 取出
  → _resolve_channel_identity(name) 从 channel_sessions 拿 (tenant_id, workspace_id)
  → ChannelStore.get_thread_mapping(channel:chat[:topic])
     ├─ 已有 → 复用 thread_id
     └─ 无 → client.threads.create() + ChannelStore.put（持久化 thread_id + tid + wid + uid）
  → command vs chat 路由
  
[chat 路径，飞书]
  → client.runs.stream(thread_id, ["messages-tuple", "values"])
  → 累积 AI text delta，每 N 个增量 publish_outbound(is_final=False, message_id=card_msg_id)
  → 流结束 publish_outbound(is_final=True)
  → channels/feishu.py 将每次 outbound PATCH 同一张 card（config.update_multi=true）

[chat 路径，Slack/Telegram]
  → client.runs.wait()（阻塞至完成）
  → 提取最终 AI 文本
  → publish_outbound(is_final=True)
```

### 4.6 多租户迁移（M7-B 一次性）

```
$ make identity-migrate-dry
  → planner.build_plan(legacy_home, repo_root, tenant_id, workspace_id)
     扫描 {home}/threads/、{repo}/skills/{custom,user}/
     对每项打 ItemKind 标签 + 计算 target（来自 storage/paths.py）
     已存在的 forwarder symlink 标 already_migrated=True
  → write report (atomic temp+fsync+replace+dir fsync)
  → 退出（不写文件系统）

$ make identity-migrate-apply
  → 双锁：fcntl LOCK_EX | LOCK_NB + PG advisory lock(hashtext('deerflow_migration'))
  → 锁失败 → exit 3
  → 对每项 os.rename src → target（EXDEV → shutil.move）
  → 校验 byte-count
  → src 留 forwarder symlink
  → skill symlink 用 assert_symlink_parent_safe 校验目标在 tenant_root 内
  → 每 50 项 fsync report
  → emit system.migration.item.moved 审计事件（critical=True）

$ make identity-migrate-rollback REPORT=<path>
  → 反向遍历 plan
  → 移除 forwarder symlink
  → os.rename target → src
```

---

## 5. 业务规则与不变量

### 5.1 身份与访问控制

| ID | 规则 | 强制点 |
|---|---|---|
| BR-1 | `ENABLE_IDENTITY=false` 时，identity 子系统完全惰性，不连数据库、不注册中间件、auth/me/admin/audit/metrics 路由不挂载 | `app.py::create_app` 条件注册；`tests/identity/test_feature_flag_offline.py` 验证 |
| BR-2 | `IdentityMiddleware` 永远不返 401。任何无效凭证（缺失、伪造、过期、撤销）都解析为 `Identity.anonymous()` | `middlewares/identity.py` |
| BR-3 | `@requires(tag, scope)` 是 401/403 的唯一来源。匿名调 → 401；有身份但权限不足 → 403 with `{detail: {missing}}` | `rbac/decorator.py` |
| BR-4 | SQLAlchemy 自动过滤对所有 `TenantScoped` / `WorkspaceScoped` 模型生效，任何 SELECT 都自动加 `WHERE tenant_id=?` / `WHERE workspace_id IN (...)` | `middlewares/tenant_scope.py::install_auto_filter` |
| BR-5 | 跨租户 INSERT/UPDATE 抛 `PermissionDeniedError`（不是 403，是 500，因为这是程序员错误而非用户操作） | 同上 |
| BR-6 | Refresh token 不出网（仅服务端 Redis），客户端只持有 access token cookie | `auth/jwt.py`、`auth/session.py` |
| BR-7 | 平台管理员（`platform_admin` 角色，`tenant_id=NULL`）绕过自动过滤；维护脚本通过 `with_platform_privilege()` 显式 opt-out 并打 INFO 日志 | `context.py::with_platform_privilege` |
| BR-8 | LangGraph 身份传播仅在 `DEERFLOW_INTERNAL_SIGNING_KEY` 设置时启用。HMAC 重放窗口默认 300s，超出抛错让 run 失败响亮 | `propagation.py` + `agents/middlewares/identity_middleware.py` |
| BR-9 | Subagent 继承父 agent 的 `state["identity"]`，子 agent IdentityMiddleware 检测到非空 state 不覆写。权限集冻结，无提权面 | `subagents/executor.py` |
| BR-10 | 工具 RBAC 默认拒绝（白名单）。未登记的工具一律 deny，MCP 工具未声明 `required_permission` 则要求 `skill:invoke` | `IdentityGuardrailMiddleware` + `TOOL_PERMISSION_MAP` |

### 5.2 多租户存储

| ID | 规则 | 强制点 |
|---|---|---|
| BR-11 | 物理路径全部位于 `$DEER_FLOW_HOME/tenants/{tid}/`，跨租户路径在 `assert_within_tenant_root` 抛 `PathEscapeError` | `storage/path_guard.py` |
| BR-12 | Skill 加载顺序 public → tenant custom → workspace user，later wins | `skills/loader` + `M4 retrofit` |
| BR-13 | 租户/workspace 配置覆盖只能 disable 全局已 enable 的技能，不能 re-enable 全局禁用的（`disable-only` 语义） | `storage/config_layers.py` |
| BR-14 | `SENSITIVE_GLOBAL_ONLY` 字段（`models[*].api_key`、`models[*].endpoint`、`models[*].base_url`、`sandbox.provisioner.{api_key,endpoint}`、`memory.storage_path`）不可被租户/workspace 覆盖，违反抛 `SensitiveFieldViolation` | 同上 |
| BR-15 | 路径越权访问（artifacts/uploads/threads.delete）一律返 `403 "Access denied"`，不暴露 tenant_id 或 file path | `routers/artifacts.py`、`uploads.py`、`threads.py` |
| BR-16 | 租户目录创建权限位 0700，由 `make identity-dirs` 幂等创建 | `storage/cli.py` |

### 5.3 审计

| ID | 规则 | 强制点 |
|---|---|---|
| BR-17 | `audit_logs` 对 `deerflow` 应用角色仅授予 INSERT/SELECT，UPDATE/DELETE 被 REVOKE。仅 `deerflow_retention` 角色有 DELETE | alembic 0003 |
| BR-18 | 写操作（POST/PUT/PATCH/DELETE）100% 审计；读操作仅在 `/api/auth/*`、`/api/audit*`、`/api/admin/*`、`/api/tenants/*` 或 401/403 时审计 | `audit/middleware.py` |
| BR-19 | Critical action（登录失败、authz 拒绝、所有 HTTP 写）队列满时同步插入；非 critical 队列满时丢弃并 `metrics["dropped"]++` | `audit/writer.py` |
| BR-20 | PG 故障时 critical event 写 `$DEER_FLOW_HOME/_audit/fallback.jsonl`，非 critical 丢弃。下次成功 flush 时 backfill | `audit/fallback.py` + `audit/writer.py::_flush_loop` |
| BR-21 | 元数据自动脱敏：键名匹配 `/password\|token\|secret\|key\|authorization/i` 的值 → `***`；命令截断 500 字符；`write_file` 仅留 path+size 丢 content | `audit/redact.py` |
| BR-22 | 默认查询窗口 7 天，最大 90 天；CSV 导出硬上限 100k 行，超额返 413 | `audit/api.py` |
| BR-23 | 保留任务每日跑，按 `(tenant_id, year_month)` 分组归档 >90 天到 `.gz`，同事务删除（幂等） | `audit/retention.py` |

### 5.4 Agent 运行时

| ID | 规则 | 强制点 |
|---|---|---|
| BR-24 | 中间件链顺序严格固定，#0 是 Identity（如启用），#19 是 Clarification（必须最后） | `_build_middlewares` 文档化顺序 |
| BR-25 | 子智能体并发 ≤3，由 `SubagentLimitMiddleware` 在 `after_model` 截断超额 task 调用 | 同名中间件 |
| BR-26 | 子智能体超时 15 分钟 | `SubagentExecutor` |
| BR-27 | LoopDetectionMiddleware hard-stop 时同时清空 `tool_calls` 和 `additional_kwargs.tool_calls`（避免孤儿 ToolMessage 导致 LLM 400） | `LoopDetectionMiddleware` |
| BR-28 | Standard 模式下记忆 updater 与 subagent executor 仍把 LLM 调用丢给临时 `asyncio.run` loop，`langchain_openai` cached httpx client 跨 loop 会触发 `Event loop is closed`。生产应优先 Gateway 模式 | `deerflow.runtime.main_loop.set_main_loop` + `submit_to_main_loop` |
| BR-29 | str_replace 同路径串行化作用域为 `(sandbox.id, path)`，独立沙箱不互相阻塞 | `sandbox/tools.py::str_replace` |
| BR-30 | `present_files` 工具仅允许 `/mnt/user-data/outputs` 下的文件 | `tools/builtins/present_files` |

### 5.5 前端 Identity

| ID | 规则 | 强制点 |
|---|---|---|
| BR-31 | `identityFetch` 是 identity 域所有 fetch 的唯一入口，所有 `identityApi.*` 函数必须经过它 | `core/identity/api.ts` |
| BR-32 | 401 → singleflight refresh：`pendingRefresh` 槽存活期间所有 401 共享同一 Promise；refresh 成功重试一次（且 `_skipRefreshOn401: true` 防递归）；失败 → 触发 `emitSessionExpired` + 抛 unauthenticated | `fetcher.ts:41-128` |
| BR-33 | `_skipRefreshOn401` 是内部 RequestInit 扩展，外部不可设置；refresh 调用本身和 retry 都标记此字段，401 直接 surfaced | 同上 |
| BR-34 | `emitSessionExpired` 通过 `sessionExpiredPending` 标志去重，多次 401 只触发一次模态 | `fetcher.ts:32-36` |
| BR-35 | 403 解析 `detail.missing`，抛 forbidden 错误供 UI 显示具体缺失权限 | `fetcher.ts:108-117` |
| BR-36 | `qs()` 序列化只接受 string/number/boolean，对象会被丢弃（防止 `[object Object]` 静默污染 query string） | `api.ts:43-55` |
| BR-37 | 所有 mutation hook 在成功后 `invalidateQueries(identityKeys.xxx())` | `hooks.ts` 全文 |
| BR-38 | `identityApi.refresh()` 委托给同一 singleflight，不创造第二条并发路径 | `api.ts:63-73` |
| BR-39 | LangGraph SDK 路径（`/api/langgraph/*`）当前不走 identityFetch 拦截器，401 时由调用方自行处理（已知容忍点） | next.config.js + `core/api/` |

### 5.6 配置与运维

| ID | 规则 | 强制点 |
|---|---|---|
| BR-40 | `config.yaml` 优先级：`config_path` 参数 > `DEER_FLOW_CONFIG_PATH` 环境变量 > backend/ 当前目录 > 项目根目录（**推荐**） | `deerflow.config.app_config::get_app_config` |
| BR-41 | `config.yaml` 自动重载：mtime 变化即重新解析（无需重启进程） | 同上 |
| BR-42 | `config.yaml` 中以 `$` 开头的值解析为环境变量（如 `$OPENAI_API_KEY`） | 同上 |
| BR-43 | `config_version` 不匹配时 `make config-upgrade` 自动合并新字段 | `scripts/config-upgrade.sh` |
| BR-44 | `extensions_config.json` 优先级与 `config.yaml` 同型，可由 `PUT /api/mcp/config` 运行时写入 | `routers/mcp.py` |
| BR-45 | nginx 中 `/api/langgraph/*` 路由在 Gateway 模式下通过 `LANGGRAPH_UPSTREAM`/`LANGGRAPH_REWRITE` envsubst 改写为 `gateway:8001`，仍走 `/api/langgraph/...` 后由 Gateway 嵌入运行时处理 | `docker/nginx/nginx.conf` |
| BR-46 | bootstrap 顺序：`bootstrap_with_advisory_lock` 锁住 → 在独立连接持锁 → 在另一连接执行 idempotent seed → 释放。锁获取失败降级到 pre-M7 路径并打 WARN | `app/gateway/identity/bootstrap_lock.py` |
| BR-47 | Prometheus `/metrics` 端点不需认证（网络层 gating），仅 `ENABLE_IDENTITY=true` 时挂载 | `routers/metrics.py` |

---

## 6. 测试点矩阵

### 6.1 后端测试（[backend/tests/](backend/tests/)）

| 测试文件 | 覆盖模块 | 关键断言 |
|---|---|---|
| test_harness_boundary.py | harness/app 边界 | `packages/harness/deerflow/` 不能 `import app.*` |
| test_memory_updater.py | memory/updater | LLM 提取、事实去重（含 whitespace normalize）、原子文件 I/O |
| test_channels.py | channels/* | inbound/outbound 消息流、命令路由 |
| test_artifacts_router.py | routers/artifacts | HTML/SVG 强制下载、跨租户 403 |
| test_agents_router.py | routers/agents | CRUD、soul prompt 同步 |
| test_aio_sandbox*.py | community/aio_sandbox | Docker 沙箱执行 |
| test_threads_router.py | routers/threads | （本次修改）租户分层命名空间、Phase 1+2 search、删除越权 |
| test_docker_sandbox_mode_detection.py | docker/provisioner | 沙箱模式检测 |
| test_provisioner_kubeconfig.py | provisioner | kubeconfig 文件/目录处理 |
| test_client.py / test_client_live.py | DeerFlowClient | 嵌入式入口 + Gateway 响应同形（`TestGatewayConformance`） |
| **identity/** test_feature_flag_offline.py | settings.py | 标志关闭时所有 identity 路由 404 |
| **identity/** test_gateway_identity_lifespan.py | app.py lifespan | 启用/禁用时的初始化路径 |
| **identity/** test_jwt.py | auth/jwt.py | RS256 签发、过期、签名验证、密钥对生成 |
| **identity/** test_oidc.py | auth/oidc.py | PKCE+state+nonce、callback 校验、Redis 防重放 |
| **identity/** test_sessions.py | auth/session.py | refresh、revoke、count_active |
| **identity/** test_lockout.py | auth/lockout.py | IP+email 锁定窗口、解锁 |
| **identity/** test_rbac_decorator.py | rbac/decorator.py | 401/403 决策、scope 提取 |
| **identity/** test_tenant_scope.py | middlewares/tenant_scope.py | SELECT 自动过滤、跨租户 INSERT 拒绝、平台管理员绕过 |
| **identity/** test_audit_writer.py | audit/writer.py | 队列容量、critical 同步、PG 故障 fallback |
| **identity/** test_audit_redact.py | audit/redact.py | 密码/token 脱敏、命令截断、`write_file` 特殊处理 |
| **identity/** test_audit_retention.py | audit/retention.py | 归档 + 同事务删除幂等 |
| **identity/** test_migration_*.py | migration/* | planner/executor/rollback、双锁、symlink 安全 |

### 6.2 前端单测（[frontend/tests/unit/](frontend/tests/unit/)）

| 测试文件 | 覆盖模块 | 关键断言 |
|---|---|---|
| **identity/** fetcher.test.ts | core/identity/fetcher.ts | 401 → refresh → retry；refresh 失败 → emitSessionExpired；403 → missing；singleflight 并发只发 1 个 refresh；`_skipRefreshOn401` 防递归 |
| **identity/** hooks.test.tsx | core/identity/hooks.ts | useIdentity、useHasPermission、各 mutation invalidateQueries |
| **identity/** RequirePermission.test.tsx | components | 权限存在 → render；缺失 → fallback |
| **identity/** SessionExpiredModal.test.tsx | components | onSessionExpired 触发 → 显示模态 |
| **identity/** admin-hooks.test.ts | hooks.ts admin 部分 | tenants/users/workspaces CRUD 后 invalidate |
| **admin-profile-page.test.tsx** | app/(admin)/admin/profile | （本次新增）profile 表单、tokens 列表、sessions 列表交互 |
| **admin-roles-page.test.tsx** | app/(admin)/admin/roles | （本次新增）角色 + 权限表 render |
| **admin-user-detail-page.test.tsx** | app/(admin)/admin/users/[id] | （本次新增）用户详情、admin 设密对话 |
| core/api/stream-mode.test.ts | core/api | LangGraph stream_mode 控制 |
| core/artifacts/* | core/artifacts | 缓存失效规则（消息驱动 vs 事件驱动） |
| core/agents/* | core/agents | tri-state 状态机 |
| core/skills/* | core/skills | thread 技能 API |
| core/messages/* | core/messages | token usage、tool call 解析 |
| core/threads/* | core/threads | agent 名称上下文、export 工具 |
| core/uploads/* | core/uploads | 文件验证、prompt input 处理 |
| core/streamdown/* | core/streamdown | markdown 插件 |

### 6.3 前端 E2E（[frontend/tests/e2e/](frontend/tests/e2e/)，Playwright/Chromium）

baseURL `http://localhost:3110`，所有后端 API 通过 `page.route()` mock。

| Spec | 流程 | 关键断言 |
|---|---|---|
| identity/A1-login.spec.ts | OIDC 登录 | 登录后 `/api/me` 返回身份；cookie 设置 |
| identity/A1-session-expired.spec.ts | 会话过期 | 401 → refresh 失败 → 弹 SessionExpiredModal → 跳 /login |
| identity/A2-tenants-users.spec.ts | 租户/用户列表 | offset 分页、搜索 |
| identity/A2-admin-layout.spec.ts | admin 侧导 | 权限驱动菜单显隐 |
| identity/A2-workspaces-audit.spec.ts | workspace + 审计 | cursor 分页、CSV 导出 |
| identity/A3-tenant-workspace.spec.ts | 租户/workspace CRUD | 创建/编辑/删除 → 列表立刻刷新 |
| identity/A3-write-actions.spec.ts | 成员操作 | 添加成员、改角色、移除 |
| identity/A4-rbac-matrix.spec.ts | RBAC 权限矩阵 | 不同角色看到的页面差异 |
| identity/A4-profile-and-audit.spec.ts | 个人资料 + tokens + sessions | 修改资料、创建 token（仅一次明文）、撤销 session |
| chat.spec.ts | 主聊天流 | 消息流式渲染、tool call 卡片 |
| agent-chat.spec.ts | 自定义 agent 聊天 | agent 名称上下文 |
| thread-history.spec.ts | 线程历史 | 列表、checkpoint 切换 |
| sidebar.spec.ts | 侧边栏交互 | 折叠/展开、链接跳转 |
| landing.spec.ts | 首页导航 | 各 section 渲染 |

### 6.4 CI 流水线（[.github/workflows/](.github/workflows/)）

| 工作流 | 触发 | 内容 |
|---|---|---|
| backend-unit-tests.yml | PR | pytest（含 `test_harness_boundary`、`test_docker_sandbox_mode_detection`、`test_provisioner_kubeconfig`） |
| frontend-unit-tests.yml | PR | vitest |
| e2e-tests.yml | PR | Playwright |
| identity-e2e-smoke.yml | PR | 绕过 OIDC，直接为 bootstrap admin 签 RS256 JWT，跑 identity E2E |
| lint-check.yml | PR | ruff + ESLint |

---

## 7. 系统配置与部署

### 7.1 文件清单

| 文件 | 用途 | 是否必需 |
|---|---|---|
| `config.yaml` | 主配置：models、tools、sandbox、skills、memory、summarization、checkpointer | ✅ 必需 |
| `config.example.yaml` | 模板（含 Ollama/Claude/Gemini/DeepSeek/Novita 等示例） | 模板 |
| `extensions_config.json` | MCP servers + skills 启停 | ✅ 必需（可空） |
| `extensions_config.example.json` | 模板（filesystem/github/postgres MCP 示例） | 模板 |
| `config/identity.yaml.example` | OIDC providers（okta/azure-ad/keycloak）模板 | 模板（仅 identity 启用时用） |
| `mise.toml` | 工具版本：python 3.12、node 22、uv latest、pnpm 10.26.2 | ✅ 必需 |
| `Makefile` | 根目标（setup/dev/start/up/...）| ✅ 必需 |
| `docker-compose.yaml` | 7 个服务（nginx/frontend/gateway/langgraph/provisioner/postgres/redis） | 部署用 |
| `docker/nginx/nginx.conf` | 反代规则（详见 §7.4） | 部署用 |
| `backend/pyproject.toml` | Python 依赖 | ✅ 必需 |
| `backend/alembic.ini` + `backend/alembic/versions/` | 数据库迁移 | identity 启用时必需 |
| `frontend/package.json` | Node 依赖 | ✅ 必需 |
| `frontend/next.config.js` | API rewrite、locale 配置 | ✅ 必需 |
| `frontend/.env.example` | 环境变量模板 | 模板 |
| `.github/workflows/*.yml` | CI 5 个工作流 | CI 用 |

### 7.2 当前 `config.yaml` 关键值（实测）

| Key | 值 |
|---|---|
| config_version | 8 |
| log_level | info |
| token_usage.enabled | false |
| **models** | qwen3.6-plus（DashScope，165536 max_tokens，supports_thinking=true）<br>minimax-m2.7（MiniMax，184096 max_tokens，supports_vision=true，supports_thinking=true）<br>kimi-k2.5（Moonshot via PatchedChatDeepSeek，32768 max_tokens，supports_vision=true） |
| tool_groups | web、file:read、file:write、bash |
| tools | web_search(DuckDuckGo)、web_fetch(Jina)、image_search(DuckDuckGo)、ls、read_file、write_file、str_replace、bash |
| sandbox.use | LocalSandboxProvider（allow_host_bash=false） |
| skills.container_path | /mnt/skills |
| title.enabled | true（max_words=6, max_chars=60） |
| summarization | enabled=true，trigger tokens=15564，keep=10 messages |
| memory | enabled=true，storage_path=memory.json，debounce=30s，max_facts=100 |
| checkpointer.type | sqlite（connection_string=checkpoints.db） |

### 7.3 关键环境变量

#### 后端

| 变量 | 默认 | 用途 |
|---|---|---|
| `ENABLE_IDENTITY` | false | identity 子系统主开关 |
| `DEERFLOW_DATABASE_URL` | — | PostgreSQL（asyncpg）连接串 |
| `DEERFLOW_REDIS_URL` | — | Redis URL |
| `DEERFLOW_BOOTSTRAP_ADMIN_EMAIL` | — | 首次启动 seed 的平台管理员邮箱 |
| `DEER_FLOW_HOME` | `backend/.deer-flow` | 数据根目录（threads、tenants、_system、_audit） |
| `DEERFLOW_JWT_PRIVATE_KEY_PATH` | `$DEER_FLOW_HOME/_system/jwt_private.pem` | RS256 私钥（0600） |
| `DEERFLOW_JWT_PUBLIC_KEY_PATH` | `$DEER_FLOW_HOME/_system/jwt_public.pem` | RS256 公钥（0644） |
| `DEERFLOW_INTERNAL_SIGNING_KEY` | — | LangGraph 身份传播 HMAC 密钥（独立于 ENABLE_IDENTITY） |
| `DEERFLOW_HMAC_SKEW_SEC` | 300 | HMAC 重放窗口 |
| `DEERFLOW_ACCESS_TOKEN_TTL_SEC` | — | access token 寿命 |
| `DEERFLOW_REFRESH_TOKEN_TTL_SEC` | — | refresh token 寿命 |
| `DEERFLOW_COOKIE_*` | — | cookie 配置（Secure、SameSite、Domain） |
| `DEERFLOW_LOGIN_LOCKOUT_*` | — | 登录锁定（max_attempts、window、block） |
| `DEERFLOW_BCRYPT_COST` | — | 密码哈希 cost factor |
| `DEERFLOW_IDENTITY_CONFIG` | `config/identity.yaml` | OIDC providers 配置文件路径 |
| `IDENTITY_AUTO_PROVISION_TENANT` | — | 首次登录自动建租户 |
| `DEER_FLOW_CONFIG_PATH` | — | 显式 `config.yaml` 路径（优先级最高） |
| `DEER_FLOW_EXTENSIONS_CONFIG_PATH` | — | 显式 `extensions_config.json` 路径 |
| `DEER_FLOW_CHANNELS_LANGGRAPH_URL` / `DEER_FLOW_CHANNELS_GATEWAY_URL` | — | Docker 部署中 IM channel 内部 URL |
| `GATEWAY_HOST` / `GATEWAY_PORT` / `CORS_ORIGINS` | 0.0.0.0 / 8100 / — | Gateway 监听 |

#### 前端

| 变量 | 用途 |
|---|---|
| `NEXT_PUBLIC_BACKEND_BASE_URL` | 设置后浏览器直连 Gateway，绕过 nginx rewrite |
| `NEXT_PUBLIC_LANGGRAPH_BASE_URL` | 同上，针对 LangGraph |
| `DEER_FLOW_INTERNAL_GATEWAY_BASE_URL` | Next 服务器侧 rewrite 目标（默认 127.0.0.1:8100，Docker dev 用 gateway:8001） |
| `DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL` | 同上，LangGraph |
| `BETTER_AUTH_SECRET` | better-auth 加密密钥（已配置未启用） |

### 7.4 Nginx 路由（[docker/nginx/nginx.conf](docker/nginx/nginx.conf)）

```
/api/langgraph/*          → langgraph:2024（envsubst LANGGRAPH_UPSTREAM/LANGGRAPH_REWRITE 可改为 gateway:8001）
/api/models               → gateway:8001
/api/memory               → gateway:8001
/api/mcp                  → gateway:8001
/api/skills               → gateway:8001
/api/agents               → gateway:8001
/api/threads/*/uploads    → gateway:8001（client_max_body_size 100M）
/api/threads*             → gateway:8001
/docs, /redoc             → gateway:8001
/openapi.json, /health    → gateway:8001
/api/sandboxes            → provisioner:8002
/                         → frontend:3000
```

**CORS**：在 nginx 层面给所有响应统一加 `Access-Control-Allow-Origin: *`。

### 7.5 启动模式矩阵

| | 本地前台 | 本地守护 | Docker Dev | Docker Prod |
|---|---|---|---|---|
| Dev | `make dev` | `make dev-daemon` | `make docker-start` | — |
| Dev + Gateway | `make dev-pro` | `make dev-daemon-pro` | `make docker-start-pro` | — |
| Prod | `make start` | `make start-daemon` | — | `make up` |
| Prod + Gateway | `make start-pro` | `make start-daemon-pro` | — | `make up-pro` |

停止：`make stop` / `make docker-stop` / `make down`。

### 7.6 数据库 ops

```bash
make db-upgrade           # alembic upgrade head
make db-downgrade-one     # alembic downgrade -1
make identity-bootstrap   # 手动跑 seed
make identity-keys        # 生成（或复用）RS256 keypair
make identity-dirs TENANT_ID=<id> [WORKSPACE_ID=<id>]   # 创建租户目录树（0700）
make identity-test        # 跑 identity test 套件（需 PG+Redis）
make identity-migrate-{dry,apply,rollback}              # 多租户一次性迁移
```

---

## 8. 验收清单

### 8.1 功能验收

#### 身份子系统（M1-M7）

- [ ] `ENABLE_IDENTITY=false` 时所有 identity 路由 404，应用照常工作
- [ ] `ENABLE_IDENTITY=true` 时 lifespan 正常完成 bootstrap，admin 邮箱已 seed
- [ ] OIDC 登录全流程（authorize → IdP → callback → cookie）通畅
- [ ] access token 过期后调任意 admin 接口能自动 refresh + 重试
- [ ] refresh 失败时弹 SessionExpiredModal 并跳 /login
- [ ] 跨租户 GET artifact 返 403 不暴露路径
- [ ] 跨租户 INSERT 抛 PermissionDeniedError
- [ ] 平台管理员能跨租户列出资源
- [ ] 工具调用未授权时被 IdentityGuardrailMiddleware 拦截，返回 ToolMessage 错误
- [ ] LangGraph 运行时 HMAC 头校验失败时 run 失败响亮（不静默降级）
- [ ] 子智能体继承父身份，权限不可放大
- [ ] `/api/tenants/{tid}/audit` 默认 7 天，最大 90 天
- [ ] CSV 导出 100k 行返 413
- [ ] PG 离线时 critical event 落 fallback.jsonl，恢复后 backfill 进 audit_logs
- [ ] `/metrics` 输出 Prometheus 格式，含 5 个核心指标

#### Agent + 工具

- [ ] `make dev` 启动 4 进程，`http://localhost:2026/health` 返回 ok
- [ ] 在工作台发起对话，流式消息正常返回，artifacts 实时更新
- [ ] PDF/Excel/PPT/Word 上传后自动转 markdown，agent 可见
- [ ] 子智能体并发 ≤3，超时 15min 触发 `task_timed_out`
- [ ] 飞书/Slack/Telegram 消息能创建/复用线程，租户 id 持久化到 channel_sessions
- [ ] 记忆系统在 30s 防抖后异步更新 memory.json，下轮注入到提示

#### 前端验收

- [ ] 登录页面 OIDC 按钮按 `config/identity.yaml` 配置渲染
- [ ] /admin/* 各页面在不同 RBAC 角色下展示正确（A4 矩阵）
- [ ] /admin/profile 修改资料、改密码、创建 token（明文一次）、撤销 session 全部可用
- [ ] /admin/audit cursor 分页、CSV 导出
- [ ] /workspace/chats 列表按 `updated_at desc`
- [ ] 浏览器 DevTools 可观察到：401 → POST /api/auth/refresh → 重发原请求
- [ ] 5 个并发 401 仅触发 1 次 refresh 调用

### 8.2 工程验收

- [ ] `make check` 通过（系统依赖完整）
- [ ] `make install` 通过（前后端依赖装齐）
- [ ] `make test`（backend）通过
- [ ] `make lint`（backend ruff）通过
- [ ] `pnpm check`（frontend lint+typecheck）通过
- [ ] `pnpm test`（frontend vitest）通过
- [ ] `pnpm test:e2e`（Playwright）通过
- [ ] 5 个 GitHub Actions 工作流全绿
- [ ] `pnpm build` 出包成功

### 8.3 部署验收

- [ ] `make up`（Docker prod）启动 7 个容器，2026 端口对外可达
- [ ] PostgreSQL 迁移到 head（`alembic current` 显示最新版本）
- [ ] `audit_logs` 表上 `deerflow` 角色仅有 INSERT/SELECT
- [ ] `make identity-migrate-dry` 输出 plan + report，不写文件系统
- [ ] `make identity-migrate-apply` 锁正常，迁移完成留 forwarder symlink
- [ ] `make identity-migrate-rollback` 反向回滚成功
- [ ] Prometheus 抓取 `:8100/metrics`，告警规则按 [docs/identity-alerting.md](docs/identity-alerting.md) 配置
- [ ] 按 [docs/identity-release-checklist.md](docs/identity-release-checklist.md) 完成 1000-thread 演练 + 回滚演练

### 8.4 已知约束（不在本验收范围）

- Standard 模式下 LLM `Event loop is closed` 已知问题（生产请用 Gateway 模式）
- 豆包模型 tool denial 后下一轮 `user name must be consistent` 错误（与本验收解耦）
- LangGraph SDK 直连路径（`/api/langgraph/*`）不走 identityFetch 401 拦截器，由 SDK 错误处理负责
- `app/api/auth/[...all]` 是 better-auth 转发器，已配置但未在生产路由启用（保留以备后续扩展）
- M7-A 管理后台 UI 部分页面仍在迭代（旧 admin_stub 路由的真实实现）

---

## 附录 A：关键源码索引

### 后端

- 应用入口与生命周期：[backend/app/gateway/app.py](backend/app/gateway/app.py)（`create_app` L356, `lifespan` L291）
- Identity 设置：[backend/app/gateway/identity/settings.py](backend/app/gateway/identity/settings.py)
- JWT：[backend/app/gateway/identity/auth/jwt.py](backend/app/gateway/identity/auth/jwt.py)
- OIDC：[backend/app/gateway/identity/auth/oidc.py](backend/app/gateway/identity/auth/oidc.py)
- Identity 中间件：[backend/app/gateway/identity/middlewares/identity.py](backend/app/gateway/identity/middlewares/identity.py)
- 租户自动过滤：[backend/app/gateway/identity/middlewares/tenant_scope.py](backend/app/gateway/identity/middlewares/tenant_scope.py)
- RBAC 装饰器：[backend/app/gateway/identity/rbac/decorator.py](backend/app/gateway/identity/rbac/decorator.py)
- Auth 路由：[backend/app/gateway/identity/routers/auth.py](backend/app/gateway/identity/routers/auth.py)
- Me 路由：[backend/app/gateway/identity/routers/me.py](backend/app/gateway/identity/routers/me.py)
- 审计 writer：[backend/app/gateway/identity/audit/writer.py](backend/app/gateway/identity/audit/writer.py)
- 审计中间件：[backend/app/gateway/identity/audit/middleware.py](backend/app/gateway/identity/audit/middleware.py)
- 审计 API：[backend/app/gateway/identity/audit/api.py](backend/app/gateway/identity/audit/api.py)
- 存储路径：[backend/app/gateway/identity/storage/paths.py](backend/app/gateway/identity/storage/paths.py)
- 路径护栏：[backend/app/gateway/identity/storage/path_guard.py](backend/app/gateway/identity/storage/path_guard.py)
- HMAC 传播：[backend/app/gateway/identity/propagation.py](backend/app/gateway/identity/propagation.py)
- 业务路由：[backend/app/gateway/routers/](backend/app/gateway/routers/)（threads/uploads/artifacts/agents/skills/models/memory/mcp/channels/runs/suggestions）
- Lead Agent：[backend/packages/harness/deerflow/agents/lead_agent/agent.py](backend/packages/harness/deerflow/agents/lead_agent/agent.py)
- 中间件链构建器：[backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py](backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py)（`build_lead_runtime_middlewares`）
- ThreadState：[backend/packages/harness/deerflow/agents/thread_state.py](backend/packages/harness/deerflow/agents/thread_state.py)
- 沙箱抽象：[backend/packages/harness/deerflow/sandbox/sandbox.py](backend/packages/harness/deerflow/sandbox/sandbox.py)
- 沙箱工具：[backend/packages/harness/deerflow/sandbox/tools.py](backend/packages/harness/deerflow/sandbox/tools.py)
- Subagent 执行器：[backend/packages/harness/deerflow/subagents/executor.py](backend/packages/harness/deerflow/subagents/executor.py)
- IM 通道管理器：[backend/app/channels/manager.py](backend/app/channels/manager.py)

### 前端

- 401 拦截器：[frontend/src/core/identity/fetcher.ts](frontend/src/core/identity/fetcher.ts)
- Identity API：[frontend/src/core/identity/api.ts](frontend/src/core/identity/api.ts)
- Identity Hooks：[frontend/src/core/identity/hooks.ts](frontend/src/core/identity/hooks.ts)
- Identity Types：[frontend/src/core/identity/types.ts](frontend/src/core/identity/types.ts)
- Query Keys：[frontend/src/core/identity/query-keys.ts](frontend/src/core/identity/query-keys.ts)
- Zod Schemas：[frontend/src/core/identity/schemas.ts](frontend/src/core/identity/schemas.ts)
- API Rewrite：[frontend/next.config.js](frontend/next.config.js)
- LangGraph SDK 客户端：[frontend/src/core/api/](frontend/src/core/api/)
- 线程 hooks：[frontend/src/core/threads/hooks.ts](frontend/src/core/threads/hooks.ts)
- Admin 页面：[frontend/src/app/(admin)/admin/](frontend/src/app/(admin)/admin/)
- Workspace 页面：[frontend/src/app/workspace/](frontend/src/app/workspace/)

### 配置与运维

- 主配置：[config.yaml](config.yaml)
- MCP/Skills 配置：[extensions_config.json](extensions_config.json)
- OIDC 模板：[config/identity.yaml.example](config/identity.yaml.example)
- Docker Compose：[docker-compose.yaml](docker-compose.yaml)
- Nginx：[docker/nginx/nginx.conf](docker/nginx/nginx.conf)
- Provisioner：[docker/provisioner/](docker/provisioner/)
- 工具版本：[mise.toml](mise.toml)
- 根 Makefile：[Makefile](Makefile)
- 后端 Makefile：[backend/Makefile](backend/Makefile)
- Alembic：[backend/alembic/](backend/alembic/)
- Python 依赖：[backend/pyproject.toml](backend/pyproject.toml)
- Node 依赖：[frontend/package.json](frontend/package.json)
- CI 工作流：[.github/workflows/](.github/workflows/)

---

**白皮书完。**
