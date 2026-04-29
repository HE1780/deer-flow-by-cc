> 📦 **归档于 2026-04-29 — 已 ship**：edit page、`GET /api/tool-groups`、tri-state helper、useToolGroups hook、i18n keys 全部交付。

---

# 自定义 Agent 编辑页设计

- Date: 2026-04-27
- Status: ✅ Shipped（详见上方 banner）
- Owner: cc-main
- Companion plan: [../plans/2026-04-27-custom-agent-edit-page.md](../plans/2026-04-27-custom-agent-edit-page.md)（10 个 task，预计 2-4h agentic 实施 + 1h 验收）
- Related code: `backend/app/gateway/routers/agents.py`, `frontend/src/components/workspace/agents/agent-card.tsx`, `frontend/src/app/workspace/agents/`, `frontend/src/core/agents/`

## 背景

后端 `PUT /api/agents/{name}` 已支持完整字段更新（description / model / tool_groups / skills / org_key_env / SOUL.md），前端 API 层 `updateAgent()` 与 hook `useUpdateAgent()` 也已实现，但 **UI 上没有任何编辑入口**：
- `AgentCard` 仅有「聊天」+「删除」两个按钮（[agent-card.tsx:107-122](frontend/src/components/workspace/agents/agent-card.tsx#L107-L122)）
- 路由 `/workspace/agents/[agent_name]/` 下面只有 `chats/`，没有 `edit/`

用户反馈："智能体创建提交后无法编辑"。本设计补齐这条闭环。

## 目标 / 非目标

**目标**
- 用户能在创建 agent 后通过表单修改 description / model / tool_groups / skills / org_key_env / SOUL.md。
- AgentCard 提供清晰的「编辑」入口。
- `tool_groups` / `skills` 三态语义（`null` 继承全部 / `[]` 全关 / `["a","b"]` 白名单）在 UI 上明确可控且无歧义。

**非目标**
- 不支持改名（后端契约不允许，目录名 = agent name）。
- 不做 skill 版本号选择 UI；如果当前配置里已有 `name@version` 字符串则透传保留，新选的项默认存 `name`。
- 不做对话式调教模式（保留为后续独立 epic）。

## 范围

### 后端

新增一个只读路由 `GET /api/tool-groups`，列出 `config.yaml` 顶层 `tool_groups[]`。
前端编辑页用它做 tool_groups 字段的候选项下拉。

`PUT /api/agents/{name}` **不动**，已支持全部字段且语义正确（用 `model_fields_set` 区分"省略"和"显式置 null"，[agents.py:288-311](backend/app/gateway/routers/agents.py#L288-L311)）。

### 前端

1. 新增编辑页 `/workspace/agents/[agent_name]/edit`
2. AgentCard 加「编辑」图标按钮
3. `core/agents/api.ts` + `hooks.ts` 新增 `listToolGroups` / `useToolGroups`
4. i18n 新增对应文案

## 详细设计

### 后端 — `GET /api/tool-groups`

文件：`backend/app/gateway/routers/agents.py`（与 agents 路由同文件，复用 `_require_agents_api_enabled` 守卫，避免新建 router 文件）

```python
class ToolGroupResponse(BaseModel):
    name: str

class ToolGroupsListResponse(BaseModel):
    tool_groups: list[ToolGroupResponse]

@router.get(
    "/tool-groups",
    response_model=ToolGroupsListResponse,
    summary="List Tool Groups",
    description="List all tool groups defined in config.yaml.",
)
async def list_tool_groups() -> ToolGroupsListResponse:
    _require_agents_api_enabled()
    cfg = get_app_config()
    return ToolGroupsListResponse(
        tool_groups=[ToolGroupResponse(name=g.name) for g in cfg.tool_groups]
    )
```

数据来源：`AppConfig.tool_groups: list[ToolGroupConfig]`（[app_config.py:56](backend/packages/harness/deerflow/config/app_config.py#L56)），每个 `ToolGroupConfig` 至少有 `name` 字段（[tool_config.py:4-8](backend/packages/harness/deerflow/config/tool_config.py#L4-L8)）。

权限：和 agents API 一致，`agents_api.enabled=false` 时 403；ENABLE_IDENTITY 启用后由现有中间件接管 401。

### 前端

#### 新页面：`/workspace/agents/[agent_name]/edit`

文件路径：`frontend/src/app/workspace/agents/[agent_name]/edit/page.tsx`

**布局**：

```
┌ Header ────────────────────────────────────────────────┐
│ ← <agent_name>                              [取消] [保存] │
└───────────────────────────────────────────────────────┘
┌ 基本信息 ────────────────────────────────────────────┐
│ Description: [textarea, 3 行]                         │
│ Model:       [Select: 使用全局默认 / model1 / model2 …] │
│ SOUL.md:     [textarea, 大区域, 等宽字体]              │
└──────────────────────────────────────────────────────┘
┌ 高级（默认折叠） ────────────────────────────────────┐
│ Tool Groups                                          │
│   ☑ 使用全部已启用的工具组（默认）                    │
│   关闭后显示候选列表：                                │
│   ☐ search   ☐ python   ☐ files   ...                │
│                                                      │
│ Skills                                               │
│   ☑ 继承所有已启用的技能                              │
│   关闭后显示候选列表：                                │
│   ☐ skill_a (v1.2 已锁)   ☐ skill_b   ...            │
│                                                      │
│ Org Key Env: [text input]                            │
└──────────────────────────────────────────────────────┘
```

**字段三态实现**（适用于 `tool_groups` 和 `skills`）：

每个字段一个 `useAll: boolean` + `selected: string[]` state：
- `useAll === true` → 提交 `null`
- `useAll === false && selected.length === 0` → 提交 `[]`
- `useAll === false && selected.length > 0` → 提交 `selected`

加载已有 agent 时反向解码：
- `field === null` → `useAll = true`, `selected = []`
- `field === []` → `useAll = false`, `selected = []`
- `field === ["a","b"]` → `useAll = false`, `selected = ["a","b"]`

**Skills `name@version` 处理**：
- 候选列表来自 `GET /api/skills`，只显示 `name`。
- 若 agent 配置里已有 `"my_skill@1.2.0"` 形式的字符串：保留版本号在 state 里，UI chip 旁标注 `(v1.2.0)`。
- 用户勾选时按 `name` 匹配，命中已有 `name@version` 则保留版本号，否则添加裸 `name`。
- 取消勾选则彻底删除（包括版本号）。

**Model select**：
- 候选项来自 `GET /api/models`（已有）。
- 第一项固定为「使用全局默认」，对应值 `null`。

**保存流程**：
1. 调 `useUpdateAgent` mutation，传入解码后的 6 个字段。
2. 成功 → toast.success + `router.push('/workspace/agents')`。
3. 失败 → toast.error 显示后端 detail。
4. 加载中（GET 未完成）显示 skeleton；保存中按钮 disable。

**错误态**：
- `useAgent` 报错（404 / agents_api disabled）→ 显示空态 + 「返回列表」按钮。
- `useToolGroups` / `useSkills` 失败 → 高级区显示 inline error，但基本信息仍可保存。

#### AgentCard 改动

文件：[agent-card.tsx:107-122](frontend/src/components/workspace/agents/agent-card.tsx#L107-L122)

在「聊天」按钮（line 108-111）和「删除」按钮之间插入：

```tsx
<Button
  size="icon"
  variant="ghost"
  className="h-8 w-8 shrink-0"
  onClick={() => router.push(`/workspace/agents/${agent.name}/edit`)}
  title={t.agents.edit}
>
  <PencilIcon className="h-3.5 w-3.5" />
</Button>
```

`PencilIcon` 来自 `lucide-react`，与现有 `Trash2Icon` 保持一致。

#### API + hooks

`frontend/src/core/agents/api.ts` 新增：

```ts
export async function listToolGroups(): Promise<{ tool_groups: { name: string }[] }> {
  const res = await fetch(`${getBackendBaseURL()}/api/tool-groups`);
  if (!res.ok) throw new Error(`Failed to load tool groups: ${res.statusText}`);
  return res.json();
}
```

`frontend/src/core/agents/hooks.ts` 新增：

```ts
export function useToolGroups() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["tool-groups"],
    queryFn: listToolGroups,
  });
  return { toolGroups: data?.tool_groups ?? [], isLoading, error };
}
```

#### 已存在但本设计也用到的 hook

- `useAgent(name)` — 加载现有 agent 详情
- `useUpdateAgent()` — 保存
- `useSkills()` — 列出系统全部技能（已有）
- `useModels()` — 列出系统全部模型（已有）

#### i18n

`frontend/src/core/i18n/locales/{en-US,zh-CN}.ts` + `types.ts` 新增 `agents.edit*` 键：

| key | en-US | zh-CN |
|---|---|---|
| `edit` | Edit | 编辑 |
| `editPageTitle` | Edit Agent | 编辑智能体 |
| `editBasicSection` | Basic info | 基本信息 |
| `editAdvancedSection` | Advanced | 高级 |
| `editFieldDescription` | Description | 描述 |
| `editFieldModel` | Model | 模型 |
| `editFieldModelDefault` | Use global default | 使用全局默认 |
| `editFieldSoul` | SOUL.md | SOUL.md |
| `editFieldToolGroups` | Tool groups | 工具组 |
| `editFieldSkills` | Skills | 技能 |
| `editFieldOrgKeyEnv` | Org key env var | 组织 key 环境变量 |
| `editUseAllToolGroups` | Use all enabled tool groups | 使用全部已启用的工具组 |
| `editUseAllSkills` | Inherit all enabled skills | 继承所有已启用的技能 |
| `editSaveSuccess` | Agent updated | 智能体已更新 |
| `editSaveFailed` | Failed to update agent | 更新智能体失败 |
| `editLoadFailed` | Failed to load agent | 加载智能体失败 |
| `editVersionPinned` | v{version} pinned | 已锁版本 v{version} |

## 数据流

```
[AgentCard 编辑按钮]
        │
        ▼
/workspace/agents/{name}/edit
        │
        ├─ useAgent(name)        → GET /api/agents/{name}
        ├─ useModels()           → GET /api/models
        ├─ useToolGroups()       → GET /api/tool-groups   (新增)
        ├─ useSkills()           → GET /api/skills
        │
        ├─ 用户编辑 → 本地 state（含三态解/编码）
        │
        └─ 点击保存
              ▼
        useUpdateAgent.mutate({ name, request })
              │
              ▼
        PUT /api/agents/{name}
              │
              ├─ 成功 → invalidate ["agents"] / ["agents", name]
              │       → toast 成功 → 路由回 /workspace/agents
              │
              └─ 失败 → toast 错误（保留页面状态）
```

## 测试

### 后端

`backend/tests/test_agents_router.py`（新建，当前不存在；放路由级 fastapi `TestClient` 测试，不依赖 PG/Redis）：

1. `GET /api/tool-groups` 返回 `config.yaml` 中的所有 tool_groups（按 name 字段提取）。
2. `agents_api.enabled=false` 时 `GET /api/tool-groups` 返回 403，detail 与现有 agents 路由文案一致。
3. `PUT /api/agents/{name}` 三态回归（如果现有覆盖不全，补一条）：
   - 起始 `tool_groups=null`，PUT `[]` → 配置文件出现 `tool_groups: []`，下次 GET 返回 `[]`。
   - 起始 `tool_groups=[]`，PUT `["a"]` → 出现 `tool_groups: [a]`。
   - 起始 `tool_groups=["a"]`，PUT `null` → 配置文件不再含 `tool_groups` 键，GET 返回 `null`。

### 前端

`frontend/tests/unit/core/agents/`（目录新建，当前不存在）：

1. `useToolGroups` 正常返回数据。
2. 编辑页三态切换（unit 级别测试 state 解/编码函数）：
   - 加载 `field=null` → state `{ useAll: true, selected: [] }`。
   - 加载 `field=[]` → `{ useAll: false, selected: [] }`。
   - 加载 `field=["a","b"]` → `{ useAll: false, selected: ["a","b"] }`。
   - 三种 state 反向 encode 出与原始一致的提交值。
3. Skill 版本号透传：加载 `["s@1.2"]` → 取消勾选 → 重新勾选 → 提交值仍为 `["s@1.2"]`（同一会话内）。

### 手动验收（本地，浏览器）

1. 创建一个新 agent → 列表卡片出现「编辑」按钮 → 进入编辑页。
2. 改 description + 切换 model → 保存 → 回列表，badge / description 已更新。
3. 关闭"使用全部工具组"且不勾任何 → 保存 → 重进编辑页，确认仍是关闭 + 空 selected（不是被识别成 null）。
4. 把一个有 `name@version` 的 skill 取消勾选再勾上 → 保存 → 重进编辑页，版本号仍在。
5. `agents_api.enabled=false` → 编辑页加载失败、显示空态、不报白屏。

## 风险与回滚

- **风险 1**: `tool_groups` 三态语义复杂，用户可能误以为关闭"使用全部"等于"全开" → 通过 helper text 显式说明 + 关闭后再展示候选列表，使勾选动作可见。
- **风险 2**: 大 SOUL.md textarea 可能让保存请求体过大 → 后端无明确限制，由 FastAPI 默认体积上限保护；本设计不引入新限制。
- **风险 3**: 编辑期间 agent 被另一个客户端删除 → PUT 返回 404 → toast 显示后端 detail，用户回列表即可。
- **回滚**: 改动是纯增量（新增 1 个 GET、1 个页面、1 个按钮、若干 i18n key）；删除 `edit/` 目录 + 还原 `agent-card.tsx` 的按钮即可完整回退，对现有功能无影响。

## 不在范围 / 后续

- 改名（后端没有 rename API；如要做需后端先支持目录 rename + 配置 `name` 字段同步）。
- 对话式调教模式（在 agent chat 页加"调教开关"）。
- skill 版本号下拉选择（需要后端先暴露每个 skill 的可用版本列表）。
- 编辑历史 / 版本对比（YAGNI）。
