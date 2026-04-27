# Skill Mgmt v2 — Remaining Work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成技能广场的核心缺口：技能绑定到会话（bind/unbind thread-skills API + 前端 badge）、会话输入框技能徽章区域、以及 admin 已拒绝/归档 tab 数据接通。

**Architecture:**
- 后端新增 `POST/DELETE /api/threads/{tid}/skills` 端点，将 `bound_skills` 列表持久化到 Thread Store 的 `values` 字段（复用现有 `_store_upsert` 机制）；同时新增 `GET /api/admin/skills/reviewed` 供 admin 已拒绝/归档 tab 调用。
- 前端在 `core/skills/` 增加 thread-skill 绑定 API 函数和 React Query hooks；在 workspace skills 广场页的"加载到会话"按钮接通真实 API；在 `[thread_id]/page.tsx` 渲染技能 badge 区域（独立组件 `SkillBadgeBar`），从 thread store 读取 `bound_skills`。
- Admin skills 页"已拒绝/归档"tab 改为调用 `GET /api/admin/skills/reviewed`。

**Tech Stack:** FastAPI (Python), Next.js 15 (React), TanStack Query, LangGraph thread Store

---

## 文件清单

### 新建
- `backend/app/gateway/routers/thread_skills.py` — `POST/DELETE /api/threads/{tid}/skills` 两个端点
- `frontend/src/components/workspace/skill-badge-bar.tsx` — 会话输入框上方的技能徽章区域组件
- `frontend/src/core/skills/thread-api.ts` — thread 绑定/解绑 API 函数

### 修改
- `backend/app/gateway/app.py` — 注册 `thread_skills` router
- `backend/app/gateway/identity/routers/admin.py` — 新增 `GET /api/admin/skills/reviewed` 端点
- `frontend/src/app/workspace/skills/page.tsx` — "加载到会话"按钮调用真实 API
- `frontend/src/app/workspace/chats/[thread_id]/page.tsx` — 在 InputBox 上方渲染 `SkillBadgeBar`
- `frontend/src/app/(admin)/admin/skills/page.tsx` — 已拒绝/归档 tab 接通数据
- `frontend/src/core/skills/hooks.ts` — 新增 thread-skill 绑定 hooks

---

## Task 1: 后端 — thread skills 绑定/解绑端点

**Files:**
- Create: `backend/app/gateway/routers/thread_skills.py`
- Modify: `backend/app/gateway/app.py`

### 背景

Thread 的持久化通过 `_store_upsert(store, thread_id, values={"bound_skills": [...]})` 实现，bound_skills 存储在 LangGraph Store 的 `values` 字典中。`store.aget(("threads",), thread_id)` 返回的 item 的 `.value["values"]["bound_skills"]` 字段即是当前绑定列表。

bound_skill 结构：
```python
{"name": str, "version": str, "bound_at": str}   # ISO timestamp
```

- [x] **Step 1: 创建 thread_skills.py**

