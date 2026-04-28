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


def test_set_main_loop_replaces_closed_loop_after_full_lifecycle():
    """Regression: a previously registered loop that has been shut down and
    closed must not block registration of a fresh loop. Covers test harnesses
    (and any future hot-reload scenario) that run multiple lifespans within
    one process."""
    loop_a = asyncio.new_event_loop()
    ml.set_main_loop(loop_a)
    asyncio.new_event_loop().run_until_complete(ml.shutdown_main_loop())
    loop_a.close()
    assert ml.has_main_loop() is False

    loop_b = asyncio.new_event_loop()
    try:
        ml.set_main_loop(loop_b)  # must not raise
        assert ml.get_main_loop() is loop_b
        assert ml.has_main_loop() is True
    finally:
        loop_b.close()


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
