# M5: LangGraph Identity Propagation + Guardrail Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Detail level: **task-list level**. Expand into TDD per-step when executing.

**Goal:** Carry identity from Gateway into the LangGraph runtime via HMAC-signed headers; LangGraph-side `IdentityMiddleware` parses them into `state["identity"]`; `GuardrailMiddleware` upgraded to enforce tool-level permissions from that identity. Subagents inherit parent identity.

**Prerequisites:** M4 merged. Branch `feat/m5-langgraph-identity`.

**Spec reference:** §5.4 (header propagation), §6.4 (Guardrail upgrade), §4.1 (identity on ThreadState).

**Non-goals:** no MCP-server-declared permissions catalogue (M6 adds the registry hook); no audit writer here — denies are queued via the stub from M3.

---

## File Structure

### Created

```
backend/packages/harness/deerflow/agents/middlewares/
  identity_middleware.py      # Reads X-Deerflow-* headers, verifies HMAC, writes state["identity"]
  audit_hook.py               # Stub (calls Gateway /internal/audit; actual queue lands in M6)

backend/app/gateway/identity/propagation.py
  # sign_identity_headers(identity, ts, key) → dict of X-Deerflow-* headers
  # verify_identity_headers(headers, key) → Identity

backend/app/gateway/identity/routers/internal.py
  # POST /internal/audit — HMAC-authenticated internal route for LangGraph-side events

backend/tests/identity/test_propagation.py
backend/tests/identity/test_langgraph_identity_middleware.py
backend/tests/identity/test_guardrail_upgrade.py
backend/tests/identity/test_subagent_identity_inherit.py
```

### Modified

```
backend/app/gateway/identity/settings.py
  # already has internal_signing_key; add hmac_skew_sec (default 300)

backend/app/gateway/deps.py  (or gateway LangGraph invocation site)
  # When Gateway calls langgraph-sdk, inject sign_identity_headers into request headers

backend/packages/harness/deerflow/agents/lead_agent/agent.py
  # Insert IdentityMiddleware at position 0 of middleware chain
  # Ensure state["identity"] exists downstream

backend/packages/harness/deerflow/agents/middlewares/guardrail.py
  # before_tool_call reads state["identity"], looks up TOOL_PERMISSION_MAP

backend/packages/harness/deerflow/agents/middlewares/__init__.py
  # export new middlewares

backend/packages/harness/deerflow/subagents/executor.py
  # forward parent state["identity"] into subagent task context
```

---

## Task 1: HMAC propagation contract

```python
# propagation.py
HEADER_USER_ID      = "X-Deerflow-User-Id"
HEADER_TENANT_ID    = "X-Deerflow-Tenant-Id"
HEADER_WORKSPACE_ID = "X-Deerflow-Workspace-Id"
HEADER_PERMISSIONS  = "X-Deerflow-Permissions"  # comma-separated sorted
HEADER_SESSION_ID   = "X-Deerflow-Session-Id"
HEADER_TS           = "X-Deerflow-Identity-Ts"
HEADER_SIG          = "X-Deerflow-Identity-Sig"

def sign_identity_headers(identity: Identity, *, workspace_id: int | None, key: bytes, ts: int | None = None) -> dict[str, str]: ...

def verify_identity_headers(headers: Mapping[str, str], *, key: bytes, skew_sec: int = 300) -> Identity: ...
```

Signature canonical form:
```
"{user_id}|{tenant_id}|{workspace_id or ''}|{permissions_sorted_joined_comma}|{ts}"
```
HMAC-SHA256, base64url.

**Tests** (`test_propagation.py`):
- roundtrip sign+verify
- tamper user_id → `InvalidSignatureError`
- tamper permissions → `InvalidSignatureError`
- stale ts beyond skew → `StaleTimestampError`
- future ts beyond skew → `StaleTimestampError`
- missing required header → `MissingHeaderError`
- permissions order-insensitive (sort before signing)

---

## Task 2: LangGraph IdentityMiddleware

```python
# agents/middlewares/identity_middleware.py
from langgraph.agents.middleware import AgentMiddleware

class IdentityMiddleware(AgentMiddleware):
    def __init__(self, *, signing_key: bytes, skew_sec: int = 300): ...

    async def before_agent(self, state, config) -> dict:
        headers = config.get("configurable", {}).get("headers", {}) or {}
        identity = verify_identity_headers(headers, key=self.signing_key, skew_sec=self.skew_sec)
        state["identity"] = identity  # NOTE: reducer must persist this across steps
        return state
```

Add `identity: dict | None` to `ThreadState` schema. Reducer: last-write-wins.

