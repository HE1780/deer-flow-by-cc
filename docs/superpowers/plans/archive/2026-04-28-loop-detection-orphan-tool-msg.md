> 📦 **归档于 2026-04-29 — hard_stop 路径已 ship；warning 路径仍 open**
>
> **当前事实（hard_stop）**：[loop_detection_middleware.py](../../../../backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py) line 508-516 的 `RemoveMessage(id=m.id)` 已经在生产环境清理 hard_stop 触发时的孤儿 ToolMessage。
>
> **未闭环（warning 路径）**：本 plan 只覆盖 hard_stop 分支。warning 分支（line 373-380）仍然在工具调用链中间注入 `HumanMessage(content=warning)`，已实证导致 thread `336b7fce-...` 永久损坏 — 详见 [OPEN_ISSUES.md OI-1](../../../OPEN_ISSUES.md) + [docs/lessons.md 2026-04-28 复盘](../../../lessons.md)。
>
> 下文为 hard_stop 修复的原始 plan，仅作历史档案保留。

---

# LoopDetectionMiddleware 孤儿 ToolMessage 修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LoopDetectionMiddleware hard-stop 触发时同步删除对应的孤儿 ToolMessage，使后续 LLM 调用不再被严格 provider（MiniMax/Anthropic）以 `tool result's tool id ... not found` 拒 400。

**Architecture:** 在 `_apply()` 的 hard_stop 分支里，先收集被 strip 的 AIMessage 的 `tool_call_ids`，扫一遍 `state["messages"]` 找出 `tool_call_id` 命中的 `ToolMessage`，把它们的 `RemoveMessage(id=...)` 和 stripped AIMessage 一起返回。LangGraph messages reducer 会按 `RemoveMessage` 协议从 history 移除孤儿，AIMessage 用 id 替换。窄范围（仅匹配本次 strip 的 tool_call_ids）确保不误删 subagent 继承或并行场景下的其他工具消息。

**Tech Stack:** Python 3.12, LangGraph, langchain_core.messages.RemoveMessage（已在 `summarization_middleware.py` 使用，无新依赖）, pytest。

**关联 spec:** [docs/superpowers/specs/2026-04-27-loop-detection-orphan-tool-msg.md](../specs/2026-04-27-loop-detection-orphan-tool-msg.md)

---

## File Structure

**单文件改动 + 单文件测试增量：**

- Modify: `backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py`
  - 第 25 行 import：追加 `RemoveMessage` 到现有 `langchain_core.messages` import
  - 第 347-356 行 `_apply()` 的 hard_stop 分支：从 last_msg 提取 `tool_call_ids` → 扫 messages 找匹配的 ToolMessage → 返回 `[*RemoveMessage(...), stripped_msg]`
- Modify: `backend/tests/test_loop_detection_middleware.py`
  - 在 `TestHardStopWithListContent` 之后追加新 class `TestHardStopOrphanToolMessageRemoval`
  - 复用现有 `_make_runtime` / `_bash_call` helpers；新增 `_make_state_with_tool_msg` helper

不动其他文件。`DanglingToolCallMiddleware` 处理反方向场景，与本修复无关。

---

## Task 1: 失败测试 — hard_stop 触发时返回 RemoveMessage

**Files:**
- Test: `backend/tests/test_loop_detection_middleware.py` (append after `TestHardStopWithListContent`, around line 454)

- [ ] **Step 1.1: 在测试文件 import 区追加 ToolMessage 与 RemoveMessage**

Open `backend/tests/test_loop_detection_middleware.py` line 6:

Current:
```python
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
```

Change to:
```python
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
```

- [ ] **Step 1.2: 在文件末尾追加新测试 class**

Append after line 638 (end of `TestToolFrequencyDetection`):

