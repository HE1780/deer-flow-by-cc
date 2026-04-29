> 📦 **归档于 2026-04-29 — 长期参考文档**
>
> M1-M7 完整 ship 详见 [SYSTEM_WHITEPAPER.md §3.1](../../../SYSTEM_WHITEPAPER.md)。OIDC 真实 IdP 烟雾、迁移 1000-thread 演练、多副本 bootstrap 等部署 gap 见 [OPEN_ISSUES.md](../../../OPEN_ISSUES.md) + [identity-release-checklist.md](../../../identity-release-checklist.md)。

---

# DeerFlow 企业身份基座（P0）设计说明

- **状态**: ✅ P0 已 ship · 长期参考文档（v2 不变量 + P1+ 路线图入口）
- **创建日期**: 2026-04-21
- **关闭里程碑**: 2026-04-28（M1-M7 全部 shipped；详见 [../../plans/archive/](../../plans/archive/) 归档目录）
- **所属路线图**: deer-flow 企业级 AI 工作平台改造（P0 身份与权限基座）
- **前置阅读**: 暂无
- **后续子项目**: P1 细粒度 RBAC · P2 知识库管理 · P3 SkillHub 集成 · P4 团队协作 · P5 工作流编排 UI（**未启动**——本文档保留作为路线图锚点；具体启动以新计划文件落地）

---

## 1. 背景与动机

DeerFlow 当前为单用户 LangGraph 研究助手：`thread_id` 是一切隔离的唯一维度，无用户/租户/角色概念。要改造成企业级 AI 工作平台，需要一个贯穿全栈的身份基座作为所有后续能力（知识库、技能市场、团队协作、工作流编排）的前置。

本 spec 定义 P0：**身份、多租户、RBAC、存储隔离、管理后台骨架、审计**。v1 不含：LDAP/SAML/MFA/邮件邀请/组织架构树/自定义角色/资源实例级 ACL/对象存储/磁盘配额/用量计费。

参考系：
- **aiflowy**（github.com/aiflowy/aiflowy）：单库 `tenant_id` 列隔离、RBAC 三层、API Key 资源绑定等模型值得借鉴；Sa-Token / Dept 树 / menu 耦合权限 / 无原生 OIDC 等实现层面不抄。
- **iflytek/skillhub**：其 namespace 模型与本 spec 的 workspace 天然对齐，为 P3 SkillHub 集成预留接口。

## 2. 目标与非目标

### 2.1 目标

1. 贯穿全栈的身份链路：Frontend → Gateway → LangGraph runtime
2. 多租户隔离：DB 列级 + 文件系统路径 + skills 目录 + config 分层
3. 5 个预置角色覆盖常见组织结构
4. 管理后台最简版：登录页 · 租户/用户/角色/Workspace/API Token/审计/个人中心
5. OIDC 登录（Okta / Azure AD / Keycloak） + API Token
6. 审计贯穿 Gateway + LangGraph tool 调用
7. 对现有部署**零破坏**：Feature Flag 默认关闭，可按业务节奏启用

### 2.2 非目标

- 本地密码登录 / MFA / 社交登录
- 邮件邀请（v1.1 再做）
- 组织架构树 / 部门 / 岗位
- 自定义角色（v1.1 再开放）
- 细粒度资源实例级 ACL（P1）
- 独立 identity 微服务（未来演进）
- Keycloak / Ory 托底
- LDAP / SAML / SCIM
- 对象存储 / 加密存储 / 配额
- 模型用量计费 / 成本分析
- 零停机切换身份

## 3. 架构总览

### 3.1 分层

```
┌─────────────────────────────────────────────────────────────┐
│ Frontend (Next.js 单 app, 新增 (admin) route group)          │
│  - 登录页 / 个人中心 / 租户·用户·角色·API Token·审计后台     │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTPS
┌──────────────────────▼──────────────────────────────────────┐
│ Gateway (backend/app/gateway, FastAPI 单体)                  │
│  新增子包 app/gateway/identity/                              │
│  ├── auth/    OIDC 登录 · token 刷新 · 登出                  │
│  ├── rbac/    权限点、角色、check 装饰器                     │
│  ├── admin/   租户·用户·角色·workspace·token API             │
│  ├── audit/   切面、审计 API                                 │
│  └── models/  SQLAlchemy + Alembic                           │
│  新增全局 middleware:                                         │
│   AuditMiddleware / TenantScopeMiddleware / IdentityMiddleware│
└──────────┬─────────────────────────┬────────────────────────┘
           │ 转发 identity header     │
┌──────────▼──────────────┐   ┌──────▼──────────────┐
│ LangGraph runtime        │   │ PostgreSQL + Redis  │
│ + IdentityMiddleware     │   └─────────────────────┘
│ + Guardrail 升级读权限   │
└─────────────────────────┘
```

### 3.2 核心原则

1. **单体内分包**：identity 代码全部在 `backend/app/gateway/identity/`，对 harness (`deerflow.*`) 零侵入，只通过 HTTP header 传递身份。
2. **双重隔离**：DB 用 `tenant_id` 列级过滤；文件系统用 `tenants/{tid}/workspaces/{wid}/` 路径。
3. **权限决策三点**：Gateway API 入口（装饰器）· LangGraph 工具调用（Guardrail 升级）· SQL 层（SQLAlchemy 自动 filter）。
4. **扩展点预留**：identity 子包通过接口抽象 `AuthProvider` / `UserStore` / `SessionStore`，未来可替换为 Keycloak 或独立微服务。

### 3.3 新增依赖

| 依赖 | 用途 |
|---|---|
| `authlib` | OIDC client |
| `python-jose[cryptography]` | 内部 JWT 签发/验签 |
| `sqlalchemy[asyncio]>=2` + `alembic` | ORM + 迁移 |
| `asyncpg` | Postgres 异步驱动 |
| `redis[hiredis]` | session / 登录锁 / 强制下线 |
| `passlib[bcrypt]` | API Token hash |

## 4. 数据模型

所有新表落在 Postgres `identity` schema，迁移用 Alembic。

### 4.1 DDL 概要

