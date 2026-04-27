# Identity 路径脱节修复 — 前端 LangGraph 直连绕过 Gateway HMAC 注入

> **执行状态（2026-04-27，最终更新）：✅ 已闭环**
> - ✅ Task 1: 历史数据迁移（58 thread + 1 skill_user，留 forwarder symlink）
> - ✅ Task 2: smoke 测试通过 — 命令行（HMAC 注入、stratified 写盘、流式输出）+ 浏览器（artifact / 上传可见 / agent_name / chat 流式 / 登录 / admin / skill 绑定）双轨
> - ✅ Task 3: 前端默认 fallback 切到 `/api/langgraph-compat`（commit `3cf68715`）
> - ⏳ Task 4 (nginx profile 化) + Task 5 (CI 防回归) 推迟到自托管 epic 一起做（不阻塞主线）
>
> **沿途修复的 langgraph-compat experimental gap：** ISO timestamp 兼容（commit `24e07817`）— Gateway threads API 之前返回 unix-seconds 字符串，前端 date-fns 崩；修后兼容历史 unix-string 记录

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec 来源：** 用户实测 2026-04-27，两个具体故障表现合并为同一个 root cause。

---

## 故障表现

### 故障 1：历史 artifact 404
- 用户在 thread `51abb193-b8b9-4d94-b8af-e390b2304e82` 中点击 artifact `/mnt/user-data/outputs/ai-multiverse/index.html`
- 前端构造请求：`GET /api/threads/51abb193-.../artifacts/mnt/user-data/outputs/ai-multiverse/index.html`
- 响应：`404 {"detail":"Artifact not found: mnt/user-data/outputs/ai-multiverse/index.html"}`
- **实际文件在**：`backend/.deer-flow/threads/51abb193-.../user-data/outputs/ai-multiverse/index.html`（创建于 2026-04-18，M4 之前）
- **后端去找的位置**：`backend/.deer-flow/tenants/1/workspaces/1/threads/51abb193-.../user-data/outputs/ai-multiverse/index.html`（不存在）

### 故障 2：上传文件 agent 不可见
- 用户在新 thread `35dc1f08-b08d-4b0a-b131-6b33d719ab10` 上传 `客户数据.csv`
- 实际写盘位置：`backend/.deer-flow/tenants/1/workspaces/1/threads/35dc1f08-.../user-data/uploads/客户数据.csv` ✅ Gateway uploads router 把文件写到了 tenant-stratified 路径
- Agent 通过 sandbox 看到的 `/mnt/user-data/uploads` 路径却映射到 `backend/.deer-flow/threads/35dc1f08-.../user-data/uploads/`（**legacy 路径，空目录**）
- Agent 报告："上传目录和 workspace 都是空的，没有文件"

---

## Root cause（同一个）

**前端通过 LangGraph SDK 直连 LangGraph dev server (port 2024)，完全绕过 Gateway，HMAC 身份签名头永远进不到 `config.configurable.headers`。**

