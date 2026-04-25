# Skill Mgmt v2 完整设计文档

**日期**：2026-04-25
**范围**：技能广场前端、CLI 推送流程、Org Key 生命周期、Token 职责分离
**前置文档**：`2026-04-25-skill-agent-i18n-design.md`（DB schema、文件系统、load_skills 已在该文档定义）
**状态**：设计确认，待实施

---

## 一、设计决策汇总

本文档基于以下已确认的设计决策：

| 维度 | 决策 |
|---|---|
| Private skill 运行身份 | 用户自己的 identity，无额外 token |
| Org skill 运行身份 | 用户 identity 做 RBAC 检查，Gateway 注入租户 org key 给外部资源调用 |
| Org key 数量 | 每租户一个，共享给所有 org skill |
| Org key 有效期 | 可配置（30–730 天）或永久；永久 = 系统每 365 天静默自动轮换 |
| Org key 对用户不可见 | 用户永远看不到明文，管理员只看前缀 + 元数据 |
| 密钥过期错误提示 | "访问权限过期，请联系管理员" |
| 技能入口 | 左侧边栏新增"技能"入口 |
| 技能广场命名 | 技能广场（不是技能市场） |
| 技能广场可见性 | public + org 统一展示，有权限就可见，不强调分类标签 |
| 技能绑定粒度 | 绑定到当前 thread，不跨 thread |
| 加载方式 | manifest 声明参数：有参数弹配置表单，无参数一键绑定 |
| 技能来源 | 管理员直接发布 + 开发者 CLI 提交（`pending_review` → 管理员审批） |
| CLI 推送认证 | 开发者自己的 API token，需含 `skill:publish` scope |
| 推送格式校验 | CLI 端 pre-publish 本地校验 + Gateway 服务端二次校验，校验失败不进审批队列 |
| 审批流程 | 简单审批（通过/拒绝 + 拒绝原因），无沙箱测试 |
| Token 职责分离 | 模型调用 key（LLM Provider key，租户级）vs CLI 推送 token（用户级 API token + `skill:publish` scope） |

---

## 二、Token 职责分离

### 2.1 两种 Token 的性质

系统中有两类不同性质的"token"，必须明确区分：

**模型调用 Key（LLM Provider Key）**

- 用途：调用 OpenAI / Anthropic / 其他 LLM API 的计费凭证
- 归属：租户级别，整个租户共享一个
- 存储：Gateway env var（`OPENAI_API_KEY` 等），未来迁移到 admin portal 的 LLM Provider 配置页
- 泄露影响：计费损失 + 滥用，影响整个租户
- 轮换责任：租户管理员
- 用户可见性：对普通用户完全不可见

**CLI 推送 Token（用户级 API Token）**

- 用途：认证开发者身份，向 Gateway 推送技能
- 归属：用户级别，每个开发者自己持有
- 存储：现有 `identity.api_tokens` 表（`dft_*` 格式，bcrypt hash）
- 泄露影响：仅限该用户权限范围内的技能操作
- 轮换责任：开发者自己
- 用户可见性：用户可在个人中心创建/查看/吊销

### 2.2 新增 `skill:publish` Scope

在现有 API token scope 体系中新增：

```
skill:publish   → 允许持有者向 Gateway 推送技能（进入 pending_review 状态）
                  不授予发布、审批、管理权限
```

权限范围约束：
- 持有 `skill:publish` 的 token 只能推送技能，不能发布或修改已发布技能
- 推送的技能自动绑定到 token 所属用户（`created_by = token.user_id`）
- 推送 private skill 不需要审批，直接生效
- 推送 org/public skill 进入 `pending_review`，需管理员审批

用户在个人中心创建 API token 时，可以选择是否勾选 `skill:publish` scope。

---

## 三、Org Key 生命周期

### 3.1 有效期模型

```
创建时设定：
  ├── 固定有效期（30–730 天）
  │     到期前 30 天：审计事件 org_key.expiring_soon → 站内通知管理员
  │     到期后：所有 org skill 调用立即失败
  │     用户侧错误：「访问权限过期，请联系管理员」
  │
  └── 永久（no_expiry = true）
        安全兜底：系统后台每 365 天静默轮换一次
        轮换过程：生成新 key → 原子替换 → 旧 key 立即作废
        无需管理员介入，用户无感知
        轮换完成后：审计事件 org_key.auto_rotated
```

