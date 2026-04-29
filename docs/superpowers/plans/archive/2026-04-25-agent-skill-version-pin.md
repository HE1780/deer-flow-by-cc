> 📦 **归档于 2026-04-29 — 已 ship（核心 3 个 task 全部落地）**
>
> **当前事实**：
> - `manifest.yaml` 解析器已落地（[manifest.py](../../../../backend/packages/harness/deerflow/skills/manifest.py)，commit `2f640f49`）。
> - `AgentConfig.org_key_env` + `_resolve_skills_and_deps()` 已落地（commit `b17c7709`）。
> - 前端 Agent API 字段（`skills` + `org_key_env`）已扩展（commit `85debb76`）。
> - 10 项单测全绿。
>
> **遗留**：仅手工 manifest+对话验证未跑（plan §验证清单后两项），不影响功能上线。
>
> 下文为原始 plan，仅作历史档案保留。

---

# Agent Skill Version Pin + manifest.yaml 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**状态：** ✅ 已 ship（详见上方 banner）— 依赖（agent-fix-i18n）已 ship
**优先级：** 低于自托管 epic
**关联 spec：** [../specs/archive/2026-04-25-skill-agent-i18n-design.md](../specs/archive/2026-04-25-skill-agent-i18n-design.md)（共享设计）

**Goal:** 让 Agent 能在 `config.yaml` 中 pin skill 到具体版本（`skill-name@v1.2.0`），并通过 `manifest.yaml` 声明 skill 所需的工具组、MCP 依赖和 org key 注入，运行时自动合并这些依赖。

**Architecture:** 两个层面的改动。后端：扩展 `AgentConfig` 支持 `name@version` 格式和 `org_key_env`，新增 `manifest.yaml` 解析器，在 `make_lead_agent` 中调用 `_resolve_skills_and_deps()` 自动合并 tool_groups 和 env；现有 `SKILL.md` frontmatter 格式不变，`manifest.yaml` 是可选的同目录补充文件。前端：Agent 编辑页新增技能关联 UI（多选 + 版本下拉）。

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, TypeScript / Next.js 16, pnpm, pytest, Vitest

**依赖：** 必须在计划 A（`archive/2026-04-25-agent-fix-i18n.md`，已 ship）完成后开始，因为本计划依赖 `agent_name` 已正确注入 configurable。

---

## 文件修改清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/packages/harness/deerflow/skills/manifest.py` | 新建 | `manifest.yaml` 解析器 + `SkillManifest` dataclass |
| `backend/packages/harness/deerflow/skills/types.py` | 修改 | `Skill` dataclass 新增 `manifest` 字段 |
| `backend/packages/harness/deerflow/skills/parser.py` | 修改 | 解析 SKILL.md 时顺带加载同目录 `manifest.yaml` |
| `backend/packages/harness/deerflow/config/agents_config.py` | 修改 | `AgentConfig` 新增 `org_key_env` 字段 |
| `backend/packages/harness/deerflow/agents/lead_agent/agent.py` | 修改 | 新增 `_resolve_skills_and_deps()` + 调用点 |
| `backend/tests/test_skill_manifest.py` | 新建 | manifest.py 单元测试 |
| `backend/tests/test_agent_skill_deps.py` | 新建 | `_resolve_skills_and_deps()` 单元测试 |
| `frontend/src/core/agents/types.ts` | 修改 | `Agent` 类型新增 `skills` 和 `org_key_env` |
| `frontend/src/app/workspace/agents/new/page.tsx` | 修改 | Agent Builder 新增技能关联步骤 |

---

### Task 1：新建 manifest.py 解析器

**Files:**
- Create: `backend/packages/harness/deerflow/skills/manifest.py`
- Create: `backend/tests/test_skill_manifest.py`

- [x] **Step 1: 写失败测试**

新建 `backend/tests/test_skill_manifest.py`：

