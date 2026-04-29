> 📦 **归档于 2026-04-29 — 已 ship**
>
> **当前事实**：
> - 后端 `GET /api/tool-groups` 已实装（[agents.py](../../../../backend/app/gateway/routers/agents.py) line 123）。
> - 前端 edit page 已上线（[frontend/src/app/workspace/agents/[agent_name]/edit/page.tsx](../../../../frontend/src/app/workspace/agents/%5Bagent_name%5D/edit/page.tsx)）。
> - i18n keys（`agents.edit*`）、tri-state helper、`useToolGroups` hook 全部交付。
>
> 下文为施工时的原始 plan，仅作历史档案保留。

---

# Custom Agent Edit Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the missing UI to edit a custom agent's full configuration (description / model / tool_groups / skills / org_key_env / SOUL.md) and add a tool-groups discovery endpoint behind it.

**Architecture:**
- Backend: add one read-only `GET /api/tool-groups` to the existing `agents.py` router (reuses `_require_agents_api_enabled`).
- Frontend: add `/workspace/agents/[agent_name]/edit` page, an Edit icon button on `AgentCard`, a `useToolGroups` hook, and i18n keys. Three-state (`null` / `[]` / `["a","b"]`) handled by a tiny `useTriState` decoder/encoder helper used twice (tool_groups + skills) to keep the page DRY and unit-testable.
- Tests: backend `tests/test_agents_router.py` (new file, FastAPI `TestClient`, no PG/Redis) + frontend `tests/unit/core/agents/` (new dir, Vitest unit tests for `useTriState` and the `useToolGroups` query).

**Tech Stack:** FastAPI, Pydantic v2, Next.js 16 App Router, React 19, TanStack Query, lucide-react, Vitest, pytest, FastAPI TestClient.

**Spec:** [docs/superpowers/specs/2026-04-27-custom-agent-edit-page-design.md](../specs/2026-04-27-custom-agent-edit-page-design.md)

**Convention notes from spec review:**
- "用户已认可可执行" — proceed without further design questions; if any new ambiguity appears mid-task, prefer the simpler option that preserves the spec's three-state semantics.
- `org_key_env`: spec doesn't define UI semantics for this single-value optional field. Decision: **render as a plain text input; empty string maps to `null` on save** (matches how the create flow leaves the field optional). Document inline in the page.
- Permission: spec says reuse `_require_agents_api_enabled`. Keep that — operators who toggle off agent management API also lose tool-groups listing, which is consistent.
- Skill `name@version` transparent passthrough — internal state stores the **full string** (`"my_skill"` or `"my_skill@1.2.0"`); checkbox match key is the bare `name` derived from `value.split("@", 1)[0]`.

---

## File Structure

**Backend** (1 file modified, 1 file created):
- Modify: [backend/app/gateway/routers/agents.py](../../backend/app/gateway/routers/agents.py) — add `ToolGroupResponse`, `ToolGroupsListResponse`, `GET /api/tool-groups` handler. ~30 lines added.
- Create: [backend/tests/test_agents_router.py](../../backend/tests/test_agents_router.py) — FastAPI `TestClient` regressions for the new route + a tool_groups three-state PUT regression.

**Frontend** (5 files modified, 4 files created):
- Modify: [frontend/src/core/agents/api.ts](../../frontend/src/core/agents/api.ts) — add `listToolGroups()`.
- Modify: [frontend/src/core/agents/hooks.ts](../../frontend/src/core/agents/hooks.ts) — add `useToolGroups()`.
- Modify: [frontend/src/core/agents/index.ts](../../frontend/src/core/agents/index.ts) — re-export the new symbols.
- Create: [frontend/src/core/agents/tri-state.ts](../../frontend/src/core/agents/tri-state.ts) — pure `decodeTriState`/`encodeTriState`, plus skill `name@version` helpers. **Pure functions, no React, fully unit-testable.**
- Modify: [frontend/src/components/workspace/agents/agent-card.tsx](../../frontend/src/components/workspace/agents/agent-card.tsx) — add Edit icon button between Chat and Delete.
- Create: [frontend/src/app/workspace/agents/\[agent_name\]/edit/page.tsx](../../frontend/src/app/workspace/agents/%5Bagent_name%5D/edit/page.tsx) — the edit form. Single client component; ~250 lines.
- Modify: [frontend/src/core/i18n/locales/types.ts](../../frontend/src/core/i18n/locales/types.ts) — add `agents.edit*` keys.
- Modify: [frontend/src/core/i18n/locales/en-US.ts](../../frontend/src/core/i18n/locales/en-US.ts) — add English values.
- Modify: [frontend/src/core/i18n/locales/zh-CN.ts](../../frontend/src/core/i18n/locales/zh-CN.ts) — add Chinese values.
- Create: [frontend/tests/unit/core/agents/tri-state.test.ts](../../frontend/tests/unit/core/agents/tri-state.test.ts) — pure unit tests of the encode/decode helpers.
- Create: [frontend/tests/unit/core/agents/hooks.test.tsx](../../frontend/tests/unit/core/agents/hooks.test.tsx) — `useToolGroups` query test against a mocked `fetch`.

---

## Task 1: Backend — `GET /api/tool-groups` endpoint

**Files:**
- Modify: `backend/app/gateway/routers/agents.py` (insert response models + handler near the existing list_agents handler)
- Test: `backend/tests/test_agents_router.py` (new file)