```sql
-- 1. 租户
CREATE TABLE identity.tenants (
  id           BIGSERIAL PRIMARY KEY,
  slug         VARCHAR(64)  NOT NULL UNIQUE,
  name         VARCHAR(128) NOT NULL,
  logo_url     TEXT,
  plan         VARCHAR(32)  DEFAULT 'free',
  status       SMALLINT     DEFAULT 1,   -- 1 active / 0 suspended / -1 deleted
  owner_id     BIGINT,
  expires_at   TIMESTAMPTZ,
  created_at   TIMESTAMPTZ  DEFAULT now(),
  created_by   BIGINT,
  updated_at   TIMESTAMPTZ  DEFAULT now()
);

-- 2. 用户（全局唯一）
CREATE TABLE identity.users (
  id              BIGSERIAL PRIMARY KEY,
  email           VARCHAR(255) NOT NULL UNIQUE,
  display_name    VARCHAR(128),
  avatar_url      TEXT,
  status          SMALLINT DEFAULT 1,
  oidc_subject    VARCHAR(255),
  oidc_provider   VARCHAR(64),
  last_login_at   TIMESTAMPTZ,
  last_login_ip   INET,
  created_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE(oidc_provider, oidc_subject)
);

-- 3. 用户-租户关系
CREATE TABLE identity.memberships (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES identity.users(id)   ON DELETE CASCADE,
  tenant_id   BIGINT NOT NULL REFERENCES identity.tenants(id) ON DELETE CASCADE,
  status      SMALLINT DEFAULT 1,
  joined_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, tenant_id)
);

-- 4. Workspace（扁平，非树）
CREATE TABLE identity.workspaces (
  id           BIGSERIAL PRIMARY KEY,
  tenant_id    BIGINT NOT NULL REFERENCES identity.tenants(id) ON DELETE CASCADE,
  slug         VARCHAR(64)  NOT NULL,
  name         VARCHAR(128) NOT NULL,
  description  TEXT,
  created_by   BIGINT,
  created_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id, slug)
);

-- 5. 权限字典
CREATE TABLE identity.permissions (
  id           BIGSERIAL PRIMARY KEY,
  tag          VARCHAR(64) NOT NULL UNIQUE,
  scope        VARCHAR(16) NOT NULL,   -- platform | tenant | workspace
  description  TEXT
);

-- 6. 角色（scope 区分层级）
CREATE TABLE identity.roles (
  id           BIGSERIAL PRIMARY KEY,
  role_key     VARCHAR(64) NOT NULL,
  scope        VARCHAR(16) NOT NULL,
  is_builtin   BOOLEAN DEFAULT TRUE,
  display_name VARCHAR(128),
  description  TEXT,
  UNIQUE(role_key, scope)
);

-- 7. 角色-权限
CREATE TABLE identity.role_permissions (
  role_id       BIGINT NOT NULL REFERENCES identity.roles(id)       ON DELETE CASCADE,
  permission_id BIGINT NOT NULL REFERENCES identity.permissions(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_id)
);

-- 8. 用户-租户级角色（仅 platform_admin / tenant_owner）
CREATE TABLE identity.user_roles (
  user_id      BIGINT NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  tenant_id    BIGINT REFERENCES identity.tenants(id) ON DELETE CASCADE,  -- NULL = platform_admin
  role_id      BIGINT NOT NULL REFERENCES identity.roles(id),
  granted_at   TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, tenant_id, role_id)
);

-- 9. Workspace 成员
CREATE TABLE identity.workspace_members (
  user_id       BIGINT NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  workspace_id  BIGINT NOT NULL REFERENCES identity.workspaces(id) ON DELETE CASCADE,
  role_id       BIGINT NOT NULL REFERENCES identity.roles(id),
  joined_at     TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, workspace_id)
);

-- 10. API Token
CREATE TABLE identity.api_tokens (
  id            BIGSERIAL PRIMARY KEY,
  tenant_id     BIGINT NOT NULL REFERENCES identity.tenants(id) ON DELETE CASCADE,
  user_id       BIGINT NOT NULL REFERENCES identity.users(id)   ON DELETE CASCADE,
  workspace_id  BIGINT REFERENCES identity.workspaces(id) ON DELETE CASCADE,
  name          VARCHAR(128) NOT NULL,
  prefix        VARCHAR(16)  NOT NULL,
  token_hash    VARCHAR(255) NOT NULL,
  scopes        TEXT[]       NOT NULL DEFAULT '{}',
  expires_at    TIMESTAMPTZ,
  last_used_at  TIMESTAMPTZ,
  last_used_ip  INET,
  revoked_at    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now(),
  created_by    BIGINT
);
CREATE INDEX ON identity.api_tokens (tenant_id, revoked_at);
CREATE INDEX ON identity.api_tokens (prefix);

-- 11. 审计日志
CREATE TABLE identity.audit_logs (
  id             BIGSERIAL PRIMARY KEY,
  tenant_id      BIGINT,
  user_id        BIGINT,
  workspace_id   BIGINT,
  action         VARCHAR(128) NOT NULL,
  resource_type  VARCHAR(64),
  resource_id    VARCHAR(128),
  ip             INET,
  user_agent     TEXT,
  result         VARCHAR(16)  NOT NULL,
  error_code     VARCHAR(64),
  duration_ms    INT,
  metadata       JSONB,
  created_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON identity.audit_logs (tenant_id, created_at DESC);
CREATE INDEX ON identity.audit_logs (user_id,  created_at DESC);
CREATE INDEX ON identity.audit_logs (action);
```

**DB 权限约束**：应用连接用户只对 `audit_logs` 有 `INSERT, SELECT`，**无 `UPDATE/DELETE`**（PG GRANT 强制）。

### 4.2 预置种子数据

**角色（5 个）**
- `platform_admin`（scope=platform）
- `tenant_owner`（scope=tenant）
- `workspace_admin` / `member` / `viewer`（scope=workspace）

**权限点（~24 个）**
- platform: `tenant:create|read|update|delete`, `user:read|disable`, `audit:read.all`
- tenant: `workspace:create|read|update|delete`, `membership:invite|read|remove`, `role:read`, `token:create|revoke|read`, `audit:read`
- workspace: `thread:read|write|delete`, `skill:read|invoke|manage`, `knowledge:read|write|manage`, `workflow:read|run|manage`, `settings:read|update`

**角色-权限映射**
- `platform_admin`: 所有 platform 权限 + 通过 bypass 机制跨租户可见
- `tenant_owner`: 所有 tenant 权限 + 其所在 workspace 自动为 workspace_admin
- `workspace_admin`: 所有 workspace 权限
- `member`: `thread:*`, `skill:read|invoke`, `knowledge:read|write`, `workflow:read|run`, `settings:read`
- `viewer`: `*:read` only

**默认租户/workspace**: `default` / `default`（供现有数据迁入）

### 4.3 SQLAlchemy 自动租户过滤