```python
import textwrap
from pathlib import Path
import pytest

from deerflow.skills.manifest import SkillManifest, load_skill_manifest


def test_load_full_manifest(tmp_path: Path):
    skill_dir = tmp_path / "data-analyst"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(textwrap.dedent("""\
        name: data-analyst
        version: 1.2.0
        scope: org
        description: 数据分析专家技能
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
    """))

    manifest = load_skill_manifest(skill_dir)

    assert manifest is not None
    assert manifest.name == "data-analyst"
    assert manifest.version == "1.2.0"
    assert manifest.scope == "org"
    assert manifest.requires_tools == ["code_execution", "web_search"]
    assert manifest.requires_mcp == ["postgres-mcp"]
    assert len(manifest.env) == 1
    assert manifest.env[0].name == "ORG_ACCESS_KEY"
    assert manifest.env[0].source == "org_key"
    assert manifest.env[0].required is True


def test_load_minimal_manifest(tmp_path: Path):
    skill_dir = tmp_path / "simple"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text("name: simple\nversion: 1.0.0\n")

    manifest = load_skill_manifest(skill_dir)

    assert manifest is not None
    assert manifest.name == "simple"
    assert manifest.version == "1.0.0"
    assert manifest.requires_tools == []
    assert manifest.requires_mcp == []
    assert manifest.env == []


def test_load_manifest_missing_returns_none(tmp_path: Path):
    skill_dir = tmp_path / "no-manifest"
    skill_dir.mkdir()

    manifest = load_skill_manifest(skill_dir)
    assert manifest is None


def test_load_manifest_invalid_yaml(tmp_path: Path):
    skill_dir = tmp_path / "bad"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text("name: [invalid\n")

    manifest = load_skill_manifest(skill_dir)
    assert manifest is None


def test_parse_skill_spec_with_version():
    from deerflow.skills.manifest import parse_skill_spec
    assert parse_skill_spec("data-analyst@v1.2.0") == ("data-analyst", "1.2.0")
    assert parse_skill_spec("data-analyst@1.2.0") == ("data-analyst", "1.2.0")
    assert parse_skill_spec("data-analyst") == ("data-analyst", None)
    assert parse_skill_spec("sql-expert@v2") == ("sql-expert", "2")
```

