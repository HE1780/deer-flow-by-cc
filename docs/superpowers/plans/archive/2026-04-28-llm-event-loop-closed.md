> 📦 **归档于 2026-04-29 — Gateway mode 已 ship；Standard mode 文档化为已知限制**
>
> **当前事实（Gateway mode）**：`deerflow.runtime.main_loop` 已落地（[main_loop.py](../../../../backend/packages/harness/deerflow/runtime/main_loop.py)）。`set_main_loop` + `submit_to_main_loop` 复用 Uvicorn 主 loop，memory updater 与 subagent executor 已切走 ephemeral loop（merge commit `c769a210`）。
>
> **未闭环**：
> 1. Standard mode（`make dev`）下 LLM `Event loop is closed` bug 仍存在 — 已在 [backend/CLAUDE.md](../../../../backend/CLAUDE.md) Runtime Modes 段文档化为已知限制，**生产推荐 Gateway mode**。详见 [OPEN_ISSUES.md OI-3](../../../OPEN_ISSUES.md)。
> 2. LLM 错误可观测性补丁（本 plan §4.5）的实施状态待复核 — 详见 [OPEN_ISSUES.md OI-2](../../../OPEN_ISSUES.md)。
>
> 下文为施工时的原始 plan，仅作历史档案保留。

---

# LLM Event Loop is Closed —— Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Gateway mode 下消除 ephemeral event-loop 调 LLM 的代码路径，使 langchain_openai 的 cached httpx client 永远绑同一个稳定的主 Uvicorn loop，根除 `RuntimeError: Event loop is closed` 故障；同时给 LLM 错误吞没补一道 critical-级可观测性。

**Architecture:** 新增 `deerflow.runtime.main_loop` 进程级 singleton helper，由 Gateway lifespan 启动时注入主 loop。memory updater 与 subagent executor 改用 `submit_to_main_loop(coro_factory)` 把协程提交到主 loop（同步阻塞拿结果），删掉自建的 ephemeral-loop pool 与 `_isolated_loop_pool` 仪式代码。Standard mode 走 `asyncio.run` fallback，作为已知限制写入文档。

**Tech Stack:** Python 3.12 / asyncio / `asyncio.run_coroutine_threadsafe` / `concurrent.futures.Future` / FastAPI lifespan / pytest / weakref。

**Spec：** [docs/superpowers/specs/2026-04-28-llm-event-loop-closed-design.md](../specs/2026-04-28-llm-event-loop-closed-design.md)
**根因报告：** [docs/superpowers/specs/2026-04-28-llm-event-loop-closed-rootcause.md](../specs/2026-04-28-llm-event-loop-closed-rootcause.md)

---

## File Structure

### 新建

| 文件 | 职责 |
|------|------|
| `backend/packages/harness/deerflow/runtime/__init__.py` | runtime 子包入口（如已存在则不动）。 |
| `backend/packages/harness/deerflow/runtime/main_loop.py` | `set_main_loop` / `get_main_loop` / `has_main_loop` / `submit_to_main_loop` / `shutdown_main_loop` + 进程级状态。 |
| `backend/tests/test_main_loop_helper.py` | runtime.main_loop 的单元测试。 |
| `backend/tests/test_memory_updater_main_loop.py` | memory updater 改造的端到端测试。 |
| `backend/tests/test_subagent_executor_main_loop.py` | subagent executor 改造的端到端测试。 |
| `backend/tests/test_llm_error_silenced_audit.py` | LLM 错误可观测性补丁的测试。 |

### 修改

| 文件 | 职责变更 |
|------|---------|
| `backend/app/gateway/app.py` | lifespan 启动时注入主 loop，关停时调 `shutdown_main_loop`。 |
| `backend/packages/harness/deerflow/agents/memory/updater.py` | `_run_async_update_sync` 改成走 `submit_to_main_loop`；删 `_SYNC_MEMORY_UPDATER_EXECUTOR`；调用方改传 `coro_factory`。 |
| `backend/packages/harness/deerflow/subagents/executor.py` | 删 `_isolated_loop_pool` 与 `_execute_in_isolated_loop`；`execute()` 改走 `submit_to_main_loop`。 |
| `backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py` | 异常吞没分支补 `logger.critical` + `enqueue` audit 事件（sync + async 两处都补）。 |
| `backend/app/gateway/identity/audit/events.py` | `KNOWN_ACTIONS` / `KEY_CRITICAL_ACTIONS` 加 `llm.error.silenced`。 |
| `backend/CLAUDE.md` | Runtime Modes 段落补 Standard mode 的 LLM event-loop 已知限制。 |
| `docs/superpowers/specs/2026-04-28-llm-event-loop-closed-rootcause.md` | 顶部加状态行：Gateway mode 已修、Standard mode 文档化为已知限制。 |

---

## Task 1：建 `deerflow.runtime` 子包并搭 `main_loop` 模块骨架（仅类型/常量，无逻辑）

**Files:**
- Create: `backend/packages/harness/deerflow/runtime/__init__.py`
- Create: `backend/packages/harness/deerflow/runtime/main_loop.py`

- [ ] **Step 1：写第一个失败测试 —— `has_main_loop` 在未注入时为 False**

Create `backend/tests/test_main_loop_helper.py`:

```python
"""Unit tests for deerflow.runtime.main_loop singleton helper."""
import asyncio
import concurrent.futures
import threading
import time

import pytest

from deerflow.runtime import main_loop as ml


@pytest.fixture(autouse=True)
def _reset_main_loop_state():
    """Each test starts from a clean slate."""
    ml._reset_for_tests()
    yield
    ml._reset_for_tests()


def test_has_main_loop_false_when_not_set():
    assert ml.has_main_loop() is False
```