### 3.2 DB 字段补充（对前置文档的扩展）

在 `identity.org_api_keys` 表上补充字段：

```sql
ALTER TABLE identity.org_api_keys ADD COLUMN no_expiry        BOOLEAN    NOT NULL DEFAULT false;
ALTER TABLE identity.org_api_keys ADD COLUMN auto_rotate_at   TIMESTAMPTZ;
ALTER TABLE identity.org_api_keys ADD COLUMN last_rotated_at  TIMESTAMPTZ;
-- auto_rotate_at = created_at + interval '365 days'（仅 no_expiry=true 时有效）
-- 后台任务检查 auto_rotate_at <= now() 触发静默轮换
```

### 3.3 自动轮换后台任务

```python
# backend/app/gateway/identity/tasks/org_key_rotation.py

async def rotate_expired_permanent_keys():
    """
    每小时运行一次。
    找出 no_expiry=true 且 auto_rotate_at <= now() 的 key，
    生成新 key，原子替换，发出审计事件。
    """
    keys = await db.fetch_all(
        "SELECT * FROM identity.org_api_keys "
        "WHERE no_expiry = true AND auto_rotate_at <= now() AND revoked_at IS NULL"
    )
    for key in keys:
        new_plaintext, new_hash, new_prefix = generate_org_key()
        await db.execute(
            "UPDATE identity.org_api_keys "
            "SET prefix=:prefix, token_hash=:hash, "
            "    auto_rotate_at=now()+interval'365 days', last_rotated_at=now() "
            "WHERE id=:id",
            {"prefix": new_prefix, "hash": new_hash, "id": key.id}
        )
        await emit_audit(AuditEvent.ORG_KEY_AUTO_ROTATED, key_id=key.id, tenant_id=key.tenant_id)
```

### 3.4 Org Key 在 Skill 调用中的注入流程

```
用户调用 org skill
  │
  ├─ Gateway 检查用户有 skill:invoke 权限
  ├─ Gateway 读取 skill manifest → requires_org_key: true
  ├─ Gateway 查询 identity.org_api_keys WHERE tenant_id = ? AND revoked_at IS NULL
  │
  ├─ [无有效 key] → 400 错误：「访问权限过期，请联系管理员」
  ├─ [key 已过期] → 400 错误：「访问权限过期，请联系管理员」
  │
  └─ [key 有效]
       → 解密 plaintext（从安全存储）
       → 注入 skill env: {ORG_ACCESS_KEY: plaintext}
       → 调用技能
       → 审计记录：actor=user_42, via_org_key=key_prefix_xxx
       → plaintext 不写入任何日志
```

---

## 四、CLI 技能推送流程

### 4.1 CLI 命令规范

```bash
# 本地开发调试
deerflow skill test [--thread-id <id>]    # 本地绑定到测试 thread，不推送
deerflow skill validate                    # 只跑格式校验，不推送

# 推送到 Gateway
deerflow skill publish                     # 推送当前目录的技能
deerflow skill publish --scope private     # 强制推送为 private（默认）
deerflow skill publish --scope org         # 推送为 org skill（需 tenant ADMIN 批准）
deerflow skill publish --scope public      # 推送为 public（需 platform ADMIN 批准）

# 查看状态
deerflow skill status <skill-name>         # 查看审批状态
deerflow skill list                        # 列出自己推送的技能

# 认证配置
deerflow auth login                        # 交互式配置 API token
deerflow auth set-token <dft_...>          # 直接设置 token
```

### 4.2 Pre-publish 本地校验（CLI 端）

推送前在本地执行，失败则阻止推送：

```
校验项：
  ├── manifest.yaml 存在且 schema 合规
  │     ├── name: 非空，只含 [a-z0-9-]，长度 ≤ 64
  │     ├── version: 合法 semver（如 1.0.0）
  │     ├── scope: 'public' | 'org' | 'private'
  │     ├── description: 非空
  │     └── author: 非空
  │
  ├── SKILL.md 存在且 frontmatter 完整
  │     ├── name 与 manifest.yaml 一致
  │     └── description 非空
  │
  ├── requires_tools 中每个工具名在已知工具列表中
  ├── requires_org_key: true 时，env 中必须有 source=org_key 的条目
  └── env 中所有 required=true 的变量都有 source 声明
```