Register in `lead_agent.agent.make_lead_agent` as **middleware position 0** (before ThreadData). When `ENABLE_IDENTITY=false` the headers are not injected on the Gateway side; middleware detects missing headers and writes `None` without raising (backward compat).

Tests: valid headers → state populated; missing headers → state["identity"]=None + no error; tampered → raises at agent startup so run fails loud.

---

## Task 3: Guardrail upgrade — TOOL_PERMISSION_MAP

```python
# agents/middlewares/guardrail.py
TOOL_PERMISSION_MAP: dict[str, str] = {
    "bash":        "thread:write",
    "write_file":  "thread:write",
    "str_replace": "thread:write",
    "read_file":   "thread:read",
    "ls":          "thread:read",
    "task":        "thread:write",
    "present_files": "thread:read",
    "view_image":    "thread:read",
    "ask_clarification": "thread:read",
    # write_todos handled by TodoListMiddleware, no explicit perm gate
}

DEFAULT_MCP_PERMISSION = "skill:invoke"
```

`before_tool_call`:
1. If `state["identity"]` is None (flag off) → fall through to existing OAP/allowlist logic (preserve v1 behavior).
2. Lookup `TOOL_PERMISSION_MAP[tool_name]` → required tag.
3. For MCP tools: if the tool registration carries a `required_permission` attribute, use it; else `DEFAULT_MCP_PERMISSION`.
4. If identity lacks the tag → return `ToolCallRejection(reason=f"Missing permission: {required}", audit_action="authz.tool.denied")`.
5. Unknown tool (neither in map nor MCP-registered) → **deny** (whitelist policy).
6. Then invoke existing guardrail provider (OAP / allowlist) — those still apply on top.

Tests (`test_guardrail_upgrade.py`):
- identity with `thread:write` → `bash` passes
- identity without `thread:write` → `bash` denied, audit event queued
- unknown tool "super_dangerous" → denied by default
- flag-off path (no identity in state) → falls through to existing provider (regression)
- MCP tool with declared permission → honored
- OAP provider still enforced when identity has permission

---

## Task 4: Subagent identity inheritance

Modify `backend/packages/harness/deerflow/subagents/executor.py`:

When spawning a subagent, the parent state's `identity` is copied into the subagent's initial state. Concurrency limit (`MAX_CONCURRENT_SUBAGENTS=3`) still enforced by `SubagentLimitMiddleware`.

Tests (`test_subagent_identity_inherit.py`):
- Parent with identity → subagent receives same identity
- Subagent attempts tool requiring same perm as parent → allowed
- Subagent cannot elevate (identity is frozen; no mutation API exposed)

---

## Task 5: Gateway outbound header injection

Inject identity headers when Gateway invokes LangGraph via `langgraph-sdk`:

- Locate `app/gateway/deps.py::langgraph_runtime` or `app/gateway/routers/runs.py` where the SDK client is created
- Wrap the SDK client with a header injector that calls `sign_identity_headers(request.state.identity, workspace_id=ws_from_path, key=settings.internal_signing_key)`
- Falls back to no-op when identity is anonymous or flag off

Tests: integration test that boots gateway + langgraph dev server, issues an authenticated `/api/threads/{id}/runs`, asserts a subsequent tool call inside the run sees identity in ThreadState.

---

## Task 6: Internal audit endpoint (stub for M6)

```python
# routers/internal.py
@router.post("/internal/audit")
async def ingest_audit_event(
    payload: AuditEventPayload,
    hmac_sig: str = Header(..., alias="X-Deerflow-Internal-Sig"),
): ...
```

HMAC-verify same key as identity propagation. In M5 this stub just appends to an in-memory queue; M6 wires the real writer.

---

## Task 7: Acceptance tests

- End-to-end: authenticated user runs a chat request → LangGraph sees identity → bash tool call succeeds for member role.
- Negative: viewer role runs chat → bash tool denied with message surfaced back to the agent as `ToolMessage(content="Permission denied: thread:write")`.
- Flag-off regression: legacy run with no identity propagation still works; existing guardrail providers unchanged.

## Self-review vs spec §5.4 / §6.4 / §4.1

- Header names + HMAC field order → Task 1.
- LangGraph middleware position 0 → Task 2.
- TOOL_PERMISSION_MAP + whitelist default-deny → Task 3.
- Subagent identity inheritance → Task 4.
- Outbound header injection from Gateway → Task 5.
- ThreadState includes identity → Task 2.
- Harness boundary unaffected: new code in harness imports only stdlib/langgraph; no `app.*` imports. Verified via existing `test_harness_boundary.py`.
