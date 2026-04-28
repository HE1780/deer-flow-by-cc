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