```python
class TenantScoped:
    tenant_id: Mapped[int] = mapped_column(index=True, nullable=False)

class WorkspaceScoped(TenantScoped):
    workspace_id: Mapped[int] = mapped_column(index=True, nullable=False)

@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(execute_state):
    if not execute_state.is_select:
        return
    identity = current_identity.get()
    if identity is None or identity.is_platform_admin:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda cls: cls.tenant_id == identity.tenant_id,
            include_aliases=True,
        )
    )
    if identity.workspace_ids:
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                WorkspaceScoped,
                lambda cls: cls.workspace_id.in_(identity.workspace_ids),
                include_aliases=True,
            )
        )
```

写入前 `before_insert` 事件校验 `tenant_id` 与 identity 一致。

## 5. 认证流程

### 5.1 OIDC 登录（Authorization Code + PKCE）

```
Browser → Frontend → Gateway → OIDC IdP → Postgres/Redis

1. 未登录访问 /admin → 302 /login
2. 点击 "Sign in with Okta" → GET /auth/oidc/okta/login
3. Gateway 生成 state + PKCE，存 Redis 5min TTL，302 到 IdP authorize
4. 用户在 IdP 登录，IdP 回跳 /auth/oidc/okta/callback?code=&state=
5. Gateway 校验 state → 交换 code → 验签 id_token (aud/iss/nonce)
6. upsert users by (provider, sub) → 若无 membership 按策略处理（§5.5）
7. 签发内部 JWT access+refresh → 写 Redis session → Set-Cookie → 302 /admin
8. 写审计 user.login.success
```

### 5.2 Token 模型

**内部 access token（JWT, 15min）**
```json
{
  "sub": "user_id",
  "email": "alice@acme.com",
  "tid": "active_tenant_id",
  "wids": [1, 2, 3],
  "permissions": ["thread:read", "thread:write", "skill:invoke", ...],
  "roles": {
    "platform": ["platform_admin"],
    "tenant":   ["tenant_owner"],
    "workspaces": {"1": "workspace_admin", "2": "member"}
  },
  "sid": "session_id",
  "exp": ..., "iat": ..., "iss": "deerflow", "aud": "deerflow-api"
}
```

**refresh token（随机 64B, 7d，存 Redis）**
```
deerflow:session:{sid} = { user_id, tenant_id, refresh_hash, created_at, ua, ip, revoked }
```

**API Token（长期凭证）**
- 明文格式：`dft_<prefix>_<random32>`
- 请求头 `Authorization: Bearer dft_...`
- Gateway 识别前缀 → 前缀索引命中候选 → bcrypt verify → 命中缓存 5min 到 Redis

### 5.3 Gateway 中间件栈

```python
app.add_middleware(AuditMiddleware)          # 最外层
app.add_middleware(TenantScopeMiddleware)    # 注入 SQLAlchemy ctx
app.add_middleware(IdentityMiddleware)       # 验 token → request.state.identity
```

**Identity 对象**
```python
@dataclass
class Identity:
    user_id:       int | None
    tenant_id:     int | None
    workspace_ids: list[int]
    permissions:   set[str]
    roles:         dict[str, list[str]]
    session_id:    str | None
    token_type:    Literal["jwt", "api_token", "anonymous"]
    ip:            str
    is_platform_admin: bool
```

### 5.4 Gateway → LangGraph 透传

```
X-Deerflow-User-Id: 42
X-Deerflow-Tenant-Id: 7
X-Deerflow-Workspace-Id: 3
X-Deerflow-Permissions: thread:read,thread:write,skill:invoke,knowledge:read
X-Deerflow-Session-Id: sess_abc123
X-Deerflow-Identity-Ts: 1745000000
X-Deerflow-Identity-Sig: <HMAC-SHA256(fields, INTERNAL_SIGNING_KEY)>
```

- 不传业务 JWT，避免内部服务解析；扁平 header + HMAC 签名
- HMAC 字段：user_id + tenant_id + workspace_id + permissions + ts
- LangGraph 端验 5min 内有效 + 签名匹配
- `X-Deerflow-Workspace-Id` 是**当前激活** workspace（thread 归属），来自 API path；`Identity.workspace_ids` 是该 user 在该 tenant 下可访问的**全部** ws 列表，仅用于 Gateway 侧 SQL filter，不透传给 LangGraph（LangGraph 运行时只关心当前 thread 所属的 ws）

LangGraph 侧新增 `IdentityMiddleware`（插在中间件链最前）：验 HMAC → 写 `state["identity"]` → 供后续所有中间件读取。

### 5.5 首次 OIDC 登录落库策略

1. 用户已存在（按 `oidc_provider + oidc_subject` 匹配）：
   - 有 membership → 选默认 tenant 进入
   - 无 membership → "未被邀请"静态页
2. 用户不存在：
   - 按 email 匹配现有 users 行 → 绑定 oidc_subject（处理跨 IdP 同一人）
   - 否则创建 users 行 + 无 membership → "未被邀请"静态页
3. 配置开关 `IDENTITY_AUTO_PROVISION_TENANT=false`（默认）：true 时首登自动建个人 tenant + workspace + tenant_owner 角色（仅内部试用场景）

### 5.6 Session 管理

- **登出**: 删 Redis session → 清 cookie → 下次请求因 sid 不在 Redis 中被拒
- **强制下线**: 禁用用户 / 撤角色时，扫描该 user 所有 session 打 revoked；下次刷新时拒绝
- **刷新**: access 过期前 2min 前端自动刷；refresh 本身不延期，7 天后重新 OIDC 登录
- **"记住我"**: v1 不做
- **并发设备**: 多端登录独立 sid；个人中心"登出其他设备"可批量 revoke

### 5.7 安全细节

- OIDC state + PKCE verifier 存 Redis 5min TTL
- JWT RS256，私钥存环境变量 `DEERFLOW_JWT_PRIVATE_KEY`
- Cookie: `HttpOnly; Secure; SameSite=Lax; Path=/`
- API Token bcrypt cost=12
- 登录失败速率限制：IP + email 复合 key，Redis 计数，5min 内 10 次触发 15min 锁定
- 关键事件全部写审计

### 5.8 OIDC 多 provider 配置

```yaml
# config/identity.yaml
oidc:
  providers:
    okta:
      issuer: https://acme.okta.com
      client_id: $OKTA_CLIENT_ID
      client_secret: $OKTA_CLIENT_SECRET
      scopes: [openid, profile, email]
    azure:
      issuer: https://login.microsoftonline.com/{tenant}/v2.0
      client_id: $AZURE_CLIENT_ID
      client_secret: $AZURE_CLIENT_SECRET
    keycloak:
      issuer: https://auth.internal/realms/deerflow
      client_id: deerflow
      client_secret: $KEYCLOAK_CLIENT_SECRET
```