### 4.3 Gateway 服务端二次校验

收到推送请求后，Gateway 重新执行所有校验（客户端不可信）：

```python
# backend/app/gateway/identity/routers/skills.py

@router.post("/api/skills/publish")
@requires("skill:publish", scope="user")
async def publish_skill(payload: SkillPublishRequest, identity: Identity = Depends(get_identity)):
    # 1. 服务端重新执行 manifest schema 校验
    validate_manifest(payload.manifest)
    validate_skill_md(payload.skill_md)

    # 2. 检查同名同版本是否已存在
    existing = await db.fetch_one(
        "SELECT id FROM identity.skill_registry WHERE name=:name AND version=:version AND tenant_id=:tid",
        {"name": payload.manifest.name, "version": payload.manifest.version, "tid": identity.tenant_id}
    )
    if existing:
        raise ConflictError("该版本已存在，请升级版本号")

    # 3. 写文件系统（按 scope 写到对应路径）
    storage_path = resolve_skill_path(payload.manifest.scope, identity, payload.manifest)
    write_skill_files(storage_path, payload.manifest, payload.skill_md)

    # 4. 写 skill_registry（status 根据 scope 决定）
    status = "active" if payload.manifest.scope == "private" else "pending_review"
    await db.execute(INSERT_SKILL_REGISTRY, {..., "status": status, "created_by": identity.user_id})

    # 5. 审计
    await emit_audit(AuditEvent.SKILL_PUBLISHED, skill_name=payload.manifest.name, status=status)

    return {"skill_id": new_id, "status": status}
```

### 4.4 审批流程

管理员在 `/admin/skills` 查看 `pending_review` 状态的技能：

```
审批操作：
  ├── 通过 → status = 'active'，is_default 自动设为 true（如果该 name 无其他 active 版本）
  └── 拒绝 → status = 'rejected'，写入 rejection_reason
              → 审计事件 skill.review.rejected
              → 推送者可在 CLI 查看拒绝原因：deerflow skill status <name>
```

`skill_registry` 表补充字段（覆盖前置文档中 `status IN ('active','archived')` 的定义，扩展为四值）：

```sql
-- 先 DROP 旧 CHECK，再重建（Alembic migration 中执行）
ALTER TABLE identity.skill_registry DROP CONSTRAINT IF EXISTS skill_registry_status_check;
ALTER TABLE identity.skill_registry
  ALTER COLUMN status SET DEFAULT 'pending_review',
  ADD CONSTRAINT skill_registry_status_check
      CHECK (status IN ('active', 'pending_review', 'rejected', 'archived'));
ALTER TABLE identity.skill_registry
  ADD COLUMN rejection_reason TEXT,
  ADD COLUMN reviewed_by BIGINT REFERENCES identity.users(id),
  ADD COLUMN reviewed_at TIMESTAMPTZ;
-- private skill 推送时直接写 status='active'，无需审批
```

---

## 五、前端技能广场

### 5.1 左侧边栏入口

在现有边栏功能区（对话 / 知识库 / 设置）中新增"技能"入口，位置在知识库下方：

```
左侧边栏
├── 对话
├── 知识库
├── 技能          ← 新增
└── 设置
```

点击"技能"进入技能广场页面（`/workspace/skills`）。

### 5.2 技能广场页面布局

```
/workspace/skills
┌─────────────────────────────────────────────────┐
│  技能广场                          [+ 上传技能]  │
│  ┌─────────────────────┐                        │
│  │ 🔍 搜索技能...      │  [筛选: 全部 / 我的]   │
│  └─────────────────────┘                        │
│                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐   │
│  │ 数据分析   │ │ SQL 专家   │ │ 文档生成   │   │
│  │ 数据查询与 │ │ 数据库优化 │ │ 自动生成报 │   │
│  │ 可视化专家 │ │ 与分析     │ │ 告与文档   │   │
│  │            │ │            │ │            │   │
│  │ [加载到会话]│ │[加载到会话]│ │[加载到会话]│   │
│  └────────────┘ └────────────┘ └────────────┘   │
│                                                  │
│  我的技能                                        │
│  ┌────────────┐                                  │
│  │ 我的私有   │                                  │
│  │ 技能 A     │                                  │
│  │ [加载到会话]│                                  │
│  └────────────┘                                  │
└─────────────────────────────────────────────────┘
```

