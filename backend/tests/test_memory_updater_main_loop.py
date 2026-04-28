"""Memory updater wires through deerflow.runtime.main_loop when registered."""
import asyncio
import threading
import time

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