```python
# backend/app/gateway/routers/thread_skills.py
"""POST/DELETE /api/threads/{tid}/skills — bind/unbind skills to a thread."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.gateway.deps import get_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["thread-skills"])

THREADS_NS: tuple[str, ...] = ("threads",)


class BindSkillRequest(BaseModel):
    skill_name: str
    version: str = "latest"


async def _get_bound_skills(store: Any, thread_id: str) -> list[dict]:
    item = await store.aget(THREADS_NS, thread_id)
    if item is None:
        return []
    return item.value.get("values", {}).get("bound_skills", [])


async def _set_bound_skills(store: Any, thread_id: str, skills: list[dict]) -> None:
    item = await store.aget(THREADS_NS, thread_id)
    if item is None:
        raise HTTPException(status_code=404, detail="thread not found")
    val = item.value.copy()
    val.setdefault("values", {})["bound_skills"] = skills
    await store.aput(THREADS_NS, thread_id, val)


@router.post("/{thread_id}/skills")
async def bind_skill(thread_id: str, body: BindSkillRequest, request: Request) -> dict:
    """Bind a skill to the thread. Idempotent — duplicate binds are ignored."""
    store = await get_store(request)
    skills = await _get_bound_skills(store, thread_id)
    # idempotent: skip if already bound with same name+version
    already = any(s["name"] == body.skill_name and s["version"] == body.version for s in skills)
    if not already:
        skills = [*skills, {
            "name": body.skill_name,
            "version": body.version,
            "bound_at": datetime.now(timezone.utc).isoformat(),
        }]
        await _set_bound_skills(store, thread_id, skills)
    return {"bound_skills": skills}


@router.delete("/{thread_id}/skills/{skill_name}")
async def unbind_skill(thread_id: str, skill_name: str, request: Request) -> dict:
    """Unbind a skill from the thread."""
    store = await get_store(request)
    skills = await _get_bound_skills(store, thread_id)
    updated = [s for s in skills if s["name"] != skill_name]
    if len(updated) != len(skills):
        await _set_bound_skills(store, thread_id, updated)
    return {"bound_skills": updated}


@router.get("/{thread_id}/skills")
async def list_bound_skills(thread_id: str, request: Request) -> dict:
    """Return the skills currently bound to this thread."""
    store = await get_store(request)
    skills = await _get_bound_skills(store, thread_id)
    return {"bound_skills": skills}
```

- [x] **Step 2: 检查 `get_store` 是否接受 Request**

```bash
grep -n "get_store" /Users/lydoc/projectscoding/deer-flow/backend/app/gateway/deps.py | head -10
```

如果 `get_store` 是 `Depends(get_store)` 风格的生成器而非接受 Request，则改写为：

```python
from fastapi import Depends
from app.gateway.deps import get_store as _get_store_dep

@router.post("/{thread_id}/skills")
async def bind_skill(thread_id: str, body: BindSkillRequest, store=Depends(_get_store_dep)) -> dict:
    ...

@router.delete("/{thread_id}/skills/{skill_name}")
async def unbind_skill(thread_id: str, skill_name: str, store=Depends(_get_store_dep)) -> dict:
    ...

@router.get("/{thread_id}/skills")
async def list_bound_skills(thread_id: str, store=Depends(_get_store_dep)) -> dict:
    ...
```

并删除 `thread_skills.py` 中的 `request: Request` 参数。

- [x] **Step 3: 注册 router 到 app.py**

在 `backend/app/gateway/app.py` 中，找到：
```python
from . import artifacts, assistants_compat, mcp, models, skills, suggestions, thread_runs, threads, uploads
```
改为：
```python
from . import artifacts, assistants_compat, mcp, models, skills, suggestions, thread_runs, thread_skills, threads, uploads
```

找到 `app.include_router(skills.router)` 附近，添加：
```python
app.include_router(thread_skills.router)
```

- [x] **Step 4: 启动后端，手动验证端点存在**

```bash
cd /Users/lydoc/projectscoding/deer-flow/backend
python -c "from app.gateway.app import create_app; app = create_app(); routes = [r.path for r in app.routes if hasattr(r,'path')]; [print(r) for r in routes if 'skills' in r]"
```

期望输出包含：
```
/api/threads/{thread_id}/skills
/api/threads/{thread_id}/skills/{skill_name}
```

- [x] **Step 5: 提交**

```bash
git add backend/app/gateway/routers/thread_skills.py backend/app/gateway/app.py
git commit -m "feat(threads): add POST/DELETE/GET /api/threads/{tid}/skills bind endpoints"
```

---

## Task 2: 后端 — admin 已拒绝/归档列表端点

**Files:**
- Modify: `backend/app/gateway/identity/routers/admin.py`

- [x] **Step 1: 在 admin.py 现有 `reject_skill` 函数之后添加 `list_reviewed_skills` 端点**