- [ ] **Step 1: Write the failing test for the new endpoint**

Create `backend/tests/test_agents_router.py`:

```python
"""TestClient regressions for the agents router (M7a edit-page support)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.gateway.routers.agents as agents_router
from deerflow.config.agents_api_config import AgentsApiConfig
from deerflow.config.app_config import AppConfig
from deerflow.config.tool_config import ToolGroupConfig


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agents_router.router)
    return app


@pytest.fixture
def enable_agents_api(monkeypatch):
    monkeypatch.setattr(
        "app.gateway.routers.agents.get_agents_api_config",
        lambda: AgentsApiConfig(enabled=True),
    )


@pytest.fixture
def stub_app_config(monkeypatch):
    """Provide a deterministic AppConfig.tool_groups list."""

    cfg = AppConfig(
        tool_groups=[
            ToolGroupConfig(name="search"),
            ToolGroupConfig(name="python"),
            ToolGroupConfig(name="files"),
        ],
    )
    monkeypatch.setattr("app.gateway.routers.agents.get_app_config", lambda: cfg)
    return cfg


def test_list_tool_groups_returns_config_names(enable_agents_api, stub_app_config):
    with TestClient(_build_app()) as client:
        response = client.get("/api/tool-groups")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "tool_groups": [
            {"name": "search"},
            {"name": "python"},
            {"name": "files"},
        ]
    }


def test_list_tool_groups_returns_403_when_agents_api_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.gateway.routers.agents.get_agents_api_config",
        lambda: AgentsApiConfig(enabled=False),
    )

    with TestClient(_build_app()) as client:
        response = client.get("/api/tool-groups")

    assert response.status_code == 403
    assert "agents_api.enabled" in response.json()["detail"]
```

- [ ] **Step 2: Run the test to verify it fails (route + import don't exist yet)**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_agents_router.py -v`
Expected: 2 tests FAIL — `test_list_tool_groups_*` either 404 (route missing) or `AttributeError` (`get_app_config` not imported in `agents.py`).

- [ ] **Step 3: Implement the endpoint**

Edit `backend/app/gateway/routers/agents.py`:

1. Add `from deerflow.config.app_config import get_app_config` near the existing config imports at the top of the file (alongside `from deerflow.config.agents_api_config import get_agents_api_config`).
2. Insert these new model definitions **immediately after** `class AgentsListResponse(BaseModel)` (around line 37):

```python
class ToolGroupResponse(BaseModel):
    """Response model for a single tool group."""

    name: str = Field(..., description="Tool group name")


class ToolGroupsListResponse(BaseModel):
    """Response model for listing all tool groups defined in config.yaml."""

    tool_groups: list[ToolGroupResponse]
```

3. Insert the handler **immediately before** `@router.get("/agents", ...)` (around line 109 — i.e. right after the helpers and before the first `/agents` route). This keeps it discoverable next to the other GET routes:

```python
@router.get(
    "/tool-groups",
    response_model=ToolGroupsListResponse,
    summary="List Tool Groups",
    description="List all tool groups defined in config.yaml.",
)
async def list_tool_groups() -> ToolGroupsListResponse:
    """Return the names of every tool group from the active config.yaml.

    Used by the agent edit page to populate the tool-groups multi-select.
    """
    _require_agents_api_enabled()
    cfg = get_app_config()
    return ToolGroupsListResponse(
        tool_groups=[ToolGroupResponse(name=g.name) for g in cfg.tool_groups]
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_agents_router.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/routers/agents.py backend/tests/test_agents_router.py
git commit -m "feat(agents): add GET /api/tool-groups for edit-page dropdown

$(cat <<'EOF'
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Backend — three-state regression for PUT `/api/agents/{name}` `tool_groups`

The spec calls out a regression matrix that is partially covered by existing tests. We add a single TestClient round-trip that covers the three transitions explicitly, hitting the real filesystem via `tmp_path`.

**Files:**
- Test: `backend/tests/test_agents_router.py` (extend the file from Task 1)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_agents_router.py`:

```python
import yaml
from pathlib import Path

from deerflow.config.paths import Paths


@pytest.fixture
def isolated_paths(monkeypatch, tmp_path):
    """Point all path helpers at a tmp dir so we can write a real agent dir."""

    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("app.gateway.routers.agents.get_paths", lambda: paths)
    return paths


def _seed_agent(paths, name: str, *, config: dict, soul: str = "") -> Path:
    agent_dir = paths.agent_dir(name)
    agent_dir.mkdir(parents=True, exist_ok=True)
    config = {"name": name, **config}
    (agent_dir / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")
    return agent_dir


def _read_yaml(agent_dir: Path) -> dict:
    return yaml.safe_load((agent_dir / "config.yaml").read_text(encoding="utf-8"))


def test_put_agent_tool_groups_three_state_transitions(
    enable_agents_api, isolated_paths
):
    """Round-trip every transition the edit page can produce.

    null  -> []       (turn off "use all", no selections)
    []    -> ["a"]    (add a selection)
    ["a"] -> null     (turn "use all" back on)
    """
    name = "edit-test-agent"
    agent_dir = _seed_agent(isolated_paths, name, config={})  # no tool_groups key = null

    client = TestClient(_build_app())

    # Transition 1: null -> []
    r1 = client.put(f"/api/agents/{name}", json={"tool_groups": []})
    assert r1.status_code == 200, r1.text
    assert r1.json()["tool_groups"] == []
    assert _read_yaml(agent_dir).get("tool_groups") == []

    # Transition 2: [] -> ["a"]
    r2 = client.put(f"/api/agents/{name}", json={"tool_groups": ["a"]})
    assert r2.status_code == 200, r2.text
    assert r2.json()["tool_groups"] == ["a"]
    assert _read_yaml(agent_dir).get("tool_groups") == ["a"]

    # Transition 3: ["a"] -> null
    # NOTE: existing handler only writes the key when value is not None,
    # so passing null in the JSON body should drop the key from the YAML.
    r3 = client.put(f"/api/agents/{name}", json={"tool_groups": None})
    assert r3.status_code == 200, r3.text
    assert r3.json()["tool_groups"] is None
    assert "tool_groups" not in _read_yaml(agent_dir)
```

- [ ] **Step 2: Run the test to confirm current behavior**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_agents_router.py::test_put_agent_tool_groups_three_state_transitions -v`
Expected: PASS (this is a regression — `update_agent` already implements the semantics correctly via `model_fields_set`). If it fails, **stop and investigate** — the spec assumes this contract holds; do NOT modify the handler.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_agents_router.py
git commit -m "test(agents): pin tool_groups three-state transitions for PUT /api/agents/{name}

$(cat <<'EOF'
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Frontend — pure `tri-state` helper module

This is the foundation the edit page sits on. Pure functions, no React, fully testable in isolation.

**Files:**
- Create: `frontend/src/core/agents/tri-state.ts`
- Test: `frontend/tests/unit/core/agents/tri-state.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/core/agents/tri-state.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  decodeTriState,
  encodeTriState,
  skillBaseName,
  toggleSkillSelection,
} from "@/core/agents/tri-state";