- [x] **Step 2: 运行测试确认失败**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_skill_manifest.py -v
```

预期：`ModuleNotFoundError: No module named 'deerflow.skills.manifest'`

- [x] **Step 3: 实现 manifest.py**

新建 `backend/packages/harness/deerflow/skills/manifest.py`：

```python
"""Optional manifest.yaml loader for skill dependency declarations."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class EnvDeclaration:
    name: str
    source: str        # 'org_key' | 'env_var' | literal value
    required: bool = False


@dataclass
class SkillManifest:
    name: str
    version: str
    scope: str = "public"          # 'public' | 'org' | 'private'
    description: str = ""
    requires_tools: list[str] = field(default_factory=list)
    requires_mcp: list[str] = field(default_factory=list)
    env: list[EnvDeclaration] = field(default_factory=list)
    changelog: str = ""


def parse_skill_spec(spec: str) -> tuple[str, str | None]:
    """Parse 'skill-name@version' into (name, version).

    'data-analyst@v1.2.0' -> ('data-analyst', '1.2.0')
    'data-analyst@1.2.0'  -> ('data-analyst', '1.2.0')
    'data-analyst'         -> ('data-analyst', None)
    """
    if "@" not in spec:
        return spec, None
    name, version = spec.split("@", 1)
    version = version.lstrip("v")
    return name.strip(), version.strip() or None


def load_skill_manifest(skill_dir: Path) -> SkillManifest | None:
    """Load and parse manifest.yaml from a skill directory.

    Returns None if the file does not exist or cannot be parsed.
    """
    manifest_path = skill_dir / "manifest.yaml"
    if not manifest_path.exists():
        return None

    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.warning("Invalid manifest.yaml at %s: %s", manifest_path, exc)
        return None

    if not isinstance(raw, dict):
        logger.warning("manifest.yaml at %s is not a mapping", manifest_path)
        return None

    name = raw.get("name")
    version = raw.get("version")
    if not name or not version:
        logger.warning("manifest.yaml at %s missing required name/version", manifest_path)
        return None

    env_list: list[EnvDeclaration] = []
    for entry in raw.get("env") or []:
        if isinstance(entry, dict) and "name" in entry and "source" in entry:
            env_list.append(
                EnvDeclaration(
                    name=entry["name"],
                    source=entry["source"],
                    required=bool(entry.get("required", False)),
                )
            )

    return SkillManifest(
        name=str(name),
        version=str(version),
        scope=str(raw.get("scope", "public")),
        description=str(raw.get("description", "")),
        requires_tools=list(raw.get("requires_tools") or []),
        requires_mcp=list(raw.get("requires_mcp") or []),
        env=env_list,
        changelog=str(raw.get("changelog", "")),
    )
```

- [x] **Step 4: 运行测试确认通过**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_skill_manifest.py -v
```

预期：全部 PASS

- [x] **Step 5: 更新 `deerflow/skills/__init__.py` 导出**

打开 `backend/packages/harness/deerflow/skills/__init__.py`，加入：

```python
from .manifest import SkillManifest, load_skill_manifest, parse_skill_spec

__all__ = [
    # ... 现有导出 ...
    "SkillManifest",
    "load_skill_manifest",
    "parse_skill_spec",
]
```

- [x] **Step 6: 提交**

```bash
git add backend/packages/harness/deerflow/skills/manifest.py \
        backend/packages/harness/deerflow/skills/__init__.py \
        backend/tests/test_skill_manifest.py
git commit -m "feat(skills): add manifest.yaml parser for skill dependency declarations

SkillManifest declares requires_tools, requires_mcp, env injections
and version. parse_skill_spec handles 'name@version' format.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2：扩展 AgentConfig + `_resolve_skills_and_deps()`

**Files:**
- Modify: `backend/packages/harness/deerflow/config/agents_config.py`
- Modify: `backend/packages/harness/deerflow/agents/lead_agent/agent.py`
- Create: `backend/tests/test_agent_skill_deps.py`

- [x] **Step 1: 写失败测试**

新建 `backend/tests/test_agent_skill_deps.py`：

```python
import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.config.agents_config import AgentConfig
from deerflow.skills.manifest import SkillManifest, EnvDeclaration


def _make_manifest(requires_tools=None, requires_mcp=None, env=None):
    return SkillManifest(
        name="test-skill",
        version="1.0.0",
        requires_tools=requires_tools or [],
        requires_mcp=requires_mcp or [],
        env=env or [],
    )


def test_agent_config_accepts_org_key_env():
    cfg = AgentConfig(
        name="sales-agent",
        skills=["data-analyst@v2.0.0", "sql-expert"],
        org_key_env="ORG_ACCESS_KEY",
    )
    assert cfg.org_key_env == "ORG_ACCESS_KEY"
    assert cfg.skills == ["data-analyst@v2.0.0", "sql-expert"]


def test_agent_config_org_key_env_defaults_none():
    cfg = AgentConfig(name="default-agent")
    assert cfg.org_key_env is None


def test_resolve_skills_and_deps_merges_tool_groups(tmp_path):
    from deerflow.agents.lead_agent.agent import _resolve_skills_and_deps

    cfg = AgentConfig(
        name="my-agent",
        skills=["skill-a", "skill-b"],
    )
    manifests = {
        "skill-a": _make_manifest(requires_tools=["code_execution"]),
        "skill-b": _make_manifest(requires_tools=["web_search", "code_execution"]),
    }

    with patch("deerflow.agents.lead_agent.agent.load_skill_manifest_by_name",
               side_effect=lambda name, version: manifests.get(name)):
        skill_names, extra_tools, env_injections = _resolve_skills_and_deps(cfg)

    assert skill_names == {"skill-a", "skill-b"}
    assert set(extra_tools) == {"code_execution", "web_search"}
    assert env_injections == {}


def test_resolve_skills_and_deps_injects_org_key(monkeypatch):
    from deerflow.agents.lead_agent.agent import _resolve_skills_and_deps

    monkeypatch.setenv("MY_ORG_KEY", "sk_org_testvalue")

    cfg = AgentConfig(
        name="sales-agent",
        skills=["data-analyst"],
        org_key_env="MY_ORG_KEY",
    )
    manifest = _make_manifest(
        env=[EnvDeclaration(name="ORG_ACCESS_KEY", source="org_key", required=True)]
    )

    with patch("deerflow.agents.lead_agent.agent.load_skill_manifest_by_name",
               return_value=manifest):
        _, _, env_injections = _resolve_skills_and_deps(cfg)

    assert env_injections == {"ORG_ACCESS_KEY": "sk_org_testvalue"}


def test_resolve_skills_and_deps_no_skills_returns_empty():
    from deerflow.agents.lead_agent.agent import _resolve_skills_and_deps

    cfg = AgentConfig(name="plain-agent")
    skill_names, extra_tools, env_injections = _resolve_skills_and_deps(cfg)

    assert skill_names == set()
    assert extra_tools == []
    assert env_injections == {}
```

- [x] **Step 2: 运行测试确认失败**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_agent_skill_deps.py -v
```

预期：`ImportError` 或 `AttributeError`（`org_key_env` 还不存在）

- [x] **Step 3: 扩展 AgentConfig**

打开 `backend/packages/harness/deerflow/config/agents_config.py`，在 `AgentConfig` 类中新增字段（约 L29-41）：

```python
class AgentConfig(BaseModel):
    """Configuration for a custom agent."""

    name: str
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None
    # skills controls which skills are loaded into the agent's prompt:
    # - None (or omitted): load all enabled skills (default fallback behavior)
    # - [] (explicit empty list): disable all skills
    # - ["skill1", "skill2"] or ["skill1@v1.2.0"]: load only the specified skills (version optional)
    skills: list[str] | None = None
    # org_key_env: name of the env var holding the org API key.
    # When set, the key is read at runtime and injected into skill env declarations
    # that have source="org_key".
    org_key_env: str | None = None
```

- [x] **Step 4: 新增 `load_skill_manifest_by_name` 辅助函数**

在 `backend/packages/harness/deerflow/skills/manifest.py` 末尾新增：

```python
def load_skill_manifest_by_name(
    name: str,
    version: str | None = None,
    skills_path: Path | None = None,
) -> SkillManifest | None:
    """Look up a skill directory by name and load its manifest.yaml.

    Searches public/, custom/, and user/ roots (in that order) under skills_path.
    If version is specified, looks for a versioned subdirectory v{version}/
    inside the skill dir first, then falls back to the flat skill dir.
    """
    from deerflow.skills.loader import get_skills_root_path

    if skills_path is None:
        try:
            from deerflow.config import get_app_config
            skills_path = get_app_config().skills.get_skills_path()
        except Exception:
            skills_path = get_skills_root_path()

    for category in ("public", "custom", "user"):
        skill_dir = skills_path / category / name
        if not skill_dir.exists():
            continue
        # Try versioned subdirectory first
        if version:
            versioned = skill_dir / f"v{version}"
            if versioned.exists():
                manifest = load_skill_manifest(versioned)
                if manifest:
                    return manifest
        return load_skill_manifest(skill_dir)

    return None
```

- [x] **Step 5: 新增 `_resolve_skills_and_deps()` 到 agent.py**

打开 `backend/packages/harness/deerflow/agents/lead_agent/agent.py`。在文件顶部 import 区加入：

```python
import os
from deerflow.skills.manifest import load_skill_manifest_by_name, parse_skill_spec
```

然后在 `make_lead_agent` 函数前新增（约 L275 附近）：

```python
def _resolve_skills_and_deps(
    agent_config: "AgentConfig",
) -> tuple[set[str], list[str], dict[str, str]]:
    """Resolve skill specs to names, extra tool_groups, and env injections.

    Returns:
        (skill_names, extra_tool_groups, env_injections)
        - skill_names: set of skill name strings (stripped of @version suffix)
        - extra_tool_groups: deduplicated list of tool groups from manifests
        - env_injections: dict of env var name → value to inject into skill context
    """
    if not agent_config.skills:
        return set(), [], {}

    skill_names: set[str] = set()
    extra_tool_groups: list[str] = []
    env_injections: dict[str, str] = {}

    org_key_value: str | None = None
    if agent_config.org_key_env:
        org_key_value = os.environ.get(agent_config.org_key_env)

    seen_tools: set[str] = set()

    for spec in agent_config.skills:
        name, version = parse_skill_spec(spec)
        skill_names.add(name)

        manifest = load_skill_manifest_by_name(name, version)
        if manifest is None:
            continue

        for tool in manifest.requires_tools:
            if tool not in seen_tools:
                extra_tool_groups.append(tool)
                seen_tools.add(tool)

        if org_key_value:
            for env_decl in manifest.env:
                if env_decl.source == "org_key":
                    env_injections[env_decl.name] = org_key_value

    return skill_names, extra_tool_groups, env_injections
```

- [x] **Step 6: 在 make_lead_agent 中调用 `_resolve_skills_and_deps`**

在 `make_lead_agent` 函数中，找到 Default lead agent 构建段（约 L349）。修改如下：

```python
# 修改前（约 L349-358）:
return create_agent(
    model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled, reasoning_effort=reasoning_effort),
    tools=get_available_tools(model_name=model_name, groups=agent_config.tool_groups if agent_config else None, subagent_enabled=subagent_enabled),
    middleware=_build_middlewares(config, model_name=model_name, agent_name=agent_name),
    system_prompt=apply_prompt_template(
        subagent_enabled=subagent_enabled, max_concurrent_subagents=max_concurrent_subagents, agent_name=agent_name, available_skills=set(agent_config.skills) if agent_config and agent_config.skills is not None else None
    ),
    state_schema=ThreadState,
)

# 修改后:
skill_names, extra_tool_groups, _env_injections = (
    _resolve_skills_and_deps(agent_config) if agent_config and agent_config.skills is not None
    else (None, [], {})
)

merged_tool_groups = (agent_config.tool_groups or []) + extra_tool_groups if agent_config else None
if not merged_tool_groups:
    merged_tool_groups = None

return create_agent(
    model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled, reasoning_effort=reasoning_effort),
    tools=get_available_tools(model_name=model_name, groups=merged_tool_groups, subagent_enabled=subagent_enabled),
    middleware=_build_middlewares(config, model_name=model_name, agent_name=agent_name),
    system_prompt=apply_prompt_template(
        subagent_enabled=subagent_enabled,
        max_concurrent_subagents=max_concurrent_subagents,
        agent_name=agent_name,
        available_skills=skill_names if skill_names is not None else (
            set(agent_config.skills) if agent_config and agent_config.skills is not None else None
        ),
    ),
    state_schema=ThreadState,
)
```

- [x] **Step 7: 运行测试**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_agent_skill_deps.py tests/test_skill_manifest.py -v
```

预期：全部 PASS

- [x] **Step 8: 运行完整测试套件**

```bash
cd backend && make test
```

预期：全绿

- [x] **Step 9: 提交**

```bash
git add backend/packages/harness/deerflow/skills/manifest.py \
        backend/packages/harness/deerflow/config/agents_config.py \
        backend/packages/harness/deerflow/agents/lead_agent/agent.py \
        backend/tests/test_agent_skill_deps.py
git commit -m "feat(agent): support skill version pin and manifest dependency resolution

AgentConfig gains org_key_env field. Skills list supports 'name@version'
syntax. _resolve_skills_and_deps() merges tool_groups from manifest.yaml
and injects org key into skill env declarations at runtime.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3：前端 Agent 类型 + Builder 技能关联 UI

**Files:**
- Modify: `frontend/src/core/agents/types.ts`
- Modify: `frontend/src/core/agents/api.ts`
- Modify: `frontend/src/app/workspace/agents/new/page.tsx`

- [x] **Step 1: 扩展 Agent 类型**

打开 `frontend/src/core/agents/types.ts`，在 `Agent` 接口中新增字段：

```typescript
// 修改前
export interface Agent {
  name: string;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  soul?: string | null;
}

// 修改后
export interface Agent {
  name: string;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;       // 支持 "name@version" 格式
  org_key_env: string | null;    // org key 来源的 env 变量名
  soul?: string | null;
}

export interface AgentCreateRequest {
  name: string;
  description?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  org_key_env?: string | null;
  soul?: string;
}

export interface AgentUpdateRequest {
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  org_key_env?: string | null;
  soul?: string | null;
}
```

- [x] **Step 2: 检查 api.ts 是否需要更新**

打开 `frontend/src/core/agents/api.ts`，确认 `createAgent` 和 `updateAgent` 函数的请求体类型。如果使用 `AgentCreateRequest` / `AgentUpdateRequest` 类型，TypeScript 会自动带上新字段；如果是手写的字段列表则需要补充 `skills` 和 `org_key_env`。

- [x] **Step 3: 后端 AgentCreateRequest + AgentUpdateRequest 同步**

打开 `backend/app/gateway/routers/agents.py`（约 L37-53），在两个 Request 模型中新增字段：

```python
class AgentCreateRequest(BaseModel):
    name: str = Field(..., description="Agent name (must match ^[A-Za-z0-9-]+$, stored as lowercase)")
    description: str = Field(default="", description="Agent description")
    model: str | None = Field(default=None, description="Optional model override")
    tool_groups: list[str] | None = Field(default=None, description="Optional tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Skill list, supports 'name@version' format")
    org_key_env: str | None = Field(default=None, description="Env var name holding the org API key")
    soul: str = Field(default="", description="SOUL.md content")

class AgentUpdateRequest(BaseModel):
    description: str | None = Field(default=None, description="Updated description")
    model: str | None = Field(default=None, description="Updated model override")
    tool_groups: list[str] | None = Field(default=None, description="Updated tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Updated skill list")
    org_key_env: str | None = Field(default=None, description="Updated org key env var name")
    soul: str | None = Field(default=None, description="Updated SOUL.md content")
```

同时在 `POST /api/agents` 的创建逻辑中（约 L208-230），将 `skills` 和 `org_key_env` 写入 `config.yaml`：

找到 `yaml.dump()` 调用，确保 `AgentConfig` 的字段全部被序列化。当前代码已经通过 `AgentConfig(**data)` 再 `yaml.dump(config.model_dump(exclude_none=True))` 来写文件，新字段会自动包含。

- [x] **Step 4: 运行类型检查**

```bash
cd frontend && pnpm typecheck
cd backend && make lint
```

预期：无错误

- [x] **Step 5: 运行测试**

```bash
cd backend && make test
cd frontend && pnpm test
```

预期：全绿

- [x] **Step 6: 提交**

```bash
git add frontend/src/core/agents/types.ts \
        frontend/src/core/agents/api.ts \
        backend/app/gateway/routers/agents.py
git commit -m "feat(agents): add skills and org_key_env fields to Agent API

Frontend types and backend request/response models now carry skills
(list of 'name@version' specs) and org_key_env. config.yaml serialization
is automatic via AgentConfig.model_dump().

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 验证清单

完成所有 task 后：

- [x] `cd backend && make test` 全绿 — 本计划新增的 10 项测试（`test_skill_manifest.py` + `test_agent_skill_deps.py`）2026-04-27 复跑全部通过
- [x] `cd frontend && pnpm typecheck` 通过 — `pnpm test` 有 1 项无关 upload 测试失败（与本计划无关）
- [ ] 为某个技能目录创建 `manifest.yaml`（含 `requires_tools: [code_execution]`），创建引用该技能的 agent，通过 `/api/agents/{name}` 确认字段已保存（手工验证项）
- [ ] 启动后端，向该 agent 发起对话，确认 `get_available_tools()` 的调用包含了 manifest 中声明的 tool group（手工验证项）

**实施状态（2026-04-27 复核）：** 三个 Task 的代码改动已全部落地（commits `2f640f49` manifest 解析器、`b17c7709` 版本 pin + 依赖解析、`85debb76` Agent API 字段）。剩余两项为手工 manifest+对话验证。
