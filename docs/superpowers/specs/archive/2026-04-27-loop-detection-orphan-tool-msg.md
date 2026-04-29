> 📦 **归档于 2026-04-29 — hard_stop 已 ship；warning 路径仍 open**
>
> hard_stop 路径修复已落地（[loop_detection_middleware.py](../../../../backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py) line 508-516 `RemoveMessage`）。warning 路径（line 373-380）注入 HumanMessage 仍未修，已实证导致 thread 永久损坏 — 详见 [OPEN_ISSUES.md OI-1](../../../OPEN_ISSUES.md) + [docs/lessons.md](../../../lessons.md) 2026-04-28 完整复盘。

---

# LoopDetectionMiddleware 清空 tool_calls 留下孤儿 ToolMessage 的修复

**记录日期：** 2026-04-27
**状态：** hard_stop ✅ shipped；warning 🟡 open（详见上方 banner）
**严重程度：** P1 — 用户分析任务被卡住无法继续
**与 langgraph-compat 关系：** 无关（standard mode 同样存在），只是切换后用户活跃度高暴露出来
**待办：** 实施计划尚未撰写；推荐 A 方案（用 `RemoveMessage` 清孤儿）。详见下文。

---

## 故障表现

用户提交分析任务，agent 中途调用了多次工具触发 loop detection，最后被强制停止。后续任何后续对话立刻收到：

```
LLM request failed: Error code: 400 - {'type': 'error', 'error': {'type': 'bad_request_error',
'message': "invalid params, tool result's tool id(call_function_rffkme0pw46g_1) not found (2013)",
'http_code': '400'}, 'request_id': '063d9ecfc928c9f8bb61a0e364f27d87'}
```

