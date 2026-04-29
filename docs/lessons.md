# Lessons Learned

A running log of mistakes and discoveries that should shape future work.
Recent entries first.

---

## 2026-04-28 — MiniMax M2.7 长内容生成截断 → LoopDetection warning → 线程永久损坏（会话 336b7fce 完整复盘）

### 触发链

```
MiniMax M2.7 生成 HTML 超过输出 token 限制 → 内容截断
  → 模型反复 write_file / read_file / str_replace 尝试续写（12 轮 LLM 调用）
    → LoopDetectionMiddleware WARNING 触发（warn_threshold=3，非 hard-stop）
      → 在工具调用链中间注入 HumanMessage("不要再重复了...")
        ├─ [问题1] 前端消息分组异常
        ├─ [问题2] 前端只显示思考内容，用户原始提问不显示
        └─ [问题3] 历史污染 → 后续追问时 MiniMax 拒绝 → 线程永久损坏
```

### 会话时间线

| 时间 | 事件 |
|------|------|
| 15:50:10 | 线程创建，Run 1 开始 (minimax-m2.7, plan_mode=true) |
| 15:50:17 – 15:56:57 | 12 轮 LLM 调用，模型反复尝试写完整 HTML |
| 15:56:59 | **LoopDetection WARNING 触发** — 注入 HumanMessage |
| 15:57:00 – 15:57:13 | 模型收到警告后生成最终回答，Run 1 结束 |
| 16:07:27 | 用户追问 "请告诉我生成文件的路径"，Run 2 开始 |
| 16:07:31 | 第 1 次 LLM → 200 OK（初始历史尚可加载） |
| 16:07:47 | 第 2 次 LLM → **400 "tool call result does not follow tool call (2013)"** |
| 16:08:46 | 用户再次尝试，Run 3 开始 |
| 16:08:55 | 第 1 次 LLM → **400 同样错误**，线程永久损坏 |

### 发现的问题

#### 问题 1：前端 Console Error — `Unexpected tool message outside a processing group`

**文件：** `frontend/src/core/messages/utils.ts:86`

**根因：** LoopDetection warning 注入的 HumanMessage 插入在工具调用链（AIMessage(tool_calls) → ToolMessage → ...）中间，导致前端 `groupMessages()` 的 `lastOpenGroup()` 在遇到后续 ToolMessage 时找不到对应的 `assistant:processing` 组。详见 `utils.ts:40-48` 的 `lastOpenGroup()` 逻辑。

#### 问题 2：前端会话只显示"模型停止前的思考"，用户原始提问消失

**根因：** 问题 1 的消息分组断裂导致前端渲染链路异常，部分消息（含最初的 HumanMessage）未被正确渲染，仅显示了最后成功分组的 AI 内容。

#### 问题 3：LoopDetection warning 注入导致线程永久损坏（严重）

**根因：** `LoopDetectionMiddleware._apply()` 在 warning 路径（`loop_detection_middleware.py:373-380`）直接在工具调用循环中间注入 `HumanMessage(content=warning)`。这条 HumanMessage 破坏了 MiniMax 严格要求的 `AIMessage(tool_calls) → ToolMessage(result)` 配对格式。当前次运行尚能结束（模型配合停止了工具调用），但持久化到 checkpointer 的历史已经"不干净"。

下次用户追问时，LangGraph 从 checkpointer 加载历史 → 模型生成回答（可能含 `write_todos` 等 tool_call）→ 工具执行后再次调用 LLM → MiniMax 检测到历史中的 ToolMessage 缺少匹配的 tool_call → 拒绝请求（2013 错误码）。

**关键细节：** 日志确认触发的是 **warning**（`warn_threshold=3`），不是 **hard-stop**（`hard_limit=5`）。Warning 路径不做任何消息清理（不 strip tool_calls、不 RemoveMessage），仅追加一条 HumanMessage。Hard-stop 路径虽然设计了消息清理逻辑（`loop_detection_middleware.py:350-371`），但注释也承认这是针对 MiniMax/Anthropic 严格校验的补丁——说明开发者已知晓严格 provider 对消息格式的敏感性。

#### 问题 4：LLMErrorHandlingMiddleware 静默吞错

**文件：** `packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py`

当 MiniMax 返回 400 时，`LLMErrorHandlingMiddleware` 捕获异常并返回 "user-facing fallback message"（通用错误提示），Run 被标记为 `success`。用户看不到真实的错误原因，只看到模糊的失败信息。且因为没有抛出异常，上层无法感知线程已损坏。

### 处置建议

| 优先级 | 问题 | 建议 |
|--------|------|------|
| **高** | 问题 3 — 线程永久损坏 | LoopDetection warning 不应在工具调用链中间注入消息。考虑：(a) 将 warning 合并到 system prompt 而非作为独立消息；(b) 或使用 HumanMessage 但在下一轮 LLM 调用前通过 `RemovableMessage` 机制清理；(c) 至少 warning 触发后标记线程状态，阻止后续运行 |
| **中** | 问题 1/2 — 前端消息分组 | `groupMessages()` 增加防御性处理：当 ToolMessage 找不到 open group 时不丢弃，而是自建一个 degraded group |
| **低** | 问题 4 — 错误静默 | 400 类协议错误（非临时性网络错误）不应静默吞掉，应向上层抛出以触发明确的错误状态展示 |

### 与多租户改造的关系

