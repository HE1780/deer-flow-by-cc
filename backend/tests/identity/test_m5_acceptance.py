"""M5 acceptance tests — end-to-end identity propagation.

These glue the pieces together without booting a full LLM:

1. Sign identity headers the way the Gateway would (:func:`sign_identity_headers`).
2. Feed them into the LangGraph-side :class:`IdentityMiddleware`.
3. Run the resulting state through :class:`IdentityGuardrailMiddleware`
   and verify the tool call outcome.

That covers the load-bearing contract: *Gateway signs → harness verifies →
guardrail enforces*. An actual agent run with a real model would add
branching and LLM non-determinism without testing any additional code
path that isn't already covered.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.propagation import sign_identity_headers
from deerflow.agents.middlewares.identity_middleware import IdentityMiddleware
from deerflow.guardrails.identity_guardrail import IdentityGuardrailMiddleware

KEY = "m5-acceptance-signing-key"


def _gateway_identity(*, permissions: set[str]) -> Identity:
    return Identity(
        token_type="jwt",
        user_id=42,
        email="member@example.com",
        tenant_id=7,
        workspace_ids=(3,),
        permissions=frozenset(permissions),
        roles={},
        session_id="sess_accept",
        ip="10.0.0.1",
    )


def _tool_call(name: str, call_id: str = "c1") -> SimpleNamespace:
    # SimpleNamespace is interchangeable with ToolCallRequest here — the
    # guardrail middleware only reads ``tool_call`` and ``state``.
    return SimpleNamespace(
        tool_call={"name": name, "args": {}, "id": call_id},
        state={},
        runtime=None,
        tool=None,
    )


def _populate_state_via_middleware(headers: dict[str, str]) -> dict:
    mw = IdentityMiddleware(signing_key=KEY)
    cfg = {"configurable": {"headers": headers}}
    with patch("deerflow.agents.middlewares.identity_middleware.get_config", return_value=cfg):
        result = mw.before_agent({}, runtime=None)
    assert result is not None, "IdentityMiddleware must populate state on valid headers"
    return {"identity": result["identity"]}


def test_member_with_thread_write_runs_bash_successfully():
    identity = _gateway_identity(permissions={"thread:read", "thread:write"})
    headers = sign_identity_headers(identity, workspace_id=3, key=KEY)

    state = _populate_state_via_middleware(headers)

    guardrail = IdentityGuardrailMiddleware()
    req = _tool_call("bash")
    req.state = state
    handler = MagicMock(return_value="tool executed")

    result = guardrail.wrap_tool_call(req, handler)
    assert result == "tool executed"
    handler.assert_called_once()


def test_viewer_without_thread_write_is_denied_for_bash():
    identity = _gateway_identity(permissions={"thread:read"})
    headers = sign_identity_headers(identity, workspace_id=3, key=KEY)

    state = _populate_state_via_middleware(headers)

    guardrail = IdentityGuardrailMiddleware()
    req = _tool_call("bash")
    req.state = state
    handler = MagicMock()

    result = guardrail.wrap_tool_call(req, handler)
    handler.assert_not_called()
    assert result.status == "error"
    # Error message surfaces to the LLM as ToolMessage.content per plan §Task 7
    assert "thread:write" in result.content
    assert result.additional_kwargs["audit_action"] == "authz.tool.denied"


def test_flag_off_legacy_run_unaffected():
    """No signing key, no propagation → pre-M5 behavior preserved."""
    # Nobody signs headers. The harness middleware sees an empty headers
    # dict and doesn't populate state["identity"]. The guardrail then
    # falls through (flag-off regression path).
    mw = IdentityMiddleware(signing_key=KEY)
    with patch("deerflow.agents.middlewares.identity_middleware.get_config", return_value={"configurable": {}}):
        out = mw.before_agent({}, runtime=None)
    assert out is None

    guardrail = IdentityGuardrailMiddleware()
    req = _tool_call("bash")
    req.state = {}  # no identity — legacy run
    handler = MagicMock(return_value="ok")
    assert guardrail.wrap_tool_call(req, handler) == "ok"


def test_tampered_headers_block_the_run():
    """Wire-level attack: tampered headers must raise so the run fails loud."""
    identity = _gateway_identity(permissions={"thread:write"})
    headers = sign_identity_headers(identity, workspace_id=3, key=KEY)
    # Flip user_id post-signature — tamper.
    headers["X-Deerflow-User-Id"] = "999"

    mw = IdentityMiddleware(signing_key=KEY)
    with patch("deerflow.agents.middlewares.identity_middleware.get_config", return_value={"configurable": {"headers": headers}}):
        from deerflow.identity_propagation import InvalidSignatureError

        with pytest.raises(InvalidSignatureError):
            mw.before_agent({}, runtime=None)


def test_subagent_inherits_identity_through_guardrail():
    """Parent identity → subagent → identical enforcement."""
    import sys
    from unittest.mock import MagicMock

    _MOCKED = [
        "deerflow.agents",
        "deerflow.agents.thread_state",
        "deerflow.agents.middlewares",
        "deerflow.agents.middlewares.thread_data_middleware",
        "deerflow.sandbox",
        "deerflow.sandbox.middleware",
        "deerflow.sandbox.security",
        "deerflow.models",
    ]
    original_modules = {n: sys.modules.get(n) for n in _MOCKED}
    original_executor = sys.modules.get("deerflow.subagents.executor")

    sys.modules.pop("deerflow.subagents.executor", None)
    for name in _MOCKED:
        sys.modules[name] = MagicMock()
    try:
        from deerflow.subagents.config import SubagentConfig
        from deerflow.subagents.executor import SubagentExecutor

        identity = _gateway_identity(permissions={"thread:read"})  # no write
        # Simulate verification producing a VerifiedIdentity-style object — we
        # use the Gateway Identity directly here; harness only duck-types.
        executor = SubagentExecutor(
            config=SubagentConfig(name="gp", description="", system_prompt=""),
            tools=[],
            parent_model="gpt-4",
            identity=identity,
        )
        subagent_state = asyncio.run(executor._build_initial_state("run bash"))

        guardrail = IdentityGuardrailMiddleware()
        req = _tool_call("bash")
        req.state = subagent_state
        handler = MagicMock()
        result = guardrail.wrap_tool_call(req, handler)

        handler.assert_not_called()
        assert result.status == "error"
        assert "thread:write" in result.content
    finally:
        sys.modules.pop("deerflow.subagents.executor", None)
        if original_executor is not None:
            sys.modules["deerflow.subagents.executor"] = original_executor
        for name, mod in original_modules.items():
            if mod is not None:
                sys.modules[name] = mod
            else:
                sys.modules.pop(name, None)


def test_full_chain_signer_middleware_guardrail_via_services():
    """Gateway path: _inject_identity_headers → IdentityMiddleware → guardrail.

    This is the most end-to-end unit-level test in the M5 suite: the same
    headers the Gateway will ship in production get verified by the
    runtime middleware and drive a positive/negative guardrail decision.
    """
    from app.gateway.services import _inject_identity_headers

    settings = SimpleNamespace(enabled=True, internal_signing_key=KEY)
    request = SimpleNamespace(
        state=SimpleNamespace(identity=_gateway_identity(permissions={"thread:write"})),
        path_params={"wid": "3"},
    )
    config: dict = {"configurable": {}}
    with patch("app.gateway.identity.settings.get_identity_settings", return_value=settings):
        _inject_identity_headers(config, request)

    mw = IdentityMiddleware(signing_key=KEY)
    with patch("deerflow.agents.middlewares.identity_middleware.get_config", return_value=config):
        result = mw.before_agent({}, runtime=None)
    assert result is not None

    guardrail = IdentityGuardrailMiddleware()
    req = _tool_call("bash")
    req.state = {"identity": result["identity"]}
    handler = MagicMock(return_value="bash ran")
    assert guardrail.wrap_tool_call(req, handler) == "bash ran"