**展示逻辑：**
- "技能广场"区：展示用户有权访问的所有技能（public + org，不区分来源标签）
- "我的技能"区：仅展示该用户的 private skill
- 筛选"我的"时，两区合并，只展示自己创建/上传的技能

### 5.3 技能加载到会话

**无参数技能 — 一键加载：**

```
用户点击「加载到会话」
  → Gateway POST /api/threads/{thread_id}/skills { skill_name, version }
  → thread state 中追加 bound_skills: [{name, version, bound_at}]
  → 会话输入框上方出现技能 badge：[数据分析 ×]
  → 后续对话 LangGraph 从 thread state 读取 bound_skills 并加载
```

**有参数技能 — 弹出配置表单：**

```
用户点击「加载到会话」
  → 读取 manifest.yaml 中 params 声明
  → 弹出配置表单（每个 param 对应一个输入项，含描述和校验规则）
  → 用户填写并确认
  → Gateway 将参数加入 thread state: bound_skills: [{name, version, params: {...}, bound_at}]
  → 会话输入框上方出现技能 badge：[数据分析 ⚙ ×]（⚙ 表示有配置）
```

**manifest.yaml params 声明格式（新增）：**

```yaml
params:
  - name: db_endpoint
    label: 数据库地址
    type: string
    required: true
    placeholder: "jdbc:postgresql://host:5432/db"
  - name: max_rows
    label: 最大返回行数
    type: integer
    required: false
    default: 1000
```

### 5.4 会话中的技能 Badge

技能绑定后，在会话输入框上方显示 badge 区域：

```
┌─────────────────────────────────────────┐
│ [数据分析 ×]  [SQL 专家 ×]              │  ← badge 区
├─────────────────────────────────────────┤
│ 请输入消息...                  [发送]   │
└─────────────────────────────────────────┘
```

- 点击 `×` 从当前 thread 解绑该技能
- 有参数的技能 badge 可点击重新编辑配置
- badge 区仅在有已绑定技能时显示

### 5.5 技能上传（用户上传 private skill）

点击「+ 上传技能」弹出上传面板：

```
上传方式：
  ├── 拖拽上传：上传 .zip（包含 SKILL.md + manifest.yaml）
  ├── 在线编辑：内嵌编辑器，分别编辑 manifest.yaml 和 SKILL.md
  └── CLI 提示：显示 deerflow skill publish 命令，引导开发者用 CLI
```

上传后默认为 private skill，直接生效，无需审批。

---

## 六、Admin 技能管理页（`/admin/skills`）

### 6.1 页面结构

```
/admin/skills
┌──────────────────────────────────────────────────────┐
│  技能管理                              [发布新技能]   │
│                                                       │
│  [全部] [待审批 (3)] [已发布] [已拒绝] [已归档]      │
│                                                       │
│  名称          版本   范围    状态        操作        │
│  ──────────────────────────────────────────────────  │
│  数据分析      1.2.0  org     ✓ 已发布   [管理][归档] │
│  SQL 专家      2.0.0  public  ⏳ 待审批  [审批][拒绝] │
│  文档生成      1.0.0  public  ✗ 已拒绝   [查看原因]   │
└──────────────────────────────────────────────────────┘
```

### 6.2 审批操作

点击「审批」展开审批面板：

```
┌─────────────────────────────────────────┐
│ 审批：SQL 专家 v2.0.0                   │
│ 推送者：dev@company.com                 │
│ 推送时间：2026-04-25 14:30              │
│                                         │
│ manifest.yaml 内容（只读预览）          │
│ SKILL.md 内容（只读预览）               │
│                                         │
│ 权限分配：                              │
│   发布为 ○ org  ● public               │
│                                         │
│ [通过发布]  [拒绝]                      │
└─────────────────────────────────────────┘
```

拒绝时需填写原因（推送者可通过 `deerflow skill status` 查看）。

### 6.3 Org Key 管理（`/admin/org-keys`）

```
/admin/org-keys
┌──────────────────────────────────────────────────────┐
│  Org Key 管理                         [创建新 Key]   │
│                                                       │
│  前缀          创建时间    有效期      最后使用  操作 │
│  ───────────────────────────────────────────────────  │
│  sk_org_abc123  2026-01-01  永久（自动轮换）  今天   [吊销]│
│                                                       │
│  ⚠ 下次自动轮换：2027-01-01（距今 250 天）           │
└──────────────────────────────────────────────────────┘
```