**全部无关。** 多租户存储层在整个会话中正常运作（产物正确写入 `tenants/1/workspaces/1/threads/336b7fce.../outputs/`），无 `PathEscapeError`、无 403。

---



**Mistake:** During the M4 storage-isolation rollout, five production call
sites were left on the legacy `Paths.sandbox_*_dir(thread_id)` /
`thread_dir` / `ensure_thread_dirs` / `delete_thread_dir` API while
documentation claimed the migration was complete. A user upload bug
surfaced months later (chat `53617e94-7d39-4174-96ba-de29a579da27`):
`UploadsMiddleware` read the legacy single-tenant path and saw nothing,
so the agent triggered `ask_clarification` instead of analysing the
uploaded CSV.

**Why it slipped:**

1. The legacy methods were left in place with no deprecation signal.
2. New code copy-pasted from old code, which still used the legacy names.
3. `backend/CLAUDE.md` described the migration as done.
4. There was no automated way to surface the discrepancy.

**Sibling latent bugs uncovered while fixing it:**

* `app/channels/manager.py:_resolve_attachments` was mixing tenant-aware
  path resolution with a legacy-path boundary check — so any IM-channel
  artifact under `tenants/{T}/...` got falsely rejected as a path-traversal
  attempt.
* `app/channels/feishu.py` ignored tenant ids the manager already had,
  so Feishu uploads written under `ENABLE_IDENTITY=true` landed in the
  wrong directory.
* `app/gateway/routers/threads.py:_delete_thread_data` silently no-op'd
  on the legacy path for identity-on threads, leaking tenant directories
  on disk forever.
* `packages/harness/deerflow/sandbox/tools.py:204` and
  `tools/builtins/invoke_acp_agent_tool.py:40` still used legacy methods.

**Rule:**

When a cross-cutting API gets a tenant-aware (or otherwise-extended) cousin:

1. Either **delete** the old API in the same PR (with all call sites
   migrated), **or**
2. Mark the old API with `DeprecationWarning` from day one. Internal
   callers of the old API are migrated in the same PR; the deprecation
   signal then catches any future regression at test time.
3. Don't rely on documentation alone. Reviewers don't grep for old API
   names; deprecation warnings do.
4. After landing the deprecation, run
   `pytest -W error::DeprecationWarning` once to confirm zero internal
   callers remain — this is the only durable guarantee.

**How to apply:** When introducing `resolve_*` / `_for` patterns alongside
legacy methods, follow up *in the same PR* with deprecation. If you find
yourself thinking "I'll add deprecation later," that means the bug we hit
will hit again. Use `grep -rn '\.legacy_method_name(' --include="*.py"`
to audit every call site before considering the migration done — and run
that grep against both `packages/` and `app/` (a single `--include` flag
plus `\|`-alternation easily masks one of them).

**Related artefacts:**

* Spec: [`docs/superpowers/specs/archive/2026-04-28-uploads-tenant-aware-design.md`](superpowers/specs/archive/2026-04-28-uploads-tenant-aware-design.md)
* Plan: [`docs/superpowers/plans/archive/2026-04-28-uploads-tenant-aware.md`](superpowers/plans/archive/2026-04-28-uploads-tenant-aware.md)
* Memory: `feedback_cross_cutting_api_migration.md`

## 2026-04-28: "假死循环" 先排查 max_tokens,再排查 prompt/检测器

**Symptom:** 模型反复 `write_file` / `str_replace` 写同一个文件直到 recursion 上限,
看起来像 prompt 死循环或 LoopDetectionMiddleware 失灵。

**Root causes are TWO, not one:**

1. **Prompt / 路径设计问题** —— ToolMessage 是 `Error: ...`,模型不断重试。LoopDetection
   Layer 3 已处理(同 path 连续失败 → warn=3 / hard=4)。
2. **LLM `max_tokens` 偏小** —— ToolMessage 是 `OK`,但上一次 AIMessage 的 `content`
   或 tool args 在传输中被服务端**截断**。模型读自己的 message 看到"没写完"于是再写一次。
   表现完全相同,但属于**模型输出容量不够**,不是 agent 行为问题。

**实战:** 2026-04-28 排查 dual-dir-loop 时,会话 1 (HTML 编码) 表现是死循环,实际触发原因
是 [config.yaml](../config.yaml) 里 MiniMax `max_tokens` 偏小,把生成中段的 HTML 切了。
用户调到 184096(模型上限附近)后问题消失。

**How to apply:**

1. 看到"反复写同一个文件" → 第一时间打开 thread state JSON,**看最近 N 条 ToolMessage 的
   content** —— 全是 `OK`?那是 max_tokens;掺着 `Error: ...`?那是 prompt/路径。
2. **不要**在 LoopDetectionMiddleware 里加 "AIMessage 输出截断检测"。那是模型容量问题,
   应该让操作员调 config,不应该让 middleware 替模型擦屁股。
3. 新模型上线时把 `max_tokens` 设到供应商文档明确支持的最大值,留 16-32k 余量给 input。
   过小的 `max_tokens` 在长产物场景(HTML/MD/代码)是隐性陷阱。

**Related artefacts:**

* Spec: [`docs/superpowers/specs/archive/2026-04-28-workspace-outputs-dual-dir-loop.md`](superpowers/specs/archive/2026-04-28-workspace-outputs-dual-dir-loop.md)(排查附录节)
* Config: [`config.yaml`](../config.yaml) `models[name=minimax-m2.7].max_tokens`