前端控制台同时报 `Unexpected tool message outside a processing group` —— 这是 [groupMessages](../../../frontend/src/core/messages/utils.ts#L83) 兜底日志，确实数据流不正常。

## 实证调查

读 thread `0042c747-ae30-4c1d-a8eb-3135562cba04` 的 messages history（前 10 条）：

```
[0] TOOL  tool_call_id=call_function_rffkme0pw46g_1  ← 孤儿，前面没有匹配的 AI tool_calls
[1] AI    tool_calls=[]  content="Let me stop the loop and provide a comprehensive summary..."
[2] human "<system_reminder> incomplete todo items..."
[3] AI    tool_calls=['call_function_p5k7tjltv9ud_1']
[4] TOOL  tool_call_id=call_function_p5k7tjltv9ud_1
[5] AI    tool_calls=['call_function_u6jxw3kp0m06_1']
[6] TOOL  tool_call_id=call_function_u6jxw3kp0m06_1
[7] AI    tool_calls=[]  content="LLM request failed: Event loop is closed"
[8] human "<system_reminder>..."
[9] AI    tool_calls=[]  content="LLM request failed: Error code: 400 ... tool id ... not found"
```

`messages[0]` 就是孤儿 ToolMessage，对应的 AI tool_calls 在 `messages[1]` 中被**清空**了。

## Root cause

[backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py:327-345](../../../backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py#L327)

```python
def _build_hard_stop_update(last_msg, content):
    update = {
        "tool_calls": [],   # ← 清空了 AI message 的 tool_calls
        "content": content,
    }
    ...
```

但**对应的 ToolMessage 已经被工具系统执行并写进 history**。LangGraph 的 messages reducer 默认按 id 替换，replace 掉那条 AIMessage 后：
- 原 AIMessage `tool_calls=[X]` → 变成 `tool_calls=[]`
- 原对应的 `ToolMessage(tool_call_id=X)` 还留在 history 里
- 下次 LLM 调用，模型看到孤儿 ToolMessage → 严格的 provider（MiniMax / Anthropic / 部分 OpenAI 兼容厂商）拒绝

`DanglingToolCallMiddleware` 处理的是反方向（AI 有 tool_calls 缺 ToolMessage），管不到这个。

## 触发条件

任何场景下 LoopDetectionMiddleware 命中 hard_limit（默认 5 次相同 tool call hash）：
- Agent 反复调用同一个工具陷入死循环
- Agent 在多步骤分析中重复 read_file / bash 同一命令
- 用户明确要求 agent 重做某个操作 N 次

每次触发，对应 thread 后续就死了（除非用户新建 thread）。

## 修复方案候选

### A. 在 _build_hard_stop_update 同时删除孤儿 ToolMessage（推荐）

在 `_apply` 里返回 `RemoveMessage` 列表清理孤儿：

```python
from langchain_core.messages import RemoveMessage

def _apply(self, state, runtime):
    warning, hard_stop = self._track_and_check(state, runtime)
    if hard_stop:
        messages = state.get("messages", [])
        last_msg = messages[-1]
        original_tool_call_ids = {tc["id"] for tc in (getattr(last_msg, "tool_calls", None) or [])}
        content = self._append_text(last_msg.content, warning or _HARD_STOP_MSG)
        stripped_msg = last_msg.model_copy(update=self._build_hard_stop_update(last_msg, content))

        # Remove orphan ToolMessages that would lose their tool_call partner
        removals = [
            RemoveMessage(id=m.id)
            for m in messages
            if m.type == "tool" and m.tool_call_id in original_tool_call_ids
        ]

        return {"messages": [*removals, stripped_msg]}
    ...
```

但要小心：被 strip 的 AI message 可能还没产生 ToolMessage（loop detection 在 after_model 触发，工具尚未执行）。这种情况下 ToolMessage 不存在，也无需删除。所以上面代码条件判断 `m.tool_call_id in original_tool_call_ids` 自动覆盖两种情况。

### B. 不清空 tool_calls，改用 prompt-injection 强制文字输出

在 last_msg 后追加一条 SystemMessage："loop detected, must answer in plain text"。但这破坏 multi-system-message 的兼容性（注释里已经说了 Anthropic 会炸）。**不推荐**。

### C. 让 `DanglingToolCallMiddleware` 也处理反方向

在 before_model 里检测 `ToolMessage` 没匹配的 AI tool_calls → 注入 fake AI message 包含 tool_call。**不推荐**：会让 history 出现伪造的 AI 消息，更乱。

## 实施成本

A 方案大约 **20-40 行代码改动 + 2-3 个测试**。需要新建测试 fixture：构造 hard_stop 触发条件，验证返回的 RemoveMessage + stripped_msg 一起作用后 history 正确。

## 用户的当前 thread 怎么办

代码修了也救不回 `0042c747-...`——它的 history 已经污染。两个选择：
1. 让用户**新建 thread** 继续工作（最简单）
2. 写一个一次性脚本扫所有 thread checkpoint，删除孤儿 ToolMessage（侵入性高，不推荐）

建议 1。

## 待办

- [ ] 写实施计划（详细 task 列表 + 测试 fixture）
- [ ] 实施 A 方案
- [ ] 跑回归测试
- [ ] commit

## 实施指引（2026-04-28 复核补充）

下一个写 plan 的工程师可直接照下表落地，避免重新做 root-cause 调查：

| 项 | 坐标 | 改动 |
|---|---|---|
| 文件 | `backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py` | 单文件改动 |
| 导入 | line 25（当前只有 `HumanMessage`） | 追加 `RemoveMessage` from `langchain_core.messages` |
| 主逻辑 | `_apply()` 方法的 hard_stop 分支（约 line 347-356）+ `_build_hard_stop_update`（约 line 327） | 提取被 strip 的 AIMessage 的 `tool_call_ids`，遍历 messages 历史找出对应孤儿 `ToolMessage`，返回 `[*RemoveMessage(id=...), stripped_msg]` 而非 `[stripped_msg]` |
| 现有测试 | 同文件已有 `TestHardStopWithListContent`（约 line 354-415） | 参考其 `_make_state` fixture 模式新增 `TestHardStopOrphanRemoval` |
| 反向 middleware | `DanglingToolCallMiddleware` 已处理"AI tool_call 没 ToolMessage"的反向场景 | 不要重复职责；本修复只补正向 |
| 已在仓库证明可用 | `summarization_middleware.py` 已用 `RemoveMessage` | 无导入阻碍 |

**预计**：~30 行编码 + ~50 行测试 + 1 处文档/changelog；2-4 小时 agentic 实施。

## 关联

- 触发的"Console Error: Unexpected tool message outside a processing group" 在 [frontend/src/core/messages/utils.ts:83](../../../frontend/src/core/messages/utils.ts#L83) 也只是兜底，可以不动——root cause 修了它就不再出现
- 同时观察到的 "Event loop is closed" 是另一个独立问题，记录在 [docs/superpowers/plans/archive/2026-04-27-identity-langgraph-passthrough-bug.md](../plans/archive/2026-04-27-identity-langgraph-passthrough-bug.md) 的副作用列表