定位文件末尾 `get_skill_review_status` 函数之前，插入：

```python
@router.get(
    "/api/admin/skills/reviewed",
    dependencies=[Depends(requires("skill:manage", "platform"))],
)
async def list_reviewed_skills(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List skills with status in ('rejected', 'archived')."""
    stmt = text(
        """
        SELECT id, name, version, scope, status, rejection_reason,
               created_at, created_by, reviewed_at, storage_path
        FROM identity.skill_registry
        WHERE status IN ('rejected', 'archived')
        ORDER BY reviewed_at DESC NULLS LAST
        """
    )
    result = await session.execute(stmt)
    rows = result.mappings().all()
    return {
        "skills": [
            {
                "id": r["id"],
                "name": r["name"],
                "version": r["version"],
                "scope": r["scope"],
                "status": r["status"],
                "rejection_reason": r["rejection_reason"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "created_by": r["created_by"],
                "reviewed_at": r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
                "storage_path": r["storage_path"],
            }
            for r in rows
        ]
    }
```

- [x] **Step 2: 验证 admin router 能加载**

```bash
cd /Users/lydoc/projectscoding/deer-flow/backend
python -c "from app.gateway.identity.routers import admin; print('OK')"
```

期望输出：`OK`

- [x] **Step 3: 提交**

```bash
git add backend/app/gateway/identity/routers/admin.py
git commit -m "feat(admin): add GET /api/admin/skills/reviewed endpoint for rejected/archived skills"
```

---

## Task 3: 前端 — thread-skill 绑定 API 与 hooks

**Files:**
- Create: `frontend/src/core/skills/thread-api.ts`
- Modify: `frontend/src/core/skills/hooks.ts`
- Modify: `frontend/src/core/skills/index.ts`

- [x] **Step 1: 创建 thread-api.ts**

```typescript
// frontend/src/core/skills/thread-api.ts
import { getBackendBaseURL } from "@/core/config";

export interface BoundSkill {
  name: string;
  version: string;
  bound_at: string;
}

export async function bindSkillToThread(
  threadId: string,
  skillName: string,
  version = "latest",
): Promise<BoundSkill[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/skills`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ skill_name: skillName, version }),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { bound_skills: BoundSkill[] };
  return data.bound_skills;
}

export async function unbindSkillFromThread(
  threadId: string,
  skillName: string,
): Promise<BoundSkill[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/skills/${encodeURIComponent(skillName)}`,
    { method: "DELETE", credentials: "include" },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { bound_skills: BoundSkill[] };
  return data.bound_skills;
}

export async function fetchBoundSkills(threadId: string): Promise<BoundSkill[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/skills`,
    { credentials: "include" },
  );
  if (!res.ok) return [];
  const data = (await res.json()) as { bound_skills: BoundSkill[] };
  return data.bound_skills;
}
```

- [x] **Step 2: 在 hooks.ts 新增 useBoundSkills、useBindSkill、useUnbindSkill**

在 `frontend/src/core/skills/hooks.ts` 末尾追加：

```typescript
import {
  bindSkillToThread,
  fetchBoundSkills,
  unbindSkillFromThread,
} from "./thread-api";
import type { BoundSkill } from "./thread-api";

export function useBoundSkills(threadId: string) {
  const { data, isLoading } = useQuery({
    queryKey: ["threads", threadId, "skills"],
    queryFn: () => fetchBoundSkills(threadId),
    enabled: !!threadId,
  });
  return { boundSkills: data ?? [], isLoading };
}

export function useBindSkill(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ skillName, version }: { skillName: string; version?: string }) =>
      bindSkillToThread(threadId, skillName, version),
    onSuccess: (data) => {
      queryClient.setQueryData<BoundSkill[]>(
        ["threads", threadId, "skills"],
        data,
      );
    },
  });
}

