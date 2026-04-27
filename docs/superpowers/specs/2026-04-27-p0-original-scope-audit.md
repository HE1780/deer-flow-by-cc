# P0 原始需求 vs 现状对照（管理端 + 账号系统）

**日期：** 2026-04-27
**目的：** 把"自托管化"暂时搁置，回到 [P0 identity foundation spec](./2026-04-21-deerflow-identity-foundation-design.md) 的原始 14 页 + REST API + 6 个目标，逐项对照实现状态，定位剩余功能/验证 gap。

---

## §2.1 原始 6 大目标 vs 实现状态

| # | 原始目标 | 状态 | 备注 |
|---|---|---|---|
| 1 | 贯穿全栈身份链路（FE→GW→LangGraph） | ✅ | langgraph-compat 切换后闭环（2026-04-27） |
| 2 | 多租户隔离（DB 列 + FS 路径 + skills + config） | ✅ | M3+M4 ship；migration 脚本验证；新 thread 走 stratified |
| 3 | 5 个预置角色覆盖常见组织 | ✅ | bootstrap 已 seed |
| 4 | 管理后台最简版 14 页 | ⚠️ **待逐页验证** | 文件全部已建，但不知每页是否真能跑通 |
| 5 | OIDC 登录 + API Token | ⚠️ | 本地 bcrypt 已通；OIDC 真实 IdP 没测过 |
| 6 | 审计贯穿 Gateway + LangGraph | ⚠️ | 写入管线 ship；fallback.jsonl 当前损坏（目录化），需要修 |
| 7 | Feature flag `ENABLE_IDENTITY=false` 零破坏 | ✅ | 回归测试守 |

---

## §8.3 14 个管理 UI 页面 — 浏览器验证矩阵

| # | 页面 | 路由 | 后端 API 就绪 | 前端文件存在 | 浏览器实测 | 备注 |
|---|---|---|---|---|---|---|
| 1 | 登录页 | `/login` | ✅ `/api/auth/login` (bcrypt) + `/api/auth/oidc/{p}/login` | ✅ | ✅ | bcrypt 已验；OIDC 未验 |
| 2 | OIDC 回调 | `/auth/oidc/[p]/callback` | ✅ `/api/auth/oidc/{p}/callback` | ✅ | ❌ | 没真实 IdP 跑过 |
| 3 | 登出 | `/logout` | ✅ `/api/auth/logout` | ✅ | ⚠️ | 待验证 |
| 4 | 会话过期弹窗 | 全局组件 | n/a (401 拦截) | ⚠️ | ❌ | 需要构造 401 场景验证 |
| 5 | 租户列表 | `/admin/tenants` | ✅ `GET /api/admin/tenants` + `POST/PATCH/DELETE` | ✅ | ⚠️ | 列表显示能否 work、新建/重命名/删除流程是否完整 |
| 6 | 租户详情 | `/admin/tenants/[id]` | ✅ | ✅ | ⚠️ | 详情字段、编辑、统计 |
| 7 | 用户列表 | `/admin/users` | ✅ `GET /api/tenants/{tid}/users` | ✅ | ⚠️ | 创建用户流程、禁用流程 |
| 8 | 用户详情 | `/admin/users/[id]` | ✅ | ✅ | ⚠️ | 角色修改、workspace 成员关系 |
| 9 | 角色列表（只读） | `/admin/roles` | ✅ `GET /api/roles` + `/api/permissions` | ✅ | ⚠️ | 5 个预置角色显示是否完整 |
| 10 | Workspace 列表 | `/admin/workspaces` | ✅ | ✅ | ⚠️ | 创建/重命名/删除 |
| 11 | Workspace 成员 | `/admin/workspaces/[id]/members` | ✅ `GET/POST/PATCH/DELETE` | ✅ | ⚠️ | 添加成员、改角色、移除 |
| 12 | API Token | `/admin/tokens` | ✅ `GET /api/me/tokens` + `POST` 一次性明文 | ✅ | ⚠️ | 创建后明文显示一次、撤销 |
| 13 | 审计日志 | `/admin/audit` | ✅ `GET /api/tenants/{tid}/audit` + `/export` | ✅ | ⚠️ | 列表分页、CSV 导出、时间范围筛选 |
| 14 | 个人中心 | `/admin/profile` | ✅ `GET/PATCH /api/me` + `/sessions` | ✅ | ⚠️ | 资料编辑、活跃 session 列表、撤销 session |

**此外项目超出 spec 自加的页面**（非 P0 范围但已经存在）：
- `/admin/skills` — Skills 管理（来自 Skill Mgmt v2，独立工作流）
- `/admin/org-keys` — Org Keys 管理（来自 Skill v2 计划 C）

---

## §8.4 REST API 清单 vs 实现