登录页根据配置动态渲染 provider 按钮。

## 6. RBAC 与中间件

### 6.1 决策点

| 决策点 | 位置 | 机制 |
|---|---|---|
| API 入口 | Gateway 路由 | `@requires(tag, scope)` FastAPI dependency |
| Tool 调用 | LangGraph Guardrail | 读 `state.identity.permissions` + `TOOL_PERMISSION_MAP` |
| SQL 查询 | SQLAlchemy event | `TenantScopeMiddleware` 注入 WHERE |

### 6.2 权限检查装饰器

```python
@router.post("/api/workspaces/{ws_id}/skills/{skill_id}/invoke")
async def invoke_skill(
    ws_id: int, skill_id: int,
    identity: Identity = Depends(requires("skill:invoke", scope="workspace")),
):
    ...
```

`requires(tag, scope)` 逻辑：
1. 读 `request.state.identity`；anonymous → 401
2. scope 校验：
   - platform → identity.permissions 含 tag
   - tenant → path tenant_id ∈ identity.memberships 且权限匹配
   - workspace → path ws_id ∈ identity.workspace_ids 且权限匹配
3. 失败 → 403 + 写审计 `authz.api.denied`

### 6.3 路由-权限映射（摘要）

| 路由 | 权限 |
|---|---|
| `GET  /api/admin/tenants` | `tenant:read` (platform) |
| `POST /api/admin/tenants` | `tenant:create` (platform) |
| `POST /api/tenants/{tid}/workspaces` | `workspace:create` (tenant) |
| `POST /api/workspaces/{wid}/threads` | `thread:write` (workspace) |
| `POST /api/tokens` | `token:create` (tenant) |
| `GET  /api/audit` | `audit:read` (tenant) |

完整映射由实现时维护在 `app/gateway/identity/rbac/routes.py`。

### 6.4 Guardrail 升级：Tool 级授权

```python
TOOL_PERMISSION_MAP = {
    "bash":        "thread:write",
    "write_file":  "thread:write",
    "str_replace": "thread:write",
    "read_file":   "thread:read",
    "ls":          "thread:read",
    "task":        "thread:write",
    # MCP 工具: 按 server 注册时声明,默认 skill:invoke
    # knowledge 检索/写入: 在 MCP adapter 侧声明
}
```

`GuardrailMiddleware.before_tool_call` 增量：
1. 读 `state.identity.permissions` + 工具名映射
2. 缺权限 → `ToolCallRejection(reason, audit_action="authz.tool.denied")`
3. 未在 MAP 中声明的工具 **默认 deny**
4. `task` 子 agent 继承主 identity

### 6.5 权限扁平化与缓存

- **登录时**扁平化：role × role_permissions → `Set[str]` 塞 JWT claims
- **API Token 命中**：DB 查出 permissions 缓存 5min 到 Redis，key `identity:perms:{user_id}:{tenant_id}`
- **变更传播**：修改 role_permissions / user_roles 时清缓存 + 标记 session 需刷新；UI 提示"角色已更新，需重新登录"

### 6.6 切换当前 active tenant

`POST /api/me/switch-tenant {tenant_id}` → 验 membership → 重新签发 JWT（permissions 重算）。

### 6.7 明确排除

- ❌ 资源实例级 ACL（精细到具体 skill/thread 的授权）
- ❌ 动态权限表达式（Casbin / OPA）
- ❌ 权限继承层级（预置角色显式展开）
- ❌ 审批流 / 临时提权
- ❌ 跨 tenant 协作

### 6.8 不变量

1. 无 identity → 只能访问 `/auth/*` 白名单
2. path 中 tenant/workspace id 必须与 identity 匹配（防横向越权）
3. SQL filter 不可绕过；显式提权走 `with_platform_privilege()` + 强制审计
4. Tool 权限映射是白名单，未声明默认 deny

## 7. 存储隔离

### 7.1 文件系统路径

**现状**
```
backend/.deer-flow/threads/{thread_id}/
  workspace/ uploads/ outputs/ memory.json
```

**P0 目标**
```
$DEER_FLOW_HOME/
  tenants/{tenant_id}/
    workspaces/{workspace_id}/
      threads/{thread_id}/
        workspace/ uploads/ outputs/ memory.json
    shared/                          # 预留 P2
  _system/                            # 迁移临时 / 审计 fallback / 归档
```

**路径生成**
```python
def thread_path(identity: Identity, thread_id: str) -> Path:
    assert identity.tenant_id and identity.workspace_id
    return (
        DEER_FLOW_HOME
        / "tenants" / str(identity.tenant_id)
        / "workspaces" / str(identity.workspace_id)
        / "threads" / thread_id
    )
```

**沙箱内可见性**：虚拟路径 `/mnt/user-data/{workspace,uploads,outputs}` 保持不变，agent 感知不到租户概念；`mount` 和 `/proc/self/mountinfo` 也不暴露 tenant/workspace id。

**路径越权防护**：宿主路径 normalize 后校验 `path.is_relative_to(tenant_root)`。

### 7.2 Skills 目录 tenant 化

**目标布局**
```
skills/
  public/                              # 跨租户共享
  tenants/{tid}/
    custom/                            # 租户级自定义
    workspaces/{wid}/user/             # workspace 内用户技能
```

**loader 改造**（`backend/packages/harness/deerflow/skills/loader.py`）
- 参数新增 `tenant_id / workspace_id`
- 扫描优先级：workspace user > tenant custom > public
- 命名冲突：更具体作用域覆盖，记录 warning
- `enabled_only` 继续从 `extensions_config.json` 读，但配置分层
- symlink 继续支持（`followlinks=True`），但规范化后父目录必须在 `skills/tenants/{tid}/` 内

**安装路径**（`POST /api/skills/install`）
- 默认：workspace/user/
- `tenant_owner|workspace_admin` + scope="tenant" → tenants/{tid}/custom/
- `platform_admin` + scope="public" → public/（需二次确认）

### 7.3 Config 分层

```
global:     $DEER_FLOW_CONFIG_PATH (或 /etc/deerflow/config.yaml)
 + tenant:  $DEER_FLOW_HOME/tenants/{tid}/config.yaml
 + ws:      $DEER_FLOW_HOME/tenants/{tid}/workspaces/{wid}/config.yaml
```