```python
class TestHardStopOrphanToolMessageRemoval:
    """Hard stop must clean orphan ToolMessages whose tool_call_id matches
    the AIMessage being stripped. Otherwise strict providers (MiniMax/Anthropic)
    reject the next call with 400 "tool result's tool id ... not found".

    Spec: docs/superpowers/specs/2026-04-27-loop-detection-orphan-tool-msg.md
    """

    def _state_with_tool_msg(self, tool_calls, tool_call_ids_for_results):
        """Build state where AIMessage has tool_calls AND matching ToolMessages
        already exist in history (simulates: tools already executed, history
        has the responses, then loop detection fires hard_stop)."""
        ai_msg = AIMessage(content="thinking...", tool_calls=tool_calls)
        tool_msgs = [
            ToolMessage(content=f"result for {tcid}", tool_call_id=tcid)
            for tcid in tool_call_ids_for_results
        ]
        # Order in real history: AI msg → its ToolMessages.
        # But the LATEST AIMessage (the one with the loop) is at the end.
        # For loop detection to trigger on it, it must be messages[-1].
        # So we layer: prior AIMessage with tool_calls → prior ToolMessages → latest looping AIMessage.
        prior_ai = AIMessage(
            content="prior turn",
            tool_calls=[{"name": tc["name"], "id": tcid, "args": tc["args"]}
                        for tc, tcid in zip(tool_calls, tool_call_ids_for_results)],
        )
        return {"messages": [prior_ai, *tool_msgs, ai_msg]}

    def test_hard_stop_emits_remove_message_for_orphan_tool_msg(self):
        """When hard_stop strips tool_calls from last AIMessage, any ToolMessage
        in history whose tool_call_id matches must be removed via RemoveMessage."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()

        looping_call_id = "call_loop_1"
        tool_calls = [{"name": "bash", "id": looping_call_id, "args": {"command": "ls"}}]

        # Trip the loop detector with 3 prior identical calls
        for _ in range(3):
            mw._apply(_make_state(tool_calls=tool_calls), runtime)

        # 4th call: hard_stop fires. Build state where the looping AIMessage's
        # tool_call already produced a ToolMessage in history.
        state = self._state_with_tool_msg(tool_calls, [looping_call_id])
        result = mw._apply(state, runtime)

        assert result is not None
        msgs = result["messages"]
        # Expect: at least one RemoveMessage + the stripped AIMessage
        remove_msgs = [m for m in msgs if isinstance(m, RemoveMessage)]
        ai_msgs = [m for m in msgs if isinstance(m, AIMessage)]

        assert len(remove_msgs) == 1, f"expected 1 RemoveMessage, got {remove_msgs}"
        assert len(ai_msgs) == 1, f"expected 1 stripped AIMessage, got {ai_msgs}"

        # The RemoveMessage targets the orphan ToolMessage by its message id.
        # ToolMessage in fixture had no explicit id, so langchain auto-assigns one.
        # Look up the orphan in fixture state and verify the RemoveMessage points to it.
        orphan_tool_msg = next(
            m for m in state["messages"]
            if isinstance(m, ToolMessage) and m.tool_call_id == looping_call_id
        )
        assert remove_msgs[0].id == orphan_tool_msg.id

        # The stripped AIMessage must have tool_calls cleared (existing contract)
        assert ai_msgs[0].tool_calls == []
        assert _HARD_STOP_MSG in ai_msgs[0].content

    def test_hard_stop_no_remove_when_no_orphan_exists(self):
        """If the looping AIMessage's tool_calls have not been executed yet
        (no matching ToolMessage in history), no RemoveMessage is emitted.
        This covers the case where loop detection fires in after_model
        before the tool node runs."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()

        tool_calls = [{"name": "bash", "id": "call_no_result", "args": {"command": "ls"}}]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=tool_calls), runtime)

        # 4th call: hard_stop fires, but ToolMessage hasn't been added to history
        result = mw._apply(_make_state(tool_calls=tool_calls), runtime)

        assert result is not None
        msgs = result["messages"]
        remove_msgs = [m for m in msgs if isinstance(m, RemoveMessage)]
        ai_msgs = [m for m in msgs if isinstance(m, AIMessage)]

        assert len(remove_msgs) == 0, f"no orphan exists → no RemoveMessage; got {remove_msgs}"
        assert len(ai_msgs) == 1
        assert ai_msgs[0].tool_calls == []

    def test_hard_stop_removes_only_matching_orphans_not_unrelated_tool_msgs(self):
        """Narrow scope: RemoveMessage targets ONLY ToolMessages whose tool_call_id
        is in the looping AIMessage's tool_calls. Unrelated ToolMessages from
        prior valid turns must remain untouched."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()

        looping_id = "call_loop"
        unrelated_id = "call_unrelated_earlier_turn"

        tool_calls = [{"name": "bash", "id": looping_id, "args": {"command": "ls"}}]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=tool_calls), runtime)

        # Build history with:
        #   - unrelated valid AI+Tool pair from earlier (must NOT be removed)
        #   - looping AI msg with its already-produced ToolMessage (orphan to clean)
        unrelated_ai = AIMessage(
            content="earlier valid turn",
            tool_calls=[{"name": "bash", "id": unrelated_id, "args": {"command": "pwd"}}],
        )
        unrelated_tool = ToolMessage(content="/home", tool_call_id=unrelated_id)
        looping_orphan_tool = ToolMessage(content="result", tool_call_id=looping_id)
        looping_ai = AIMessage(content="loop", tool_calls=tool_calls)

        state = {
            "messages": [unrelated_ai, unrelated_tool, looping_orphan_tool, looping_ai]
        }
        result = mw._apply(state, runtime)

        assert result is not None
        remove_msgs = [m for m in result["messages"] if isinstance(m, RemoveMessage)]
        # Only the looping orphan ToolMessage gets removed
        assert len(remove_msgs) == 1
        assert remove_msgs[0].id == looping_orphan_tool.id
        # The unrelated ToolMessage's id must NOT be in any RemoveMessage
        removed_ids = {m.id for m in remove_msgs}
        assert unrelated_tool.id not in removed_ids

    def test_hard_stop_handles_multiple_tool_calls_in_one_message(self):
        """Hard-stop AIMessage may carry several tool_calls; each with a matching
        ToolMessage in history must produce its own RemoveMessage."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()

        ids = ["call_a", "call_b"]
        tool_calls = [
            {"name": "bash", "id": "call_a", "args": {"command": "ls"}},
            {"name": "bash", "id": "call_b", "args": {"command": "pwd"}},
        ]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=tool_calls), runtime)

        looping_ai = AIMessage(content="loop", tool_calls=tool_calls)
        orphans = [ToolMessage(content=f"r_{tcid}", tool_call_id=tcid) for tcid in ids]
        state = {"messages": [*orphans, looping_ai]}

        result = mw._apply(state, runtime)
        assert result is not None
        remove_msgs = [m for m in result["messages"] if isinstance(m, RemoveMessage)]
        assert len(remove_msgs) == 2
        removed_ids = {m.id for m in remove_msgs}
        assert removed_ids == {orphans[0].id, orphans[1].id}
```

