# 注册码注册流程 设计文档

**日期**：2026-04-29
**作者**：lydoc + Claude（brainstorm）
**目标受众**：执行 plan 的 agent / 自己重读时的人
**状态**：设计完成，待 review

---

## 1. 目标

为 deer-flow 的 identity 子系统补一条**自助注册入口**：tenant_owner 生成一次性注册码 → 把链接发给候选人 → 候选人凭码完成注册 → 自动加入大群（tenant）和 default 小群（默认 workspace）→ 后续业务小群由 workspace_admin 显式添加。

这是当前系统第一个支持"管理员之外的人进入系统"的端点。在此之前，新用户只能通过 OIDC（需 IdP 配置）或被 admin 用 password 创建（user 必须先存在）进入。

## 2. 范围（Scope）

### 包含

- 一张 `registration_codes` 新表（identity schema）
- Alembic 迁移 `0006`
- 一个新 role：`workspace_member`（workspace scope）
- bootstrap 注册新 role + 把 role-permission 绑定写入 `PREDEFINED_ROLE_PERMISSIONS`
- 三个 admin 端点：`POST/GET/DELETE /api/tenants/{tid}/registration-codes`
- 一个公开端点：`POST /api/auth/register`
- 一个 env 配置：`REGISTRATION_CODE_EXPIRES_DAYS`（默认 7，范围 1-90）
- 后端单测（admin CRUD + 注册流程 + 边界）

### 不包含（已知限制）

- **前端注册页面**：UI 部分留待后续单独立项；本期只做后端，admin 用 curl/Postman 验证即可
- **业务 workspace 的 thread/data 共享**：当前 thread 命名空间是 user 级（`("threads", "tenant:{tid}", "workspace:{wid}", "user:{uid}")`），workspace 内成员之间不共享 thread。本期不动这个隔离层。需要"团队成员看到团队数据"的产品形态时，独立立项做 identity v2 的隔离改造。
- **skill publish 审核**：`skill:publish` 权限本期**不分配**给 `workspace_member`，等审核机制做完再放开
- **email 通知**：注册码链接由 admin 通过 IM/邮件等外部渠道分发，系统不直接发邮件
- **码 reveal 端点**：码只在创建时返回一次明文，丢失只能 revoke 重发

## 3. 心智模型

```
租户 = 一个部署 = 一个大群（tenant_owner = 大群管理员）
  │
  ├── default 小群（workspace_id=1，bootstrap 已建）
  │     └── 谁在里面：所有进了大群的人都自动在这里
  │
  ├── 项目 A 小群（workspace #2）
  │     └── 谁在里面：被 workspace_admin 拉进来的人
  │
  └── 项目 B 小群（workspace #3）
        └── ...
```

### 入职流程

1. tenant_owner 调 `POST /api/tenants/{tid}/registration-codes` 生成码
2. 后端返回 **一次性明文码**（DB 仅存 bcrypt hash）
3. tenant_owner 通过外部渠道把链接 / 码发给候选人
4. 候选人调 `POST /api/auth/register {code, email, password, display_name?}`
5. 后端校验码 → 建 `User` + `Membership(tenant_id=1)` + `WorkspaceMember(workspace_id=1, role=workspace_member)`，把码标记为 `accepted` → 设置 session cookie，登录完成
6. 候选人现在已经是大群 + default 小群的成员；后续业务小群归属由 `workspace_admin` 用现有 `POST /api/tenants/{tid}/workspaces/{wid}/members` 端点添加

### 不变量

- 注册码只绑 tenant_id，不绑 workspace_id、不绑 email、不绑 role
- 一张码仅能成功使用一次（用过 → status=accepted，不可再用）
- 过期由 env 全局控制，admin 创建时不可调
- email 全局唯一（schema 既有约束）；冲突直接返回 409，不做"激活已有 shell user"的合并逻辑

## 4. 数据模型