- 深度合并（dict 递归，list 整体替换）
- 敏感字段（API key 等）只允许 global 层；tenant/workspace 层忽略并 warn
- 合并产物缓存到 Redis `config:merged:{tid}:{wid}`，mtime 变化失效
- `extensions_config.json` 同规则分层，启用 skill 名单可合并

### 7.4 Memory & Artifacts

- `memory.json` 位于 thread 目录内，自动随 tenant/workspace 隔离
- 用户级 memory：`$DEER_FLOW_HOME/tenants/{tid}/users/{uid}/memory.json`；该 user 在该 tenant 下所有 thread 共享，跨 tenant 不共享
- Artifacts API 加 identity 校验：thread_id 归属租户/ws 必须匹配

### 7.5 迁移

见 §9。

### 7.6 明确排除

- ❌ 对象存储（S3/MinIO）
- ❌ 跨 workspace 文件共享
- ❌ 加密存储 / KMS
- ❌ 磁盘配额

### 7.7 不变量

1. 存储路径从 identity 派生，不从用户输入拼
2. symlink 可用但不可跨租户
3. config 分层只下沉不上浮（敏感字段强制在 global）
4. 迁移必须可回滚（symlink + 24h 保留）

## 8. 管理 UI

### 8.1 组织（单 Next.js app，route group）

```
frontend/src/app/
  (public)/login/ · auth/oidc/[provider]/callback/ · logout/
  (app)/  现有聊天 UI（加 identity guard）
  (admin)/admin/  管理后台入口
    tenants/ · users/ · roles/ · workspaces/[id]/members/ · tokens/ · audit/ · profile/
```

### 8.2 导航权限守卫

- `middleware.ts` 拦 `/admin/*` → `/api/me` 校验 → 无 session 跳 `/login`
- 页面级：`useIdentity()` + `<RequirePermission tag="...">`
- 服务端也校验，防前端被篡改

### 8.3 页面清单（14 个）

| # | 页面 | 路由 | 权限 |
|---|---|---|---|
| 1 | 登录页 | `/login` | public |
| 2 | OIDC 回调 | `/auth/oidc/[p]/callback` | public |
| 3 | 登出 | `/logout` | public |
| 4 | 会话过期弹窗 | 全局组件 | authed |
| 5 | 租户列表 | `/admin/tenants` | `tenant:read` (platform) |
| 6 | 租户详情 | `/admin/tenants/[id]` | 同上 |
| 7 | 用户列表 | `/admin/users` | `membership:read` |
| 8 | 用户详情 | `/admin/users/[id]` | 同上 |
| 9 | 角色列表（只读） | `/admin/roles` | authed |
| 10 | Workspace 列表 | `/admin/workspaces` | `workspace:read` |
| 11 | Workspace 成员 | `/admin/workspaces/[id]/members` | 同上 |
| 12 | API Token | `/admin/tokens` | `token:read` |
| 13 | 审计日志 | `/admin/audit` | `audit:read` |
| 14 | 个人中心 | `/admin/profile` | authed |

### 8.4 REST API 清单

**Auth**
```
GET  /api/auth/oidc/{provider}/login
GET  /api/auth/oidc/{provider}/callback
POST /api/auth/refresh
POST /api/auth/logout
```

**Me**
```
GET  /api/me
POST /api/me/switch-tenant
GET  /api/me/tokens
POST /api/me/tokens                    # 返回一次性明文
DELETE /api/me/tokens/{id}
GET  /api/me/sessions
DELETE /api/me/sessions/{sid}
PATCH /api/me
```

**Platform admin**
```
GET    /api/admin/tenants
POST   /api/admin/tenants
PATCH  /api/admin/tenants/{tid}
DELETE /api/admin/tenants/{tid}        # 软删
GET    /api/admin/tenants/{tid}/stats
```

**Tenant admin**
```
GET    /api/tenants/{tid}/users
POST   /api/tenants/{tid}/users
PATCH  /api/tenants/{tid}/users/{uid}
DELETE /api/tenants/{tid}/users/{uid}

GET    /api/tenants/{tid}/workspaces
POST   /api/tenants/{tid}/workspaces
PATCH  /api/tenants/{tid}/workspaces/{wid}
DELETE /api/tenants/{tid}/workspaces/{wid}

GET    /api/tenants/{tid}/workspaces/{wid}/members
POST   /api/tenants/{tid}/workspaces/{wid}/members
PATCH  /api/tenants/{tid}/workspaces/{wid}/members/{uid}
DELETE /api/tenants/{tid}/workspaces/{wid}/members/{uid}

GET    /api/tenants/{tid}/tokens
DELETE /api/tenants/{tid}/tokens/{id}

GET    /api/tenants/{tid}/audit
GET    /api/tenants/{tid}/audit/export
```

**Roles / Permissions（只读）**
```
GET /api/roles
GET /api/permissions
```

### 8.5 前端技术栈

- 复用现有 Tailwind 4 + shadcn/ui + TanStack Query + React Table
- 新增：`react-hook-form` + `zod`
- `useIdentity()` / `<RequirePermission>` hook/组件
- fetch wrapper：自动带 cookie、401 触发过期弹窗
- i18n：v1 中英双语，不接平台

### 8.6 空状态与引导

| 场景 | 体验 |
|---|---|
| 首次启动 | bootstrap 自动建 default 租户 + workspace + 首个 platform_admin（`DEERFLOW_BOOTSTRAP_ADMIN_EMAIL`） |
| 首次登录管理员 | 落在 `/admin/tenants`，提示"建议创建正式租户" |
| 用户无 membership | "未被邀请"静态页 |
| 单租户单 ws 用户 | 直接跳 `/`，隐藏租户切换器 |

### 8.7 明确排除

- ❌ 三端拆分
- ❌ Dashboard 图表
- ❌ 审计图表化
- ❌ 主题定制 / logo 动态渲染
- ❌ 邮件通知中心

## 9. 审计

### 9.1 记录范围

**A. Gateway HTTP 入口**（中间件自动）
- 所有变更类（POST/PATCH/PUT/DELETE）必记
- 读类仅白名单：登录、审计查询、审计导出

**B. 身份与授权**
```
user.login.success  user.login.failure  user.logout  user.switch_tenant
user.disabled  user.deleted
api_token.created  api_token.revoked  api_token.used
session.created  session.revoked  session.expired
authz.api.denied  authz.tool.denied  authz.path.denied
role.assigned  role.revoked
```