- [ ] **Step 1.3: 跑测试确认全部 fail**

Run from `backend/`:
```
PYTHONPATH=. uv run pytest tests/test_loop_detection_middleware.py::TestHardStopOrphanToolMessageRemoval -v
```

Expected: 4 tests fail. Failure mode for first test should be `AssertionError: expected 1 RemoveMessage, got []` (current code returns only `[stripped_msg]`).

---

## Task 2: 实施 — 在 hard_stop 分支生成 RemoveMessage

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py:25` (import)
- Modify: `backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py:347-356` (`_apply` hard_stop branch)

- [ ] **Step 2.1: 追加 RemoveMessage import**

Edit line 25 of `loop_detection_middleware.py`:

Current:
```python
from langchain_core.messages import HumanMessage
```

Change to:
```python
from langchain_core.messages import HumanMessage, RemoveMessage
```

- [ ] **Step 2.2: 修改 `_apply` 的 hard_stop 分支返回 RemoveMessage + stripped_msg**

Replace lines 347-356 (the existing `_apply` method body up to and including the hard_stop return):

Current:
```python
    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        warning, hard_stop = self._track_and_check(state, runtime)

        if hard_stop:
            # Strip tool_calls from the last AIMessage to force text output
            messages = state.get("messages", [])
            last_msg = messages[-1]
            content = self._append_text(last_msg.content, warning or _HARD_STOP_MSG)
            stripped_msg = last_msg.model_copy(update=self._build_hard_stop_update(last_msg, content))
            return {"messages": [stripped_msg]}
```

Change to:
```python
    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        warning, hard_stop = self._track_and_check(state, runtime)

        if hard_stop:
            # Strip tool_calls from the last AIMessage to force text output.
            # Also remove any ToolMessage in history whose tool_call_id matches
            # the stripped AIMessage's tool_calls — otherwise strict providers
            # (MiniMax / Anthropic) reject the next request with
            # "tool result's tool id ... not found".
            messages = state.get("messages", [])
            last_msg = messages[-1]
            stripped_tool_call_ids = {
                tc["id"]
                for tc in (getattr(last_msg, "tool_calls", None) or [])
                if tc.get("id")
            }
            orphan_removals = [
                RemoveMessage(id=m.id)
                for m in messages
                if getattr(m, "type", None) == "tool"
                and getattr(m, "tool_call_id", None) in stripped_tool_call_ids
            ]
            content = self._append_text(last_msg.content, warning or _HARD_STOP_MSG)
            stripped_msg = last_msg.model_copy(update=self._build_hard_stop_update(last_msg, content))
            return {"messages": [*orphan_removals, stripped_msg]}