describe("decodeTriState", () => {
  it("treats null as 'use all'", () => {
    expect(decodeTriState(null)).toEqual({ useAll: true, selected: [] });
  });

  it("treats [] as 'all off'", () => {
    expect(decodeTriState([])).toEqual({ useAll: false, selected: [] });
  });

  it("treats a non-empty list as 'whitelist'", () => {
    expect(decodeTriState(["a", "b"])).toEqual({
      useAll: false,
      selected: ["a", "b"],
    });
  });

  it("preserves skills with @version pin in selected", () => {
    expect(decodeTriState(["my_skill@1.2.0", "plain"])).toEqual({
      useAll: false,
      selected: ["my_skill@1.2.0", "plain"],
    });
  });
});

describe("encodeTriState", () => {
  it("returns null when useAll", () => {
    expect(encodeTriState({ useAll: true, selected: [] })).toBeNull();
    expect(encodeTriState({ useAll: true, selected: ["ignored"] })).toBeNull();
  });

  it("returns [] when useAll is false and nothing selected", () => {
    expect(encodeTriState({ useAll: false, selected: [] })).toEqual([]);
  });

  it("returns the selected list verbatim otherwise", () => {
    expect(encodeTriState({ useAll: false, selected: ["a", "b"] })).toEqual([
      "a",
      "b",
    ]);
  });
});

describe("skillBaseName", () => {
  it("strips @version suffix", () => {
    expect(skillBaseName("my_skill@1.2.0")).toBe("my_skill");
    expect(skillBaseName("plain")).toBe("plain");
  });
});