**C. LangGraph 运行时**（IdentityMiddleware + Guardrail）
```
thread.created  thread.deleted
skill.invoked  skill.installed  skill.removed
tool.called  tool.denied  tool.failed
knowledge.queried  knowledge.written
workflow.started  workflow.completed  workflow.failed
```

**不记录**：心跳、/api/me、静态资源、健康检查。

### 9.2 事件字段（与 §4 DDL 对齐）

```python
@dataclass
class AuditEvent:
    tenant_id:     int | None
    user_id:       int | None
    workspace_id:  int | None
    action:        str
    resource_type: str | None
    resource_id:   str | None
    ip:            str | None
    user_agent:    str | None
    result:        Literal["success", "failure"]
    error_code:    str | None
    duration_ms:   int | None
    metadata:      dict
    created_at:    datetime
```

**metadata 约定**
- `http`: `{method, path, status_code}`
- `tool`: `{name, args_summary}`
- `skill`: `{slug, version}`
- `authz`: `{required_permission, granted_permissions_count}`
- `actor_token_type`: `'jwt' | 'api_token'`

### 9.3 写入管线

```
AuditMiddleware
 → asyncio.Queue(maxsize=10000, 内存)
 → AuditBatchWriter 后台 task (每 1s 或 500 条)
 → Postgres executemany
```

**故障处理**
- 队列满：关键事件（登录/授权/写）同步写；非关键丢弃计数
- Postgres 挂：关键事件 fallback 写本地 `$DEER_FLOW_HOME/_system/audit_fallback/{date}.jsonl`；恢复后独立 job 回灌
- SIGTERM：drain 队列 timeout 5s

**写放大控制**：同事件 10s 内 > 100 次 → 合并写 + `metadata.count`。

**LangGraph 侧**：新增 `AuditHook` middleware，在 before/after tool call 调 Gateway 内部 `POST /internal/audit`（HMAC 签名），失败不阻塞。

### 9.4 脱敏

- HTTP body 不记录
- Tool args：
  - bash 命令 → 前 500 字截断
  - write_file → 路径 + size（**不记内容**）
  - MCP args → 整体截断 1KB；字段名含 `password/token/secret/key` 的 value 替换为 `***`
- IP 按配置可末字节脱敏（默认不脱）

### 9.5 查询与导出

- 筛选：`user_id / action / resource_type / result / date_from / date_to`
- 分页：游标 `(created_at DESC, id DESC)`
- 默认窗：最近 7 天；最大 90 天
- 导出 CSV：同步流式，单次最多 10 万条，超过 413
- 导出操作本身写审计 `audit.exported`（metadata 含筛选条件）

### 9.6 保留

- 默认 90 天（`AUDIT_RETENTION_DAYS`）
- 后台 job 每日归档到 `$DEER_FLOW_HOME/_system/audit_archive/{tenant_id}/{yyyy-mm}.jsonl.gz` 后删除
- 租户软删：审计保留 90 天后级联清

### 9.7 前端交互

- 表格字段：时间 / 操作者（email + token_type icon）/ action / 资源 / IP / 结果 / 详情
- 详情抽屉：完整 metadata JSON
- 虚拟滚动 + 服务端分页；默认 50/页
- 权限：`audit:read`（tenant）或 `audit:read.all`（platform）

### 9.8 明确排除

- ❌ 实时流（Kafka）/ SIEM 对接
- ❌ 变更前后 diff
- ❌ 异常检测
- ❌ 全文检索 / 图表化

### 9.9 不变量

1. 关键事件不丢（队列满时同步写）
2. 审计表不可变（DB GRANT 禁 UPDATE/DELETE）
3. 脱敏在入队前完成
4. 租户隔离同业务表

## 10. 迁移与上线

### 10.1 双轨策略：Feature Flag `ENABLE_IDENTITY`

- `false`（默认）：identity 中间件短路注入 anonymous-admin，SQL filter bypass，路径走旧结构 → 完全向后兼容
- `true`：强制鉴权 + 多租户隔离

### 10.2 阶段

**阶段 0 准备**：Alembic 建 identity schema + 10 表 + seed 数据，不触碰现有 threads/

**阶段 1 代码部署（flag=false）**：发布新镜像，IdentityMiddleware 短路；CI + smoke 验证无回归；可停留任意久

**阶段 2 数据迁移（run once）**
```
python -m scripts.migrate_to_multitenant --dry-run
python -m scripts.migrate_to_multitenant --apply
```
- 移动 threads/ → tenants/{default_tid}/workspaces/{default_wid}/threads/
- 原路径保留 symlink（24h 回滚窗口）
- 迁移 skills/custom + skills/user 到 tenants 子目录
- 回填任何现有业务元数据表的 tenant_id/workspace_id
- 写迁移报告 `_system/migration_report_{ts}.json`，审计 `system.migration.completed`

**阶段 3 启用身份（flag=true）**
- 设 `DEERFLOW_BOOTSTRAP_ADMIN_EMAIL` + OIDC provider 配置
- 重启 Gateway，bootstrap 自动建首个 platform_admin
- 验证登录 + 旧 thread 可访问
- 回滚窗口 24h：flag=false 即回退

**阶段 4 收尾**：移除 symlink，归档旧路径结构。

### 10.3 迁移脚本契约

`scripts/migrate_to_multitenant.py`

```
Usage: python -m scripts.migrate_to_multitenant [--dry-run|--apply]
                                                [--tenant-slug default]

Steps:
  1. Pre-check: PG/Redis 可达 · identity schema 存在 · default tenant/ws seeded
                · $DEER_FLOW_HOME 可写 · migration_lock 不冲突
  2. Enumerate: threads/* · skills/custom/* · skills/user/*
  3. Plan: 打印 source → target 映射 + 所需磁盘
  4. Execute (--apply):
     a. mkdir target 树
     b. mv 每个 thread + skills dir (rename 而非 copy, 回滚友好)
     c. 建 symlink 旧 → 新
     d. 每项写 audit system.migration.item.moved
     e. 写最终报告（计数/耗时/错误）
  5. Post-check: symlink 可读 · 目录 size 一致 · 抽样 thread 可打开
  6. Exit codes: 0 / 1 precheck / 2 partial (需人工)
```

**幂等**：`migration_lock` 标记 + 已迁移项跳过。

### 10.4 Bootstrap

启动时（Gateway 第一次起）跑 `bootstrap.py`，幂等：
1. seed 5 预置角色 + ~24 权限点 + role_permissions
2. 确保 default tenant + default workspace
3. 若 `DEERFLOW_BOOTSTRAP_ADMIN_EMAIL` 且无 platform_admin → 创建 user + 授 platform_admin + 加入 default tenant 为 tenant_owner + workspace_admin
4. 生成/加载 INTERNAL_SIGNING_KEY（Redis 多副本共享）

