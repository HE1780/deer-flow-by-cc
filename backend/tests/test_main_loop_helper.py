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
