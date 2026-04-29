> 📦 **归档于 2026-04-29** — Gateway mode 主线已 ship（[main_loop.py](../../../../backend/packages/harness/deerflow/runtime/main_loop.py)，merge `c769a210`）。Standard mode 已知限制 + LLM 错误可观测性补丁未跑见 [OPEN_ISSUES.md OI-2 / OI-3](../../../OPEN_ISSUES.md)。

---

# Event Loop is Closed —— Design Spec

**关联根因报告：** [`2026-04-28-llm-event-loop-closed-rootcause.md`](./2026-04-28-llm-event-loop-closed-rootcause.md)
**状态：** ✅ 设计已采纳并交付（详见上方 banner）
**作者：** Claude (Opus 4.7) + 用户协作
**日期：** 2026-04-28

---

## 1. Problem Statement

Gateway mode 下，langchain_openai 的 `_get_default_async_httpx_client` 是模块级 `@lru_cache`（cache key 不含 event loop identity）。memory updater（[`updater.py:231,236`](../../backend/packages/harness/deerflow/agents/memory/updater.py#L231)）和 subagent executor（[`executor.py:472,527`](../../backend/packages/harness/deerflow/subagents/executor.py#L472)）当前用 `asyncio.run` / `asyncio.new_event_loop` 起 ephemeral loop 调 LLM。ephemeral loop 关闭后，cached httpx client 的 connection pool 里残留绑在死 loop 上的 idle connection；下一次主 Uvicorn loop 触碰 cached client 时，httpx 调 `aclose()` → anyio → asyncio transport.close → `loop.call_soon(...)` 指向已 close 的 loop → `RuntimeError("Event loop is closed")`。

详细根因、时间线证据、上游 issue 链接见根因报告。

---

## 2. Goal / Non-Goal

### Goal

- **G1**：Gateway mode 下彻底消除 ephemeral loop 调 LLM 的路径，使 langchain_openai 的 cached httpx client 永远绑同一个稳定的 event loop（主 Uvicorn loop）。
- **G2**：调用方契约零变化——`MemoryUpdater.update_memory()` 仍然 sync 返回 `bool`；`SubagentExecutor.execute()` 仍然 sync 返回 `SubagentResult`。
- **G3**：lifespan 关停时所有在途 future 立即 cancel，`CancelledError` 不被吞，shutdown 后再 submit 直接抛 `RuntimeError`。
- **G4**：补一道可观测性——LLM 错误被 middleware 吞掉时也写一条 critical 级 audit/log，便于下次类似 silent failure 早发现（根因报告后续步骤 5）。

### Non-Goal

- **NG1**：不修 Standard mode（`make dev`）。LangGraph Server 是独立进程，无 lifespan 注入点；当前阶段 Standard mode 已是 advanced profile，作为已知限制写进文档即可。
- **NG2**：不改 langchain_openai 内部、不绕过 lru_cache、不传 `http_async_client=`（候选方案 B/D 都是治标，不在此次范围）。
- **NG3**：不引入新的 worker loop 抽象。不在主 loop 之外另起后台 loop。
- **NG4**：MCP cache 的一次性 ephemeral loop（[`cache.py:114`](../../backend/packages/harness/deerflow/mcp/cache.py#L114)）只在启动时跑一次，影响有限，不在此次范围。
- **NG5**：不重构 memory queue 的 timer 模型；不改 subagent 的并发上限和 timeout 语义；调用契约保持 sync 阻塞。

---

## 3. 架构决定

### 3.1 选定方案：复用主 loop + sync 跳板

参考根因报告 §候选修复方向，选定**方案 A 的改良版**：不新建后台 worker loop，而是复用 Gateway lifespan 持有的主 Uvicorn loop。

memory updater / subagent executor 等"sync 调用方"通过一个新增的 helper `submit_to_main_loop(coro_factory)` 把协程提交到主 loop。helper 内部用 `asyncio.run_coroutine_threadsafe`，调用方拿 `concurrent.futures.Future` 后同步阻塞 `future.result()`。这样 LLM 调用（`model.ainvoke`）真正在主 loop 上跑，langchain_openai 的 cached client 永远绑同一个 loop，根因消除。

### 3.2 为什么不另起 worker loop（方案 A 原版）

- 没必要——主 loop 已经存在、长寿命、由 lifespan 管理。多搭一个等同于复制。
- 多一层间接（线程 + 自建 loop + run_forever 仪式 + shutdown 协调）= 多一处可能出错。
- "memory/subagent 和用户对话物理隔离"是过度防御——asyncio 协程在 IO 等待时本来就让出，不会真正阻塞用户对话；真正的 CPU 密集场景应该用 `asyncio.to_thread`，而不是另起 loop。

### 3.3 为什么 Gateway mode 优先 / Standard mode 文档化

- Gateway mode（`langgraph-compat`）已是默认部署形态（前端 fallback 已切，docker-compose 默认 profile）。
- Standard mode 没有 lifespan 钩子可注入主 loop（LangGraph Server 是独立进程，deer-flow 不控制其启动代码），强行修需要 hack 注入点（如 `make_lead_agent` 首次调用时懒注册），引入隐式假设。
- 项目主线是自托管 epic，Standard mode 是给 LangSmith / Studio 用户的 advanced profile。修 Gateway mode = 修 99% 用户路径。

### 3.4 调用方契约（同步阻塞）

```python
# memory updater（updater.py:_run_async_update_sync 改造后）
return submit_to_main_loop(lambda: aupdate_memory(...))   # blocks until done, returns bool

# subagent executor（executor.py:execute 改造后）
return submit_to_main_loop(lambda: self._aexecute(task, result_holder))  # blocks until done, returns SubagentResult
```

唯一的契约变化：调用方传一个 zero-arg `coro_factory`（lambda）而非 `coro` 实例（避免跨线程 coroutine 复用风险）。除此之外，sync 阻塞行为、返回类型、异常传播全部和现状（`_SYNC_MEMORY_UPDATER_EXECUTOR.submit(asyncio.run, coro).result()`）一致——只是 future 的来源从「worker pool 起 ephemeral loop」变成「主 loop 直接跑」。

### 3.5 死锁防护（fail-fast 而非跳板）

`asyncio.run_coroutine_threadsafe` 的语义是调用方所在线程必须**不是 target loop 跑的那个线程**。否则 `future.result()` 永远等不到结果——主 loop 正在等当前调用阻塞返回，没机会跑 coro，死锁。

**真实调用现状盘点：**

- `MemoryUpdater._run_async_update_sync` 从 memory queue 的 `threading.Timer` 线程进入（[`queue.py:139-194`](../../backend/packages/harness/deerflow/agents/memory/queue.py#L139)）—— 不在主 loop 线程。
- `SubagentExecutor.execute` 从 LangChain sync `task_tool` 进入。LangGraph 在主 loop 上跑 agent 时，sync tool 通过 `loop.run_in_executor` / `asyncio.to_thread` 调度到工作线程跑 —— 也不在主 loop 线程。

主 loop 线程上调用 `submit_to_main_loop` 是**反模式**（async 上下文里应该直接 `await coro_factory()`，不该走 sync helper）。

**处理方式：fail-fast。** `submit_to_main_loop` 内部检测当前线程 ID 是否等于 `_main_loop_thread_id`：

- 不等于（正常情况）→ 直接 `run_coroutine_threadsafe(coro_factory(), main_loop)` + `future.result()`。
- 等于（反模式 / bug）→ 抛 `RuntimeError("submit_to_main_loop called from main loop thread; use 'await coro_factory()' instead")`。

不引入 `_submitter_pool` 跳板池——理由：
- 跳板池本质是「在主 loop 线程上 sync 阻塞等主 loop」的 hack，加层间接掩盖反模式而非修正。
- 现有两个调用点都不会触发这条路径；测试可用 mock 校验防御逻辑工作。
- 删 `_isolated_loop_pool` + `_SYNC_MEMORY_UPDATER_EXECUTOR` 之后**不再引入新 pool**——线程数净减少，且没有 worker 阻塞的尾部行为问题。

---

## 4. 关键组件

### 4.1 新增模块：`deerflow.runtime.main_loop`

文件：`backend/packages/harness/deerflow/runtime/main_loop.py`（新建）

提供进程级 singleton 入口。

#### 4.1.1 公开 API

```python
def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Lifespan 启动时由当前 loop 注入。重复调用同一 loop 是 no-op；不同 loop 抛 RuntimeError。"""

def get_main_loop() -> asyncio.AbstractEventLoop:
    """返回已注入的主 loop。未注入时抛 RuntimeError。"""

def has_main_loop() -> bool:
    """主 loop 是否已注入且未关停。Standard mode / 测试环境会返回 False。"""

def submit_to_main_loop(coro_factory: Callable[[], Coroutine]) -> Any:
    """提交协程到主 loop 并阻塞等结果。
    - coro_factory 必须是 zero-arg callable（避免跨线程 coro 复用问题）。
    - 调用方必须在非主 loop 线程；否则抛 RuntimeError（防死锁，见 §3.5）。
    - 主 loop 未注入或已关停：抛 RuntimeError。
    - 内部用 asyncio.run_coroutine_threadsafe + future.result() 同步阻塞。
    - 在途 future 进 _tracked_futures 弱引用集合，shutdown 时全部 cancel。
    """

async def shutdown_main_loop() -> None:
    """Lifespan 关停时调。
    1. 标记 _shutting_down = True，后续 submit 直接抛 RuntimeError。
    2. 遍历 _tracked_futures cancel 全部在途 future。
    3. 清空 _main_loop / _main_loop_thread_id 引用。
    不阻塞、不留超时——开发阶段策略，丢失 in-flight memory 更新可接受。
    """
```

#### 4.1.2 内部状态

```python
_main_loop: asyncio.AbstractEventLoop | None = None
_main_loop_thread_id: int | None = None    # 用于死锁防护检测（threading.get_ident()）
_tracked_futures: weakref.WeakSet[concurrent.futures.Future] = WeakSet()
_shutting_down: bool = False
_lock: threading.Lock = ...   # 保护 set/shutdown 时的状态翻转
```

**没有 `_submitter_pool`** —— 见 §3.5 fail-fast 决定。

#### 4.1.3 错误处理

- `submit_to_main_loop` 触发 `_shutting_down` → 抛 `RuntimeError("main loop is shutting down")`，调用方自然走异常路径。
- `future.result()` 抛 `concurrent.futures.CancelledError` → 直接 raise 给调用方，**不转译成 `False` / `None`**（让调用方知道是被 cancel 而非正常完成）。
- 主 loop 未注入（Standard mode / 测试）→ `has_main_loop()` 为 False，调用方走 fallback 路径（保留现有 `asyncio.run`）。

### 4.2 Gateway lifespan 集成

文件：[`backend/app/gateway/app.py`](../../backend/app/gateway/app.py)

在 `lifespan` 函数 LangGraph runtime 启动**之前**注入 main loop，关停时**之后**清理。位置紧贴现有 audit batch writer 的初始化/关停模式。

```python
async def lifespan(app: FastAPI):
    get_app_config()
    await _init_identity_subsystem()
    if get_identity_settings().enabled:
        await _init_audit_subsystem(app)

    # 新增：注入主 loop（在 langgraph_runtime 之前，确保 LangGraph 启动时 helper 已可用）
    set_main_loop(asyncio.get_running_loop())

    async with langgraph_runtime(app):
        channel_service = await start_channel_service()
        try:
            yield
        finally:
            ...
            # 新增：关停主 loop helper（在 langgraph_runtime 退出之后）
            await shutdown_main_loop()
            ...
```

### 4.3 Memory updater 改造

文件：[`backend/packages/harness/deerflow/agents/memory/updater.py`](../../backend/packages/harness/deerflow/agents/memory/updater.py)

修改 `_run_async_update_sync`（[L220-L250](../../backend/packages/harness/deerflow/agents/memory/updater.py#L220)）：

- 优先走 `submit_to_main_loop` 路径。
- `has_main_loop()` 为 False 时（Standard mode / 测试）走现有 `asyncio.run` fallback——**这条 fallback 保留就是 NG1 的体现**。
- 删除 `_SYNC_MEMORY_UPDATER_EXECUTOR`（[L29-L33](../../backend/packages/harness/deerflow/agents/memory/updater.py#L29)）以及 `loop.is_running()` 分支判断——helper 内部统一处理。

改造后骨架：

```python
def _run_async_update_sync(coro_factory: Callable[[], Awaitable[bool]]) -> bool:
    """Run an async memory update from sync code."""
    if has_main_loop():
        try:
            return submit_to_main_loop(coro_factory)
        except concurrent.futures.CancelledError:
            logger.info("Memory update cancelled (loop shutting down)")
            return False
    # Fallback: Standard mode / test path
    try:
        return asyncio.run(coro_factory())
    except Exception:
        logger.exception("Failed to run async memory update from sync context")
        return False
```

调用方改为传 `coro_factory`（lambda 形式）而非 `coro` 实例——这是必要的契约变化（避免跨线程 coro 复用），但只影响 `update_memory` 内部一处调用，对外 API 不变。

### 4.4 Subagent executor 改造

文件：[`backend/packages/harness/deerflow/subagents/executor.py`](../../backend/packages/harness/deerflow/subagents/executor.py)

**删除：**

- `_isolated_loop_pool`（[L80](../../backend/packages/harness/deerflow/subagents/executor.py#L80)）—— 整个 ThreadPoolExecutor 删掉。
- `_execute_in_isolated_loop`（[L459-L495](../../backend/packages/harness/deerflow/subagents/executor.py#L459)）—— 整个方法删掉，包括 loop 创建/清理仪式。
- `execute()` 中的 `loop.is_running()` 分支（[L515-L524](../../backend/packages/harness/deerflow/subagents/executor.py#L515)）。

**改造 `execute()`（[L497-L543](../../backend/packages/harness/deerflow/subagents/executor.py#L497)）：**

```python
def execute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
    if has_main_loop():
        try:
            return submit_to_main_loop(lambda: self._aexecute(task, result_holder))
        except concurrent.futures.CancelledError:
            # 关停时被 cancel，构造一个 FAILED 结果返回
            result = result_holder or SubagentResult(...)
            result.status = SubagentStatus.FAILED
            result.error = "Cancelled during shutdown"
            return result
        except Exception as e:
            logger.exception(...)
            result = result_holder or SubagentResult(...)
            result.status = SubagentStatus.FAILED
            return result
    # Fallback: no main loop registered
    try:
        return asyncio.run(self._aexecute(task, result_holder))
    except Exception:
        ...
```

`_scheduler_pool` 和 `_execution_pool`（[L73,L77](../../backend/packages/harness/deerflow/subagents/executor.py#L73)）保留——它们和 ephemeral loop 无关，是 task scheduling 用的。

### 4.5 LLM 错误可观测性补丁

文件：[`backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py`](../../backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py)

针对根因报告 §后续步骤 5：当前异常被 middleware 吞 + 1 次 retry 后，run manager 报 success，前端却看到 "LLM request failed"。这是 silent failure，需要被审计。

修改 [L275 附近](../../backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py#L275) 的异常 catch 分支：

- 异常被吞之前先 `logger.critical(..., exc_info=True)`。
- 如果 audit batch writer 已挂（`app.state.audit_writer`），enqueue 一个 `llm.error.silenced` 事件（critical=True），payload 含 `error_class`, `model_name`, `tenant_id`, `thread_id`, `run_id`。

`KNOWN_ACTIONS` 加 `llm.error.silenced`、`KEY_CRITICAL_ACTIONS` 也加同名。这两处在 `app/gateway/identity/audit/events.py`。

---

## 5. 关停语义

### 5.1 顺序

1. lifespan teardown → `await shutdown_main_loop()`。
2. `_shutting_down = True`（后续 submit 抛 RuntimeError）。
3. 遍历 `_tracked_futures` 调 `future.cancel()`。
4. `_main_loop = None`、`_main_loop_thread_id = None`。

### 5.2 in-flight 行为

- 在主 loop 上跑的协程：`future.cancel()` 触发 `CancelledError` 在协程内冒出，调用方 `future.result()` 也收到 `CancelledError`。
- memory updater 调用方：catch `CancelledError`、log info、返回 `False`，timer 下次重跑（30s 后）。
- subagent executor 调用方：catch `CancelledError`、构造 FAILED 结果返回。
- 不留超时、不等待——开发阶段策略，简单一致。

### 5.3 后续 submit

shutdown 完成后任何调用 `submit_to_main_loop` 直接抛 `RuntimeError("main loop is shutting down")`。调用方自然走异常路径（memory updater 走 fallback `asyncio.run`，但此时 lifespan 已关，进程在退出，不会被实际触发）。

---

## 6. Standard Mode Fallback

`has_main_loop()` 为 False（即 LangGraph Server 进程内、或测试环境无 lifespan）时：

- memory updater 走现有 `asyncio.run` fallback。
- subagent executor 走现有 `asyncio.run` fallback。
- **保留 P1 bug**——根因不消除，但符合"Standard mode 是 advanced profile"的项目定位。

文档化位置：

- `docs/UPGRADE_v2.md` 加一节"Known Limitations: Standard Mode"
- `backend/CLAUDE.md` 在 Runtime Modes 段落补一行
- 根因报告 [`2026-04-28-llm-event-loop-closed-rootcause.md`](./2026-04-28-llm-event-loop-closed-rootcause.md) 加一段说明 Gateway mode 已修、Standard mode 未修

---

## 7. 测试策略

新建文件：`backend/tests/test_main_loop_helper.py`、`backend/tests/test_memory_updater_main_loop.py`、`backend/tests/test_subagent_executor_main_loop.py`

### 7.1 `runtime.main_loop` 单元测试

- `set_main_loop` / `get_main_loop` / `has_main_loop` 基本语义。
- 重复 `set_main_loop` 同一 loop = no-op；不同 loop 抛 RuntimeError。
- 未注入时 `get_main_loop` 抛 RuntimeError、`has_main_loop` 为 False。
- `submit_to_main_loop` 从 worker 线程提交，`future.result()` 拿到协程返回值。
- `submit_to_main_loop` 从主 loop 线程提交抛 `RuntimeError`（fail-fast 防死锁）。
- `shutdown_main_loop` 后 `submit_to_main_loop` 抛 RuntimeError。
- `shutdown_main_loop` 取消在途 future（`CancelledError` 传到调用方）。

### 7.2 端到端：cached httpx client 跨 loop 复用回归测试

**目标：确认根因修复。**

- 模拟两个 loop（旧 ephemeral loop + 主 loop）共享 langchain_openai 的 lru_cache httpx client。
- 旧 loop 发完请求 close。
- 主 loop 上 submit memory update / subagent execute → `model.ainvoke` 不抛 `Event loop is closed`。

实现方式：mock `_get_default_async_httpx_client`，断言所有 LLM 调用观察到的 loop identity 相同。

### 7.3 Memory updater 端到端

- `MemoryUpdater.update_memory()` 在 `set_main_loop` 后路由到主 loop（断言 coro 在主 loop 线程运行）。
- `has_main_loop()` 为 False 时走 fallback `asyncio.run`。
- 主 loop 关停时 memory update 返回 `False`，下次 timer 重试。

### 7.4 Subagent executor 端到端

- `SubagentExecutor.execute()` 在 `set_main_loop` 后不再创建 ephemeral loop（断言 `_isolated_loop_pool` 不存在；可通过 import 时确认 attribute 已删）。
- 关停期间 cancel → 返回 FAILED 结果，`error="Cancelled during shutdown"`。
- 主 loop 线程上调用 `execute()`（反模式）抛 `RuntimeError`（fail-fast 防死锁）。

### 7.5 LLM error 可观测性

- middleware 吞异常时 `logger.critical` 被调用一次。
- audit writer 挂时 enqueue 一条 `llm.error.silenced` 事件。

### 7.6 现有测试回归

- `test_memory_updater.py`、`test_subagent_executor.py`、`test_memory_queue.py` 全绿——契约不变。

---

## 8. 可观测性补丁（Goal G4）

详见 §4.5。补充：

- `llm.error.silenced` 加入 `app/gateway/identity/audit/events.py::KNOWN_ACTIONS` 和 `KEY_CRITICAL_ACTIONS`。
- `app/gateway/identity/audit/redact.py::redact_metadata` 对该 action 不需要特殊处理（payload 不含敏感字段）。

---

## 9. 回滚 / 兼容

- 纯内部重构，无 schema / DB migration / API endpoint 变更。
- `ENABLE_IDENTITY` 行为不受影响。
- 回滚 = git revert 这次的 commit；不影响运行中的 tenant 数据 / audit log / sandbox 文件。
- 现有调用方契约保持不变（`update_memory` / `execute` 返回类型一致）。

---

## 10. Out of Scope

| 项目 | 原因 |
|------|------|
| MCP cache 的 ephemeral loop（[`cache.py:114`](../../backend/packages/harness/deerflow/mcp/cache.py#L114)） | 一次性启动时跑，影响有限；后续单独评估 |
| 升级 langchain_openai 等上游修 #35783 | 候选方案 C，被动等，不在此次范围 |
| 给 ChatOpenAI 传独立 `http_async_client=`（候选方案 B） | 治标不治本；改造后 cached client 已永远绑主 loop，不需要 |
| Standard mode 修同样的 bug | NG1，记录为已知限制 |
| 重构 memory queue / subagent 并发模型 | 不在此次范围 |

---

## 11. 待 brainstorm 阶段未覆盖的开放问题

- 暂无。所有设计问题已通过 Q1-Q5 对齐。

---

## 12. 后续步骤

1. 用户 review 本 design spec。
2. 通过后进 writing-plans 阶段，把改造拆成可执行的实现计划（含测试先行的 TDD 步骤）。
3. 实施 + 验证（Gateway mode 下手动跑 spec 描述的"连续两轮对话"复现场景，确认不再出现 `Event loop is closed`）。