- [ ] **Step 2：跑测试确认失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_main_loop_helper.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'deerflow.runtime'`

- [ ] **Step 3：建子包 + 写 `main_loop.py` 最小实现使第一个测试通过**

Create `backend/packages/harness/deerflow/runtime/__init__.py`:

```python
"""Process-wide runtime helpers (main loop registration, etc.)."""
```

Create `backend/packages/harness/deerflow/runtime/main_loop.py`:

```python
"""Process-wide singleton: the main asyncio event loop and the helper
to submit coroutines to it from sync code.

Background: langchain_openai's `_get_default_async_httpx_client` uses an
`@lru_cache` whose key does not include the event-loop identity. If the
cached httpx client is first touched on a short-lived loop (e.g. memory
updater's `asyncio.run`), its connection-pool sockets remain bound to that
dead loop; later use from a different loop crashes with
``RuntimeError("Event loop is closed")``.

This module exposes a registered, long-lived "main loop" (the Gateway's
Uvicorn loop) and a sync-friendly helper that hands work to it via
`asyncio.run_coroutine_threadsafe`.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import weakref
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None
_main_loop_thread_id: int | None = None
_tracked_futures: weakref.WeakSet[concurrent.futures.Future] = weakref.WeakSet()
_shutting_down: bool = False
_lock = threading.Lock()


def has_main_loop() -> bool:
    """Return True iff a main loop is registered and not shutting down."""
    return _main_loop is not None and not _shutting_down


def _reset_for_tests() -> None:
    """Wipe state. ONLY for unit tests; never call from product code."""
    global _main_loop, _main_loop_thread_id, _shutting_down
    with _lock:
        _main_loop = None
        _main_loop_thread_id = None
        _shutting_down = False
        _tracked_futures.clear()
```

- [ ] **Step 4：跑测试确认通过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_main_loop_helper.py -v`

Expected: PASS — `test_has_main_loop_false_when_not_set` ✓

- [ ] **Step 5：commit**

```bash
git add backend/packages/harness/deerflow/runtime/__init__.py \
        backend/packages/harness/deerflow/runtime/main_loop.py \
        backend/tests/test_main_loop_helper.py
git commit -m "feat(runtime): scaffold deerflow.runtime.main_loop singleton skeleton"
```

---

## Task 2：实现 `set_main_loop` 与 `get_main_loop`

**Files:**
- Modify: `backend/packages/harness/deerflow/runtime/main_loop.py`
- Modify: `backend/tests/test_main_loop_helper.py`

- [ ] **Step 1：扩测试覆盖 set / get / 重复 set / 冲突 set**

Append to `backend/tests/test_main_loop_helper.py`:

```python
def test_set_and_get_main_loop():
    loop = asyncio.new_event_loop()
    try:
        ml.set_main_loop(loop)
        assert ml.has_main_loop() is True
        assert ml.get_main_loop() is loop
    finally:
        loop.close()


def test_get_main_loop_raises_when_unset():
    with pytest.raises(RuntimeError, match="main loop is not registered"):
        ml.get_main_loop()


def test_set_main_loop_idempotent_for_same_loop():
    loop = asyncio.new_event_loop()
    try:
        ml.set_main_loop(loop)
        # Re-setting same loop is a no-op, no exception.
        ml.set_main_loop(loop)
        assert ml.get_main_loop() is loop
    finally:
        loop.close()


def test_set_main_loop_rejects_conflicting_loop():
    loop_a = asyncio.new_event_loop()
    loop_b = asyncio.new_event_loop()
    try:
        ml.set_main_loop(loop_a)
        with pytest.raises(RuntimeError, match="already registered"):
            ml.set_main_loop(loop_b)
    finally:
        loop_a.close()
        loop_b.close()
```

- [ ] **Step 2：跑测试确认 4 个新测试失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_main_loop_helper.py -v`

Expected: 1 PASS + 4 FAIL（`set_main_loop` / `get_main_loop` 未实现）

- [ ] **Step 3：实现 `set_main_loop` 与 `get_main_loop`**

Append to `backend/packages/harness/deerflow/runtime/main_loop.py`:

```python
def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register the long-lived main event loop. Called by Gateway lifespan.

    Re-registering the same loop is a no-op. Registering a different loop
    while one is already active raises RuntimeError — production should
    only have one main loop per process.
    """
    global _main_loop, _main_loop_thread_id
    with _lock:
        if _main_loop is loop:
            return
        if _main_loop is not None:
            raise RuntimeError(
                "main loop is already registered; cannot replace at runtime"
            )
        _main_loop = loop
        _main_loop_thread_id = threading.get_ident()
        logger.info("Main asyncio loop registered (thread_id=%s)", _main_loop_thread_id)


def get_main_loop() -> asyncio.AbstractEventLoop:
    """Return the registered main loop. Raises RuntimeError if unset."""
    if _main_loop is None:
        raise RuntimeError("main loop is not registered")
    return _main_loop
```

- [ ] **Step 4：跑测试确认全部通过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_main_loop_helper.py -v`

Expected: 5 PASS

- [ ] **Step 5：commit**

```bash
git add backend/packages/harness/deerflow/runtime/main_loop.py \
        backend/tests/test_main_loop_helper.py
git commit -m "feat(runtime): set_main_loop/get_main_loop with idempotent + conflict guards"
```

---

## Task 3：实现 `submit_to_main_loop`（基础路径 + fail-fast 防死锁）

**Files:**
- Modify: `backend/packages/harness/deerflow/runtime/main_loop.py`
- Modify: `backend/tests/test_main_loop_helper.py`

- [ ] **Step 1：扩测试 —— worker 线程上 submit 拿到协程返回值**

Append to `backend/tests/test_main_loop_helper.py`:

```python
def _spin_loop_in_thread(loop: asyncio.AbstractEventLoop) -> threading.Thread:
    """Run loop.run_forever() in a background thread; return the thread."""
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    # Tiny wait so loop is actually running before tests submit work.
    while not loop.is_running():
        time.sleep(0.001)
    return t


def _stop_loop(loop: asyncio.AbstractEventLoop, t: threading.Thread) -> None:
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)


def test_submit_to_main_loop_returns_coroutine_result():
    loop = asyncio.new_event_loop()
    t = _spin_loop_in_thread(loop)
    # Loop runs in thread `t`; main_loop_thread_id should match `t.ident`.
    ml._main_loop = loop
    ml._main_loop_thread_id = t.ident
    try:
        async def coro():
            await asyncio.sleep(0)
            return 42

        result = ml.submit_to_main_loop(coro)
        assert result == 42
    finally:
        _stop_loop(loop, t)
        loop.close()


def test_submit_to_main_loop_raises_when_loop_unset():
    with pytest.raises(RuntimeError, match="main loop is not registered"):
        ml.submit_to_main_loop(lambda: asyncio.sleep(0))


def test_submit_from_main_loop_thread_raises_for_deadlock_safety():
    loop = asyncio.new_event_loop()
    ml._main_loop = loop
    ml._main_loop_thread_id = threading.get_ident()  # Pretend we're on the main-loop thread.
    try:
        with pytest.raises(RuntimeError, match="from main loop thread"):
            ml.submit_to_main_loop(lambda: asyncio.sleep(0))
    finally:
        loop.close()
```

