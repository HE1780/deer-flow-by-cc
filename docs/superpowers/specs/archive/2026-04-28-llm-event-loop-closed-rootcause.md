> 📦 **归档于 2026-04-29 — 根因报告，作为历史档案保留**
>
> Gateway mode 修复已 ship（main_loop helper），Standard mode 仍是已知限制 — 见 [OPEN_ISSUES.md OI-3](../../../OPEN_ISSUES.md)。

---

# Event Loop is Closed — 根因报告（草稿）

**状态：** Gateway mode 已闭环（main-loop reuse 改造，见 [`2026-04-28-llm-event-loop-closed-design.md`](./2026-04-28-llm-event-loop-closed-design.md)）；Standard mode 文档化为已知限制（见 backend/CLAUDE.md Runtime Modes 章节）。
**报告日期：** 2026-04-28
**复现日期：** 2026-04-28 08:35:14（gateway.log line 981）
**部署模式：** Gateway 模式（`make dev-pro`），LangGraph 标准模式未观测到该 bug

---

## 现象

用户在 `/workspace/agents/123/chats/908663b7-8189-4bdd-8cec-48bfaa49a695` 发起对话：

- 第 1 次发消息：成功，agent 正常回复。
- 第 2 次发消息：前端收到 `LLM request failed: Event loop is closed`，run 状态被 manager 标记为 `success`（middleware 吞了异常），但实际 LLM 没生成内容。

`logs/gateway.log:981-1054` 抓到完整 traceback，终点：

```
File "anyio/_backends/_asyncio.py:1329", in aclose
    self._transport.close()
File "asyncio/selector_events.py:875", in close
    self._loop.call_soon(self._call_connection_lost, None)
File "asyncio/base_events.py:545", in _check_closed
    raise RuntimeError('Event loop is closed')
```

---

## 根因