### Auth ✅
- [x] `GET /api/auth/oidc/{provider}/login`
- [x] `GET /api/auth/oidc/{provider}/callback`
- [x] `POST /api/auth/refresh`
- [x] `POST /api/auth/logout`
- [x] `POST /api/auth/login` (本地 bcrypt，spec 之外的扩展)

### Me ✅
- [x] `GET /api/me`
- [x] `POST /api/me/switch-tenant`
- [x] `GET /api/me/tokens` / `POST /api/me/tokens` / `DELETE /api/me/tokens/{id}`
- [x] `GET /api/me/sessions` / `DELETE /api/me/sessions/{sid}`
- [x] `PATCH /api/me`

### Platform admin ✅
- [x] `GET/POST/PATCH/DELETE /api/admin/tenants` 全部到位
- [x] `GET /api/admin/tenants/{tid}/stats`

### Tenant admin ✅
- [x] `GET/POST/PATCH/DELETE /api/tenants/{tid}/users`
- [x] `GET/POST/PATCH/DELETE /api/tenants/{tid}/workspaces`
- [x] `GET/POST/PATCH/DELETE /api/tenants/{tid}/workspaces/{wid}/members`
- [x] `GET/DELETE /api/tenants/{tid}/tokens`
- [x] `GET /api/tenants/{tid}/audit` + `/export`

### Roles / Permissions ✅
- [x] `GET /api/roles`
- [x] `GET /api/permissions`

**结论：REST API 100% 实现，差距全部在 UI 端到端验证。**

---

## §5 认证流程 vs 现状

| 子项 | 状态 | gap |
|---|---|---|
| OIDC Authorization Code + PKCE | ✅ 代码就绪 | 真实 IdP 没跑过 |
| Internal JWT (RS256) | ✅ ship + bootstrap-token 验证 | — |
| API Token (`dft_*` 前缀，bcrypt) | ✅ | UI 验证待做 |
| Redis Session | ✅ | 撤销流程 UI 验证待做 |
| Login Lockout | ✅ | UI 验证待做（连续失败锁定提示） |
| Cookie (`deerflow_session`, HttpOnly, Secure) | ✅ | 浏览器实测 |

---

## §9 审计 vs 现状

| 子项 | 状态 | gap |
|---|---|---|
| AuditMiddleware | ✅ | — |
| AuditBatchWriter (PG 写入 + 队列) | ✅ | — |
| Fallback JSONL | ✅ 已修复 | 2026-04-27 修 `migrate_to_multitenant.py` 构造 FallbackLog 的 bug（commit `9e7184fd`），救回 58 条迁移审计事件并 backfill 到 PG |
| Retention job | ✅ 代码 | 实际 cron 没启过 |
| `GET /api/tenants/{tid}/audit` 分页 | ✅ | UI 验证 |
| `GET /api/tenants/{tid}/audit/export` CSV | ✅ | UI 验证 |
| `audit_logs` 表 GRANT 不可改 | ✅ | — |

---

## 当前真正剩余的工作（按优先级）

### P0 — 阻塞"管理端可用"的修复

1. ~~**Audit fallback.jsonl 损坏**~~ ✅ 已修复（commit `9e7184fd`，2026-04-27）
2. **14 个 admin 页面浏览器逐项验证** — 重点关注：
   - 5/6 租户增删改 + stats
   - 7/8 用户创建/禁用/角色关联
   - 10/11 Workspace 增删改 + 成员管理
   - 12 Token 创建明文显示 + 撤销
   - 13 审计列表分页 + CSV 导出
   - 14 Profile 编辑 + session 撤销

### P1 — 非阻塞但应做的

3. **LoopDetectionMiddleware 孤儿 ToolMessage** — [独立 spec 已记录](./2026-04-27-loop-detection-orphan-tool-msg.md)
4. **登录 Lockout / 会话过期弹窗** — 需要构造场景测试
5. **OIDC 真实 IdP 测试** — 至少跑一遍 Keycloak 自托管或 Okta dev 账号

### P2 — 推迟到自托管阶段

6. **nginx `/api/langgraph/*` profile 化**
7. **CI 防回归测试（langgraph-compat）**
8. **Identity 测试覆盖率 ≥ 80%**

---

## 建议下一步

按"逐页验证 + 修阻塞 bug"路线，分两条独立工作流：

**A. 14 页 manual smoke**（你来做）：
- 我帮你按页准备一份"操作 → 期望结果"的 checklist
- 你在浏览器走一遍，把不工作的页面截图/列出
- 我针对每个 gap 单独定位修复

**B. 修 audit fallback.jsonl 损坏**（我来做，约 15 分钟）：
- 它独立于 UI，不阻塞 A
- 修完 Gateway 启动日志干净

**两条线可并行**——你启动 A 时我做 B。

或者你想换个路径，先做哪个具体的页面/功能验证？告诉我即可。