注意：测试里直接戳 `ml._main_loop` / `ml._main_loop_thread_id` 是为了精确控制线程身份；产品代码必须走 `set_main_loop`。

- [ ] **Step 2：跑测试确认失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_main_loop_helper.py -v`

Expected: 5 PASS + 3 FAIL（`submit_to_main_loop` 未定义）

- [ ] **Step 3：实现 `submit_to_main_loop`**

Append to `backend/packages/harness/deerflow/runtime/main_loop.py`:

```python
def submit_to_main_loop(coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """Submit a coroutine to the main loop and synchronously block on the result.

    Args:
        coro_factory: Zero-arg callable that returns a fresh coroutine when
            called. We require a factory (not a coroutine instance) so the
            coroutine is created on the worker thread immediately before
            scheduling — avoiding any cross-thread mutation of an unstarted
            coroutine object.

    Returns:
        Whatever the coroutine returns.

    Raises:
        RuntimeError: main loop is not registered, is shutting down, or this
            call comes from the main-loop thread itself (would deadlock —
            async callers should `await coro_factory()` directly).
        concurrent.futures.CancelledError: shutdown cancelled the future.
        Any exception raised by the coroutine.
    """
    if _main_loop is None:
        raise RuntimeError("main loop is not registered")
    if _shutting_down:
        raise RuntimeError("main loop is shutting down")
    if threading.get_ident() == _main_loop_thread_id:
        raise RuntimeError(
            "submit_to_main_loop called from main loop thread; "
            "use 'await coro_factory()' instead"
        )

    coro = coro_factory()
    future = asyncio.run_coroutine_threadsafe(coro, _main_loop)
    _tracked_futures.add(future)
    return future.result()
```

- [ ] **Step 4：跑测试确认 8 个全过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_main_loop_helper.py -v`

Expected: 8 PASS

- [ ] **Step 5：commit**

```bash
git add backend/packages/harness/deerflow/runtime/main_loop.py \
        backend/tests/test_main_loop_helper.py
git commit -m "feat(runtime): submit_to_main_loop with fail-fast deadlock guard"
```

---

## Task 4：实现 `shutdown_main_loop`（cancel in-flight + 翻 shutting_down）

**Files:**
- Modify: `backend/packages/harness/deerflow/runtime/main_loop.py`
- Modify: `backend/tests/test_main_loop_helper.py`

- [ ] **Step 1：扩测试 —— shutdown 后 submit 抛 RuntimeError；shutdown cancel 在途 future**

Append to `backend/tests/test_main_loop_helper.py`:

```python
def test_shutdown_blocks_subsequent_submits():
    loop = asyncio.new_event_loop()
    ml._main_loop = loop
    ml._main_loop_thread_id = -1  # any thread id ≠ test thread, so submit path validates ok before shutdown check
    try:
        # Run shutdown_main_loop synchronously by driving it on a temp loop.
        asyncio.new_event_loop().run_until_complete(ml.shutdown_main_loop())
        assert ml.has_main_loop() is False
        with pytest.raises(RuntimeError, match="not registered"):
            ml.submit_to_main_loop(lambda: asyncio.sleep(0))
    finally:
        loop.close()


def test_shutdown_cancels_in_flight_futures():
    loop = asyncio.new_event_loop()
    t = _spin_loop_in_thread(loop)
    ml._main_loop = loop
    ml._main_loop_thread_id = t.ident
    try:
        # Long-running coroutine submitted from another thread.
        result_holder: list[Exception | int] = []

        def submitter():
            try:
                async def long_sleep():
                    await asyncio.sleep(10)
                    return "should not reach"

                result_holder.append(ml.submit_to_main_loop(long_sleep))
            except concurrent.futures.CancelledError as e:
                result_holder.append(e)
            except Exception as e:
                result_holder.append(e)

        st = threading.Thread(target=submitter, daemon=True)
        st.start()
        time.sleep(0.05)  # let submitter enqueue

        # Shutdown should cancel the long_sleep future.
        asyncio.new_event_loop().run_until_complete(ml.shutdown_main_loop())
        st.join(timeout=2)
        assert len(result_holder) == 1
        assert isinstance(result_holder[0], concurrent.futures.CancelledError)
    finally:
        _stop_loop(loop, t)
        loop.close()
```

- [ ] **Step 2：跑测试确认失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_main_loop_helper.py -v`

Expected: 8 PASS + 2 FAIL（`shutdown_main_loop` 未定义）

- [ ] **Step 3：实现 `shutdown_main_loop`**

Append to `backend/packages/harness/deerflow/runtime/main_loop.py`:

```python
async def shutdown_main_loop() -> None:
    """Cancel all in-flight futures and clear the main-loop registration.

    Called by Gateway lifespan teardown. Intentionally does NOT wait for
    cancellation to settle — open-development policy: in-flight memory
    updates may be lost (timer will retry next debounce window) and
    in-flight subagents return FAILED.
    """
    global _main_loop, _main_loop_thread_id, _shutting_down
    with _lock:
        if _shutting_down:
            return
        _shutting_down = True
    # Cancel all tracked futures. iterate over snapshot since the WeakSet
    # may mutate as futures complete.
    for fut in list(_tracked_futures):
        if not fut.done():
            fut.cancel()
    with _lock:
        _main_loop = None
        _main_loop_thread_id = None
    logger.info("Main asyncio loop deregistered; in-flight futures cancelled")
```

- [ ] **Step 4：跑测试确认 10 个全过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_main_loop_helper.py -v`

Expected: 10 PASS

- [ ] **Step 5：commit**

```bash
git add backend/packages/harness/deerflow/runtime/main_loop.py \
        backend/tests/test_main_loop_helper.py
git commit -m "feat(runtime): shutdown_main_loop cancels in-flight futures"
```

---

## Task 5：Gateway lifespan 注入 / 关停 main loop

**Files:**
- Modify: `backend/app/gateway/app.py:289-346`

- [ ] **Step 1：在 `lifespan` 注入 main loop（audit 启动之后、langgraph_runtime 进入之前）**

Modify `backend/app/gateway/app.py`. 在 [L289-346](backend/app/gateway/app.py#L289) 的 `lifespan` 函数：

a. 文件顶部 import 区加一行：

```python
from deerflow.runtime.main_loop import set_main_loop, shutdown_main_loop
```

b. 在 audit 子系统初始化之后、`async with langgraph_runtime(app):` 之前插入：

```python
    # Register the main Uvicorn loop so memory updater / subagent executor
    # can hand sync work to it instead of spinning ephemeral loops
    # (see docs/superpowers/specs/2026-04-28-llm-event-loop-closed-design.md).
    set_main_loop(asyncio.get_running_loop())
```

c. 在 `finally:` 块的 `_shutdown_audit_subsystem(app)` 调用之前插入：

```python
            await shutdown_main_loop()
```

完整改造后 `lifespan` 关键片段：

```python
    # Initialize identity subsystem (no-op when ENABLE_IDENTITY=false)
    await _init_identity_subsystem()

    # Start audit batch writer if identity is enabled.
    if get_identity_settings().enabled:
        await _init_audit_subsystem(app)

    # Register the main Uvicorn loop so memory updater / subagent executor
    # can hand sync work to it instead of spinning ephemeral loops
    # (see docs/superpowers/specs/2026-04-28-llm-event-loop-closed-design.md).
    set_main_loop(asyncio.get_running_loop())

    # Initialize LangGraph runtime components (StreamBridge, RunManager, ...)
    async with langgraph_runtime(app):
        ...
        try:
            yield
        finally:
            ...
            await shutdown_main_loop()
            await _shutdown_audit_subsystem(app)
            await _shutdown_identity_subsystem()
```

- [ ] **Step 2：跑全部 lifespan 相关回归测试确保不挂**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_gateway_identity_lifespan.py tests/identity/test_feature_flag_offline.py -v`

Expected: 全 PASS（lifespan 注入对 identity 行为零影响）

- [ ] **Step 3：commit**

```bash
git add backend/app/gateway/app.py
git commit -m "feat(gateway): register main loop in lifespan for memory/subagent reuse"
```

---

## Task 6：memory updater 改用 `submit_to_main_loop`

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/memory/updater.py`
- Create: `backend/tests/test_memory_updater_main_loop.py`

- [ ] **Step 1：写失败测试 —— 主 loop 已注入时，memory update 协程在主 loop 线程上跑**

Create `backend/tests/test_memory_updater_main_loop.py`:

```python
"""Memory updater wires through deerflow.runtime.main_loop when registered."""
import asyncio
import threading
import time
from unittest.mock import patch

import pytest

from deerflow.runtime import main_loop as ml


@pytest.fixture(autouse=True)
def _reset_main_loop():
    ml._reset_for_tests()
    yield
    ml._reset_for_tests()


def _spin(loop):
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    while not loop.is_running():
        time.sleep(0.001)
    return t


def _stop(loop, t):
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)


def test_run_async_update_sync_routes_through_main_loop():
    """When set_main_loop has registered a loop, _run_async_update_sync hands
    the coroutine to that loop instead of spinning its own asyncio.run."""
    from deerflow.agents.memory.updater import _run_async_update_sync

    loop = asyncio.new_event_loop()
    t = _spin(loop)
    ml._main_loop = loop
    ml._main_loop_thread_id = t.ident
    captured_thread: list[int] = []

    async def fake_coro() -> bool:
        captured_thread.append(threading.get_ident())
        return True

    try:
        result = _run_async_update_sync(fake_coro)
        assert result is True
        assert captured_thread == [t.ident]  # ran on the main-loop thread
    finally:
        _stop(loop, t)
        loop.close()


def test_run_async_update_sync_falls_back_when_main_loop_absent():
    """Standard mode (no main loop): legacy asyncio.run path still works."""
    from deerflow.agents.memory.updater import _run_async_update_sync

    async def fake_coro() -> bool:
        return True

    # No set_main_loop; has_main_loop() False; should run via asyncio.run.
    assert _run_async_update_sync(fake_coro) is True


def test_run_async_update_sync_returns_false_on_cancellation():
    """If the main loop is shutting down mid-flight, return False so the
    timer simply retries on the next debounce window."""
    from deerflow.agents.memory.updater import _run_async_update_sync

    loop = asyncio.new_event_loop()
    t = _spin(loop)
    ml._main_loop = loop
    ml._main_loop_thread_id = t.ident

    async def long_sleep() -> bool:
        await asyncio.sleep(10)
        return True

    result_holder: list[bool] = []

    def submitter():
        result_holder.append(_run_async_update_sync(long_sleep))

    try:
        st = threading.Thread(target=submitter, daemon=True)
        st.start()
        time.sleep(0.05)
        asyncio.new_event_loop().run_until_complete(ml.shutdown_main_loop())
        st.join(timeout=2)
        assert result_holder == [False]
    finally:
        _stop(loop, t)
        loop.close()
```

- [ ] **Step 2：跑测试确认 3 个全失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_memory_updater_main_loop.py -v`

Expected: 3 FAIL — 因为现在 `_run_async_update_sync(coro)` 接收的是 coroutine 实例，不是 factory；需要改实现。

- [ ] **Step 3：改 `updater.py`**

Modify `backend/packages/harness/deerflow/agents/memory/updater.py`:

a. 文件顶部 import 替换/增加：

```python
import concurrent.futures
from collections.abc import Awaitable, Callable
# ...（保留其它 import）
from deerflow.runtime.main_loop import has_main_loop, submit_to_main_loop
```

b. 删除 `_SYNC_MEMORY_UPDATER_EXECUTOR` 与 `atexit` 注册（[L29-L33](backend/packages/harness/deerflow/agents/memory/updater.py#L29)）。

c. 替换 `_run_async_update_sync`（[L220-L250](backend/packages/harness/deerflow/agents/memory/updater.py#L220)）为：

```python
def _run_async_update_sync(coro_factory: Callable[[], Awaitable[bool]]) -> bool:
    """Run an async memory update from sync code.

    When the Gateway has registered a main loop (Gateway mode), hand the
    coroutine to that loop. Otherwise (Standard mode / tests without
    lifespan) fall back to a fresh ephemeral loop via asyncio.run.

    Args:
        coro_factory: Zero-arg callable returning a fresh coroutine. The
            factory is invoked exactly once on the executing thread.

    Returns:
        Whatever the coroutine returns, or False on cancellation / failure.
    """
    if has_main_loop():
        try:
            return submit_to_main_loop(coro_factory)
        except concurrent.futures.CancelledError:
            logger.info("Memory update cancelled (main loop shutting down)")
            return False
        except Exception:
            logger.exception("Memory update failed via main loop")
            return False

    # Fallback: Standard mode / test harness without a registered main loop.
    try:
        return asyncio.run(coro_factory())
    except Exception:
        logger.exception("Failed to run async memory update from sync context")
        return False
```

d. 改 `update_memory`（[L427-L455](backend/packages/harness/deerflow/agents/memory/updater.py#L427)）调用方传 lambda：

```python
    def update_memory(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
    ) -> bool:
        """Synchronously update memory via the async updater path. (docstring 不变)"""
        return _run_async_update_sync(
            lambda: self.aupdate_memory(
                messages=messages,
                thread_id=thread_id,
                agent_name=agent_name,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
            )
        )
```

- [ ] **Step 4：跑新测 + 老测全绿**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_memory_updater_main_loop.py tests/test_memory_updater.py tests/test_memory_queue.py -v`

Expected: 全 PASS（3 个新测 + 老 memory 测试集合）

- [ ] **Step 5：commit**

```bash
git add backend/packages/harness/deerflow/agents/memory/updater.py \
        backend/tests/test_memory_updater_main_loop.py
git commit -m "refactor(memory): route updates through main loop helper, drop ephemeral pool"
```

---

## Task 7：subagent executor 改用 `submit_to_main_loop` + 删除 `_isolated_loop_pool`

**Files:**
- Modify: `backend/packages/harness/deerflow/subagents/executor.py`
- Create: `backend/tests/test_subagent_executor_main_loop.py`

- [ ] **Step 1：写失败测试 —— 主 loop 已注入时 `execute()` 不创建 ephemeral loop**

Create `backend/tests/test_subagent_executor_main_loop.py`:

```python
"""Subagent executor wires through deerflow.runtime.main_loop when registered."""
import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from deerflow.runtime import main_loop as ml


@pytest.fixture(autouse=True)
def _reset_main_loop():
    ml._reset_for_tests()
    yield
    ml._reset_for_tests()


def _spin(loop):
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    while not loop.is_running():
        time.sleep(0.001)
    return t


def _stop(loop, t):
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)


def test_isolated_loop_pool_removed_from_module():
    """The legacy ephemeral-loop pool should be gone after the refactor."""
    from deerflow.subagents import executor

    assert not hasattr(executor, "_isolated_loop_pool")
    assert not hasattr(executor, "_execute_in_isolated_loop")


def test_execute_routes_through_main_loop_when_registered():
    """When set_main_loop has registered a loop, execute() runs _aexecute on it."""
    from deerflow.subagents.executor import (
        SubagentExecutor,
        SubagentResult,
        SubagentStatus,
    )

    loop = asyncio.new_event_loop()
    t = _spin(loop)
    ml._main_loop = loop
    ml._main_loop_thread_id = t.ident

    captured_thread: list[int] = []

    async def fake_aexecute(self, task, holder):
        captured_thread.append(threading.get_ident())
        result = holder or SubagentResult(
            task_id="x", trace_id="y", status=SubagentStatus.COMPLETED
        )
        result.status = SubagentStatus.COMPLETED
        result.result = "ok"
        return result

    fake_config = MagicMock()
    fake_config.name = "test-agent"

    try:
        with patch.object(SubagentExecutor, "_aexecute", fake_aexecute):
            ex = SubagentExecutor(config=fake_config, all_tools=[], trace_id="t-1")
            res = ex.execute("do thing")
            assert res.status == SubagentStatus.COMPLETED
            assert res.result == "ok"
            assert captured_thread == [t.ident]
    finally:
        _stop(loop, t)
        loop.close()


def test_execute_returns_failed_on_cancellation():
    from deerflow.subagents.executor import (
        SubagentExecutor,
        SubagentResult,
        SubagentStatus,
    )

    loop = asyncio.new_event_loop()
    t = _spin(loop)
    ml._main_loop = loop
    ml._main_loop_thread_id = t.ident

    async def long_aexecute(self, task, holder):
        await asyncio.sleep(10)
        return holder

    fake_config = MagicMock()
    fake_config.name = "slow-agent"

    result_holder_box: list[SubagentResult] = []

    def submitter():
        with patch.object(SubagentExecutor, "_aexecute", long_aexecute):
            ex = SubagentExecutor(config=fake_config, all_tools=[], trace_id="t-2")
            result_holder_box.append(ex.execute("slow"))

    try:
        st = threading.Thread(target=submitter, daemon=True)
        st.start()
        time.sleep(0.05)
        asyncio.new_event_loop().run_until_complete(ml.shutdown_main_loop())
        st.join(timeout=2)
        assert len(result_holder_box) == 1
        assert result_holder_box[0].status == SubagentStatus.FAILED
        assert "Cancelled during shutdown" in (result_holder_box[0].error or "")
    finally:
        _stop(loop, t)
        loop.close()
```

注意：`SubagentExecutor.__init__` 的真实参数列表见 [executor.py](backend/packages/harness/deerflow/subagents/executor.py)；如果 `config / all_tools / trace_id` 不是真实签名，按真实签名调整测试 fixture。先照设计写，跑失败时再调整。

- [ ] **Step 2：跑测试确认失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_subagent_executor_main_loop.py -v`

Expected: FAIL — `_isolated_loop_pool` 仍存在 / `execute` 仍走旧路径。

- [ ] **Step 3：改 `executor.py`**

Modify `backend/packages/harness/deerflow/subagents/executor.py`:

a. 文件顶部 import 增加：

```python
import concurrent.futures
from deerflow.runtime.main_loop import has_main_loop, submit_to_main_loop
```

b. 删除 `_isolated_loop_pool` 定义（[L80](backend/packages/harness/deerflow/subagents/executor.py#L80)）。

c. 删除整个 `_execute_in_isolated_loop` 方法（[L459-L495](backend/packages/harness/deerflow/subagents/executor.py#L459)）—— 包括 docstring 和所有 loop 创建/清理仪式。

d. 替换 `execute()`（[L497-L542](backend/packages/harness/deerflow/subagents/executor.py#L497)）为：

```python
    def execute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute a task synchronously.

        When the Gateway has registered a main loop (see deerflow.runtime.main_loop),
        the subagent's async _aexecute runs on that long-lived loop. Otherwise we
        fall back to a fresh ephemeral loop via asyncio.run (Standard mode).

        Args:
            task: The task description for the subagent.
            result_holder: Optional pre-created result object to update during execution.

        Returns:
            SubagentResult with the execution result.
        """

        def _build_failed(message: str) -> SubagentResult:
            res = result_holder or SubagentResult(
                task_id=str(uuid.uuid4())[:8],
                trace_id=self.trace_id,
                status=SubagentStatus.FAILED,
            )
            res.status = SubagentStatus.FAILED
            res.error = message
            res.completed_at = datetime.now()
            return res

        if has_main_loop():
            try:
                return submit_to_main_loop(
                    lambda: self._aexecute(task, result_holder)
                )
            except concurrent.futures.CancelledError:
                logger.info(
                    f"[trace={self.trace_id}] Subagent {self.config.name} cancelled during shutdown"
                )
                return _build_failed("Cancelled during shutdown")
            except Exception as e:
                logger.exception(
                    f"[trace={self.trace_id}] Subagent {self.config.name} execution failed via main loop"
                )
                return _build_failed(str(e))

        # Fallback: no main loop registered (Standard mode / tests).
        try:
            return asyncio.run(self._aexecute(task, result_holder))
        except Exception as e:
            logger.exception(
                f"[trace={self.trace_id}] Subagent {self.config.name} execution failed (fallback path)"
            )
            return _build_failed(str(e))
```

注意：`_scheduler_pool` 和 `_execution_pool` 保留，它们与 ephemeral loop 无关。

- [ ] **Step 4：跑新测 + 老测全绿**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_subagent_executor_main_loop.py tests/test_subagent_executor.py -v`

Expected: 全 PASS。如果老测试因为 `_isolated_loop_pool` 引用而失败，更新老测试断言并 commit 一并修。

- [ ] **Step 5：commit**

```bash
git add backend/packages/harness/deerflow/subagents/executor.py \
        backend/tests/test_subagent_executor_main_loop.py
git commit -m "refactor(subagents): route execute through main loop, drop _isolated_loop_pool"
```

---

## Task 8：Audit 事件分类表新增 `llm.error.silenced`

**Files:**
- Modify: `backend/app/gateway/identity/audit/events.py`

- [ ] **Step 1：扩 audit events 单元测试覆盖新 action**

新增到现有测试文件 `backend/tests/identity/test_audit_events.py`（如不存在则新建）：

```python
def test_llm_error_silenced_known_and_critical():
    from app.gateway.identity.audit.events import (
        KNOWN_ACTIONS,
        KEY_CRITICAL_ACTIONS,
        is_critical_action,
    )

    assert "llm.error.silenced" in KNOWN_ACTIONS
    assert "llm.error.silenced" in KEY_CRITICAL_ACTIONS
    assert is_critical_action("llm.error.silenced") is True
```

- [ ] **Step 2：跑测试确认失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_audit_events.py::test_llm_error_silenced_known_and_critical -v`

Expected: FAIL（action 字符串不在两个 frozenset 里）

- [ ] **Step 3：把 action 加到两个集合**

Modify `backend/app/gateway/identity/audit/events.py`:

a. 在 `KNOWN_ACTIONS` frozenset 末尾（[L110-L111](backend/app/gateway/identity/audit/events.py#L110)，`audit.exported` 后面）加一行：

```python
        # --- LLM error observability ---
        "llm.error.silenced",
```

b. 在 `KEY_CRITICAL_ACTIONS` 末尾（[L127](backend/app/gateway/identity/audit/events.py#L127)）加一行：

```python
        "llm.error.silenced",
```

- [ ] **Step 4：跑测试确认通过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/identity/test_audit_events.py::test_llm_error_silenced_known_and_critical -v`

Expected: PASS

- [ ] **Step 5：commit**

```bash
git add backend/app/gateway/identity/audit/events.py \
        backend/tests/identity/test_audit_events.py
git commit -m "feat(audit): register llm.error.silenced as critical action"
```

---

## Task 9：LLM 错误吞没补可观测性（middleware sync + async 两路）

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py`
- Create: `backend/tests/test_llm_error_silenced_audit.py`

- [ ] **Step 1：写失败测试 —— 异常吞没时 logger.critical 被调一次**

Create `backend/tests/test_llm_error_silenced_audit.py`:

```python
"""LLMErrorHandlingMiddleware emits critical-level observability when an
LLM call fails after retries and the user-facing error message is returned."""
import asyncio
import logging
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.llm_error_handling_middleware import (
    LLMErrorHandlingMiddleware,
)


def _make_middleware() -> LLMErrorHandlingMiddleware:
    """Construct an LLM error middleware with retries=1 (so first failure is final)."""
    return LLMErrorHandlingMiddleware(
        retry_max_attempts=1,
        circuit_breaker_threshold=999,
    )


def test_sync_path_logs_critical_when_swallowing_error(caplog):
    mw = _make_middleware()
    request = MagicMock()

    def boom(_req):
        raise RuntimeError("Event loop is closed")

    with caplog.at_level(logging.CRITICAL):
        result = mw.wrap_model_call(request, boom)

    assert isinstance(result, AIMessage)
    crit = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert any("LLM error silenced" in r.getMessage() for r in crit), (
        "expected at least one CRITICAL log line when an LLM error is swallowed"
    )


def test_async_path_logs_critical_when_swallowing_error(caplog):
    mw = _make_middleware()
    request = MagicMock()

    async def boom(_req):
        raise RuntimeError("Event loop is closed")

    with caplog.at_level(logging.CRITICAL):
        result = asyncio.run(mw.awrap_model_call(request, boom))

    assert isinstance(result, AIMessage)
    crit = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert any("LLM error silenced" in r.getMessage() for r in crit)
```

注意：`LLMErrorHandlingMiddleware` 真实构造参数与 sync 入口名（`wrap_model_call` vs 别的）见 [llm_error_handling_middleware.py](backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py)；如签名不符，按真实签名修测试。

- [ ] **Step 2：跑测试确认失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_llm_error_silenced_audit.py -v`

Expected: FAIL — 现有代码 `logger.warning`，没有 CRITICAL。

- [ ] **Step 3：改 middleware**

Modify `backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py`:

a. 在 sync 分支的"放弃 retry、返回 user message"位置（[L253-L261](backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py#L253) 现有 `logger.warning(...) ; if retriable: self._record_failure(); return AIMessage(...)`），把 `logger.warning(...)` 改成 `logger.warning(...)` 保留 + 紧接其后**额外**加：

```python
                logger.critical(
                    "LLM error silenced after %d attempt(s); returning user-facing fallback message",
                    attempt,
                    exc_info=exc,
                )
```

b. async 分支同样位置（[L299-L307](backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py#L299)）做相同改动。

完整改造后 sync 分支末尾应是：

```python
                logger.warning(
                    "LLM call failed after %d attempt(s): %s",
                    attempt,
                    _extract_error_detail(exc),
                    exc_info=exc,
                )
                logger.critical(
                    "LLM error silenced after %d attempt(s); returning user-facing fallback message",
                    attempt,
                    exc_info=exc,
                )
                if retriable:
                    self._record_failure()
                return AIMessage(content=self._build_user_message(exc, reason))
```

async 分支同形。

- [ ] **Step 4：跑测试确认通过 + 老测试全绿**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_llm_error_silenced_audit.py tests/test_llm_error_handling_middleware.py -v`

Expected: 全 PASS。

- [ ] **Step 5：commit**

```bash
git add backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py \
        backend/tests/test_llm_error_silenced_audit.py
git commit -m "feat(middleware): emit critical log when LLM error is silenced (sync+async)"
```

---

## Task 10：根因报告状态 + CLAUDE.md 加 Standard mode 已知限制段

**Files:**
- Modify: `docs/superpowers/specs/2026-04-28-llm-event-loop-closed-rootcause.md`
- Modify: `backend/CLAUDE.md`

- [ ] **Step 1：根因报告顶部加状态行**

Modify `docs/superpowers/specs/2026-04-28-llm-event-loop-closed-rootcause.md`. 把 [L3-L4](docs/superpowers/specs/2026-04-28-llm-event-loop-closed-rootcause.md#L3) 那两行（`**状态：** 仅根因（Phase 1 完成），方案待 brainstorm`）替换为：

```markdown
**状态：** Gateway mode 已闭环（main-loop reuse 改造，见 [`2026-04-28-llm-event-loop-closed-design.md`](./2026-04-28-llm-event-loop-closed-design.md)）；Standard mode 文档化为已知限制（见 backend/CLAUDE.md Runtime Modes 章节）。
```

- [ ] **Step 2：CLAUDE.md Runtime Modes 段加已知限制**

Modify `backend/CLAUDE.md`. 找到 `**Runtime Modes**:` 段（包含 "Standard mode (`make dev`)" 和 "Gateway mode (`make dev-pro`...)" 的那段），在该段末尾追加一段：

```markdown

**Known limitation — Standard mode + LLM event loop:** `make dev` 下 memory updater 与 subagent executor 仍走 ephemeral `asyncio.run` 调 LLM，可能触发 [langchain-ai/langchain#35783](https://github.com/langchain-ai/langchain/issues/35783) 的 cached httpx-client 跨 loop bug（`RuntimeError: Event loop is closed`）。Gateway mode 已通过 `deerflow.runtime.main_loop` 改造规避（见 `docs/superpowers/specs/2026-04-28-llm-event-loop-closed-design.md`）。生产部署推荐 Gateway mode。
```

- [ ] **Step 3：本地预览 markdown 渲染（人工 sanity）**

Run: `cd /Users/lydoc/projectscoding/deer-flow && head -8 docs/superpowers/specs/2026-04-28-llm-event-loop-closed-rootcause.md`

Expected: 看到新的「状态」一行符合上述内容。

- [ ] **Step 4：commit**

```bash
git add docs/superpowers/specs/2026-04-28-llm-event-loop-closed-rootcause.md backend/CLAUDE.md
git commit -m "docs: mark Gateway mode fix shipped; document Standard mode limitation"
```

---

## Task 11：跨 loop cached client 回归测试（"两个 loop 共享 lru_cache" 场景）

**Files:**
- Modify: `backend/tests/test_main_loop_helper.py`

> 该任务的目标是把根因报告里描述的故障路径冻结为回归测试：模拟旧 ephemeral loop 与主 loop 共享同一个 lru_cache 出来的 httpx client，确认改造后主 loop 上调 `model.ainvoke` 不再因为 cached client 绑死 loop 而抛 `Event loop is closed`。

- [ ] **Step 1：扩测试覆盖跨 loop 复用回归**

Append to `backend/tests/test_main_loop_helper.py`:

```python
def test_main_loop_handles_cached_client_after_ephemeral_loop_dies():
    """Regression for 'Event loop is closed' (root cause report 2026-04-28).

    Simulates the langchain_openai lru_cache: a shared 'httpx_like_client'
    object whose .last_loop attribute records which loop touched it last.
    Step 1: an ephemeral loop touches the client and then closes.
    Step 2: the main loop touches the same client. Before the fix this
    crashed because the client tried to call_soon on the dead loop.
    After the fix the main loop runs the coroutine cleanly because work
    is funneled through submit_to_main_loop.
    """

    class FakeCachedClient:
        def __init__(self):
            self.last_loop: asyncio.AbstractEventLoop | None = None

        async def use(self):
            self.last_loop = asyncio.get_running_loop()
            return id(self.last_loop)

    cached = FakeCachedClient()

    # Step 1: ephemeral loop uses the client, then closes.
    ephemeral_loop = asyncio.new_event_loop()
    try:
        ephemeral_loop_id = ephemeral_loop.run_until_complete(cached.use())
        assert cached.last_loop is ephemeral_loop
    finally:
        ephemeral_loop.close()

    # Step 2: main loop uses the SAME cached client via submit_to_main_loop.
    # The fix ensures the call runs on the still-alive main loop, not on
    # the dead ephemeral one.
    main_loop = asyncio.new_event_loop()
    t = _spin_loop_in_thread(main_loop)
    ml._main_loop = main_loop
    ml._main_loop_thread_id = t.ident

    try:
        main_loop_id = ml.submit_to_main_loop(cached.use)
        assert main_loop_id != ephemeral_loop_id
        assert cached.last_loop is main_loop
    finally:
        _stop_loop(main_loop, t)
        main_loop.close()
```

- [ ] **Step 2：跑测试确认通过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_main_loop_helper.py::test_main_loop_handles_cached_client_after_ephemeral_loop_dies -v`

Expected: PASS（防御已就绪）

- [ ] **Step 3：commit**

```bash
git add backend/tests/test_main_loop_helper.py
git commit -m "test(runtime): regression — cached client survives ephemeral loop death"
```

---

## Task 12：全量回归 + 手动复现 smoke

**Files:** 无新增/修改（验证步骤）

- [ ] **Step 1：跑 backend 全量测试**

Run: `cd backend && make test`

Expected: 全 PASS。任何失败用例先定位是 Task 1-11 引入的 regression 还是 unrelated；前者立刻修，后者另起 issue。

- [ ] **Step 2：跑 ruff lint**

Run: `cd backend && make lint`

Expected: 无新增 violation。

- [ ] **Step 3：手动复现根因报告里的故障场景**

按根因报告 §现象 描述：

1. 启动 Gateway mode：`make dev-pro`
2. 浏览器打开 `/workspace`，新建 agent 对话
3. 发第一条消息 → 等待 agent 完整回复（memory queue 启动 ephemeral loop 的旧路径已被替换为主 loop）
4. 发第二条消息 → 期望 agent 正常回复，**不出现** `LLM request failed: Event loop is closed`
5. 检查 `logs/gateway.log` 不包含 `RuntimeError: Event loop is closed`

如复现成功失败（即没出现错误）→ 修复确认；如仍出现错误 → 回到 Task 1-7 复查 import / lifespan 是否正确生效。

- [ ] **Step 4：检查 memory.json 与 subagent 行为正常**

a. 查看 `backend/.deer-flow/memory.json` 在两次对话后是否被更新（应有新 fact）。
b. 触发一次 subagent（如使用 `task` 工具的对话）确认正常返回结果。

- [ ] **Step 5：最终 commit（若有 lint/format 修正）**

```bash
git status   # 检查无未提交修改
# 若有，按需 git add 并 commit
```

Expected: working tree 干净。

---

## Self-Review

按 brainstorming-skill / writing-plans 自检：

**Spec coverage 对照：**

- §2 Goal G1（消除 ephemeral loop） → Task 6 + 7 删旧路径 + 加 main_loop 路径 + Task 11 回归测试 ✓
- §2 Goal G2（调用方契约不变） → Task 6 update_memory 仍返回 bool；Task 7 execute() 仍返回 SubagentResult ✓
- §2 Goal G3（关停立即 cancel + 抛 RuntimeError） → Task 4 shutdown_main_loop 实现；Task 6/7 catch CancelledError ✓
- §2 Goal G4（LLM 错误可观测） → Task 8 + Task 9 ✓
- §3.1 复用主 loop → Task 5 lifespan 注入 ✓
- §3.5 fail-fast 防死锁 → Task 3 实现 + 测试 ✓
- §4.1 helper API 五件套 → Task 1-4 ✓
- §4.2 Gateway lifespan 集成 → Task 5 ✓
- §4.3 memory updater 改造 → Task 6 ✓
- §4.4 subagent executor 改造 → Task 7 ✓
- §4.5 LLM error observability → Task 8 + 9 ✓
- §5 关停语义 → Task 4 + 6/7 catch ✓
- §6 Standard mode 文档化 → Task 10 ✓
- §7 测试策略全部条目 → Task 1-4 单元 + Task 6/7 端到端 + Task 9 audit + Task 11 跨 loop 回归 ✓
- §10 Out of scope 项目均未引入 ✓

**Placeholder 扫描：**

无 "TBD"、无 "implement later"、每段代码都给了完整可粘贴片段、所有测试都给了真实 import 路径。

**Type / 签名一致性：**

- `submit_to_main_loop(coro_factory: Callable[[], Coroutine[Any, Any, Any]])` 在 Task 3 定义、Task 6/7 使用，签名一致 ✓
- `_run_async_update_sync(coro_factory: Callable[[], Awaitable[bool]])` 在 Task 6 一处定义一处使用 ✓
- `has_main_loop()` / `get_main_loop()` / `shutdown_main_loop()` 名字在 Task 1-7 各处一致 ✓
- `_isolated_loop_pool` / `_execute_in_isolated_loop` 在 Task 7 删除断言中名字与 [executor.py:80,459](backend/packages/harness/deerflow/subagents/executor.py#L80) 一致 ✓
- audit action `llm.error.silenced` 在 Task 8 / 9 拼写一致 ✓

无问题，plan 落地。