```

- [ ] **Step 2.3: 跑新增的 4 个测试，确认全部 pass**

Run from `backend/`:
```
PYTHONPATH=. uv run pytest tests/test_loop_detection_middleware.py::TestHardStopOrphanToolMessageRemoval -v
```

Expected: 4 passed.

- [ ] **Step 2.4: 跑整个 loop_detection 测试文件，确认零回归**

Run from `backend/`:
```
PYTHONPATH=. uv run pytest tests/test_loop_detection_middleware.py -v
```

Expected: all tests pass (existing TestHashToolCalls / TestLoopDetection / TestAppendText / TestHardStopWithListContent / TestToolFrequencyDetection + new 4 = full green).

特别检查：`test_hard_stop_at_limit`、`test_hard_stop_with_list_content`、`test_hard_stop_with_none_content`、`test_hard_stop_with_str_content`、`test_hard_stop_clears_raw_tool_call_metadata` 这五个原有 hard_stop 测试必须仍然 pass — 它们的 fixture 用的是 `_make_state(tool_calls=...)`（无 ToolMessage in history），所以新逻辑下 `orphan_removals` 应为空列表，行为不变。

---

## Task 3: 完整后端回归

**Files:** none (verification only)

- [ ] **Step 3.1: 跑整个 backend test suite**

Run from `backend/`:
```
make test
```

Expected: 全 pass。如果有失败：
- 先看是否与本次改动相关（grep 失败堆栈是否提到 `loop_detection` / `RemoveMessage` / `tool_calls`）
- 不相关的 flaky / 已存在失败：记录但不阻塞本任务
- 相关失败：停下来分析，必要时回 Task 2 调整

- [ ] **Step 3.2: lint + format 确认零警告**

Run from `backend/`:
```
make lint
```

Expected: 干净，无新 warning。

---

## Task 4: Commit

**Files:** all modified files staged.

- [ ] **Step 4.1: 检查改动**

Run:
```
git -C /Users/lydoc/projectscoding/deer-flow status
git -C /Users/lydoc/projectscoding/deer-flow diff backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py backend/tests/test_loop_detection_middleware.py
```

Expected: 仅 2 个文件改动 — 中间件 + 测试。

- [ ] **Step 4.2: Stage + commit（特定文件，避免 add -A）**

Run:
```
git -C /Users/lydoc/projectscoding/deer-flow add backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py backend/tests/test_loop_detection_middleware.py
git -C /Users/lydoc/projectscoding/deer-flow commit -m "$(cat <<'EOF'
fix(loop-detection): remove orphan ToolMessages on hard_stop

LoopDetectionMiddleware hard_stop cleared the AIMessage's tool_calls
but left matching ToolMessages in history, causing strict providers
(MiniMax / Anthropic) to reject the next request with
"tool result's tool id ... not found".

Now emits RemoveMessage for any ToolMessage whose tool_call_id matches
the stripped AIMessage's tool_calls. Narrow scope: only the looping
AIMessage's ids — unrelated ToolMessages from prior valid turns are
preserved.

Spec: docs/superpowers/specs/2026-04-27-loop-detection-orphan-tool-msg.md
EOF
)"
```

Expected: 一个新 commit。

---

## Self-Review

**1. Spec coverage:**

| Spec section | Plan task |
|---|---|
| Root cause: hard_stop strips tool_calls but leaves ToolMessage | Task 2 Step 2.2 |
| Fix recommendation A: RemoveMessage for orphans | Task 2 Step 2.2 |
| Narrow scope: only IDs from stripped AIMessage | Task 1 Step 1.2 (`test_hard_stop_removes_only_matching_orphans_not_unrelated_tool_msgs`) + Task 2 Step 2.2 (`stripped_tool_call_ids` filter) |
| 边界：tool_call 还没产生 ToolMessage 的情况自然覆盖 | Task 1 (`test_hard_stop_no_remove_when_no_orphan_exists`) |
| 多 tool_call 同一 message | Task 1 (`test_hard_stop_handles_multiple_tool_calls_in_one_message`) |
| RemoveMessage import 已在 summarization_middleware.py 验证可用 | Task 2 Step 2.1 |
| 不和 DanglingToolCallMiddleware 重叠职责 | Plan architecture note + Task 2 仅改 loop_detection 一个文件 |

无 gap。

**2. Placeholder scan:** None — all code blocks complete, all commands have expected output, no "TBD"/"TODO".

**3. Type consistency:**
- `RemoveMessage(id=...)` — 与 `summarization_middleware.py:12` 同名导入路径一致
- `tc.get("id")` — 与现有 `_track_and_check` 第 244 行的 `tc.get("name", "?")` 同 dict 接口
- `getattr(m, "type", None) == "tool"` — 与 `_track_and_check` 第 220 行的 `getattr(last_msg, "type", None) != "ai"` 同 LangChain message contract
- `tool_call_id` 属性 — 与测试文件 `ToolMessage(..., tool_call_id=...)` 构造参数一致
- `_make_runtime` / `_bash_call` / `_make_state` / `_HARD_STOP_MSG` — 全部从测试文件顶部已有 helpers / imports 拿，无重复定义

无不一致。