export function useUnbindSkill(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (skillName: string) =>
      unbindSkillFromThread(threadId, skillName),
    onSuccess: (data) => {
      queryClient.setQueryData<BoundSkill[]>(
        ["threads", threadId, "skills"],
        data,
      );
    },
  });
}
```

- [x] **Step 3: 在 index.ts 导出新模块**

将 `frontend/src/core/skills/index.ts` 改为：
```typescript
export * from "./api";
export * from "./type";
export * from "./thread-api";
```

- [x] **Step 4: TypeScript 类型检查**

```bash
cd /Users/lydoc/projectscoding/deer-flow/frontend
npx tsc --noEmit 2>&1 | grep -E "error TS|skills" | head -20
```

期望：无 error。

- [x] **Step 5: 提交**

```bash
git add frontend/src/core/skills/thread-api.ts frontend/src/core/skills/hooks.ts frontend/src/core/skills/index.ts
git commit -m "feat(skills): add thread-skill bind/unbind API and React Query hooks"
```

---

## Task 4: 前端 — SkillBadgeBar 组件

**Files:**
- Create: `frontend/src/components/workspace/skill-badge-bar.tsx`

这个组件显示在会话输入框上方，展示已绑定技能，每个 badge 有 × 按钮。

- [x] **Step 1: 创建 skill-badge-bar.tsx**

```tsx
// frontend/src/components/workspace/skill-badge-bar.tsx
"use client";

import { SparklesIcon, XIcon } from "lucide-react";

import { useUnbindSkill } from "@/core/skills/hooks";
import type { BoundSkill } from "@/core/skills/thread-api";

interface SkillBadgeBarProps {
  threadId: string;
  boundSkills: BoundSkill[];
}