### 10.5 配置迁移

- 现有 `config.yaml` / `extensions_config.json` → 保留为 global 层，不动
- 不自动为 default 租户生成覆盖配置

### 10.6 依赖变更

```yaml
# docker/docker-compose.yaml 追加
postgres:
  image: postgres:16
  environment:
    POSTGRES_DB: deerflow
    POSTGRES_USER: deerflow
    POSTGRES_PASSWORD: $POSTGRES_PASSWORD
  volumes: [deerflow_pg:/var/lib/postgresql/data]
redis:
  image: redis:7-alpine
  volumes: [deerflow_redis:/data]
```

外接现有 PG/Redis：`DEERFLOW_DATABASE_URL` / `DEERFLOW_REDIS_URL`。

### 10.7 回滚策略

| 失败点 | 动作 |
|---|---|
| 代码部署回归 | 回滚镜像；identity schema 保留不动 |
| 迁移脚本中途失败 | 脚本反向（清 symlink + mv 回旧路径）；lock 标记失败 |
| 启用身份后重大问题 | flag=false + 重启 → symlink 保证旧路径可达 |
| DB 损坏 | PG 备份还原；文件目录不受影响 |

**不可回滚**：阶段 4 移除 symlink 后，必须保持 flag=true。Release note 明确说明。

### 10.8 灰度与监控

**v1 灰度**：单租户部署一次切；多租户 SaaS 场景的 `ENABLE_IDENTITY_TENANTS` 白名单留作扩展点。

**指标**
- `identity_login_total{provider, result}`
- `identity_authz_denied_total{resource_type}`
- `identity_session_active`
- `audit_queue_depth`
- `audit_write_failures_total`

**告警**
- 登录失败率 > 30% / 5min
- 审计队列深度 > 5000
- 授权拒绝激增

### 10.9 开发与 CI

- `make dev`：检测 flag，若 true 自动启 pg/redis + bootstrap
- CI 新增 `backend-identity-tests` job（pg:16 + redis:7 service + alembic upgrade + pytest）
- identity 子包覆盖率门槛 80%；核心授权路径 100%

### 10.10 升级路径文案（给用户）

```text
v1.x → v2.0 Upgrade (企业身份基座)

Impact: 默认关闭，可继续单用户使用新代码

A) 继续单用户:
   - docker compose up -d (flag 未设 → 默认 false)

B) 启用多租户:
   1. 部署 v2.0 + PG + Redis (flag=false)
   2. 运行迁移脚本 dry-run → apply
   3. 配置 OIDC + BOOTSTRAP_ADMIN_EMAIL
   4. flag=true + 重启
   5. 验证登录 + 旧数据可见
   6. 24h 后移除 symlink
```

### 10.11 明确排除

- ❌ 零停机切换身份
- ❌ 按租户白名单的分步灰度
- ❌ SCIM 用户导入
- ❌ 跨版本回迁
- ❌ 数据加密升级 / 密钥轮换工具

### 10.12 不变量

1. `flag=false` 时行为与 v1.x 完全一致（CI 守护）
2. 迁移脚本 dry-run 可预览，apply 可中断重试
3. bootstrap 幂等
4. symlink 阶段新旧路径读写都能成功

## 11. 测试策略

### 11.1 层级与目标

| 层级 | 工具 | 规模 | 目标 |
|---|---|---|---|
| Unit | pytest | ~200 | identity 子包 ≥ 80%，授权分支 100% |
| Integration | pytest + testcontainers | ~80 | 真 PG/Redis，路由/OIDC/Token/SQL filter/迁移 |
| Contract | pytest | ~30 | OpenAPI schema / 审计事件 schema / JWT claims |
| E2E | Playwright | ~15 | 登录→管理→建资源→调工具→审计 |

### 11.2 关键测试清单

（详细用例见 design 第 9 节；在 implementation plan 里展开为逐项 pytest 函数）

- **认证 (10)**：OIDC state/nonce/code 验证 · 首登落库 · refresh · session revoke · 登录锁定
- **API Token (7)**：明文仅一次返回 · hash 验证 · 过期/撤销 · scope · last_used 异步
- **RBAC 矩阵 (8)**：5 角色 × 核心动作 · 横向越权防护 · tenant 切换
- **SQL 过滤 (5)**：自动 filter · platform bypass · 写入校验 · 显式提权审计 · JOIN 覆盖
- **Guardrail Tool (5)**：权限拒绝 · 子 agent 继承 · 未声明默认 deny · MCP 注册权限 · 拒绝可对话
- **存储隔离 (8)**：路径派生 · 沙箱不泄露 · 跨租户拒绝 · symlink 读写 · skills 优先级 · config 合并
- **审计 (9)**：登录/拒绝事件 · 队列满 fallback · PG 挂 fallback · DB 权限强制 · 导出 · 脱敏
- **迁移 (5)**：dry-run / apply / 中断恢复 / 幂等 / 回滚
- **Feature Flag (3)**：false 零回归 / true 无 bootstrap email 报错 / 切换需重启

### 11.3 基础设施

- `tests/conftest.py` 提供 pg/redis container + db_session + OIDC mock fixture
- 身份 fixtures：`as_platform_admin / as_tenant_owner / as_workspace_admin / as_member / as_viewer / as_api_token / as_anonymous`
- 权限矩阵测试工具：`pytest.mark.parametrize` 覆盖 5 角色 × 核心路由 × 动作

### 11.4 性能守护（冒烟级）

- 登录 P95 < 300ms（500 并发）
- SQL filter 延迟差 < 10%
- 审计 1000 req/s × 60s → 队列水位 < 5000 + 零丢事件

### 11.5 安全测试

- 横向越权（path vs JWT）
- SQL 注入（审计筛选 / tenant slug）
- JWT / HMAC 伪造
- Token 泄漏（response 明文扫描）
- HMAC 重放（> 5min 拒绝）
- 登录爆破（IP 锁定）

### 11.6 CI 集成

- 新 job `backend-identity-tests`（pg:16 + redis:7 service + alembic upgrade + pytest + coverage 80%）
- 新 job `frontend-e2e-identity`（Playwright + OIDC mock + 截图 artifact）
- PR 门禁：identity 代码变更必有单测；RBAC 路径必有矩阵测试；Alembic 必有 up+down

### 11.7 手工测试（首次 release 前）

