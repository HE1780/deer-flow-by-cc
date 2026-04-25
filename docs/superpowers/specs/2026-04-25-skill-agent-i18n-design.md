# DeerFlow 改进设计文档

**日期**：2026-04-25
**范围**：技能管理 v2、Agent 编排修复、默认语言中文化
**状态**：已确认，待实施

---

## 一、背景与问题定义

### 1.1 技能管理现状问题

当前 Skill 系统本质上是一个「全局文件开关列表」：

- 所有用户/项目共享 `extensions_config.json` 里的 `enabled` 字段
- 没有版本管理，更新即覆盖
- 没有所有权概念，无法区分公共/组织/私有技能
- 没有数据访问层面的权限隔离
- Skill 仅作为 system prompt 片段注入，未声明工具/MCP 依赖

### 1.2 Agent 编排问题

**根本原因**（代码层面确认）：

[frontend/src/core/threads/hooks.ts:215-219](../../../frontend/src/core/threads/hooks.ts#L215-L219)

```typescript
// agent_name 只写入 thread metadata，未进入 configurable
if (context.agent_name && !isMock) {
  void getAPIClient().threads.update(meta.thread_id, {
    metadata: { agent_name: context.agent_name },
  });
}
```

[frontend/src/core/threads/hooks.ts:487-506](../../../frontend/src/core/threads/hooks.ts#L487-L506) 中的 `context`（= LangGraph configurable）里没有 `agent_name`。

而后端 `make_lead_agent` 读取的是 configurable：

```python
# backend/packages/harness/deerflow/agents/lead_agent/agent.py:294
agent_name = validate_agent_name(cfg.get("agent_name"))  # 永远是 None
```

因此 agent 创建后**始终以 default 模式运行**，自定义配置（model、tool_groups、skills、SOUL）全部失效。

### 1.3 语言默认值问题

[frontend/src/core/i18n/locale.ts:3](../../../frontend/src/core/i18n/locale.ts#L3) 中 `DEFAULT_LOCALE = "en-US"`，但系统的主要用户群体为中文用户。

---

## 二、模块 1：技能管理 v2

### 2.1 核心概念重定义

**新定义**：Skill = 知识体 + 工具声明 + MCP 绑定 + 数据访问权限 + 版本

Skill 不再只是 system prompt 片段，而是一个完整的「能力单元」，声明自己运行所需的一切依赖。

### 2.2 三层可见性模型

```
public  (全局)   → 系统内置，platform admin 维护，全员可用
org     (组织)   → 由 org key 控制访问，org ADMIN 管理，范围是一个组织/部门/项目组
private (私有)   → 用户自己创建，仅本人可用，无审批
```

**使用时零摩擦**：Agent session 继承调用者身份，自动可见权限范围内的所有技能，无需额外操作。

### 2.3 Org Key 设计

Org key 是**组织身份凭证**，统一代表「某个组织的访问权限」。持有者可以是用户、agent、CI/CD pipeline 或外部系统。

```
org key 语义：
  ├── 颁发者：org OWNER 或 ADMIN
  ├── 持有者：任何需要代表该 org 运行的实体
  ├── skill 访问范围：该 org 下被授权的 skill 列表（默认全部，可收窄到子集）
  ├── 数据权限：注入 skill env，作为下游 MCP/数据库的行级过滤凭证
  ├── 审计：每次使用记录 key_id + action + timestamp
  └── 吊销：ADMIN 随时可 revoke，不影响其他 key
```

**Org key 作为数据层 service account token（无侵入集成）**：

```yaml
# manifest.yaml 中声明
env:
  - name: ORG_ACCESS_KEY
    source: org_key        # 运行时从当前 org key 注入，skill 代码不感知权限逻辑
    required: true
requires_mcp:
  - postgres-mcp           # MCP server 用此 key 做行级过滤
```

运行时数据流：
```
Agent 调用 skill
  → load_skill(name, version, org_key)
  → org_key 注入 skill env 上下文
  → skill 调用 postgres-mcp（携带 ORG_ACCESS_KEY）
  → MCP server 解析 key → 得到 tenant/org 范围
  → SQL 自动加 WHERE tenant_id = ? 过滤
```

权限边界在数据层，skill 层完全解耦。

### 2.4 版本管理

版本**并行存在**，不是覆盖关系。同一 skill 可以同时有 v1.0.0、v1.1.0、v2.0.0，各自独立的 enabled/disabled 状态。

**版本选择规则**：
- `skill_registry` 中每个版本有独立的 `is_default` 标记
- 同一 skill + scope 下只能有一个 `is_default = true`
- Agent 不指定版本时使用 `is_default` 版本
- Agent 可以在 `config.yaml` 中 pin 到具体版本：`required_skills: ["data-analyst@v1.2.0"]`

**管理员操作**：
- 切换 default 版本：`PUT /api/skills/{name}/versions/{version}/default`
- 禁用某版本：`PUT /api/skills/{name}/versions/{version}` → `{ enabled: false }`
- 历史版本保留在文件系统，不自动删除

### 2.5 数据库 Schema

在现有 Identity DB（M1-M7）上扩展，新增两张表：

```sql
-- 技能注册表（元数据层，文件本体仍在文件系统）
CREATE TABLE identity.skill_registry (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    version      TEXT NOT NULL,                   -- semver: "1.2.0"
    scope        TEXT NOT NULL                    -- 'public' | 'org' | 'private'
                 CHECK (scope IN ('public','org','private')),
    tenant_id    BIGINT REFERENCES identity.tenants(id) ON DELETE CASCADE,
    owner_id     BIGINT REFERENCES identity.users(id)  ON DELETE CASCADE,
    enabled      BOOLEAN NOT NULL DEFAULT true,
    is_default   BOOLEAN NOT NULL DEFAULT false,  -- 该 scope+name 下的默认版本
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','archived')),
    storage_path TEXT NOT NULL,                   -- 文件系统相对路径
    created_by   BIGINT REFERENCES identity.users(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version, tenant_id),            -- org 内唯一
    UNIQUE (name, version, owner_id)              -- private 内唯一（owner_id 非 NULL 时）
);

-- org API key 表（独立于 user api_tokens）
CREATE TABLE identity.org_api_keys (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES identity.tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    prefix          TEXT NOT NULL,                -- 'sk_org_' 前缀，用于日志显示
    token_hash      TEXT NOT NULL,                -- SHA-256，只存 hash
    allowed_skills  JSONB NOT NULL DEFAULT '[]',  -- [] = 全部 org skills；[{name,version},...] = 子集
    scopes          JSONB NOT NULL DEFAULT '["skill:invoke"]',
    created_by      BIGINT REFERENCES identity.users(id),
    expires_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ,
    last_used_ip    INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- is_default 唯一性约束（同一 scope+name 下只能有一个 default）
CREATE UNIQUE INDEX skill_registry_default_public
    ON identity.skill_registry (name)
    WHERE is_default = true AND scope = 'public';

CREATE UNIQUE INDEX skill_registry_default_org
    ON identity.skill_registry (name, tenant_id)
    WHERE is_default = true AND scope = 'org';

CREATE UNIQUE INDEX skill_registry_default_private
    ON identity.skill_registry (name, owner_id)
    WHERE is_default = true AND scope = 'private';
```

### 2.6 文件系统布局

扩展现有 M4 路径结构：

```
$DEER_FLOW_HOME/
  skills/
    public/                        ← 现有，全局公开
      {skill-name}/
        v{version}/
          SKILL.md
          manifest.yaml            ← 新增
        .versions/                 ← 历史备份
  tenants/{tid}/
    org-skills/                    ← 新增（原 custom/ 仍保留兼容）
      {skill-name}/
        v{version}/
          SKILL.md
          manifest.yaml
    users/{uid}/
      skills/                      ← 新增，private skills
        {skill-name}/
          v{version}/
            SKILL.md
            manifest.yaml
```

**manifest.yaml 格式**：

```yaml
name: data-analyst
version: 1.2.0
scope: org
description: 数据分析专家技能
author: admin@company.com
requires_tools:
  - code_execution
  - web_search
requires_mcp:
  - postgres-mcp
env:
  - name: ORG_ACCESS_KEY
    source: org_key
    required: true
changelog: "增加 SQL 优化建议"
```

### 2.7 技能加载逻辑

```python
def load_skills(
    tenant_id: int | None = None,
    workspace_id: int | None = None,
    user_id: int | None = None,
    org_key: str | None = None,         # 新增
    skill_overrides: list[str] | None = None,  # agent 指定版本
) -> list[Skill]:
    """
    加载顺序（后者覆盖同名前者）：
      1. public skills（global enabled 状态检查）
      2. org skills（tenant_id 匹配 OR org_key 验证通过）
      3. private skills（user_id 匹配）

    版本选择：
      - skill_overrides 中指定 name@version → 使用指定版本
      - 否则使用 is_default = true 的版本
      - 无 default → 使用最新 enabled 版本

    名称冲突：private > org > public（后者覆盖）
    """
```

### 2.8 访问控制矩阵

| 操作 | public | org | private |
|------|--------|-----|---------|
| 查看/使用 | 所有人 | org 成员 / org key 持有者 | 所有者 |
| 启用/禁用版本 | platform admin | org ADMIN | 所有者 |
| 设置 default 版本 | platform admin | org ADMIN | 所有者 |
| 创建/更新 | platform admin | org ADMIN | 所有者 |
| 删除 | platform admin | org OWNER | 所有者 |
| 生成 org key | — | org OWNER / ADMIN | — |
| 吊销 org key | — | org OWNER / ADMIN | — |

### 2.9 Gateway API 变更

```
新增端点：
GET  /api/skills/{name}/versions              → 列出所有版本
PUT  /api/skills/{name}/versions/{v}/default  → 设置 default 版本
GET  /api/org-keys                            → 列出当前 org 的 key（需 org ADMIN）
POST /api/org-keys                            → 创建 org key（需 org ADMIN）
DELETE /api/org-keys/{id}                     → 吊销 key

修改端点：
GET /api/skills  → 新增 scope / version / org_key 参数
PUT /api/skills/{name}  → 新增 version 参数
```

### 2.10 前端变更

- Skills Hub 页面增加版本切换 UI（下拉选择版本，标记 default）
- Admin 面板增加 Org Keys 管理页（列表、创建、吊销、查看审计）
- Agent 编辑页中 `required_skills` 支持 `name@version` 格式

---

## 三、模块 2：Agent 编排修复

### 3.1 Bug 修复：agent_name 注入 configurable

**问题**：`agent_name` 只写入 thread metadata，未进入 LangGraph configurable，导致 `make_lead_agent` 每次都以 default 模式运行。

**修复**：在 `thread.submit()` 的 `context` 对象中加入 `agent_name`：

```typescript
// frontend/src/core/threads/hooks.ts
context: {
  ...extraContext,
  ...context,
  agent_name: context.agent_name,    // ← 新增这一行
  thinking_enabled: context.mode !== "flash",
  // ...
}
```

同时保留 metadata 写入（用于 UI 路由），两者并行不冲突。

### 3.2 Agent 声明 required_skills

**当前**：`AgentConfig.skills` 是白名单过滤列表（skill 名称），运行时从全局已启用 skill 中过滤。

**新增**：支持版本 pin 和 org key 绑定：

```yaml
# agents/{name}/config.yaml
name: sales-agent
description: 销售数据分析 Agent
model: claude-opus-4-7
tool_groups:
  - code_execution
  - web_search
skills:
  - data-analyst@v2.0.0        # pin 到特定版本
  - sql-expert                  # 不指定版本 → 使用 default 版本
org_key_env: ORG_ACCESS_KEY    # 新增：从环境变量读取 org key，注入 skill env
```

**AgentConfig 扩展**：

```python
class AgentConfig(BaseModel):
    name: str
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None
    skills: list[str] | None = None          # 支持 "name@version" 格式
    org_key_env: str | None = None           # 新增：org key 来源的 env 变量名
```

### 3.3 Skill 依赖工具和 MCP 的自动加载

当 agent 声明了 `required_skills`，运行时自动：

1. 读取每个 skill 的 `manifest.yaml`
2. 将 `requires_tools` 合并到 agent 的 tool_groups
3. 将 `requires_mcp` 确保对应 MCP server 已启用
4. 将 `env` 中声明的变量（注入 org_key）传递给 MCP 调用上下文

```python
# packages/harness/deerflow/agents/lead_agent/agent.py
def _resolve_skills_and_deps(agent_config: AgentConfig) -> tuple[set[str], list[str], dict]:
    """
    返回：(skill_names, extra_tool_groups, env_injections)
    """
    skill_specs = agent_config.skills or []
    extra_tool_groups = []
    env_injections = {}

    for spec in skill_specs:
        name, version = _parse_skill_spec(spec)  # "data-analyst@v2" → ("data-analyst", "v2")
        manifest = load_skill_manifest(name, version)
        if manifest:
            extra_tool_groups.extend(manifest.requires_tools or [])
            # env 注入
            for env_decl in manifest.env or []:
                if env_decl.source == "org_key" and agent_config.org_key_env:
                    env_injections[env_decl.name] = os.environ.get(agent_config.org_key_env, "")

    return set(skill_specs), list(set(extra_tool_groups)), env_injections
```

### 3.4 前端 Agent Builder 扩展

Agent 创建/编辑页面新增：

- **关联技能**步骤：多选 skill，支持指定版本（下拉）
- **Org Key**：可选填入 org key 或选择已保存的 key（与 Skills Hub 中 org keys 联动）
- 保存时将 `skills: ["name@version", ...]` 和 `org_key_env` 写入 config.yaml

---

## 四、模块 3：默认语言中文化

### 4.1 修改默认语言

```typescript
// frontend/src/core/i18n/locale.ts:3
// 改前
export const DEFAULT_LOCALE: Locale = "en-US";
// 改后
export const DEFAULT_LOCALE: Locale = "zh-CN";
```

**影响范围**：仅影响「首次访问且浏览器语言不在支持列表内」时的 fallback 行为。已有 cookie 的用户不受影响；浏览器语言为英文的用户仍自动使用 en-US（`detectLocale()` 保持不变）。

### 4.2 补全缺失翻译 key

检查 `frontend/src/core/i18n/locales/zh-CN.ts` 中与 `en-US.ts` 对比缺失的 key，补全所有中文翻译。

---

## 五、实施顺序与依赖关系

```
阶段 0（独立，无依赖）：
  └── 模块 3：改默认语言（1行代码 + 补翻译）

阶段 1（独立，无依赖）：
  └── 模块 2.1：修复 agent_name 注入 configurable（1行前端代码）

阶段 2（依赖阶段 1）：
  └── 模块 2.2：AgentConfig 扩展 + skill version pin
  └── 模块 2.3：manifest.yaml 解析 + 工具/MCP 自动加载

阶段 3（依赖 Identity M1-M7 已就绪）：
  └── 模块 1.1：Alembic migration（skill_registry + org_api_keys 表）
  └── 模块 1.2：文件系统路径扩展（M4 paths.py）
  └── 模块 1.3：load_skills() 逻辑重写（三层 + 版本 + org key）
  └── 模块 1.4：Gateway API 新增端点

阶段 4（依赖阶段 3）：
  └── 模块 1.5：前端 Skills Hub 版本 UI
  └── 模块 1.6：前端 Org Keys 管理页
  └── 模块 1.7：前端 Agent Builder 技能关联步骤
```

---

## 六、不在本次范围内

- Skill 的 DRAFT → REVIEW → PUBLISHED 审核流程（SkillHub 模式）：当前 org ADMIN 直接创建即生效，无需审核流
- Skill 跨 org 提升为 public 的流程：由 platform admin 手动操作
- Skill 的安全扫描（content scanning）：复用现有 `scan_skill_content()`
- Agent 作为独立 service account 的 JWT 签发：org key 已覆盖此需求