export function SkillBadgeBar({ threadId, boundSkills }: SkillBadgeBarProps) {
  const { mutate: unbind } = useUnbindSkill(threadId);

  if (boundSkills.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 px-3 py-1.5">
      {boundSkills.map((skill) => (
        <span
          key={skill.name}
          className="bg-primary/10 text-primary flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
        >
          <SparklesIcon className="h-3 w-3" />
          {skill.name}
          <button
            onClick={() => unbind(skill.name)}
            className="hover:text-primary/60 ml-0.5 transition-colors"
            aria-label={`解绑 ${skill.name}`}
          >
            <XIcon className="h-3 w-3" />
          </button>
        </span>
      ))}
    </div>
  );
}
```

- [x] **Step 2: TypeScript 类型检查**

```bash
cd /Users/lydoc/projectscoding/deer-flow/frontend
npx tsc --noEmit 2>&1 | grep -E "error TS|skill-badge" | head -10
```

期望：无 error。

- [x] **Step 3: 提交**

```bash
git add frontend/src/components/workspace/skill-badge-bar.tsx
git commit -m "feat(workspace): add SkillBadgeBar component for bound skills display"
```

---

## Task 5: 前端 — thread chat 页面接入 SkillBadgeBar

**Files:**
- Modify: `frontend/src/app/workspace/chats/[thread_id]/page.tsx`

- [x] **Step 1: 导入新 hooks 和组件**

在 `frontend/src/app/workspace/chats/[thread_id]/page.tsx` 顶部导入区，在现有 imports 后添加：

```typescript
import { SkillBadgeBar } from "@/components/workspace/skill-badge-bar";
import { useBoundSkills } from "@/core/skills/hooks";
```

- [x] **Step 2: 调用 useBoundSkills**

在组件函数内，在 `const [settings, setSettings] = useThreadSettings(threadId);` 之后添加：

```typescript
const { boundSkills } = useBoundSkills(threadId);
```

- [x] **Step 3: 在 InputBox 的 extraHeader 中渲染 SkillBadgeBar**

将现有的：
```typescript
extraHeader={
  isNewThread && <Welcome mode={settings.context.mode} />
}
```
改为：
```typescript
extraHeader={
  isNewThread ? (
    <Welcome mode={settings.context.mode} />
  ) : boundSkills.length > 0 ? (
    <SkillBadgeBar threadId={threadId} boundSkills={boundSkills} />
  ) : undefined
}
```

- [x] **Step 4: TypeScript 类型检查**

```bash
cd /Users/lydoc/projectscoding/deer-flow/frontend
npx tsc --noEmit 2>&1 | grep "error TS" | head -10
```

期望：无 error。

- [x] **Step 5: 提交**

```bash
git add frontend/src/app/workspace/chats/\[thread_id\]/page.tsx
git commit -m "feat(workspace): integrate SkillBadgeBar into thread chat page"
```

---

## Task 6: 前端 — 技能广场"加载到会话"接通真实 API

**Files:**
- Modify: `frontend/src/app/workspace/skills/page.tsx`

技能广场目前的"加载到会话"只有一个 `toast.success`，需要：
1. 知道当前 threadId（从 URL 或路由拿 — 新 thread 用 `/workspace/chats/new`，此时无 thread ID）。
2. 如果有 active threadId 则调用 bind API；如果无（用户直接从技能广场点击），则跳转到 `/workspace/chats/new` 并将技能名放到 query param，由 chat 页启动后自动绑定。

**策略：简化版（YAGNI）** — 因为技能广场是独立页面而非会话内的弹窗，最简单的设计是：用户点击"加载到会话"时跳转到 `/workspace/chats/new?bind_skill=<name>&bind_version=<version>`，chat 页检测该 param 并在 thread 创建后绑定。这避免跨页面状态管理。

- [x] **Step 1: 修改 SkillCard 的 handleLoad，改为跳转**

在 `frontend/src/app/workspace/skills/page.tsx` 中，在文件顶部 imports 添加：

```typescript
import { useRouter } from "next/navigation";
```

修改 `SkillCard` 组件：

```typescript
function SkillCard({ skill }: { skill: Skill }) {
  const router = useRouter();

  const handleLoad = () => {
    router.push(
      `/workspace/chats/new?bind_skill=${encodeURIComponent(skill.name)}&bind_version=${encodeURIComponent("latest")}`,
    );
  };

  return (
    // ... rest unchanged
  );
}
```

- [x] **Step 2: 在 thread chat 页检测 bind_skill param 并绑定**

在 `frontend/src/app/workspace/chats/[thread_id]/page.tsx` 中，在 `useSearchParams` 相关代码附近（或在 useEffect 区域）添加：

首先确认文件中是否已有 `useSearchParams`：
```bash
grep -n "useSearchParams\|searchParams" /Users/lydoc/projectscoding/deer-flow/frontend/src/app/workspace/chats/\[thread_id\]/page.tsx | head -10
```

然后在组件函数内，在 `const { boundSkills } = useBoundSkills(threadId);` 之后添加：

```typescript
const searchParams = useSearchParams();
const { mutate: bindSkill } = useBindSkill(threadId);

// Auto-bind skill from URL param (e.g. navigated from skills square)
useEffect(() => {
  const skillName = searchParams.get("bind_skill");
  const skillVersion = searchParams.get("bind_version") ?? "latest";
  if (skillName && !isNewThread && threadId) {
    bindSkill({ skillName, version: skillVersion });
  }
}, [isNewThread, threadId, searchParams, bindSkill]);
```

Also add `useBindSkill` to the hooks import:
```typescript
import { useBoundSkills, useBindSkill } from "@/core/skills/hooks";
```

- [x] **Step 3: TypeScript 类型检查**

```bash
cd /Users/lydoc/projectscoding/deer-flow/frontend
npx tsc --noEmit 2>&1 | grep "error TS" | head -10
```

期望：无 error。

- [x] **Step 4: 提交**

```bash
git add frontend/src/app/workspace/skills/page.tsx frontend/src/app/workspace/chats/\[thread_id\]/page.tsx
git commit -m "feat(skills): wire 'load to chat' button — navigate with bind_skill param and auto-bind on thread load"
```

---

## Task 7: 前端 — admin 已拒绝/归档 tab 接通数据

**Files:**
- Modify: `frontend/src/app/(admin)/admin/skills/page.tsx`

- [x] **Step 1: 添加 ReviewedSkill 接口和 fetchReviewedSkills 函数**

在 `frontend/src/app/(admin)/admin/skills/page.tsx` 中，在已有的 `PendingSkill` interface 和 `fetchPendingSkills` 之后添加：

```typescript
interface ReviewedSkill {
  id: number;
  name: string;
  version: string;
  scope: string;
  status: string;
  rejection_reason: string | null;
  created_at: string | null;
  created_by: number;
  reviewed_at: string | null;
  storage_path: string;
}