- 真 Okta / Azure AD / Keycloak 各一次完整登录
- 生产规模数据迁移（> 1000 threads）dry-run + apply
- docker-compose / k8s 两种部署各启一次
- 回滚演练：flag=true → flag=false → 旧 thread 可访问

### 11.8 明确排除

- ❌ chaos testing
- ❌ 长时间压测
- ❌ 合规测试（GDPR）
- ❌ i18n 测试

## 12. 关键文件清单

### 12.1 新增

```
backend/app/gateway/identity/
  __init__.py
  auth/
    __init__.py
    oidc.py           # OIDC login/callback
    jwt.py            # 内部 JWT 签发/验证
    api_token.py      # API Token 创建/verify
    session.py        # Redis session 管理
    dependencies.py   # FastAPI Depends (current_identity)
  rbac/
    __init__.py
    permissions.py    # 权限字典 + 扁平化
    roles.py          # 预置角色 seed
    decorator.py      # @requires
    routes.py         # 路由-权限映射
  admin/
    tenants.py users.py workspaces.py tokens.py
  audit/
    middleware.py     # Gateway AuditMiddleware
    writer.py         # AuditBatchWriter
    api.py            # 查询 + 导出路由
    redact.py         # 脱敏
  models/
    base.py           # TenantScoped / WorkspaceScoped mixin
    tenant.py user.py role.py permission.py
    workspace.py token.py audit.py
    session.py        # Session event listener (auto filter)
  middlewares/
    identity.py       # IdentityMiddleware
    tenant_scope.py   # TenantScopeMiddleware
  config.py           # OIDC providers + 其他 identity config
  bootstrap.py        # seed + first admin

backend/packages/harness/deerflow/agents/middlewares/
  identity.py         # LangGraph IdentityMiddleware (HMAC 验签 + 写 state)
  audit.py            # LangGraph AuditHook

backend/alembic/
  env.py
  versions/20260421_0001_identity_schema.py

scripts/
  migrate_to_multitenant.py

frontend/src/app/(public)/
  login/page.tsx auth/oidc/[provider]/callback/page.tsx logout/page.tsx
frontend/src/app/(admin)/admin/
  layout.tsx tenants/ users/ roles/ workspaces/ tokens/ audit/ profile/

frontend/src/core/identity/
  hooks.ts            # useIdentity / useSwitchTenant
  components.tsx      # RequirePermission / SessionExpiredModal
  api.ts              # /api/me 等封装

config/identity.yaml.example

docker/docker-compose.yaml  # 追加 postgres/redis
```

### 12.2 修改

```
backend/packages/harness/deerflow/skills/loader.py
  - 参数新增 tenant_id / workspace_id
  - 扫描目录改为 tenants/{tid}/{custom, workspaces/{wid}/user}
  - 符号链接父目录校验

backend/packages/harness/deerflow/agents/middlewares/
  guardrail.py        # before_tool_call 增 TOOL_PERMISSION_MAP 检查
  thread_data.py      # 路径从 identity 派生
  sandbox.py          # 挂载点使用新路径

backend/app/gateway/__init__.py (或 main.py)
  # 注册 AuditMiddleware / TenantScopeMiddleware / IdentityMiddleware

frontend/src/app/layout.tsx
  # 全局 SessionExpiredModal
frontend/middleware.ts
  # /admin/* 跳转 /login 守卫

.github/workflows/backend-unit-tests.yml
  # 新 job: backend-identity-tests
```

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Alembic 迁移在生产 PG 冲突 | 启动失败 | 独立 identity schema；先跑 dry-run；迁移脚本反向可清理 |
| SQL 自动过滤漏覆盖某个表 | 数据泄漏 | 所有业务 model 强制继承 `TenantScoped`；CI 脚本扫描 model 无 `tenant_id` 的告警 |
| Guardrail 改动破坏现有 agent | 运行时崩溃 | `ENABLE_IDENTITY=false` 时短路保持旧行为；独立测试 fixture |
| OIDC provider 不稳定 | 无法登录 | API Token 作为兜底；登录失败率告警 |
| 迁移期 symlink 遗失 | 旧路径找不到数据 | 迁移报告留存；回滚脚本可重建 symlink |
| 审计表膨胀 | DB 压力 | 90d 保留 + 归档 job；索引预建 |
| 权限缓存不一致 | 变更后仍用旧权限 | 变更时清 Redis + session 标记刷新；UI 提示重新登录 |
| HMAC 密钥泄漏 | LangGraph 被注入伪身份 | 密钥只存环境变量 + Redis；不入日志；轮换文档留后 |
| K8s 多副本 bootstrap 并发 | 重复建 default | bootstrap 内部加 advisory lock |

## 14. 后续项目接口

本 P0 为以下子项目预埋接口：

- **P1 细粒度 RBAC**：`permissions` 表已可扩展；资源实例级 ACL 可加新表 `resource_permissions(resource_type, resource_id, subject_type, subject_id, permission_id)`
- **P2 知识库**：`tenants/{tid}/shared/` 目录、`knowledge:*` 权限点、MCP adapter 权限声明
- **P3 SkillHub**：workspace ≈ SkillHub namespace；`workspace_admin` ≈ namespace OWNER；loader.py 已可扩展为从 registry 拉取
- **P4 团队协作**：workspace_members 已具备；未来加 `thread_shares` / `comments`
- **P5 工作流编排 UI**：`workflow:*` 权限点；workflow 归属 workspace；作者/只读/可执行对应 admin/member/viewer

## 15. 验收清单

P0 交付可验收时满足：

- [ ] Alembic 迁移成功，`identity` schema 含 10 表 + seed
- [ ] `make dev` 可在 `ENABLE_IDENTITY=false` 启动，功能与 v1.x 完全一致（CI 绿）
- [ ] `make dev` 可在 `ENABLE_IDENTITY=true` 启动，OIDC 登录走通
- [ ] 迁移脚本 dry-run + apply 可演示（至少 100 threads）
- [ ] 管理后台 14 页全部可用
- [ ] 5 角色 × 核心动作 RBAC 矩阵测试全绿
- [ ] Guardrail 升级后现有 smoke 测试通过 + 新 tool 权限测试绿
- [ ] 审计日志：登录/授权/工具调用三类事件可在 UI 查询
- [ ] 路径隔离：跨租户越权尝试 403 + 审计
- [ ] 回滚演练成功：flag=true → false → 旧 thread 仍可访问
- [ ] 真实 Okta / Azure AD / Keycloak 各自登录通过（至少一次）
- [ ] 全部 CI job 绿；identity 覆盖率 ≥ 80%