### 4.1 新表：`identity.registration_codes`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | BigInteger | PK, autoincrement | |
| `tenant_id` | BigInteger | FK → `identity.tenants.id` ON DELETE CASCADE, NOT NULL, indexed | 码绑定的大群 |
| `creator_id` | BigInteger | FK → `identity.users.id` ON DELETE CASCADE, NOT NULL | 谁创建的（tenant_owner） |
| `code_hash` | String(60) | NOT NULL | bcrypt hash（固定 60 字符），DB 永不存明文 |
| `code_prefix` | String(8) | NOT NULL | 明文码前 8 位（脱敏标识，便于 list 时辨认） |
| `status` | SmallInteger | NOT NULL, server_default 0 | 0=pending, 1=accepted, 2=expired, 3=revoked |
| `expires_at` | DateTime(timezone) | NOT NULL | 创建时 = now + env 配置的天数 |
| `accepted_by` | BigInteger | FK → `identity.users.id` ON DELETE SET NULL, nullable | 用码的人（注册成功后回填） |
| `accepted_at` | DateTime(timezone) | nullable | 注册成功时间戳 |
| `created_at` | DateTime(timezone) | NOT NULL, server_default `now()` | |

无 unique 约束（不同明文码理论可能 hash 碰撞，且明文不存即 unique 没意义）。靠 hash 列查找 → list 时 admin 端按 prefix 模糊匹配辅助识别。

### 4.2 模型放置

- 新文件：`backend/app/gateway/identity/models/registration_code.py`
- `models/__init__.py` 添加 `from .registration_code import RegistrationCode` + `__all__` 添加 `"RegistrationCode"`

### 4.3 不引入 `TenantScoped` mixin？

引入。`tenant_id` 列存在，应该按现有 `TenantScoped` 模式纳入 auto-filter。但 admin 端点已经用 `@requires("...", "tenant")` 守住跨租户，注册端点是公开端点（无 identity），不会触发 auto-filter。**结论：声明 `TenantScoped` mixin 以保持一致性，跨租户写入由 mixin 的 insert guard 兜底**。

## 5. Role 体系扩展

### 5.1 新 role：`workspace_member`

`bootstrap.py` 的 `PREDEFINED_ROLES` 追加：

```python
("workspace_member", "workspace", "Workspace member (basic usage of own resources)"),
```

### 5.2 权限组

`PREDEFINED_ROLE_PERMISSIONS` 追加：

```python
("workspace_member", "workspace"): [
    "thread:read", "thread:write", "thread:delete",
    "skill:read", "skill:invoke",
    "knowledge:read", "knowledge:write",
    "workflow:read", "workflow:run",
    "settings:read",
],
```

**对照 `_WORKSPACE_PERMS` 的对照表**：

| Permission | 给 workspace_member？ | 理由 |
|---|---|---|
| thread:read / write / delete | ✅ | 看/写/删自己的 thread（user 级隔离已天然限制为自己的） |
| skill:read | ✅ | 看 workspace 可用 skill |
| skill:invoke | ✅ | 用 skill 是核心使用功能 |
| skill:publish | ❌ | 审核机制未实现，本期不放开 |
| skill:manage | ❌ | 管理类，留给 workspace_admin |
| knowledge:read / write | ✅ | 写自己的知识 |
| knowledge:manage | ❌ | 整库管理，留给 workspace_admin |
| workflow:read / run | ✅ | 跑预设 workflow |
| workflow:manage | ❌ | 管理类 |
| settings:read | ✅ | 看 workspace 设置 |
| settings:update | ❌ | 改设置是管理类 |

### 5.3 bootstrap 行为

bootstrap 是 idempotent 的，新增 role 在重启时会自动 ensure 注册（已有的 `ensure_roles` 逻辑覆盖）。无需 alembic 迁移操作 role/permission，bootstrap 处理。

## 6. 配置

### 6.1 env 变量

| 名称 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `REGISTRATION_CODE_EXPIRES_DAYS` | int | 7 | 码的过期天数。范围 1-90，超出范围按默认 7 处理 |

`identity/settings.py::IdentitySettings` 增加 `registration_code_expires_days: int` 字段，`get_identity_settings()` 工厂里读取并裁剪到 [1, 90]。

### 6.2 不新增 env

不引入 `REGISTRATION_ENABLED` 类总开关。"码即授权"——admin 不发码就没人能注册。

## 7. API 设计

### 7.1 `POST /api/tenants/{tid}/registration-codes`（admin）

**权限**：`@requires("membership:invite", "tenant")`