async function fetchReviewedSkills(): Promise<ReviewedSkill[]> {
  const data = await identityFetch<{ skills: ReviewedSkill[] }>(
    `${getBackendBaseURL()}/api/admin/skills/reviewed`,
  );
  return data.skills;
}
```

- [x] **Step 2: 在 SkillsHubPage 组件中添加 useQuery for reviewed skills**

在 `pendingSkills` useQuery 之后添加：

```typescript
const {
  data: reviewedSkills = [],
  isLoading: reviewedLoading,
  error: reviewedError,
} = useQuery({
  queryKey: ["admin", "skills", "reviewed"],
  queryFn: fetchReviewedSkills,
});
```

- [x] **Step 3: 替换 archived tab 内容为真实数据**

将现有的 `TabsContent value="archived"` 里的占位内容全部替换为：

```tsx
<TabsContent value="archived">
  <div className="mt-4 space-y-3">
    {reviewedLoading && (
      <p className="text-sm text-muted-foreground">加载中…</p>
    )}
    {reviewedError && (
      <p className="text-sm text-destructive">
        加载失败: {(reviewedError as Error).message}
      </p>
    )}
    {!reviewedLoading && !reviewedError && reviewedSkills.length === 0 && (
      <div className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
        暂无已拒绝或归档的 Skill
      </div>
    )}
    {reviewedSkills.map((skill) => (
      <ArchivedSkillRow key={skill.id} skill={skill} />
    ))}
  </div>
</TabsContent>
```

- [x] **Step 4: 在 ArchivedSkillRow 中显示拒绝原因**

将现有的 `ArchivedSkillRow` 组件中 `<p className="mt-1 text-xs text-muted-foreground">` 那行改为：

```tsx
<p className="mt-1 text-xs text-muted-foreground">
  提交者: {skill.created_by} · {skill.created_at ? new Date(skill.created_at).toLocaleString("zh-CN") : "—"}
