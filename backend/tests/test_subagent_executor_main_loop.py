"""Subagent executor wires through deerflow.runtime.main_loop when registered."""
import asyncio
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# Module names that need to be mocked to break circular imports (same as test_subagent_executor.py)
_MOCKED_MODULE_NAMES = [
    "deerflow.agents",
    "deerflow.agents.thread_state",
    "deerflow.agents.middlewares",
    "deerflow.agents.middlewares.thread_data_middleware",
    "deerflow.sandbox",
    "deerflow.sandbox.middleware",
    "deerflow.sandbox.security",
    "deerflow.models",
]


@pytest.fixture(scope="module", autouse=True)
def _setup_mocks():
    """Set up mocked modules to break circular imports for the executor."""
    original_modules = {name: sys.modules.get(name) for name in _MOCKED_MODULE_NAMES}
    original_executor = sys.modules.get("deerflow.subagents.executor")

    if "deerflow.subagents.executor" in sys.modules:
        del sys.modules["deerflow.subagents.executor"]

    for name in _MOCKED_MODULE_NAMES:
        sys.modules[name] = MagicMock()

    yield

    for name in _MOCKED_MODULE_NAMES:
        if original_modules[name] is not None:
            sys.modules[name] = original_modules[name]
        elif name in sys.modules:
            del sys.modules[name]

    if original_executor is not None:
        sys.modules["deerflow.subagents.executor"] = original_executor
    elif "deerflow.subagents.executor" in sys.modules:
        del sys.modules["deerflow.subagents.executor"]


from deerflow.runtime import main_loop as ml  # noqa: E402


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
    from deerflow.subagents.config import SubagentConfig
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

    fake_config = SubagentConfig(
        name="test-agent",
        description="Test agent",
        system_prompt="You are a test agent.",
        max_turns=10,
        timeout_seconds=60,
    )

    try:
        with patch.object(SubagentExecutor, "_aexecute", fake_aexecute):
            ex = SubagentExecutor(config=fake_config, tools=[], trace_id="t-1")
            res = ex.execute("do thing")
            assert res.status == SubagentStatus.COMPLETED
            assert res.result == "ok"
            assert captured_thread == [t.ident]
    finally:
        _stop(loop, t)
        loop.close()


def test_execute_returns_failed_on_cancellation():
    from deerflow.subagents.config import SubagentConfig
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

    fake_config = SubagentConfig(
        name="slow-agent",
        description="Slow agent",
        system_prompt="You are a slow agent.",
        max_turns=10,
        timeout_seconds=60,
    )

    result_holder_box: list[SubagentResult] = []

    def submitter():
        with patch.object(SubagentExecutor, "_aexecute", long_aexecute):
            ex = SubagentExecutor(config=fake_config, tools=[], trace_id="t-2")
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
