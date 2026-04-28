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


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register the long-lived main event loop. Called by Gateway lifespan.

    Re-registering the same loop is a no-op. Registering a different loop
    while one is already active raises RuntimeError — production should
    only have one main loop per process. A previously registered loop that
    is now closed is treated as unregistered (covers test harnesses that
    run multiple lifespans against the same process).
    """
    global _main_loop, _main_loop_thread_id, _shutting_down
    with _lock:
        if _main_loop is loop:
            return
        if _main_loop is not None and not _main_loop.is_closed():
            raise RuntimeError(
                "main loop is already registered; cannot replace at runtime"
            )
        _main_loop = loop
        _main_loop_thread_id = threading.get_ident()
        _shutting_down = False
        logger.info("Main asyncio loop registered (thread_id=%s)", _main_loop_thread_id)


def get_main_loop() -> asyncio.AbstractEventLoop:
    """Return the registered main loop. Raises RuntimeError if unset."""
    if _main_loop is None:
        raise RuntimeError("main loop is not registered")
    return _main_loop


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


async def shutdown_main_loop() -> None:
    """Cancel all in-flight futures and clear the main-loop registration.

    Called by Gateway lifespan teardown. Intentionally does NOT wait for
    cancellation to settle — open-development policy: in-flight memory
    updates may be lost (timer will retry next debounce window) and
    in-flight subagents return FAILED.
    """
    global _main_loop, _main_loop_thread_id, _shutting_down
    with _lock:
        if _main_loop is None:
            # Either already shut down, or never registered — nothing to do.
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


def _reset_for_tests() -> None:
    """Wipe state. ONLY for unit tests; never call from product code."""
    global _main_loop, _main_loop_thread_id, _shutting_down
    with _lock:
        _main_loop = None
        _main_loop_thread_id = None
        _shutting_down = False
        _tracked_futures.clear()