**`langchain_openai` 的 `_get_default_async_httpx_client` 用了 `@lru_cache`，cache key 不含 event loop identity。** 已有上游 issue [langchain-ai/langchain#35783](https://github.com/langchain-ai/langchain/issues/35783) 跟踪该 bug。

deer-flow 在 Gateway 模式下同时存在两个调用 langchain_openai 的执行上下文：

1. **主 Uvicorn loop**（长寿命）—— gateway run worker 跑用户 agent 对话。
2. **Ephemeral loop**（短寿命）—— [`packages/harness/deerflow/agents/memory/updater.py:231,236`](../../backend/packages/harness/deerflow/agents/memory/updater.py#L231-L236) 在线程池里通过 `asyncio.run(coro)` 跑 memory 抽取，每次起一个新 loop，跑完即关。

调用链：

- ephemeral loop 第一次跑 memory updater → 调 `ChatOpenAI.ainvoke` → langchain_openai 通过 `lru_cache` 创建一个 `httpx.AsyncClient` → connection pool 绑在 ephemeral loop。
- ephemeral loop 跑完 → `asyncio.run` 退出 → loop close。
- 主 loop 上的 Run #2 调 `ChatOpenAI.ainvoke` → langchain_openai 从 lru_cache 取回**同一个 client** → 新 socket 在主 loop 上建立 OK，但 connection pool 里有 **idle connection 是绑在已 close 的 ephemeral loop 上**。
- 流读完后 httpx 调 `response.aclose()` → 走 anyio → asyncio transport.close → `loop.call_soon(...)` 指向已 close 的 ephemeral loop → `RuntimeError`。

---

## 时间线证据

来自 `logs/gateway.log` thread `908663b7-8189-4bdd-8cec-48bfaa49a695`：

| 时间 | 事件 | 上下文 |
|------|------|--------|
| 08:34:11 | Run #1 创建（`231226e1...`）| 主 loop |
| 08:34:17 | Chat completions 200 OK | 主 loop |
| 08:34:23 | Chat completions 200 OK | 主 loop |
| 08:34:28 | Run #1 success；memory update **queued** | 主 loop → 入队列 |
| 08:34:58 | memory.queue 开始 process（`Updating memory for thread ...`）| **第一次 ephemeral loop 启动**（`asyncio.run` in thread pool） |
| 08:35:05 | 用户提交 Run #2（`222dc7cb...`）| 主 loop |
| 08:35:07 | Chat completions 200 OK（memory updater）| ephemeral loop |
| 08:35:07 | `Failed to parse LLM response for memory update` | ephemeral loop 退出，**loop close** |
| 08:35:07 | Chat completions 200 OK（Run #2 第一次 LLM 调用）| 主 loop（新 socket OK） |
| 08:35:11 | Chat completions 200 OK（Run #2 第二次 LLM 调用）| 主 loop |
| 08:35:14 | `LLM call failed after 1 attempt(s): Event loop is closed` | 主 loop close 老 idle connection 时挂 |

**关键观察：** Run #1 干净是因为 ephemeral loop 那时还没启动；问题出现在 ephemeral loop close 之后主 loop 触碰 cached client 池里的老 connection。

---

## 关联代码位置

| 文件 | 行 | 说明 |
|------|----|------|
| [`backend/packages/harness/deerflow/agents/memory/updater.py`](../../backend/packages/harness/deerflow/agents/memory/updater.py#L231) | 231 | `_SYNC_MEMORY_UPDATER_EXECUTOR.submit(asyncio.run, coro)` —— ephemeral loop 来源（线程池路径） |
| `…/memory/updater.py` | 236 | `return asyncio.run(coro)` —— ephemeral loop 来源（直调路径） |
| [`backend/packages/harness/deerflow/models/factory.py`](../../backend/packages/harness/deerflow/models/factory.py#L140) | 140 | `model_class(**{**model_settings_from_config, **kwargs})` —— 实例化 ChatOpenAI 时**未传** `http_async_client=`，使用 langchain_openai 默认 lru_cache |
| [`backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py`](../../backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py#L275) | 275 | 异常被 middleware 吞 + 1 次 retry，所以 run manager 报 success，前端却看到 "LLM request failed" |
| [`backend/app/gateway/services.py`](../../backend/app/gateway/services.py#L415) | 415 | gateway 模式 run worker 用 `asyncio.create_task` 调度到主 Uvicorn loop |
| [`backend/packages/harness/deerflow/subagents/executor.py`](../../backend/packages/harness/deerflow/subagents/executor.py#L472) | 472,527 | 另一个 ephemeral loop 来源（subagent 执行）—— 同样会复用 cached client，理论上同样有风险 |
| [`backend/packages/harness/deerflow/mcp/cache.py`](../../backend/packages/harness/deerflow/mcp/cache.py#L114) | 114,118,122 | MCP 初始化也走 ephemeral loop，但只在启动时跑一次，影响有限 |

---

## 影响面

- **可见性：** Gateway 模式（`make dev-pro` / `make start-pro`）下，任何启用 memory 的 agent 在第 2 次起的对话都有概率挂 LLM 调用，concrete 重现：单线程连续聊 2 轮即可触发。
- **静默失败：** middleware 吞异常 + run manager 标 success，前端看到一句话错误但 telemetry/audit 不会自然报警。需要补可观测。
- **subagent 路径：** `subagents/executor.py:472,527` 也用 ephemeral loop 调 LLM，等同样模式触发——目前 subagent 用得少所以未浮出，但根因相同。
- **标准模式：** LangGraph Server 进程独立运行，进程内若没有 ephemeral loop 路径就不出现。但 deer-flow 的 memory updater 在 LangGraph Server 进程里也跑同样的 `asyncio.run`，**理论上 standard 模式也有这个 bug**，只是当时没在 standard 模式下复现到——后续验证。

---

## 候选修复方向（仅枚举，不选型）

待 brainstorm 阶段决策。先列出来供讨论：

1. **A — 治本：把 ephemeral loop 改成长寿命 worker loop。** memory updater / subagent executor 用单一 thread + 永久 loop（`new_event_loop` + `run_forever`）替换 `asyncio.run`。任务通过 `run_coroutine_threadsafe` 提交。优点：langchain_openai 的 cached client 始终绑同一个 loop。缺点：改动 worker 模型，要小心 shutdown / 异常隔离。
2. **B — 治标 + 局部：每次创建 ChatOpenAI 时传一个独立 `http_async_client=httpx.AsyncClient(...)`。** 跳过 langchain_openai 的 lru_cache 单例。优点：改动小，集中在 [`models/factory.py:140`](../../backend/packages/harness/deerflow/models/factory.py#L140) 一处。缺点：每次 ainvoke 起新 connection pool，TLS 握手开销略增，且 client lifecycle 要靠 GC。
3. **C — 升级依赖。** 关注 langchain-ai/langchain#35783 的修复进度，等上游修了直接升 langchain_openai。优点：零自有代码改动。缺点：上游 PR 状态未知，被动等。
4. **D — Workaround：在 ephemeral loop 入口前后清 lru_cache。** memory updater / subagent executor 调 `_get_default_async_httpx_client.cache_clear()`（或类似手段）做隔离。优点：最小手术。缺点：依赖 langchain_openai 内部 API，脆弱。

---

## 后续步骤

1. brainstorm：从上述 4 个方向选一个，确认 trade-off
2. 写正式 design spec
3. 写 implementation plan
4. 实施 + 加回归测试（单元测试模拟两个 loop 复用同一个 cached client 的场景）
5. 同时给 [`llm_error_handling_middleware.py:275`](../../backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py#L275) 补可观测：异常被吞时也要发一条 critical 级 audit/log，方便下次类似 silent failure 早发现
