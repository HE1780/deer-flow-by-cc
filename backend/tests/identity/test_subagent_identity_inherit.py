"""Subagent identity inheritance tests (M5 Task 4).

Subagents must inherit the parent identity into their initial state so
the downstream ``IdentityGuardrailMiddleware`` enforces the same
permissions — and so identity cannot be elevated by a runaway subagent.

Note: backend/tests/conftest.py mocks ``deerflow.subagents.executor``
globally to break a circular import that otherwise trips lightweight
tests. We follow the pattern from ``tests/test_subagent_executor.py`` and
restore the real module at session scope via a local fixture.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

# Modules mocked out so the real subagents.executor can be imported
# without triggering the lead-agent import chain. Same list the
# ``test_subagent_executor.py`` file uses.
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
def _real_executor():
    """Swap the conftest-level executor mock out for the real module."""
    original_modules = {name: sys.modules.get(name) for name in _MOCKED_MODULE_NAMES}
    original_executor = sys.modules.get("deerflow.subagents.executor")

    sys.modules.pop("deerflow.subagents.executor", None)
    for name in _MOCKED_MODULE_NAMES:
        sys.modules[name] = MagicMock()

    # Force re-import so this test file gets the real class
    from deerflow.subagents import config as _subagent_config  # noqa: F401
    from deerflow.subagents import executor as _subagent_executor  # noqa: F401

    yield

    sys.modules.pop("deerflow.subagents.executor", None)
    if original_executor is not None:
        sys.modules["deerflow.subagents.executor"] = original_executor

    for name, module in original_modules.items():
        if module is not None:
            sys.modules[name] = module
        else:
            sys.modules.pop(name, None)


class _Identity:
    def __init__(self, *, user_id=42, permissions=frozenset({"thread:write"})):
        self.user_id = user_id
        self.permissions = frozenset(permissions)


def _make_executor(identity=None):
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentExecutor

    cfg = SubagentConfig(
        name="general-purpose",
        description="test",
        system_prompt="You are a test agent.",
    )
    return SubagentExecutor(
        config=cfg,
        tools=[],
        parent_model="gpt-4",
        sandbox_state=None,
        thread_data=None,
        thread_id="thr_abc",
        identity=identity,
    )


def test_parent_identity_flows_into_initial_state():
    identity = _Identity(permissions={"thread:write", "thread:read"})
    executor = _make_executor(identity=identity)

    state = asyncio.run(executor._build_initial_state("do the thing"))
    assert state["identity"] is identity
    assert state["identity"].permissions == frozenset({"thread:write", "thread:read"})


def test_identity_absent_does_not_add_key():
    """Flag-off / legacy mode: no identity on parent → subagent state is clean."""
    executor = _make_executor(identity=None)
    state = asyncio.run(executor._build_initial_state("do the thing"))
    assert "identity" not in state


def test_executor_stores_identity_on_instance():
    identity = _Identity()
    executor = _make_executor(identity=identity)
    assert executor.identity is identity


def test_subagent_cannot_elevate_permissions():
    """frozenset — no mutation API. Structural regression guard."""
    identity = _Identity(permissions={"thread:read"})
    executor = _make_executor(identity=identity)
    state = asyncio.run(executor._build_initial_state("task"))

    with pytest.raises(AttributeError):
        state["identity"].permissions.add("admin:write")  # type: ignore[attr-defined]


def test_identity_guardrail_sees_inherited_permissions():
    """End-to-end flavor: subagent starts with parent's identity and
    the guardrail denies tools the parent would also have been denied.
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from deerflow.guardrails.identity_guardrail import IdentityGuardrailMiddleware

    identity = _Identity(permissions={"thread:read"})  # no write perm
    executor = _make_executor(identity=identity)
    subagent_state = asyncio.run(executor._build_initial_state("please run bash"))

    mw = IdentityGuardrailMiddleware()
    req = SimpleNamespace(
        tool_call={"name": "bash", "args": {}, "id": "c1"},
        state=subagent_state,
        runtime=None,
        tool=None,
    )
    handler = MagicMock()
    result = mw.wrap_tool_call(req, handler)

    handler.assert_not_called()
    assert result.status == "error"
    assert "thread:write" in result.content


def test_inherited_permissions_allow_what_parent_can_do():
    """Positive flip: parent has thread:write → subagent's bash passes the gate."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from deerflow.guardrails.identity_guardrail import IdentityGuardrailMiddleware

    identity = _Identity(permissions={"thread:write"})
    executor = _make_executor(identity=identity)
    subagent_state = asyncio.run(executor._build_initial_state("please run bash"))

    mw = IdentityGuardrailMiddleware()
    req = SimpleNamespace(
        tool_call={"name": "bash", "args": {}, "id": "c2"},
        state=subagent_state,
        runtime=None,
        tool=None,
    )
    handler = MagicMock(return_value="ok")
    result = mw.wrap_tool_call(req, handler)

    assert result == "ok"
    handler.assert_called_once()