**请求**：空 body（或 `{}`）

**响应 201**：
```json
{
  "id": 42,
  "tenant_id": 1,
  "code": "abc123def456...XYZ",   // 仅创建时返回的明文，唯一一次
  "code_prefix": "abc123de",
  "expires_at": "2026-05-06T10:00:00+00:00",
  "created_at": "2026-04-29T10:00:00+00:00"
}
```

**实现要点**：
- 用 `secrets.token_urlsafe(32)` 生成明文码（≈43 字符）
- bcrypt hash 写入 `code_hash`
- 明文前 8 位写入 `code_prefix`
- `expires_at = now() + timedelta(days=settings.registration_code_expires_days)`
- `creator_id = caller_user_id`
- 响应 schema 上 `code` 字段**仅此一次返回**，list 端点不返回

### 7.2 `GET /api/tenants/{tid}/registration-codes`（admin）

**权限**：`@requires("membership:read", "tenant")`（与 list_invitations 归档计划一致——读权限可以更宽）

**Query**：`limit`（默认 50，上限 200），`offset`（默认 0）

**响应 200**：
```json
{
  "items": [
    {
      "id": 42,
      "tenant_id": 1,
      "code_prefix": "abc123de",
      "status": 0,
      "expires_at": "2026-05-06T10:00:00+00:00",
      "accepted_by": null,
      "accepted_at": null,
      "created_at": "2026-04-29T10:00:00+00:00"
    }
  ],
  "total": 1
}
```

**注意**：`code_hash` 永远不在响应里。`code_prefix` 用作 admin 视觉识别。

### 7.3 `DELETE /api/tenants/{tid}/registration-codes/{rid}`（admin）

**权限**：`@requires("membership:invite", "tenant")`

**行为**：
- 码不存在 / 不属于该 tenant → 404
- status != pending（已 accepted/expired/revoked）→ 409 "only pending codes can be revoked"
- pending → status 改为 3（revoked），返回 204

**不真正物理删除**——保留审计痕迹。

### 7.4 `POST /api/auth/register`（公开）

**权限**：无（匿名访问）

**请求**：
```json
{
  "code": "abc123def456...XYZ",
  "email": "newuser@example.com",
  "password": "atleast8chars",
  "display_name": "New User"   // 可选
}
```

**校验**（按顺序）：
1. password 长度 >= 8 → 否则 422
2. email 格式合法（复用 `_EMAIL_RE`）→ 否则 422
3. 查 `registration_codes`：**先按 `code_prefix == provided_code[:8] AND status == pending` 过滤候选**（这一步是强制安全要求，参见 §11），再对候选逐个 bcrypt.checkpw 比对 → 找不到 / hash 不匹配 → 404 "invalid registration code"
4. 码已 accepted (1) → 410 "code already used"
5. 码已 revoked (3) → 410 "code has been revoked"
6. 码已过期（`expires_at < now()`）→ 把 status 标 2 → 410 "code has expired"
7. email 已存在（`User.email == email` 命中）→ 409 "email already registered"

**全部通过后**（在同一个 DB session 事务内）：
- 创建 `User(email, display_name=display_name or email.split('@')[0], status=1, password_hash=bcrypt(password))`
- 创建 `Membership(user_id=user.id, tenant_id=code.tenant_id)`
- 查询并加入 default workspace：`select(Workspace).where(Workspace.tenant_id == code.tenant_id).order_by(Workspace.id.asc()).limit(1)` 取第一个 workspace（即 bootstrap 建的 default）；查 `workspace_member` role_id → 创建 `WorkspaceMember(user_id, workspace_id=ws.id, role_id=member_role_id)`
- 把码标记 accepted：`status = 1, accepted_by = user.id, accepted_at = now()`
- `await db.commit()`
- 调用 `resolve_active_tenant` + `build_identity_for_user` 构造 identity（参考 `password_login` 实现）
- 创建 session（`rt.session_store.create`）+ 签 access token + 设置 cookie
- 返回 201：`{"status": "ok", "email": "..."}`

**响应 201 body**：
```json
{
  "status": "ok",
  "email": "newuser@example.com"
}
```