</p>
{skill.rejection_reason && (
  <p className="mt-1 text-xs text-destructive">
    拒绝原因：{skill.rejection_reason}
  </p>
)}
```

但 `ArchivedSkillRow` 当前的 props 类型是 `PendingSkill`（没有 `rejection_reason`）。需要将其 prop 类型改为 `ReviewedSkill`：

```typescript
function ArchivedSkillRow({ skill }: { skill: ReviewedSkill }) {
```

- [x] **Step 5: TypeScript 类型检查**

```bash
cd /Users/lydoc/projectscoding/deer-flow/frontend
npx tsc --noEmit 2>&1 | grep "error TS" | head -10
```

期望：无 error。

- [x] **Step 6: 提交**

```bash
git add frontend/src/app/\(admin\)/admin/skills/page.tsx
git commit -m "feat(admin): wire rejected/archived skills tab to GET /api/admin/skills/reviewed"
```

---

## Task 8: 前端 unit 测试 — thread-skill hooks

**Files:**
- Create: `frontend/tests/unit/core/skills/thread-skills.test.ts`

- [x] **Step 1: 创建测试文件**

```typescript
// frontend/tests/unit/core/skills/thread-skills.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { bindSkillToThread, unbindSkillFromThread, fetchBoundSkills } from "@/core/skills/thread-api";

const BACKEND = "http://localhost:8000";

vi.mock("@/core/config", () => ({ getBackendBaseURL: () => BACKEND }));

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

beforeEach(() => mockFetch.mockReset());

describe("bindSkillToThread", () => {
  it("POSTs to /api/threads/{id}/skills and returns bound_skills", async () => {
    const bound = [{ name: "data-analyst", version: "1.0.0", bound_at: "2026-04-25T00:00:00Z" }];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ bound_skills: bound }),
    });

    const result = await bindSkillToThread("thread-1", "data-analyst", "1.0.0");

    expect(mockFetch).toHaveBeenCalledWith(
      `${BACKEND}/api/threads/thread-1/skills`,
      expect.objectContaining({ method: "POST" }),
    );
    expect(result).toEqual(bound);
  });

  it("throws on HTTP error", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ detail: "thread not found" }),
    });
    await expect(bindSkillToThread("no-thread", "skill", "latest")).rejects.toThrow("thread not found");
  });
});

describe("unbindSkillFromThread", () => {
  it("DELETEs to /api/threads/{id}/skills/{name}", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ bound_skills: [] }),
    });

    const result = await unbindSkillFromThread("thread-1", "data-analyst");
    expect(mockFetch).toHaveBeenCalledWith(
      `${BACKEND}/api/threads/thread-1/skills/data-analyst`,
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(result).toEqual([]);
  });
});

describe("fetchBoundSkills", () => {
  it("returns empty array on 404", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 404, json: async () => ({}) });
    const result = await fetchBoundSkills("missing-thread");
    expect(result).toEqual([]);
  });

  it("returns skills list on success", async () => {
    const bound = [{ name: "sql-expert", version: "2.0.0", bound_at: "2026-04-25T00:00:00Z" }];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ bound_skills: bound }),
    });
    const result = await fetchBoundSkills("thread-1");
    expect(result).toEqual(bound);
  });
});
```

- [x] **Step 2: 运行测试，确认通过**

```bash
cd /Users/lydoc/projectscoding/deer-flow/frontend
npx vitest run tests/unit/core/skills/thread-skills.test.ts
```

期望输出：
```
Test Files  1 passed (1)
     Tests  4 passed (4)
```

- [x] **Step 3: 运行所有 unit 测试，确认无回归**

```bash
cd /Users/lydoc/projectscoding/deer-flow/frontend
npx vitest run --passWithNoTests
```

期望：全部通过，之前的 38 个测试保持 pass。

- [x] **Step 4: 提交**

```bash
git add frontend/tests/unit/core/skills/thread-skills.test.ts
git commit -m "test(skills): unit tests for thread-skill bind/unbind API functions"
```

---

## 自检：规格覆盖对照

| 设计规格项 | 覆盖任务 |
|---|---|
| `POST /api/threads/{tid}/skills` 绑定端点 | Task 1 |
| `DELETE /api/threads/{tid}/skills/{name}` 解绑端点 | Task 1 |
| `GET /api/threads/{tid}/skills` 获取列表 | Task 1 |
| `GET /api/admin/skills/reviewed` 已拒绝/归档列表 | Task 2 |
| `BoundSkill` 类型 + thread-api 函数 | Task 3 |
| `useBoundSkills` / `useBindSkill` / `useUnbindSkill` hooks | Task 3 |
| `SkillBadgeBar` 会话输入框技能徽章 | Task 4 |
| Chat 页面接入 badge 显示 | Task 5 |
| 技能广场"加载到会话"跳转 + auto-bind | Task 6 |
| Admin 已拒绝/归档 tab 接通真实数据 | Task 7 |
| 单元测试覆盖 API 函数 | Task 8 |