describe("toggleSkillSelection", () => {
  it("adds bare name when not present", () => {
    expect(toggleSkillSelection(["a"], "b")).toEqual(["a", "b"]);
  });

  it("removes by base name (drops @version too)", () => {
    expect(toggleSkillSelection(["my_skill@1.2.0", "other"], "my_skill")).toEqual(
      ["other"],
    );
  });

  it("preserves @version pin when re-toggling within session", () => {
    // Off then on within the same session: the page tracks the previous value
    // and passes it back as initialPin.
    const offThenOn = toggleSkillSelection(
      ["other"],
      "my_skill",
      "my_skill@1.2.0",
    );
    expect(offThenOn).toEqual(["other", "my_skill@1.2.0"]);
  });

  it("falls back to bare name when no pin remembered", () => {
    expect(toggleSkillSelection(["other"], "my_skill")).toEqual([
      "other",
      "my_skill",
    ]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test tests/unit/core/agents/tri-state.test.ts`
Expected: FAIL with "Cannot find module '@/core/agents/tri-state'".

- [ ] **Step 3: Implement the helper**

Create `frontend/src/core/agents/tri-state.ts`:

```ts
/**
 * Tri-state encoder/decoder for fields whose backend value is one of:
 *   null         → "inherit / use all"
 *   []           → "explicitly all off"
 *   ["a", ...]   → "whitelist"
 *
 * Used by the agent edit page for both `tool_groups` and `skills`.
 */

export interface TriState {
  useAll: boolean;
  selected: string[];
}

export function decodeTriState(value: string[] | null | undefined): TriState {
  if (value === null || value === undefined) {
    return { useAll: true, selected: [] };
  }
  return { useAll: false, selected: [...value] };
}

export function encodeTriState(state: TriState): string[] | null {
  if (state.useAll) return null;
  return [...state.selected];
}

/** Skill values may be `name` or `name@version`. The base name is the part
 *  before the first `@`. Used as the checkbox match key. */
export function skillBaseName(value: string): string {
  const idx = value.indexOf("@");
  return idx === -1 ? value : value.slice(0, idx);
}

/**
 * Toggle a skill in/out of the selected list, matching by base name so
 * `name@version` strings survive the round trip.
 *
 * Off → On with `initialPin = "name@1.2"` re-attaches the version that was
 * stored before the user toggled off.
 */
export function toggleSkillSelection(
  selected: string[],
  baseName: string,
  initialPin?: string,
): string[] {
  const idx = selected.findIndex((v) => skillBaseName(v) === baseName);
  if (idx >= 0) {
    return [...selected.slice(0, idx), ...selected.slice(idx + 1)];
  }
  return [...selected, initialPin ?? baseName];
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm test tests/unit/core/agents/tri-state.test.ts`
Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/agents/tri-state.ts frontend/tests/unit/core/agents/tri-state.test.ts
git commit -m "feat(agents): add tri-state helper for tool_groups/skills encoding

$(cat <<'EOF'
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Frontend — `listToolGroups` API client + `useToolGroups` hook

**Files:**
- Modify: `frontend/src/core/agents/api.ts`
- Modify: `frontend/src/core/agents/hooks.ts`
- Modify: `frontend/src/core/agents/index.ts`
- Test: `frontend/tests/unit/core/agents/hooks.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/core/agents/hooks.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { useToolGroups } from "@/core/agents/hooks";

function wrapper({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useToolGroups", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the tool_groups from the API response", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tool_groups: [{ name: "search" }, { name: "python" }] }),
    });

    const { result } = renderHook(() => useToolGroups(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.toolGroups).toEqual([
      { name: "search" },
      { name: "python" },
    ]);
  });

  it("surfaces errors", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      statusText: "Forbidden",
    });

    const { result } = renderHook(() => useToolGroups(), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.toolGroups).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test tests/unit/core/agents/hooks.test.tsx`
Expected: FAIL with "useToolGroups is not exported".

- [ ] **Step 3: Add `listToolGroups` to `api.ts`**

Append to `frontend/src/core/agents/api.ts` (after the existing `checkAgentName` function):

```ts
export interface ToolGroupSummary {
  name: string;
}

export async function listToolGroups(): Promise<ToolGroupSummary[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/tool-groups`);
  if (!res.ok) {
    throw new Error(`Failed to load tool groups: ${res.statusText}`);
  }
  const data = (await res.json()) as { tool_groups: ToolGroupSummary[] };
  return data.tool_groups;
}
```

- [ ] **Step 4: Add `useToolGroups` to `hooks.ts`**

Edit `frontend/src/core/agents/hooks.ts`:

1. Add `listToolGroups` to the imports from `./api`:

```ts
import {
  createAgent,
  deleteAgent,
  getAgent,
  listAgents,
  listToolGroups,
  updateAgent,
} from "./api";
```

2. Append at the end of the file:

```ts
export function useToolGroups() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["tool-groups"],
    queryFn: () => listToolGroups(),
  });
  return { toolGroups: data ?? [], isLoading, error };
}
```

- [ ] **Step 5: Re-export from `index.ts`**

Open `frontend/src/core/agents/index.ts`, add to the existing re-exports so the new symbols are reachable from `@/core/agents`:

```ts
export { listToolGroups, type ToolGroupSummary } from "./api";
export { useToolGroups } from "./hooks";
```

(If the file uses `export *` already, this step may be a no-op — verify by reading the file first.)

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && pnpm test tests/unit/core/agents/hooks.test.tsx`
Expected: both tests PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/core/agents/api.ts frontend/src/core/agents/hooks.ts frontend/src/core/agents/index.ts frontend/tests/unit/core/agents/hooks.test.tsx
git commit -m "feat(agents): listToolGroups API client + useToolGroups hook

$(cat <<'EOF'
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Frontend — i18n keys

**Files:**
- Modify: `frontend/src/core/i18n/locales/types.ts`
- Modify: `frontend/src/core/i18n/locales/en-US.ts`
- Modify: `frontend/src/core/i18n/locales/zh-CN.ts`

- [ ] **Step 1: Add the new keys to the type definition**

Edit `frontend/src/core/i18n/locales/types.ts`. Locate the `agents:` block (around line 123) and append these new keys **before the closing `}`** of `agents`:

```ts
    edit: string;
    editPageTitle: string;
    editBasicSection: string;
    editAdvancedSection: string;
    editFieldDescription: string;
    editFieldDescriptionPlaceholder: string;
    editFieldModel: string;
    editFieldModelDefault: string;
    editFieldSoul: string;
    editFieldSoulPlaceholder: string;
    editFieldToolGroups: string;
    editFieldSkills: string;
    editFieldOrgKeyEnv: string;
    editFieldOrgKeyEnvPlaceholder: string;
    editUseAllToolGroups: string;
    editUseAllSkills: string;
    editSaveSuccess: string;
    editSaveFailed: string;
    editLoadFailed: string;
    editLoadFailedBack: string;
    editVersionPinned: string;
    editToolGroupsLoadFailed: string;
    editSkillsLoadFailed: string;
```

- [ ] **Step 2: Add English values**

Edit `frontend/src/core/i18n/locales/en-US.ts`. Find the `agents:` block, add at the end of it (before the closing brace):

```ts
    edit: "Edit",
    editPageTitle: "Edit Agent",
    editBasicSection: "Basic info",
    editAdvancedSection: "Advanced",
    editFieldDescription: "Description",
    editFieldDescriptionPlaceholder: "Short summary of what this agent does",
    editFieldModel: "Model",
    editFieldModelDefault: "Use global default",
    editFieldSoul: "SOUL.md",
    editFieldSoulPlaceholder: "Personality and behavioral guardrails (Markdown)",
    editFieldToolGroups: "Tool groups",
    editFieldSkills: "Skills",
    editFieldOrgKeyEnv: "Org key env var",
    editFieldOrgKeyEnvPlaceholder: "e.g. MY_ORG_OPENAI_API_KEY (leave blank to inherit)",
    editUseAllToolGroups: "Use all enabled tool groups",
    editUseAllSkills: "Inherit all enabled skills",
    editSaveSuccess: "Agent updated",
    editSaveFailed: "Failed to update agent",
    editLoadFailed: "Failed to load agent",
    editLoadFailedBack: "Back to agents",
    editVersionPinned: "v{version} pinned",
    editToolGroupsLoadFailed: "Failed to load tool groups",
    editSkillsLoadFailed: "Failed to load skills",
```

- [ ] **Step 3: Add Chinese values**

Edit `frontend/src/core/i18n/locales/zh-CN.ts`. Find the `agents:` block, add at the end of it:

```ts
    edit: "编辑",
    editPageTitle: "编辑智能体",
    editBasicSection: "基本信息",
    editAdvancedSection: "高级",
    editFieldDescription: "描述",
    editFieldDescriptionPlaceholder: "简单介绍这个智能体的用途",
    editFieldModel: "模型",
    editFieldModelDefault: "使用全局默认",
    editFieldSoul: "SOUL.md",
    editFieldSoulPlaceholder: "性格设定与行为约束（Markdown）",
    editFieldToolGroups: "工具组",
    editFieldSkills: "技能",
    editFieldOrgKeyEnv: "组织 key 环境变量",
    editFieldOrgKeyEnvPlaceholder: "如 MY_ORG_OPENAI_API_KEY，留空表示继承",
    editUseAllToolGroups: "使用全部已启用的工具组",
    editUseAllSkills: "继承所有已启用的技能",
    editSaveSuccess: "智能体已更新",
    editSaveFailed: "更新智能体失败",
    editLoadFailed: "加载智能体失败",
    editLoadFailedBack: "返回列表",
    editVersionPinned: "已锁版本 v{version}",
    editToolGroupsLoadFailed: "加载工具组失败",
    editSkillsLoadFailed: "加载技能失败",
```

- [ ] **Step 4: Run typecheck**

Run: `cd frontend && pnpm typecheck`
Expected: PASS (no missing-key errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/i18n/locales/types.ts frontend/src/core/i18n/locales/en-US.ts frontend/src/core/i18n/locales/zh-CN.ts
git commit -m "i18n(agents): add edit-page keys (en-US, zh-CN)

$(cat <<'EOF'
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Frontend — Edit page (`/workspace/agents/[agent_name]/edit`)

This is the largest task. It assembles tri-state state, hooks, and i18n into a single client component.

**Files:**
- Create: `frontend/src/app/workspace/agents/[agent_name]/edit/page.tsx`

- [ ] **Step 1: Create the edit page**

Create `frontend/src/app/workspace/agents/[agent_name]/edit/page.tsx`:

```tsx
"use client";

import { ArrowLeftIcon } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useAgent, useToolGroups, useUpdateAgent } from "@/core/agents";
import {
  decodeTriState,
  encodeTriState,
  skillBaseName,
  toggleSkillSelection,
  type TriState,
} from "@/core/agents/tri-state";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useSkills } from "@/core/skills/hooks";

