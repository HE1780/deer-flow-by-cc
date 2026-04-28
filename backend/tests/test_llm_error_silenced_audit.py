"""LLMErrorHandlingMiddleware emits critical-level observability when an
LLM call fails after retries and the user-facing error message is returned."""
import asyncio
import logging
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.llm_error_handling_middleware import (
    LLMErrorHandlingMiddleware,
)


def _make_middleware() -> LLMErrorHandlingMiddleware:
    """Construct an LLM error middleware with retries=1 (so first failure is final)."""
    mw = LLMErrorHandlingMiddleware()
    mw.retry_max_attempts = 1                # do not retry — first failure is final
    mw.circuit_failure_threshold = 999       # do not trip the breaker mid-test
    return mw


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