**Cookie**：`deerflow_session` HttpOnly，与 `password_login` 一致（同 `rt.cookie_secure` / `samesite=lax` / `max_age=rt.access_ttl_sec`）。

### 7.5 性能注解

7.4 步骤 3 的"遍历 pending 码逐个 bcrypt 比对"在码数量爆炸时（>1000 pending）会变慢。本期不优化——自托管单租户场景下 pending 码数量预计 <100。如果将来需要优化，方案是：码生成时除了 hash 还存一个 fast lookup 字段（如 sha256 prefix），先用 prefix 缩到 1-2 个候选再走 bcrypt。

## 8. 文件清单

| 操作 | 文件 | 责任 |
|---|---|---|
| 创建 | `backend/app/gateway/identity/models/registration_code.py` | `RegistrationCode` ORM 模型（含 `TenantScoped` mixin） |
| 修改 | `backend/app/gateway/identity/models/__init__.py` | 重导出 `RegistrationCode` |
| 创建 | `backend/alembic/versions/20260429_0006_registration_codes.py` | 建表迁移 |
| 修改 | `backend/app/gateway/identity/settings.py` | 加 `registration_code_expires_days` 字段 + env 读取 |
| 修改 | `backend/app/gateway/identity/bootstrap.py` | 加 `workspace_member` role + role-permission 绑定 |
| 修改 | `backend/app/gateway/identity/routers/admin_writes.py` | 三个 admin 端点 + schemas |
| 修改 | `backend/app/gateway/identity/routers/auth.py` | `POST /register` 端点 + RegisterIn schema |
| 创建 | `backend/tests/identity/test_registration_codes.py` | admin CRUD + 边界测试 |
| 创建 | `backend/tests/identity/test_registration.py` | 注册流程 + 边界测试 |
| 修改 | `backend/CLAUDE.md` | identity 章节追加 "Registration code flow" 小节 |

## 9. 测试矩阵

### 9.1 admin CRUD（`test_registration_codes.py`）

| Case | 期望 |
|---|---|
| `tenant_owner` 创建码 → 返回 201 + 明文码 + prefix | 通过 |
| 普通 member（无 invite 权限）→ 创建码 | 403 |
| 创建码后 list → 至少包含刚创建的，且无 `code` 字段 | 通过 |
| 匿名 list → | 401 |
| revoke pending 码 → 204；再 list 时 status=3 | 通过 |
| revoke 不存在的码 → | 404 |
| revoke 已 accepted 码 → | 409 |
| 普通 member revoke → | 403 |

### 9.2 注册流程（`test_registration.py`）

| Case | 期望 |
|---|---|
| 用合法 pending 码注册 → 201 + cookie 设置 + DB 中 user/membership/workspace_member 都建好 + 码 status=1 + accepted_by 回填 | 通过 |
| 同一码二次使用 → | 410 |
| 不存在的码 → | 404 |
| 弱密码（<8 字符）→ | 422 |
| 非法 email 格式 → | 422 |
| 过期码（expires_at 在过去）→ 码自动标 2 + 返回 | 410 |
| revoked 码（status=3）→ | 410 |
| email 已注册 → | 409 |
| 注册后 user 在 default workspace 里且 role=`workspace_member` | 通过 |
| 注册后能用返回的 cookie 调 `/api/me` 拿到正确身份 | 通过（smoke） |

### 9.3 回归

`make identity-test` 全绿。

## 10. 影响面 & 兼容性

- **新表**：alembic 0006，向下兼容（drop_table 干净回滚）
- **新 role**：bootstrap 自动注册，幂等。已有部署重启后 ensure_roles 把 `workspace_member` 写入。**已有 user 不会自动获得这个 role**——只对未来扫码注册的人生效
- **新 env 变量**：未设置时使用默认 7 天，无破坏
- **新 admin 端点**：完全增量
- **`/api/auth/register`**：之前不存在，新增，对老调用者无影响
- **identity 子系统总开关**：仍受 `ENABLE_IDENTITY` 控制。flag off 时 register 路由不应注册（与 auth.py 现有路由一致）

## 11. 安全审视