export default function EditAgentPage() {
  const { t } = useI18n();
  const router = useRouter();
  const params = useParams<{ agent_name: string }>();
  const agentName = params?.agent_name ?? "";

  const { agent, isLoading: agentLoading, error: agentError } = useAgent(agentName);
  const { models } = useModels();
  const { toolGroups, error: toolGroupsError } = useToolGroups();
  const { skills, error: skillsError } = useSkills();
  const updateAgent = useUpdateAgent();

  // Form state — initialized from the loaded agent.
  const [description, setDescription] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [orgKeyEnv, setOrgKeyEnv] = useState("");
  const [soul, setSoul] = useState("");
  const [toolGroupsState, setToolGroupsState] = useState<TriState>({
    useAll: true,
    selected: [],
  });
  const [skillsState, setSkillsState] = useState<TriState>({
    useAll: true,
    selected: [],
  });

  // Remember the @version pin per skill name across toggle off/on within the
  // same session (spec §详细设计 — Skills name@version 处理).
  const [skillPins, setSkillPins] = useState<Record<string, string>>({});

  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (!agent || hydrated) return;
    setDescription(agent.description ?? "");
    setModel(agent.model);
    setOrgKeyEnv(agent.org_key_env ?? "");
    setSoul(agent.soul ?? "");
    setToolGroupsState(decodeTriState(agent.tool_groups));

    const decodedSkills = decodeTriState(agent.skills);
    setSkillsState(decodedSkills);
    // Seed pin memory from any name@version values present at load.
    const pins: Record<string, string> = {};
    for (const v of decodedSkills.selected) {
      if (v.includes("@")) pins[skillBaseName(v)] = v;
    }
    setSkillPins(pins);
    setHydrated(true);
  }, [agent, hydrated]);

  const advancedOpen = useMemo(
    () =>
      !toolGroupsState.useAll ||
      !skillsState.useAll ||
      orgKeyEnv.trim().length > 0,
    [toolGroupsState.useAll, skillsState.useAll, orgKeyEnv],
  );
  const [advancedExpanded, setAdvancedExpanded] = useState(false);
  useEffect(() => {
    if (advancedOpen) setAdvancedExpanded(true);
  }, [advancedOpen]);

  if (agentLoading) {
    return (
      <div className="mx-auto w-full max-w-2xl p-6 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (agentError || !agent) {
    return (
      <div className="mx-auto w-full max-w-2xl p-6 space-y-4">
        <Alert variant="destructive">
          <AlertDescription>{t.agents.editLoadFailed}</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => router.push("/workspace/agents")}>
          {t.agents.editLoadFailedBack}
        </Button>
      </div>
    );
  }

  function handleToolGroupToggle(name: string) {
    setToolGroupsState((s) => ({
      useAll: s.useAll,
      selected: s.selected.includes(name)
        ? s.selected.filter((g) => g !== name)
        : [...s.selected, name],
    }));
  }

  function handleSkillToggle(baseName: string) {
    setSkillsState((s) => ({
      useAll: s.useAll,
      selected: toggleSkillSelection(s.selected, baseName, skillPins[baseName]),
    }));
  }

  async function handleSave() {
    try {
      await updateAgent.mutateAsync({
        name: agentName,
        request: {
          description,
          model,
          tool_groups: encodeTriState(toolGroupsState),
          skills: encodeTriState(skillsState),
          org_key_env: orgKeyEnv.trim() === "" ? null : orgKeyEnv.trim(),
          soul,
        },
      });
      toast.success(t.agents.editSaveSuccess);
      router.push("/workspace/agents");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.agents.editSaveFailed);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl p-6 space-y-6">
      {/* Header */}
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => router.push("/workspace/agents")}
          >
            <ArrowLeftIcon className="h-4 w-4" />
          </Button>
          <h1 className="text-lg font-semibold truncate">{agentName}</h1>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button
            variant="outline"
            onClick={() => router.push("/workspace/agents")}
            disabled={updateAgent.isPending}
          >
            {t.common.cancel}
          </Button>
          <Button onClick={() => void handleSave()} disabled={updateAgent.isPending}>
            {updateAgent.isPending ? t.common.loading : t.common.save}
          </Button>
        </div>
      </header>

      {/* Basic */}
      <section className="space-y-4 rounded-lg border p-4">
        <h2 className="text-sm font-semibold">{t.agents.editBasicSection}</h2>

        <div className="space-y-2">
          <Label htmlFor="description">{t.agents.editFieldDescription}</Label>
          <Textarea
            id="description"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t.agents.editFieldDescriptionPlaceholder}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="model">{t.agents.editFieldModel}</Label>
          <Select
            value={model ?? "__default__"}
            onValueChange={(v) => setModel(v === "__default__" ? null : v)}
          >
            <SelectTrigger id="model">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__default__">{t.agents.editFieldModelDefault}</SelectItem>
              {models.map((m) => (
                <SelectItem key={m.name} value={m.name}>
                  {m.display_name ?? m.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="soul">{t.agents.editFieldSoul}</Label>
          <Textarea
            id="soul"
            rows={12}
            className="font-mono text-xs"
            value={soul}
            onChange={(e) => setSoul(e.target.value)}
            placeholder={t.agents.editFieldSoulPlaceholder}
          />
        </div>
      </section>

      {/* Advanced */}
      <section className="space-y-4 rounded-lg border p-4">
        <button
          type="button"
          className="flex w-full items-center justify-between text-sm font-semibold"
          onClick={() => setAdvancedExpanded((e) => !e)}
        >
          <span>{t.agents.editAdvancedSection}</span>
          <span className="text-muted-foreground text-xs">
            {advancedExpanded ? "−" : "+"}
          </span>
        </button>

        {advancedExpanded ? (
          <div className="space-y-6">
            {/* Tool groups */}
            <div className="space-y-3">
              <Label>{t.agents.editFieldToolGroups}</Label>
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={toolGroupsState.useAll}
                  onCheckedChange={(checked) =>
                    setToolGroupsState((s) => ({
                      ...s,
                      useAll: checked === true,
                    }))
                  }
                />
                {t.agents.editUseAllToolGroups}
              </label>
              {!toolGroupsState.useAll ? (
                toolGroupsError ? (
                  <p className="text-destructive text-xs">
                    {t.agents.editToolGroupsLoadFailed}
                  </p>
                ) : (
                  <div className="ml-6 grid grid-cols-2 gap-2">
                    {toolGroups.map((g) => (
                      <label key={g.name} className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={toolGroupsState.selected.includes(g.name)}
                          onCheckedChange={() => handleToolGroupToggle(g.name)}
                        />
                        {g.name}
                      </label>
                    ))}
                  </div>
                )
              ) : null}
            </div>

            {/* Skills */}
            <div className="space-y-3">
              <Label>{t.agents.editFieldSkills}</Label>
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={skillsState.useAll}
                  onCheckedChange={(checked) =>
                    setSkillsState((s) => ({
                      ...s,
                      useAll: checked === true,
                    }))
                  }
                />
                {t.agents.editUseAllSkills}
              </label>
              {!skillsState.useAll ? (
                skillsError ? (
                  <p className="text-destructive text-xs">
                    {t.agents.editSkillsLoadFailed}
                  </p>
                ) : (
                  <div className="ml-6 grid grid-cols-2 gap-2">
                    {skills.map((s) => {
                      const checked = skillsState.selected.some(
                        (v) => skillBaseName(v) === s.name,
                      );
                      const pin = skillsState.selected.find(
                        (v) => skillBaseName(v) === s.name && v.includes("@"),
                      );
                      const version = pin ? pin.split("@", 2)[1] : null;
                      return (
                        <label key={s.name} className="flex items-center gap-2 text-sm">
                          <Checkbox
                            checked={checked}
                            onCheckedChange={() => handleSkillToggle(s.name)}
                          />
                          <span className="truncate">{s.name}</span>
                          {version ? (
                            <span className="text-muted-foreground text-xs">
                              ({t.agents.editVersionPinned.replace("{version}", version)})
                            </span>
                          ) : null}
                        </label>
                      );
                    })}
                  </div>
                )
              ) : null}
            </div>

            {/* Org key env */}
            <div className="space-y-2">
              <Label htmlFor="org-key-env">{t.agents.editFieldOrgKeyEnv}</Label>
              <Input
                id="org-key-env"
                value={orgKeyEnv}
                onChange={(e) => setOrgKeyEnv(e.target.value)}
                placeholder={t.agents.editFieldOrgKeyEnvPlaceholder}
              />
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Verify the page imports resolve**

Run: `cd frontend && pnpm typecheck`
Expected: PASS. Common failures and fixes:
- "Cannot find name 'Checkbox'" → existing primitive should live at `@/components/ui/checkbox`. If absent, the codebase uses Shadcn — install or adjust the import path. Verify with `ls frontend/src/components/ui/`.
- "Property 'display_name' does not exist on type ..." → inspect `frontend/src/core/models/api.ts` for the exact field name; replace `m.display_name ?? m.name` with whatever the model summary actually exposes.
- "Cannot find module '@/core/skills/hooks'" → file exists; check that `useSkills` returns `{ skills, ... }` (it does — verified in plan prep).

If a Shadcn primitive is missing, scaffold it with: `cd frontend && pnpm dlx shadcn@latest add checkbox label select textarea` (only the missing ones).

- [ ] **Step 3: Sanity-test in the dev server (manual)**

Manual verification (spec §测试 → 手动验收 part of it; full list in Task 9):

```bash
cd /Users/lydoc/projectscoding/deer-flow && make dev
```

Open `http://localhost:2026/workspace/agents/<existing_agent>/edit` directly. Confirm:
- Page loads, fields populate from the agent.
- Save button calls PUT and returns to `/workspace/agents`.

If something is broken, fix in this task before committing.

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/workspace/agents/[agent_name]/edit/page.tsx"
git commit -m "feat(agents): edit page for description/model/SOUL/tool_groups/skills/org_key_env

$(cat <<'EOF'
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Frontend — AgentCard "Edit" button

**Files:**
- Modify: `frontend/src/components/workspace/agents/agent-card.tsx`

- [ ] **Step 1: Add the Edit icon import**

Edit `frontend/src/components/workspace/agents/agent-card.tsx`. Replace the lucide import on line 3:

```tsx
import { BotIcon, MessageSquareIcon, PencilIcon, Trash2Icon } from "lucide-react";
```

- [ ] **Step 2: Insert the Edit button**

In the `CardFooter` (around lines 107-122), find the `<div className="flex gap-1">` block and insert the Edit button **before** the Delete button so the order reads: Chat | Edit | Delete.

Replace lines 112-122 (the `<div className="flex gap-1">…</div>` block) with:

```tsx
          <div className="flex gap-1">
            <Button
              size="icon"
              variant="ghost"
              className="h-8 w-8 shrink-0"
              onClick={() => router.push(`/workspace/agents/${agent.name}/edit`)}
              title={t.agents.edit}
            >
              <PencilIcon className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="text-destructive hover:text-destructive h-8 w-8 shrink-0"
              onClick={() => setDeleteOpen(true)}
              title={t.agents.delete}
            >
              <Trash2Icon className="h-3.5 w-3.5" />
            </Button>
          </div>
```

- [ ] **Step 3: Run typecheck**

Run: `cd frontend && pnpm typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/workspace/agents/agent-card.tsx
git commit -m "feat(agents): add Edit button on AgentCard

$(cat <<'EOF'
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Run the full test suites

- [ ] **Step 1: Run backend tests**

Run: `cd backend && make test`
Expected: full suite PASS, including the 3 new tests in `tests/test_agents_router.py`.

If anything unrelated fails (the existing tree has known-flaky integration tests that need PG/Redis), narrow to: `cd backend && PYTHONPATH=. uv run pytest tests/test_agents_router.py -v`. Both router-specific suites must pass.

- [ ] **Step 2: Run frontend tests**

Run: `cd frontend && pnpm test`
Expected: full Vitest suite PASS, including the 13 new tests (11 in tri-state + 2 in hooks).

- [ ] **Step 3: Run frontend lint + typecheck**

Run: `cd frontend && pnpm check`
Expected: PASS (no new ESLint or TS errors).

- [ ] **Step 4: If anything fails, fix in place — do not commit broken state**

This is a verification gate, not a code-change task. If a test fails, return to the relevant earlier task and fix the implementation. Re-run the failing suite alone before re-running the full sweep.

---

## Task 9: Manual verification (browser)

This task has no commit. It validates the spec's manual acceptance list against a live dev server.

- [ ] **Step 1: Start the dev environment**

Run from project root: `make dev`

Wait for nginx (`http://localhost:2026`) and confirm Gateway, LangGraph, and frontend logs show no errors.

- [ ] **Step 2: Walk through each acceptance scenario**

For each, record PASS/FAIL plus a one-line note. Move to the next only after the current one passes. If any fails, return to the relevant task and fix.

1. **Edit button visible.** Navigate to `/workspace/agents`. Each agent card shows an Edit (pencil) icon between Chat and Delete. → PASS / FAIL.

2. **Round-trip basic edit.** Click Edit on an existing agent. Change Description, change Model from default to a configured model, click Save. Toast shows "Agent updated". Page redirects to `/workspace/agents`. The card now shows the new description and model badge. → PASS / FAIL.

3. **Tool groups three-state survives reload.** Open Edit again. Uncheck "Use all enabled tool groups". Don't check anything. Save. Re-open Edit page. Confirm "Use all" is still unchecked AND no boxes are checked (i.e. backend stored `[]`, not got coerced back to `null`). → PASS / FAIL.

4. **Skill `name@version` round-trip.** Pre-condition: edit an agent's `config.yaml` directly to set `skills: ["<some_skill>@1.2.0"]`. Open Edit page → confirm the `(v1.2.0 pinned)` indicator appears next to that skill. Uncheck it, recheck it, Save. Re-open Edit → the `@1.2.0` pin should still be there in the indicator (and the YAML round-trips). → PASS / FAIL.

5. **`agents_api.enabled=false` graceful degradation.** Stop the dev stack. Set `agents_api.enabled: false` in `config.yaml`. Restart `make dev`. Open `/workspace/agents/<any>/edit`. Page should show the load-error empty state with a "Back to agents" button — no white screen, no console crash loop. → PASS / FAIL.

After Step 2 passes, restore `agents_api.enabled` to its prior value before stopping work.

- [ ] **Step 3: Stop the dev environment**

Run: `make stop`

---

## Task 10: Update `MEMORY.md` with the closure note

The user's auto-memory tracks the open epic. Add a closure note so future sessions see this epic shipped without reading every commit.

**Files:**
- Modify: `/Users/lydoc/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/project_skill_agent_i18n.md` — append a "## 2026-04-27 — Custom-agent edit page shipped" section pointing at this plan and the spec.
- Modify: `/Users/lydoc/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/MEMORY.md` — only if a one-line index entry needs to change; otherwise leave it.

- [ ] **Step 1: Read the existing memory file to find the right insertion point**

Run: `cat /Users/lydoc/.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/project_skill_agent_i18n.md`

Append a new section noting the edit-page shipped on 2026-04-27, with a one-line summary and pointers to the spec + plan path.

- [ ] **Step 2: Commit (memory files live outside the repo, so this is a no-op for `git`).**

The memory directory is the user's `.claude/` profile, not the project repo. No git action needed.

---

## Self-Review

After writing this plan, I checked it against the spec section by section:

**Spec coverage:**
- ✅ Backend `GET /api/tool-groups` → Task 1
- ✅ Spec's three-state PUT regression → Task 2 (added explicit round-trip test)
- ✅ AgentCard Edit button → Task 7
- ✅ `listToolGroups` + `useToolGroups` → Task 4
- ✅ Edit page route + form + tri-state UI + skill `@version` passthrough → Task 6 (using helpers from Task 3)
- ✅ i18n keys → Task 5
- ✅ Backend test scaffolding → Task 1 + Task 2
- ✅ Frontend unit tests for tri-state encoding/decoding → Task 3
- ✅ Frontend unit test for `useToolGroups` → Task 4
- ✅ Manual acceptance steps → Task 9 (covers all 5 scenarios from spec §测试)

**Spec gaps the plan resolves:**
- `org_key_env` UI semantics not in spec → Task 6 commits to "plain text input, empty → null on save" with placeholder hint.
- Spec called out `useTriState` only conceptually → Task 3 makes it a real, unit-tested module so Task 6 stays small.

**Placeholders:** none — every step has the actual code or command.

**Type consistency:** `TriState`, `ToolGroupSummary`, `decodeTriState`, `encodeTriState`, `skillBaseName`, `toggleSkillSelection` are defined once in Task 3 and used by Tasks 4 and 6 with matching signatures. The backend `ToolGroupResponse` shape (`{name: str}`) matches what the frontend `ToolGroupSummary` expects.

**Risk notes from spec carried into the plan:**
- Risk 1 (UI confusion on three-state): mitigated by helper text + checkbox visibility in Task 6 advanced section.
- Risk 2 (large SOUL.md): not addressed, as spec said "no new limits". Plan inherits this stance.
- Risk 3 (concurrent delete during edit): the toast on save error covers this — backend returns 404, `useUpdateAgent.mutateAsync` rejects, the catch block toasts the detail. No additional task needed.