创建 Key 时的选项：

```
有效期：
  ○ 固定有效期  [____] 天（30–730）
  ● 永久（系统每年自动轮换）

Key 名称（可选，便于识别）：[__________]
```

Key 创建后明文**只展示一次**，提示用户复制保存。之后只显示前缀。

---

## 七、Gateway API 完整端点（对前置文档的扩展）

### 7.1 技能相关端点

```
# 技能广场
GET  /api/skills                          → 列出可见技能（public + org + private）
GET  /api/skills/{name}                   → 技能详情（含最新版本 manifest）
GET  /api/skills/{name}/versions          → 列出所有版本

# 技能绑定（thread 级别）
POST /api/threads/{tid}/skills            → 绑定技能到 thread
DELETE /api/threads/{tid}/skills/{name}   → 解绑技能

# CLI 推送
POST /api/skills/publish                  → 推送技能（需 skill:publish scope）
GET  /api/skills/{name}/review-status     → 查看审批状态（推送者可查）

# 管理员审批
GET  /api/admin/skills/pending            → 待审批列表
POST /api/admin/skills/{id}/approve       → 通过审批
POST /api/admin/skills/{id}/reject        → 拒绝审批（body: {reason}）

# 管理员版本管理
PUT  /api/admin/skills/{name}/versions/{v}/default   → 设置 default 版本
PUT  /api/admin/skills/{name}/versions/{v}           → 启用/禁用版本
```

### 7.2 Org Key 端点

```
GET    /api/admin/org-keys             → 列出当前租户的 key（需 tenant ADMIN）
POST   /api/admin/org-keys             → 创建 key（返回明文，仅此一次）
DELETE /api/admin/org-keys/{id}        → 吊销 key
GET    /api/admin/org-keys/{id}/audit  → 查看该 key 的使用审计
```

### 7.3 新增 API Token Scope

```
POST /api/tokens  → 创建 API token 时，scopes 数组新增合法值：skill:publish
```

---

## 八、审计事件扩展

在现有审计管道中新增以下事件：

| 事件 | 触发时机 |
|---|---|
| `skill.published` | CLI 推送技能（任意状态） |
| `skill.review.approved` | 管理员通过审批 |
| `skill.review.rejected` | 管理员拒绝审批 |
| `skill.bound_to_thread` | 用户绑定技能到 thread |
| `skill.unbound_from_thread` | 用户解绑技能 |
| `org_key.created` | 管理员创建 org key |
| `org_key.revoked` | 管理员吊销 org key |
| `org_key.auto_rotated` | 系统静默轮换永久 key |
| `org_key.expiring_soon` | key 将在 30 天内过期 |
| `org_key.used` | org skill 调用时 key 被注入（记录 key prefix，不记录明文） |

---

## 九、实施阶段（对前置文档的补充）

前置文档已定义阶段 0–4，本文档新增阶段 5：

```
阶段 5（依赖阶段 3 + 4）：
  ├── 5.1 Org Key 生命周期
  │     ├── org_api_keys 表补充字段（no_expiry, auto_rotate_at, status 等）
  │     ├── 后台自动轮换任务
  │     └── /admin/org-keys 管理页
  │
  ├── 5.2 CLI 推送流程
  │     ├── skill:publish scope 新增
  │     ├── POST /api/skills/publish 端点
  │     ├── skill_registry status/rejection_reason 字段
  │     └── deerflow CLI skill 子命令
  │
  ├── 5.3 前端技能广场
  │     ├── 左侧边栏"技能"入口
  │     ├── /workspace/skills 广场页面
  │     ├── thread 绑定/解绑逻辑（含 manifest params 表单）
  │     └── 会话输入框技能 badge 区域
  │
  └── 5.4 Admin 审批页
        ├── /admin/skills 审批管理页
        └── 审批通过/拒绝操作
```

---

## 十、不在本次范围内

- SkillHub（Java 应用）与 DeerFlow identity 的集成（P3）
- 技能的安全内容扫描（复用现有 `scan_skill_content()`，不在本设计范围）
- 沙箱测试环境（审批前自动运行技能验证），留 v3
- 技能跨租户市场化（付费/授权流程）
- 多 org key（每个 org skill 绑定独立 key）的细粒度模式，留 v3