| 风险 | 缓解 |
|---|---|
| 码 brute force | bcrypt cost ≥ 12（`DEERFLOW_BCRYPT_COST`）+ 码本身 token_urlsafe(32) ≈ 256 bit 熵；遍历 pending 码必须按 prefix 过滤后再 bcrypt，否则 DOS 风险（攻击者发送任意 code 触发服务器对所有 pending 码做 bcrypt）。**实现必须先按 `code_prefix == provided_code[:8]` 过滤**再 bcrypt 候选 |
| 码泄漏 | admin 责任。系统层面：码只在创建时返回一次；DB 仅存 hash；revoke 端点支持紧急止血 |
| 重放（同码并发使用）| 注册端点 step 3 找到候选码后，**用 `SELECT ... FOR UPDATE` 锁该行**，再依次校验 status / expires_at（step 4-6）。状态变更 + Membership/WorkspaceMember 写入 + commit 在同一事务内。并发的第二个请求会等到第一个 commit 后读到 status=1 → 返回 410。简化做法（自托管小群）：可省略 FOR UPDATE，依赖 user.email unique 约束兜底——并发的第二个请求会 IntegrityError，捕获后转 409。**实现选其一并明确注释**。 |
| 时序攻击（404 vs 410 信号差）| 接受。攻击者无法从中提取明文码（256 bit 不可枚举） |
| 过期自动转 status | 在请求路径里 lazy 触发（步骤 6）。后台没有定时清扫——本期可接受，之后可选加 cron |

## 12. 后续工作（不在本期）

- 前端注册页（POST /api/auth/register 表单）
- 业务 workspace 共享 thread/data（identity v2）
- skill publish 审核机制（启用 `skill:publish` 权限）
- email 通知（注册码链接通过邮件发送）
- 码批量生成 / 导出
- 码审计事件接入（M6 audit pipeline）

## 13. 决策日志

| 决策 | 选项 | 选定 | 理由 |
|---|---|---|---|
| 范围 | A 完整 / B 后端 / C 极简 | C → 调整 | 自托管单租户最小可用 |
| 码绑定 | A 纯白 / B 半绑 / C 全绑 | A 纯白 | 心智最简 |
| 全局开关 | A 永远开 / B 默认开 / C 默认关 | A | 码即授权 |
| 码存储 | A hash / B 明文 / C 折中 | A hash | 安全标准 |
| admin 端点 | A 三件套 / B 二件套 / C 单端点 | A | list 几乎零成本 |
| 注册输入 | A 最小 / B 标准 / C 含 username | B | email 是登录主键 |
| email 冲突 | B1 直接 409 / B2 激活 shell user / B3 不区分 | B1 | YAGNI |
| 过期 | A 必填 / B 默认 7 / C 绝对时间 / D 24h | env 配置 | 全局唯一来源 |
| 心智模型 | 多租户 SaaS / 自托管单租户 | 自托管单租户 | 业务定位 |
| workspace 含义 | 共享工作台 / 个人沙盒 | 大群/小群类比，default 小群所有人都进 | 用户讲清后锁定 |
| 入职流程 | 扫码进 workspace / 扫码进 tenant 后 admin 加 workspace | **扫码进 tenant + 自动进 default workspace** | 等价于 H2 |
| role 变种 | A 单 workspace_member / B 双 role | A | YAGNI，本期单一 role 够用 |
| 路径 | 1 单文件 router / 2 独立 router 文件 | 1 | admin_writes.py 已是该职责 |

---

## 附录 A：相对此前 invitation plan 的方向变化

此前曾有过一份 `2026-04-28-invitation-registration` plan + spec（已于 2026-04-29 删除，未实施）。本设计与其方向变化如下：

| 维度 | 旧 invitation plan | 本设计 |
|---|---|---|
| 资源名 | invitations | registration_codes |
| 码绑定 | tenant + email | 仅 tenant |
| 码存储 | 明文 | bcrypt hash |
| 端点路径 | `/api/tenants/{tid}/invitations` | `/api/tenants/{tid}/registration-codes` |
| 注册输入 | invitation_token + password + display_name | code + email + password + display_name |
| 创建后续动作 | 仅 Membership | Membership + WorkspaceMember(default, role=workspace_member) |
| 过期参数 | admin 输入 | env 配置 |
| 新建 role | 无 | 新建 `workspace_member` |

旧文档已删除，本设计为唯一来源。