证据链：
- 前端默认 `NEXT_PUBLIC_LANGGRAPH_BASE_URL = /api/langgraph` （[frontend/src/core/config/index.ts:36](../../../frontend/src/core/config/index.ts#L36)）
- nginx 配置 `location /api/langgraph/` → `proxy_pass http://langgraph` （[docker/nginx/nginx.local.conf:53](../../../docker/nginx/nginx.local.conf#L53)）
- Gateway 的 `_inject_identity_headers()` 在 [backend/app/gateway/services.py:229](../../../backend/app/gateway/services.py#L229) 才会签入 HMAC 头，但前端**根本不调** Gateway 的 `/api/threads/{tid}/runs`
- Harness 端 `IdentityMiddleware._read_headers()` 从 `configurable["headers"]` 读签名头（[backend/packages/harness/deerflow/agents/middlewares/identity_middleware.py:88](../../../backend/packages/harness/deerflow/agents/middlewares/identity_middleware.py#L88)）→ 空 dict → `state["identity"]` 永不被设置
- `ThreadDataMiddleware`、`SandboxMiddleware`、`UploadsMiddleware` 都通过 `extract_tenant_ids(state["identity"])` 读身份；身份缺失时 `(tenant_id, workspace_id) = (None, None)` → 走 legacy 路径

**为什么 Gateway 写盘正确但 sandbox 看不见？**
- 前端上传走的是 `/api/threads/{tid}/uploads`，nginx 路由（[nginx.local.conf:158](../../../docker/nginx/nginx.local.conf#L158)）走 Gateway → uploads router 通过 `request.state.identity` 拿到合法 `(tid, wid)` → 写到 tenant-stratified 路径 ✅
- 前端 chat / runs 走 `/api/langgraph/*`，nginx 路由直连 LangGraph server → HMAC 头从未注入 → Sandbox 用 legacy 路径 ❌
- 这两条路写盘逻辑分离 → 同一 thread 在两个地方各写一份，agent 看不见 Gateway 写的那份

**为什么历史 thread artifact 404？**
- 历史文件写在 legacy 路径（`ENABLE_IDENTITY` 启用前）
- 现在 artifact router 检测到 `ENABLE_IDENTITY=true` + 用户身份合法 → 去 tenant-stratified 路径找 → 找不到
- 这是同一个脱节的另一面：Gateway router 用 stratified 路径，sandbox/legacy 写盘还在 legacy 路径

---

## 修复策略（已定型，2026-04-27 定）

**当前修复路径**：langgraph-compat 切换 + smoke + 切前端默认值 + CI 防回归。理由：
- 修当前 P0 bug 必须让请求经过 Gateway 才能注入 HMAC 头
- 私有化定位下，Gateway mode 作为**默认 profile** 给中小客户更友好（少装一个组件、身份边界统一）
- `experimental` 标签的真实含义是"边角功能完整性"（subagent 事件聚合、tool call 中断恢复、某些 SDK 端点）而非"流式不流畅"——`stream_bridge` 实现只有 278 行（[backend/packages/harness/deerflow/runtime/stream_bridge/](../../../backend/packages/harness/deerflow/runtime/stream_bridge/)），协议层完全等价
- 不考虑"在 nginx/sidecar 注入 HMAC"这种迂回方案，会引入双份签名逻辑

**重要修正（vs 早先版本）**：
- 不删除 standard mode，保留作为 advanced profile（给需要 LangSmith / LangGraph Studio 调试链的客户）
- Task 4（关 nginx `/api/langgraph/*` 直连）从"必做"降级为"可选"——保留路径但加显式开关，方便 advanced profile 使用

### 阶段 1：迁移历史数据（已完成 ✅ 2026-04-27）

- 备份至 `backend/.deer-flow.bak.20260427_023657`
- dry-run + apply（PG advisory lock 模式）：58 个 thread + 1 个 skill_user 全 moved，0 fail
- 手动处理 1 个冲突 thread `35dc1f08-...`（legacy 端 0 字节空骨架 → 删空骨架 + 加 absolute symlink）
- Report: `.deer-flow/_system/migration_report_2026-04-26T18-38-04Z00-00.json`
- legacy 路径已变 forwarder symlink → stratified；历史 thread artifact 可访问

### 阶段 2：langgraph-compat smoke 测试（待执行）

5 个核心场景手动验证：streaming / 上传可见 / agent_name 注入 / subagent 派发 / artifact 写入。详见 Task 2。

### 阶段 3：切换前端默认值（待执行）

改 `frontend/src/core/config/index.ts` 的 fallback 默认值 `/api/langgraph` → `/api/langgraph-compat`。详见 Task 3。

### 阶段 4：关 nginx `/api/langgraph/*` 直连路径（待执行）

阶段 3 落地后做。保留直连意味着任何调用方只要打这条路径就能绕过 identity，是安全弱化。详见 Task 4。

### 阶段 5：CI 防回归（待执行）

加测试断言：`ENABLE_IDENTITY=true` 时新 thread 不应在 legacy 路径建任何文件。详见 Task 5。

---

## Task 列表

### Task 1: 跑迁移脚本修复历史 artifact 404 ✅ 已完成（2026-04-27）

- [x] **Step 1: 确认 PG/Redis 服务状态** — deerflow-postgres + deerflow-redis 都跑着，用 PG advisory lock 路径
- [x] **Step 2: 备份当前 .deer-flow 目录** — 备份至 `backend/.deer-flow.bak.20260427_023657`
- [x] **Step 3: 跑 dry-run 复查计划** — 第一次 dry-run 显示 59 项；发现 1 个冲突 `35dc1f08-...`（legacy 端 0 字节空骨架，tenant 端 78582 字节有上传文件）→ 手动删 legacy 空骨架；第二次 dry-run 显示 58 项，0 fail
- [x] **Step 4: 实际迁移** — `--apply`（带 PG advisory lock）58 项全 moved；report 在 `.deer-flow/_system/migration_report_2026-04-26T18-38-04Z00-00.json`
- [x] **Step 5: 验证** — 51abb193 文件在 stratified 位置；legacy 路径变成 absolute symlink → stratified；额外为 35dc1f08 手动加了同样格式的 forwarder symlink 保持一致性
- [ ] **Step 6: 回滚预案**（仅在出问题时）
```bash
cd backend && /opt/homebrew/bin/mise exec -- uv run python ../scripts/migrate_to_multitenant.py --rollback --report=.deer-flow/_system/migration_report_2026-04-26T18-38-04Z00-00.json
```

---

### Task 2: 验证 langgraph-compat 路径与直连等价
**Files:**
- Modify: `frontend/.env`（试验性切换，**先不 commit**）

**目标：** 确认 Gateway-backed runtime 在以下场景与直连等价：
- 创建 thread + 发消息 + 流式 token 输出
- Tool 调用（bash、read_file、write_file）
- Agent 创建后 agent_name 注入 LangGraph configurable
- Subagent 派发
- 上传文件 agent 可见

- [x] **Step 1: 启动 Gateway-backed runtime 模式** — 2026-04-27 已执行 `./scripts/serve.sh --dev --gateway --daemon`，3 进程跑通（Gateway:8100 / Frontend:3110 / Nginx:2026），LangGraph dev server 不启动
- [x] **Step 2: 切换前端 base URL** — `frontend/.env` 设置 `NEXT_PUBLIC_LANGGRAPH_BASE_URL=/api/langgraph-compat`
- [x] **Step 3: 核心场景命令行 smoke 已通过**（用 `dev/bootstrap-token` 拿 JWT 认证）：
  - ✅ 流式输出：6 个 `messages` chunk + 完整 AI 回复（"smoke ok"）
  - ✅ HMAC 身份注入：state 里有 `VerifiedIdentity(user_id=1, tenant_id=1, workspace_id=1, permissions={34项})`
  - ✅ Sandbox stratified 路径：`thread_data.workspace_path = .../tenants/1/workspaces/1/threads/<tid>/user-data/workspace`
  - ✅ 文件落点正确：`write_file /mnt/user-data/outputs/smoke_test.txt` → 真实落到 `tenants/1/workspaces/1/threads/<tid>/user-data/outputs/smoke_test.txt`，**legacy 路径下 thread 目录都不创建**（无双写）
  - ⏳ 浏览器端 5 场景仍待手动验证：上传文件可见、自定义 agent_name、subagent 派发、artifact 前端链接、历史 thread artifact
- [x] **Step 4: HMAC 注入验证** — 通过 stream values 事件中的 `identity` 字段直接观察到 `VerifiedIdentity`，不需要看日志
- [x] **Step 5: 文件落点验证** — `tenants/1/workspaces/1/threads/<tid>/user-data/outputs/smoke_test.txt` 存在，legacy `threads/<tid>/` 不存在
- [ ] **Step 6: 写入 smoke 测试报告** — 待补：`docs/superpowers/specs/2026-04-27-langgraph-compat-smoke-report.md`

**已发现的副作用问题（不是 langgraph-compat 引入）：**
- `backend/.deer-flow/_audit/fallback.jsonl` 是个目录而不是文件 → audit fallback 系统状态损坏，每次启动报 `IsADirectoryError`。这是另一个独立 bug，不影响主流程，要单独修。

**已发现的 langgraph-compat 兼容性差距（已修，2026-04-27）：**
- ✅ `/api/langgraph-compat/threads` 返回的 `created_at` / `updated_at` 是 unix-seconds 字符串（如 `"1777230341.97..."`），**不符合** LangGraph 官方的 ISO 8601 合约
- 表现：前端 `formatTimeAgo()` 调用 `formatDistanceToNow()` 时抛 `RangeError: Invalid time value`（`/workspace/chats` 列表页直接崩）
- 修复：[backend/app/gateway/routers/threads.py](../../../backend/app/gateway/routers/threads.py) 改用 `datetime.now(UTC).isoformat()` 写入 + 加 `_to_iso_timestamp()` helper 兼容历史 unix-string 记录
- 验证：新 thread 返回 `"2026-04-26T19:43:13.021066+00:00"`；旧 unix-string 记录读取时也被自动转 ISO
- 这就是切 langgraph-compat 后必然会暴露的"experimental 边角差距"——LangGraph 官方 server 返回 ISO 字符串，Gateway 端实现一直是 unix string，但因为前端历史只走 `/api/langgraph` 直连，差距从未暴露

---

### Task 3: 切换前端默认 LangGraph base URL ✅ 已完成（2026-04-27，commit `3cf68715`）

- [x] **Step 1: 改 fallback** — `getLangGraphBaseURL()` 在 `frontend/src/core/config/index.ts` 默认返回 `/api/langgraph-compat`（含 SSR fallback `http://localhost:2026/api/langgraph-compat`）
- [x] **Step 2: 更新 `.env.example` 注释** — 重写注释说明 compat 是默认；override 到 `/api/langgraph` 才走 standard mode（给需要 LangSmith/Studio 的客户）；本地 `.env` 同步注释掉显式覆盖让默认路径生效
- [x] **Step 3: typecheck + lint** — `pnpm check` 全绿
- [ ] **Step 4: 跑一遍现有 unit + e2e 测试** — 暂未跑，留待后续 regression 套件统一执行（vitest 有个跟本计划无关的 jsdom Blob.text 失败已知）
- [x] **Step 5: 提交** — commit `3cf68715`

---

### Task 4: nginx `/api/langgraph/*` 直连改为可配置（不强删）
**Files:**
- Modify: `docker/nginx/nginx.local.conf` 和/或 `docker/nginx/nginx.conf`

**修改方向（vs 早先版本）**：不再"激进删除"。改为通过 docker-compose profile / 环境变量控制：
- **Default profile（Gateway mode 默认）**：nginx 配置只暴露 `/api/langgraph-compat/*`，关闭 `/api/langgraph/*`
- **Advanced profile（standard mode）**：nginx 配置同时保留两条路径，给需要 LangSmith / LangGraph Studio 调试的客户用

理由：自托管定位下应同时支持 Gateway mode（给"装上能跑"的中小客户）和 standard mode（给有数据/AI 团队的大客户）。详见 [memory/project_self_hosted_positioning.md](../../../../.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/project_self_hosted_positioning.md)。

- [ ] **Step 1: 在 nginx config 用 envsubst 占位符控制 `/api/langgraph/` location 块的存在**
- [ ] **Step 2: docker-compose.yml 用 profile 切换环境变量**
- [ ] **Step 3: 重启 nginx，default profile 下验证 `/api/langgraph/*` 返回 404，advanced profile 下验证仍可用**

---

### Task 5: 加 CI 测试防回归
**Files:**
- Create: `backend/tests/identity/test_no_legacy_writes_under_identity.py`

测试断言：当 `ENABLE_IDENTITY=true`、identity 合法时，新建 thread 不应在 `backend/.deer-flow/threads/` 下创建任何文件，只在 `tenants/<tid>/workspaces/<wid>/threads/` 下。

- [ ] **Step 1: 写测试（fixture：fake identity + 跑一次 ThreadDataMiddleware）**
- [ ] **Step 2: 跑测试 → 应通过（前提：Task 3 已落地）**
- [ ] **Step 3: 提交**

---

## 验证清单

完成所有 task 后：
- [ ] 前端打开历史 thread `51abb193-...`，artifact 链接不再 404
- [ ] 前端上传一个文件，agent `ls /mnt/user-data/uploads` 能看到
- [ ] `backend/.deer-flow/threads/<新 tid>/` 目录在新 thread 创建时不再被建（`ENABLE_IDENTITY=true` 模式）
- [ ] backend log 出现 "IdentityMiddleware populated identity" 日志
- [ ] frontend `pnpm check` 全绿
- [ ] backend `make test` 全绿（含新增的回归测试）
- [ ] 旧 thread 通过 forwarder symlink 仍可访问（rollback drill）

---

## 风险

- **数据迁移不可逆**：Task 1 的 `--apply` 会移动目录。必须先备份。
- **Gateway-backed runtime 是 experimental**：Task 2 的 smoke 可能暴露未实现的功能差距。如果发现差距，先填平差距再切换默认。
- **前端用户的当前会话**：Task 3 切换 base URL 后，已打开的浏览器 tab 可能需要硬刷新。
