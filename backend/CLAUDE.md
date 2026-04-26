# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DeerFlow is a LangGraph-based AI super agent system with a full-stack architecture. The backend provides a "super agent" with sandbox execution, persistent memory, subagent delegation, and extensible tool integration - all operating in per-thread isolated environments.

**Architecture**:
- **LangGraph Server** (port 2024): Agent runtime and workflow execution
- **Gateway API** (port 8100): REST API for models, MCP, skills, memory, artifacts, uploads, and local thread cleanup
- **Frontend** (port 3110): Next.js web interface
- **Nginx** (port 2026): Unified reverse proxy entry point
- **Provisioner** (port 8002, optional in Docker dev): Started only when sandbox is configured for provisioner/Kubernetes mode

**Runtime Modes**:
- **Standard mode** (`make dev`): LangGraph Server handles agent execution as a separate process. 4 processes total.
- **Gateway mode** (`make dev-pro`, experimental): Agent runtime embedded in Gateway via `RunManager` + `run_agent()` + `StreamBridge` (`packages/harness/deerflow/runtime/`). Service manages its own concurrency via async tasks. 3 processes total, no LangGraph Server.

**Project Structure**:
```
deer-flow/
├── Makefile                    # Root commands (check, install, dev, stop)
├── config.yaml                 # Main application configuration
├── extensions_config.json      # MCP servers and skills configuration
├── backend/                    # Backend application (this directory)
│   ├── Makefile               # Backend-only commands (dev, gateway, lint)
│   ├── langgraph.json         # LangGraph server configuration
│   ├── packages/
│   │   └── harness/           # deerflow-harness package (import: deerflow.*)
│   │       ├── pyproject.toml
│   │       └── deerflow/
│   │           ├── agents/            # LangGraph agent system
│   │           │   ├── lead_agent/    # Main agent (factory + system prompt)
│   │           │   ├── middlewares/   # 10 middleware components
│   │           │   ├── memory/        # Memory extraction, queue, prompts
│   │           │   └── thread_state.py # ThreadState schema
│   │           ├── sandbox/           # Sandbox execution system
│   │           │   ├── local/         # Local filesystem provider
│   │           │   ├── sandbox.py     # Abstract Sandbox interface
│   │           │   ├── tools.py       # bash, ls, read/write/str_replace
│   │           │   └── middleware.py  # Sandbox lifecycle management
│   │           ├── subagents/         # Subagent delegation system
│   │           │   ├── builtins/      # general-purpose, bash agents
│   │           │   ├── executor.py    # Background execution engine
│   │           │   └── registry.py    # Agent registry
│   │           ├── tools/builtins/    # Built-in tools (present_files, ask_clarification, view_image)
│   │           ├── mcp/               # MCP integration (tools, cache, client)
│   │           ├── models/            # Model factory with thinking/vision support
│   │           ├── skills/            # Skills discovery, loading, parsing
│   │           ├── config/            # Configuration system (app, model, sandbox, tool, etc.)
│   │           ├── community/         # Community tools (tavily, jina_ai, firecrawl, image_search, aio_sandbox)
│   │           ├── reflection/        # Dynamic module loading (resolve_variable, resolve_class)
│   │           ├── utils/             # Utilities (network, readability)
│   │           └── client.py          # Embedded Python client (DeerFlowClient)
│   ├── app/                   # Application layer (import: app.*)
│   │   ├── gateway/           # FastAPI Gateway API
│   │   │   ├── app.py         # FastAPI application
│   │   │   └── routers/       # FastAPI route modules (models, mcp, memory, skills, uploads, threads, artifacts, agents, suggestions, channels)
│   │   └── channels/          # IM platform integrations
│   ├── tests/                 # Test suite
│   └── docs/                  # Documentation
├── frontend/                   # Next.js frontend application
└── skills/                     # Agent skills directory
    ├── public/                # Public skills (committed)
    └── custom/                # Custom skills (gitignored)
```

## Important Development Guidelines

### Documentation Update Policy
**CRITICAL: Always update README.md and CLAUDE.md after every code change**

When making code changes, you MUST update the relevant documentation:
- Update `README.md` for user-facing changes (features, setup, usage instructions)
- Update `CLAUDE.md` for development changes (architecture, commands, workflows, internal systems)
- Keep documentation synchronized with the codebase at all times
- Ensure accuracy and timeliness of all documentation

## Commands

**Root directory** (for full application):
```bash
make check      # Check system requirements
make install    # Install all dependencies (frontend + backend)
make dev        # Start all services (LangGraph + Gateway + Frontend + Nginx), with config.yaml preflight
make dev-pro    # Gateway mode (experimental): skip LangGraph, agent runtime embedded in Gateway
make start-pro  # Production + Gateway mode (experimental)
make stop       # Stop all services
```

**Backend directory** (for backend development only):
```bash
make install    # Install backend dependencies
make dev        # Run LangGraph server only (port 2024)
make gateway    # Run Gateway API only (port 8100)
make test       # Run all backend tests
make lint       # Lint with ruff
make format     # Format code with ruff
```

Regression tests related to Docker/provisioner behavior:
- `tests/test_docker_sandbox_mode_detection.py` (mode detection from `config.yaml`)
- `tests/test_provisioner_kubeconfig.py` (kubeconfig file/directory handling)

Boundary check (harness → app import firewall):
- `tests/test_harness_boundary.py` — ensures `packages/harness/deerflow/` never imports from `app.*`

CI runs these regression tests for every pull request via [.github/workflows/backend-unit-tests.yml](../.github/workflows/backend-unit-tests.yml).

## Architecture

### Harness / App Split

The backend is split into two layers with a strict dependency direction:

- **Harness** (`packages/harness/deerflow/`): Publishable agent framework package (`deerflow-harness`). Import prefix: `deerflow.*`. Contains agent orchestration, tools, sandbox, models, MCP, skills, config — everything needed to build and run agents.
- **App** (`app/`): Unpublished application code. Import prefix: `app.*`. Contains the FastAPI Gateway API and IM channel integrations (Feishu, Slack, Telegram).

**Dependency rule**: App imports deerflow, but deerflow never imports app. This boundary is enforced by `tests/test_harness_boundary.py` which runs in CI.

**Import conventions**:
```python
# Harness internal
from deerflow.agents import make_lead_agent
from deerflow.models import create_chat_model

# App internal
from app.gateway.app import app
from app.channels.service import start_channel_service

# App → Harness (allowed)
from deerflow.config import get_app_config

# Harness → App (FORBIDDEN — enforced by test_harness_boundary.py)
# from app.gateway.routers.uploads import ...  # ← will fail CI
```

### Agent System

**Lead Agent** (`packages/harness/deerflow/agents/lead_agent/agent.py`):
- Entry point: `make_lead_agent(config: RunnableConfig)` registered in `langgraph.json`
- Dynamic model selection via `create_chat_model()` with thinking/vision support
- Tools loaded via `get_available_tools()` - combines sandbox, built-in, MCP, community, and subagent tools
- System prompt generated by `apply_prompt_template()` with skills, memory, and subagent instructions

**ThreadState** (`packages/harness/deerflow/agents/thread_state.py`):
- Extends `AgentState` with: `sandbox`, `thread_data`, `title`, `artifacts`, `todos`, `uploaded_files`, `viewed_images`
- Uses custom reducers: `merge_artifacts` (deduplicate), `merge_viewed_images` (merge/clear)

**Runtime Configuration** (via `config.configurable`):
- `thinking_enabled` - Enable model's extended thinking
- `model_name` - Select specific LLM model
- `is_plan_mode` - Enable TodoList middleware
- `subagent_enabled` - Enable task delegation tool

### Middleware Chain

Lead-agent middlewares are assembled in strict append order across `packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` (`build_lead_runtime_middlewares`) and `packages/harness/deerflow/agents/lead_agent/agent.py` (`_build_middlewares`):

0. **IdentityMiddleware** *(M5, only when `DEERFLOW_INTERNAL_SIGNING_KEY` is set)* — Verifies HMAC-signed `X-Deerflow-*` headers injected by the Gateway, writes a `VerifiedIdentity` into `state["identity"]`. Pre-populated state (subagent inheritance) is never overwritten. Tampered/stale signatures raise.
1. **ThreadDataMiddleware** - Creates per-thread directories (`backend/.deer-flow/threads/{thread_id}/user-data/{workspace,uploads,outputs}`); Web UI thread deletion now follows LangGraph thread removal with Gateway cleanup of the local `.deer-flow/threads/{thread_id}` directory
2. **UploadsMiddleware** - Tracks and injects newly uploaded files into conversation
3. **SandboxMiddleware** - Acquires sandbox, stores `sandbox_id` in state
4. **DanglingToolCallMiddleware** - Injects placeholder ToolMessages for AIMessage tool_calls that lack responses (e.g., due to user interruption), including raw provider tool-call payloads preserved only in `additional_kwargs["tool_calls"]`
5. **LLMErrorHandlingMiddleware** - Normalizes provider/model invocation failures into recoverable assistant-facing errors before later middleware/tool stages run
6. **IdentityGuardrailMiddleware** *(M5, only when `DEERFLOW_INTERNAL_SIGNING_KEY` is set)* — Identity-driven tool authorization. Reads `state["identity"].permissions`, matches against the built-in `TOOL_PERMISSION_MAP` (spec §6.4). Unknown tools default-deny (whitelist). MCP tools honor a declared `required_permission` attribute or fall back to `DEFAULT_MCP_PERMISSION = "skill:invoke"`. Runs before the optional OAP `GuardrailMiddleware` so both gates compose.
7. **GuardrailMiddleware** - Pre-tool-call authorization via pluggable `GuardrailProvider` protocol (optional, if `guardrails.enabled` in config). Evaluates each tool call and returns error ToolMessage on deny. Three provider options: built-in `AllowlistProvider` (zero deps), OAP policy providers (e.g. `aport-agent-guardrails`), or custom providers. See [docs/GUARDRAILS.md](docs/GUARDRAILS.md) for setup, usage, and how to implement a provider.
7. **SandboxAuditMiddleware** - Audits sandboxed shell/file operations for security logging before tool execution continues
8. **ToolErrorHandlingMiddleware** - Converts tool exceptions into error `ToolMessage`s so the run can continue instead of aborting
9. **SummarizationMiddleware** - Context reduction when approaching token limits (optional, if enabled)
10. **TodoListMiddleware** - Task tracking with `write_todos` tool (optional, if plan_mode)
11. **TokenUsageMiddleware** - Records token usage metrics when token tracking is enabled (optional)
12. **TitleMiddleware** - Auto-generates thread title after first complete exchange and normalizes structured message content before prompting the title model
13. **MemoryMiddleware** - Queues conversations for async memory update (filters to user + final AI responses)
14. **ViewImageMiddleware** - Injects base64 image data before LLM call (conditional on vision support)
15. **DeferredToolFilterMiddleware** - Hides deferred tool schemas from the bound model until tool search is enabled (optional)
16. **SubagentLimitMiddleware** - Truncates excess `task` tool calls from model response to enforce `MAX_CONCURRENT_SUBAGENTS` limit (optional, if `subagent_enabled`)
17. **LoopDetectionMiddleware** - Detects repeated tool-call loops; hard-stop responses clear both structured `tool_calls` and raw provider tool-call metadata before forcing a final text answer
18. **ClarificationMiddleware** - Intercepts `ask_clarification` tool calls, interrupts via `Command(goto=END)` (must be last)

### Configuration System

**Main Configuration** (`config.yaml`):

Setup: Copy `config.example.yaml` to `config.yaml` in the **project root** directory.

**Config Versioning**: `config.example.yaml` has a `config_version` field. On startup, `AppConfig.from_file()` compares user version vs example version and emits a warning if outdated. Missing `config_version` = version 0. Run `make config-upgrade` to auto-merge missing fields. When changing the config schema, bump `config_version` in `config.example.yaml`.

**Config Caching**: `get_app_config()` caches the parsed config, but automatically reloads it when the resolved config path changes or the file's mtime increases. This keeps Gateway and LangGraph reads aligned with `config.yaml` edits without requiring a manual process restart.

Configuration priority:
1. Explicit `config_path` argument
2. `DEER_FLOW_CONFIG_PATH` environment variable
3. `config.yaml` in current directory (backend/)
4. `config.yaml` in parent directory (project root - **recommended location**)

Config values starting with `$` are resolved as environment variables (e.g., `$OPENAI_API_KEY`).
`ModelConfig` also declares `use_responses_api` and `output_version` so OpenAI `/v1/responses` can be enabled explicitly while still using `langchain_openai:ChatOpenAI`.

**Extensions Configuration** (`extensions_config.json`):

MCP servers and skills are configured together in `extensions_config.json` in project root:

Configuration priority:
1. Explicit `config_path` argument
2. `DEER_FLOW_EXTENSIONS_CONFIG_PATH` environment variable
3. `extensions_config.json` in current directory (backend/)
4. `extensions_config.json` in parent directory (project root - **recommended location**)

### Gateway API (`app/gateway/`)

FastAPI application on port 8100 with health check at `GET /health`.

**Routers**:

| Router | Endpoints |
|--------|-----------|
| **Models** (`/api/models`) | `GET /` - list models; `GET /{name}` - model details |
| **MCP** (`/api/mcp`) | `GET /config` - get config; `PUT /config` - update config (saves to extensions_config.json) |
| **Skills** (`/api/skills`) | `GET /` - list skills; `GET /{name}` - details; `PUT /{name}` - update enabled; `POST /install` - install from .skill archive (accepts standard optional frontmatter like `version`, `author`, `compatibility`) |
| **Memory** (`/api/memory`) | `GET /` - memory data; `POST /reload` - force reload; `GET /config` - config; `GET /status` - config + data |
| **Uploads** (`/api/threads/{id}/uploads`) | `POST /` - upload files (auto-converts PDF/PPT/Excel/Word); `GET /list` - list; `DELETE /{filename}` - delete |
| **Threads** (`/api/threads/{id}`) | `DELETE /` - remove DeerFlow-managed local thread data after LangGraph thread deletion; unexpected failures are logged server-side and return a generic 500 detail |
| **Artifacts** (`/api/threads/{id}/artifacts`) | `GET /{path}` - serve artifacts; active content types (`text/html`, `application/xhtml+xml`, `image/svg+xml`) are always forced as download attachments to reduce XSS risk; `?download=true` still forces download for other file types |
| **Suggestions** (`/api/threads/{id}/suggestions`) | `POST /` - generate follow-up questions; rich list/block model content is normalized before JSON parsing |

Proxied through nginx: `/api/langgraph/*` → LangGraph, all other `/api/*` → Gateway.

### Sandbox System (`packages/harness/deerflow/sandbox/`)

**Interface**: Abstract `Sandbox` with `execute_command`, `read_file`, `write_file`, `list_dir`
**Provider Pattern**: `SandboxProvider` with `acquire`, `get`, `release` lifecycle
**Implementations**:
- `LocalSandboxProvider` - Singleton local filesystem execution with path mappings
- `AioSandboxProvider` (`packages/harness/deerflow/community/`) - Docker-based isolation

**Virtual Path System**:
- Agent sees: `/mnt/user-data/{workspace,uploads,outputs}`, `/mnt/skills`
- Physical: `backend/.deer-flow/threads/{thread_id}/user-data/...`, `deer-flow/skills/`
- Translation: `replace_virtual_path()` / `replace_virtual_paths_in_command()`
- Detection: `is_local_sandbox()` checks `sandbox_id == "local"`

**Tenant-aware bind mounts (M4, `ENABLE_IDENTITY=true`)**: When `SandboxMiddleware` observes a valid `(tenant_id, workspace_id)` pair on `state["identity"]`, `SandboxProvider.acquire(thread_id, *, tenant_id, workspace_id)` resolves stratified host-side sources under `$DEER_FLOW_HOME/tenants/{tid}/workspaces/{wid}/threads/{thread_id}/user-data/...` and `/.../acp-workspace/`. The container-side destinations remain unchanged (`/mnt/user-data/{workspace,uploads,outputs}`, `/mnt/acp-workspace`), so agent prompts and tool contracts are stable. Cross-tenant path escapes are rejected at two layers: `Paths.resolve_virtual_path(..., tenant_id=..., workspace_id=...)` (raises `PathEscapeError`) and the per-scan root-boundary check inside sandbox bind-mount assembly. Legacy single-tenant behavior is preserved when either id is absent (both `LocalSandboxProvider` and `AioSandboxProvider`).

**Sandbox Tools** (in `packages/harness/deerflow/sandbox/tools.py`):
- `bash` - Execute commands with path translation and error handling
- `ls` - Directory listing (tree format, max 2 levels)
- `read_file` - Read file contents with optional line range
- `write_file` - Write/append to files, creates directories
- `str_replace` - Substring replacement (single or all occurrences); same-path serialization is scoped to `(sandbox.id, path)` so isolated sandboxes do not contend on identical virtual paths inside one process

### Subagent System (`packages/harness/deerflow/subagents/`)

**Built-in Agents**: `general-purpose` (all tools except `task`) and `bash` (command specialist)
**Execution**: Dual thread pool - `_scheduler_pool` (3 workers) + `_execution_pool` (3 workers)
**Concurrency**: `MAX_CONCURRENT_SUBAGENTS = 3` enforced by `SubagentLimitMiddleware` (truncates excess tool calls in `after_model`), 15-minute timeout
**Flow**: `task()` tool → `SubagentExecutor` → background thread → poll 5s → SSE events → result
**Events**: `task_started`, `task_running`, `task_completed`/`task_failed`/`task_timed_out`

### Tool System (`packages/harness/deerflow/tools/`)

`get_available_tools(groups, include_mcp, model_name, subagent_enabled)` assembles:
1. **Config-defined tools** - Resolved from `config.yaml` via `resolve_variable()`
2. **MCP tools** - From enabled MCP servers (lazy initialized, cached with mtime invalidation)
3. **Built-in tools**:
   - `present_files` - Make output files visible to user (only `/mnt/user-data/outputs`)
   - `ask_clarification` - Request clarification (intercepted by ClarificationMiddleware → interrupts)
   - `view_image` - Read image as base64 (added only if model supports vision)
4. **Subagent tool** (if enabled):
   - `task` - Delegate to subagent (description, prompt, subagent_type, max_turns)

**Community tools** (`packages/harness/deerflow/community/`):
- `tavily/` - Web search (5 results default) and web fetch (4KB limit)
- `jina_ai/` - Web fetch via Jina reader API with readability extraction
- `firecrawl/` - Web scraping via Firecrawl API

**ACP agent tools**:
- `invoke_acp_agent` - Invokes external ACP-compatible agents from `config.yaml`
- ACP launchers must be real ACP adapters. The standard `codex` CLI is not ACP-compatible by itself; configure a wrapper such as `npx -y @zed-industries/codex-acp` or an installed `codex-acp` binary
- Missing ACP executables now return an actionable error message instead of a raw `[Errno 2]`
- Each ACP agent uses a per-thread workspace at `{base_dir}/threads/{thread_id}/acp-workspace/`. The workspace is accessible to the lead agent via the virtual path `/mnt/acp-workspace/` (read-only). In docker sandbox mode, the directory is volume-mounted into the container at `/mnt/acp-workspace` (read-only); in local sandbox mode, path translation is handled by `tools.py`
- `image_search/` - Image search via DuckDuckGo

### MCP System (`packages/harness/deerflow/mcp/`)

- Uses `langchain-mcp-adapters` `MultiServerMCPClient` for multi-server management
- **Lazy initialization**: Tools loaded on first use via `get_cached_mcp_tools()`
- **Cache invalidation**: Detects config file changes via mtime comparison
- **Transports**: stdio (command-based), SSE, HTTP
- **OAuth (HTTP/SSE)**: Supports token endpoint flows (`client_credentials`, `refresh_token`) with automatic token refresh + Authorization header injection
- **Runtime updates**: Gateway API saves to extensions_config.json; LangGraph detects via mtime

### Skills System (`packages/harness/deerflow/skills/`)

- **Location**: `deer-flow/skills/{public,custom}/`
- **Format**: Directory with `SKILL.md` (YAML frontmatter: name, description, license, allowed-tools)
- **Loading**: `load_skills()` recursively scans `skills/{public,custom}` for `SKILL.md`, parses metadata, and reads enabled state from extensions_config.json
- **Injection**: Enabled skills listed in agent system prompt with container paths
- **Installation**: `POST /api/skills/install` extracts .skill ZIP archive to custom/ directory

**Tenant-aware loading (M4, `ENABLE_IDENTITY=true`)**: When `load_skills(..., *, tenant_id=..., workspace_id=...)` is called with a resolved tenant/workspace pair, the loader scans three roots in order under `$DEER_FLOW_HOME`:

1. `skills/public/` — cross-tenant, shared skills (same physical dir used in legacy mode)
2. `tenants/{tid}/custom/` — tenant-scoped skills
3. `tenants/{tid}/workspaces/{wid}/user/` — workspace user-tier skills

Collisions on the same skill name resolve with **later-in-order winning** (workspace > tenant > public), so operators can override a tenant skill per workspace or a public skill per tenant. Symlinks whose real path escapes outside the current scan's allowed root are skipped with a warning (protected by `assert_symlink_parent_safe`). Tenant-level `extensions_config.json` (under `tenants/{tid}/`) can **disable** globally-enabled skills but **cannot re-enable** skills that are disabled at the global layer — disable-only semantics keep tenant overrides from loosening the platform default. Legacy single-tenant behavior is preserved when either id is missing.

### Identity Subsystem (`app/gateway/identity/`)

**Status:** M1 (schema + bootstrap), M2 (authentication), M3 (RBAC + tenant-scope auto-filter), M4 (storage isolation), M5 (LangGraph identity propagation), and M6 (audit pipeline) landed. Gated behind `ENABLE_IDENTITY` env var (default off).

**Components**:
- `settings.py` — reads `ENABLE_IDENTITY`, `DEERFLOW_DATABASE_URL`, `DEERFLOW_REDIS_URL`, `DEERFLOW_BOOTSTRAP_ADMIN_EMAIL`, `DEER_FLOW_HOME` (M4 storage root, default `backend/.deer-flow`), plus M2 auth knobs (`DEERFLOW_JWT_*`, `DEERFLOW_ACCESS_TOKEN_TTL_SEC`, `DEERFLOW_REFRESH_TOKEN_TTL_SEC`, `DEERFLOW_COOKIE_*`, `DEERFLOW_LOGIN_LOCKOUT_*`, `DEERFLOW_BCRYPT_COST`, `DEERFLOW_INTERNAL_SIGNING_KEY`, `IDENTITY_AUTO_PROVISION_TENANT`)
- `models/` — 11 ORM tables matching spec §4 (tenants, users, memberships, workspaces, permissions, roles, role_permissions, user_roles, workspace_members, api_tokens, audit_logs). `TenantScoped` / `WorkspaceScoped` mixins (`models/base.py`) mark rows for auto-filter — new M4 tables subscribe by declaring the mixin.
- `db.py` — async engine, session factory, `get_session()` dependency
- `context.py` — `current_identity` / `current_tenant_id` / `current_session_id` ContextVars, plus M3's `with_platform_privilege()` context manager that temporarily bypasses the tenant auto-filter (for maintenance scripts, admin jobs).
- `bootstrap.py` — idempotent seed (roles, permissions, default tenant/workspace, first admin)
- `cli.py` — `python -m app.gateway.identity.cli bootstrap`
- **M2** `auth/` — `Identity` dataclass (M3 adds `has_permission`/`in_tenant`/`in_workspace`/`is_platform_admin` helpers + `ip` field); `jwt.py` (RS256 issue/verify, refresh token generator, `ensure_rsa_keypair`); `session.py` (Redis SessionStore); `lockout.py` (LoginLockout); `api_token.py` (create/verify/revoke `dft_*` tokens, bcrypt at rest); `oidc.py` (login redirect + callback, PKCE + state + nonce in Redis); `config.py` (OIDC provider loader from `config/identity.yaml`); `identity_factory.py` (first-login upsert + tenant resolution + Identity flattening); `dependencies.py` (`require_authenticated`, `get_current_identity` FastAPI deps); `runtime.py` (shared AuthRuntime handle populated at lifespan)
- **M2** `middlewares/identity.py` — `IdentityMiddleware`: reads `Authorization` header or session cookie, resolves to `Identity` (anonymous on failure), sets `request.state.identity` + ContextVars; M3 also populates `identity.ip` from the client host for audit events.
- **M2** `routers/auth.py` (`/api/auth/oidc/{provider}/login`, `/api/auth/oidc/{provider}/callback`, `/api/auth/refresh`, `/api/auth/logout`)
- **M2** `routers/me.py` (`/api/me`, `/api/me/switch-tenant`, `/api/me/tokens`, `/api/me/sessions`, `PATCH /api/me`)
- **M3** `rbac/` — `decorator.py` exports `requires(tag, scope)` (FastAPI dependency factory); `errors.py` (`PermissionDeniedError`); `permission_cache.py` (Redis-backed `PermissionCache` for API-token callers, 300s TTL — JWT callers don't need it because permissions are in the claims).
- **M3** `middlewares/tenant_scope.py` — `install_auto_filter(session_maker)` registers SQLAlchemy `do_orm_execute` and `before_flush` listeners. SELECTs are auto-filtered by `identity.tenant_id` (and `workspace_id IN (...)` when the mixin applies); cross-tenant / cross-workspace INSERTs raise `PermissionDeniedError`. Platform admins bypass both. `with_platform_privilege()` extends that bypass to any identity for maintenance paths.
- **M3** `routers/roles.py` (`GET /api/roles`, `GET /api/permissions`) — read-only, require only `require_authenticated`. Admin UI and frontend guards consume these.
- **M3** `routers/admin_stub.py` — placeholder routes (`/api/tenants/{tid}/workspaces/{wid}/threads`, `/api/tenants/{tid}/workspaces/{wid}/skills/{skid}`, `/api/tenants/{tid}/workspaces`, `/api/admin/tenants`) that exist to exercise `@requires` in tests. M4 and M7 replace them with real handlers — **do not rely on these shapes in production callers.**

**Schema + ops:**
```bash
make db-upgrade           # run alembic migrations
make db-downgrade-one     # rollback one revision
make identity-bootstrap   # run bootstrap seed manually
make identity-keys        # generate (or reuse) the M2 RS256 keypair
make identity-dirs TENANT_ID=<id> [WORKSPACE_ID=<id>]  # M4 tenant/workspace dir bootstrap (0700 perms, idempotent)
make identity-test        # run identity test suite (needs postgres+redis)
```

**OIDC provider setup (M2):** copy `config/identity.yaml.example` to `config/identity.yaml` and fill in provider credentials. Providers listed there become available at `/api/auth/oidc/{provider}/login`. Override the path with `DEERFLOW_IDENTITY_CONFIG`.

**Auth runtime (M2):** on startup with flag on, the gateway ensures an RS256 keypair on disk (default `$DEERFLOW_HOME/_system/jwt_{private,public}.pem`, 0600/0644), opens a Redis client, loads OIDC providers, and builds a shared `AuthRuntime` consumed by the middleware and routers.

**Cookie flow (M2):** the access token lives in the `deerflow_session` HttpOnly cookie (`Secure` in prod, `SameSite=Lax`). The refresh token is stored server-side in Redis only. `POST /api/auth/refresh` re-issues an access token from the `sid` embedded in the current (possibly expired) token, as long as the Redis session record still exists.

**When flag is OFF:** identity subsystem is completely inert. No DB connection attempted, no middleware registered, auth/me routers are not included, legacy endpoints unchanged. Verified by `tests/identity/test_feature_flag_offline.py` and `tests/identity/test_gateway_identity_lifespan.py::test_auth_routes_absent_when_flag_off`.

**When flag is ON:** gateway lifespan initializes engine + session factory, runs `bootstrap()`, builds the `AuthRuntime`, and then proceeds with LangGraph runtime. Bootstrap is idempotent (safe to restart).

**Note on `user_roles` table:** `tenant_id` is nullable (NULL = platform-scoped grant, e.g. `platform_admin`). Since Postgres PK columns must be NOT NULL, `user_roles` uses a surrogate `id` primary key plus `UNIQUE(user_id, tenant_id, role_id)` and a partial unique index to enforce at-most-one platform grant per (user, role).

**Note on M2 vs M3 enforcement:** M2 never returns 401 from `IdentityMiddleware` — unknown/expired/revoked credentials all resolve to `Identity.anonymous()`. M3's `@requires(tag, scope)` dependency maps anonymous callers to 401 (`UNAUTHENTICATED`) and missing permissions to 403 (`PERMISSION_DENIED`, with `missing` field for UI). When you only need authentication (no permission tag), use `Depends(require_authenticated)` — it raises 401 on its own.

**Using `@requires` on new routes:**

```python
from fastapi import Depends
from app.gateway.identity.rbac.decorator import requires

@router.post(
    "/api/tenants/{tid}/workspaces/{wid}/threads",
    dependencies=[Depends(requires("thread:write", "workspace"))],
)
async def create_thread(tid: int, wid: int): ...
```

Scopes: `"platform"` (permission check only), `"tenant"` (also verifies caller is in `{tid}`/`{tenant_id}`), `"workspace"` (also verifies caller is in `{wid}`/`{workspace_id}`/`{ws_id}`). A `scope="tenant"` route with no tenant path param falls through to the permission check — this is how cross-tenant list endpoints like `/api/admin/tenants` are expressed.

**SQLAlchemy auto-filter:** When `ENABLE_IDENTITY=true`, `install_auto_filter(sessionmaker)` attaches `do_orm_execute` and `before_flush` listeners to the global Session class. Any mapped class that inherits `TenantScoped` or `WorkspaceScoped` gets an automatic `WHERE tenant_id = ?` / `workspace_id IN (...)` clause injected into every SELECT. Platform admins bypass; regular users cannot escape their tenant even via a JOIN. Insert guard rejects cross-tenant / cross-workspace writes with `PermissionDeniedError`. Use `with_platform_privilege()` (from `app.gateway.identity.context`) to opt out of the filter for migration scripts or admin jobs — it's logged at INFO so privileged access leaves a trail.

**Storage (M4):**

- `app/gateway/identity/storage/paths.py` — 13 tenant-aware path helpers (`deerflow_home`, `tenant_root`, `workspace_root`, `thread_path`, `skills_public_root`, `skills_tenant_custom_root`, `skills_workspace_user_root`, `user_memory_path`, `tenant_shared_root`, `audit_fallback_path`, `audit_archive_path`, `migration_report_path`, `migration_lock_path`). All are derived from `$DEER_FLOW_HOME` (default `backend/.deer-flow`) and follow the spec §7.1 / §7.4 layout:

  ```
  $DEER_FLOW_HOME/
    tenants/{tenant_id}/
      custom/                      # tenant-scoped skills
      shared/                      # reserved for P2
      users/{user_id}/memory.json  # per-user memory
      workspaces/{workspace_id}/
        user/                      # workspace user-tier skills
        threads/{thread_id}/
          user-data/{workspace,uploads,outputs}
          acp-workspace/
    skills/public/                 # cross-tenant shared skills
    _system/
      audit_fallback/{yyyymmdd}.jsonl
      audit_archive/{tid}/{yyyy-mm}.jsonl.gz
      migration_report_{ts}.json
      migration.lock
  ```

- `app/gateway/identity/storage/path_guard.py` — `PathEscapeError`, `assert_within_tenant_root(path, tenant_id)`, `safe_join(base, *parts)`, `assert_symlink_parent_safe(path, allowed_root)`. Every tenant-scoped I/O path in Gateway/harness routes through these guards.
- `app/gateway/identity/storage/config_layers.py` — `load_layered_config(global_cfg, tenant_id, workspace_id, *, deerflow_home) -> (merged, cache_key)` layers `global → tenant → workspace` YAML fragments. Tenant/workspace overlays cannot set `SENSITIVE_GLOBAL_ONLY` fields (model API keys, model endpoints, provisioner keys, memory storage path) — any attempt raises `SensitiveFieldViolation`. The function is pure (returns `(merged, cache_key)`); Redis caching is the consumer layer's responsibility.
- `app/gateway/identity/storage/cli.py` + `make identity-dirs TENANT_ID=X [WORKSPACE_ID=Y]` — idempotent directory bootstrap that creates the tenant tree with `0700` permissions. Safe to re-run; missing dirs are created, existing dirs are left alone.
- **Harness tenant-aware paths**: `packages/harness/deerflow/config/paths.py::Paths` gained `resolve_thread_dir`, `resolve_sandbox_{work,uploads,outputs,user_data}_dir`, `resolve_acp_workspace_dir`, `ensure_thread_dirs_for`, and their host-side variants. Legacy methods are untouched so single-tenant callers keep working. `resolve_virtual_path` accepts optional `tenant_id`/`workspace_id` kwargs.
- **Identity extraction helper**: `packages/harness/deerflow/agents/middlewares/_identity.py::extract_tenant_ids()` is the shared defensive reader for `state["identity"]` — returns `(tenant_id, workspace_id)` only when both are positive ints, otherwise `(None, None)`. Consumed by `ThreadDataMiddleware`, `SandboxMiddleware`, `UploadsMiddleware`, and `present_file_tool`.
- **Middleware / router consumption**: `ThreadDataMiddleware` and `SandboxMiddleware` read `state["identity"]` and route through the tenant-aware path helpers when the pair is valid. Gateway routers `routers/artifacts.py` and `routers/uploads.py` enforce `assert_within_tenant_root` on every GET/POST/LIST/DELETE; cross-tenant attempts return a generic `403 "Access denied"` (no leak of tenant IDs or filesystem paths). Flag off → legacy flat paths.
- **Channel identity**: `app/channels/manager.py::_resolve_channel_identity` reads `tenant_id`/`workspace_id` from `channel_sessions.<name>` (falling back to `default_session`) when `ENABLE_IDENTITY=true`. `ChannelManager._create_thread` persists the pair into `ChannelStore` at thread creation time; `_handle_chat` + `_handle_streaming_chat` read them back via `get_thread_mapping` and pass them to `paths.resolve_virtual_path` so IM artifacts land under the tenant-stratified outputs directory. Flag off → both values `None` → legacy single-tenant path preserved.

**LangGraph identity propagation (M5):**

- **HMAC header contract (`app/gateway/identity/propagation.py` + harness-side `deerflow.identity_propagation`):** Gateway signs the caller's `Identity` into `X-Deerflow-User-Id`, `X-Deerflow-Tenant-Id`, `X-Deerflow-Workspace-Id`, `X-Deerflow-Permissions`, `X-Deerflow-Session-Id`, `X-Deerflow-Identity-Ts`, `X-Deerflow-Identity-Sig` using `HMAC-SHA256(DEERFLOW_INTERNAL_SIGNING_KEY)` over `"{uid}|{tid}|{wid}|{perms_sorted}|{ts}"`. Canonical form + signer/verifier live in the harness so the agent runtime can verify without importing `app.*`. Replay window defaults to 300s (`DEERFLOW_HMAC_SKEW_SEC`).
- **Outbound injection (`app/gateway/services._inject_identity_headers`):** `start_run()` stamps the signed header dict into `config["configurable"]["headers"]` on every run. Active `workspace_id` resolution order: explicit `configurable.workspace_id` → path param `wid`/`workspace_id`/`ws_id` → caller's first workspace membership. No-ops when the flag is off, signing key is missing, or the caller is anonymous.
- **LangGraph `IdentityMiddleware` (`packages/harness/deerflow/agents/middlewares/identity_middleware.py`):** Registered at position 0 of the lead-agent middleware chain whenever `DEERFLOW_INTERNAL_SIGNING_KEY` is set (flag-scoped). Verifies headers, writes a `VerifiedIdentity` into `state["identity"]`. Tampered signatures and stale timestamps raise so the run fails loud. Missing headers is a silent no-op (backwards compat).
- **Guardrail upgrade (`deerflow.guardrails.IdentityGuardrailMiddleware` + `TOOL_PERMISSION_MAP`):** Whitelist-mode permission gate sitting just before the (optional) OAP/allowlist `GuardrailMiddleware`. Denies unknown tools by default; mapped built-ins enforce their required tag (`bash`/`write_file`/`str_replace`/`task` → `thread:write`, `read_file`/`ls`/`present_files`/`view_image`/`ask_clarification` → `thread:read`). MCP tools may declare `required_permission` on their `BaseTool`; otherwise `DEFAULT_MCP_PERMISSION = "skill:invoke"` applies. `write_todos` is an internal-plumbing allowlist bypass. Flag-off / missing identity → fall through (no regression). Also registered only when the signing key is set.
- **Subagent inheritance (`deerflow.subagents.SubagentExecutor(identity=...)` + `task_tool`):** `task_tool` reads `runtime.state["identity"]` and forwards it to the executor; `_build_initial_state` copies it into the subagent's starting state. The subagent's `IdentityMiddleware` detects the pre-populated state and does not overwrite, so the parent's identity propagates without a second HMAC roundtrip. Frozen permissions set = no elevation surface.
- **Internal audit endpoint (`POST /internal/audit`):** HMAC-authenticated (separate `X-Deerflow-Internal-Sig` / `X-Deerflow-Internal-Ts` headers over `body|ts`). Payload matches `AuditEventPayload` (action + tenant/user/workspace/thread/resource/outcome). M6 forwards the event into the real `AuditBatchWriter` when `app.state.audit_writer` is set; falls back to the legacy in-memory queue when it isn't (preserving M5 test contracts).

**Audit pipeline (M6, `app/gateway/identity/audit/`):**

- `events.py` — `AuditEvent` frozen dataclass + `KNOWN_ACTIONS` taxonomy + `KEY_CRITICAL_ACTIONS` subset. `is_critical_action(action, http_method=...)` is the single decision point: enumerated criticals or any HTTP write method always go through the fallback path on PG outage.
- `redact.py` — `redact_metadata(action, raw)`: scrubs values of any key matching `/password|token|secret|key|authorization/i` to `***`, drops `http.body`/`body`/`request_body`/`response_body`, truncates `command`/`cmd` to 500 chars, and special-cases `tool.called(write_file)` to keep `path`+`size` while dropping `content`. Recurses through nested dicts and lists.
- `fallback.py` — `FallbackLog` is an `asyncio.Lock`-serialised JSONL writer at `$DEER_FLOW_HOME/_audit/fallback.jsonl`. `drain()` rotates the file before reading so concurrent writers don't lose events; on read failure the rotated file is restored.
- `writer.py` — `AuditBatchWriter` runs a single background `_flush_loop` (max `flush_interval_sec=1.0`, `batch_size=500`, `queue_max=10_000`). Queue full + critical → synchronous insert (with PG-failure fallback). Queue full + non-critical → drop + `metrics["dropped"]++`. PG failure during a batch → critical events route to the fallback log, non-critical are dropped. Backfill happens at the start of each successful flush (cheap when no file exists).
- `middleware.py` — `AuditMiddleware` registered as the outermost HTTP middleware (wraps `IdentityMiddleware` so it sees `request.state.identity` after downstream populates it). Skips `/api/me`, `/health`, `/docs`, `/internal/*`, `/api/langgraph`. Audits all writes; reads only on `/api/auth/*`, `/api/audit*`, `/api/admin/*`, `/api/tenants/*`, or 401/403 responses. Action derivation maps OIDC callbacks to `user.login.{success,failure}`, `/logout` to `user.logout`, 401/403 to `authz.api.denied`, everything else to `http.<method>`.
- `api.py` — `GET /api/tenants/{tid}/audit` (paginated, base64url cursor of `created_at|id`, default 7-day / max 90-day window, `limit` 1–500), `GET /api/tenants/{tid}/audit/export` (StreamingResponse CSV, hard-capped at 100k rows → 413, emits its own `audit.exported` event), `GET /api/admin/audit` (cross-tenant, requires `audit:read.all`).
- `retention.py` — `run_retention_job(session_maker, retention_days=90, archive_dir=...)`: archives `(tenant_id, year_month)`-grouped rows older than the cutoff into `{archive_dir}/{tenant_id}/{yyyy-mm}.jsonl.gz`, then deletes the same row IDs in the same transaction (idempotent on retry). `start_retention_task` wraps it in an asyncio loop with stop-event for daily cron.
- `alembic/versions/20260421_0003_audit_grants.py` — REVOKE UPDATE/DELETE on `identity.audit_logs` from the `deerflow` app role; GRANT INSERT+SELECT only. A `deerflow_retention` role gets DELETE for the retention job. Falls through silently when those roles don't exist (dev superuser deploys are unaffected since superuser bypasses GRANT).

**Audit producers wired in M6:**
- M3 RBAC `_queue_denied()` enqueues `authz.api.denied` (critical) when the writer is mounted.
- M5 `POST /internal/audit` forwards to the writer with `is_critical_action(payload.action)`.
- Auth router actions (login/logout/refresh) ride on the `AuditMiddleware` HTTP-event capture — no inline enqueues needed.

**Audit env vars:**
- `DEER_FLOW_HOME` — fallback JSONL + retention archive root (reused from M4).
- Retention day count, archive dir, and schedule interval are currently passed at task-spawn time; they're not yet env-tunable. (M7 may surface them.)

**When flag is OFF:** none of the M6 components are imported by lifespan, no batch writer task is spawned, no PG insert is attempted, and `/api/tenants/*/audit*` + `/api/admin/audit` return 404. Verified by `tests/identity/test_feature_flag_offline.py::test_audit_routes_404_when_flag_off`.

**M7 migration pipeline (`app/gateway/identity/migration/`):**

The one-shot migration script at `scripts/migrate_to_multitenant.py` walks the three legacy source trees and moves them into the multi-tenant layout established in M4 (spec §10.2).

- `planner.py` — `build_plan(legacy_home, repo_root, tenant_id, workspace_id, ...)` enumerates direct children of `{home}/threads/`, `{repo}/skills/custom/`, `{repo}/skills/user/`, tagging each with `ItemKind` (`THREAD` | `SKILL_CUSTOM` | `SKILL_USER`) and a deterministic `target` derived from the M4 `storage/paths.py` helpers. Items whose source is already a symlink resolving to `target` are marked `already_migrated=True` so re-runs are a safe no-op.
- `executor.py` — `apply_plan(plan, report_path, *, audit_writer=None, dry_run=False)` iterates the plan, `os.rename`s source → target (falls back to `shutil.move` on `EXDEV`), drops a forwarder symlink at the old path, and verifies byte-count parity. Skill symlinks are validated via `assert_symlink_parent_safe` against `tenant_root(tid)` so a post-rename tamper cannot route to another tenant's subtree. Emits `system.migration.item.moved` audit events (critical=True) when a writer is wired. Report is fsync'd every 50 items so a mid-run crash leaves a partial, readable JSON.
- `rollback.py` — `rollback_plan(plan, report_path, ...)` reverses the executor: removes the forwarder symlink, renames target → source. Operates on reverse order. Safe to re-run.
- `report.py` — `MigrationReport` + atomic `write_report(path, report)` (temp file + fsync + replace + dir fsync) with JSON shape `{mode, tenant_id, workspace_id, started_at, ended_at, counts, errors, items[]}`.
- `lock.py` — `file_lock(path)` uses `fcntl.LOCK_EX | LOCK_NB` on `migration_lock_path()`; `pg_advisory_lock(engine)` holds `pg_try_advisory_lock(hashtext('deerflow_migration'))` for the run so K8s multi-replica invocations fail-fast rather than race. Both raise `LockAcquireError` on contention.

**CLI** at `scripts/migrate_to_multitenant.py` (also wired into `backend/Makefile`):

```bash
make identity-migrate-dry                      # plan + report, no filesystem writes
make identity-migrate-apply                    # real migration (takes both locks, writes audit events)
make identity-migrate-rollback REPORT=<path>   # reverse a prior apply using its report
```

Exit codes: `0` success, `1` pre-check failure (DB or home not writable), `2` argument error, `3` lock contention, `4` one or more items failed. `--no-db` skips the PG connectivity pre-check and the advisory lock for air-gapped rehearsals; `--legacy-home` + `--repo-root` redirect the source roots for tests. When a DB engine is wired, audit events route to the M6 fallback JSONL at `$DEER_FLOW_HOME/_audit/fallback.jsonl` so the batch writer's next backfill pushes them into Postgres.

**M7 release hardening (C.1 – C.5 + C.7):**

- `app/gateway/identity/bootstrap_lock.py` — `bootstrap_with_advisory_lock(engine, session, *, bootstrap_admin_email=None)` wraps the M1 `bootstrap()` seed inside a blocking PG advisory lock (`pg_advisory_lock(hashtext('deerflow_bootstrap'))`), so K8s rolling restarts cannot race on idempotent seed inserts. Lock runs on a **separate** connection from the seed session so it survives the inner `session.commit()`. On acquire failure the wrapper degrades to the pre-M7 path with a logged warning — preserves prior behaviour rather than deadlocking startup. Wired into `app/gateway/app.py::_init_identity_subsystem`.
- `app/gateway/identity/metrics.py` — dependency-free Prometheus text-format exporter. Process-wide `IdentityMetrics` singleton with thread-safe counters: `identity_login_total{result=success|failure}`, `identity_authz_denied_total` (counters — recorded by `AuditMiddleware._emit_identity_metric` when it observes matching actions) plus `identity_session_active` (gauge — `SessionStore.count_active()`), `audit_queue_depth` (gauge — `AuditBatchWriter.qsize()`), and `audit_write_failures_total` (counter — `flush_errors + fallback_written` from the writer's `metrics` dict).
- `app/gateway/identity/routers/metrics.py` — `GET /metrics` returning the canonical `text/plain; version=0.0.4` payload. Unauthenticated (scrape is network-level gated) and included only when `ENABLE_IDENTITY=true`; absent → 404 otherwise (`tests/identity/test_feature_flag_offline.py::test_metrics_route_absent_when_flag_off`).
- `app/gateway/identity/auth/session.py::SessionStore.count_active()` — SCAN-based Redis probe that returns the count of non-revoked sessions; used once per scrape.
- `app/gateway/identity/audit/middleware.py` — `dispatch` mirrors enqueued events through `_emit_identity_metric(action)` so the Prometheus counters track the same population the audit log does.

Lifespan attaches the writer + session source to the metrics singleton in `_init_audit_subsystem` and detaches them in `_shutdown_audit_subsystem`, so the gauges never read a stopped writer or a disposed Redis client.

Docs: `docs/UPGRADE_v2.md` (path A greenfield / path B migration), `docs/identity-alerting.md` (sample Prometheus alert rules + Grafana panels), `docs/identity-release-checklist.md` (spec §11.7 manual runbook — IdP smoke tests, 1 000-thread rehearsal, rollback drill), `CHANGELOG.md` (identity release notes).

**Still open for a follow-up session:** None — M7 Part C.8 (GitHub Actions identity E2E smoke) shipped via `.github/workflows/identity-e2e-smoke.yml` (bypasses OIDC by minting an RS256 JWT directly for the bootstrap admin); channel identity TODO resolved via `ChannelStore` persistence of `tenant_id`/`workspace_id` and `Paths.resolve_virtual_path` wiring.

**Roadmap:** M1 – M6 + M7 B (migration) + M7 C (release hardening) shipped. M7 A (admin UI) still open. See `docs/superpowers/specs/2026-04-21-deerflow-identity-foundation-design.md`.

### Model Factory (`packages/harness/deerflow/models/factory.py`)

- `create_chat_model(name, thinking_enabled)` instantiates LLM from config via reflection
- Supports `thinking_enabled` flag with per-model `when_thinking_enabled` overrides
- Supports vLLM-style thinking toggles via `when_thinking_enabled.extra_body.chat_template_kwargs.enable_thinking` for Qwen reasoning models, while normalizing legacy `thinking` configs for backward compatibility
- Supports `supports_vision` flag for image understanding models
- Config values starting with `$` resolved as environment variables
- Missing provider modules surface actionable install hints from reflection resolvers (for example `uv add langchain-google-genai`)

### vLLM Provider (`packages/harness/deerflow/models/vllm_provider.py`)

- `VllmChatModel` subclasses `langchain_openai:ChatOpenAI` for vLLM 0.19.0 OpenAI-compatible endpoints
- Preserves vLLM's non-standard assistant `reasoning` field on full responses, streaming deltas, and follow-up tool-call turns
- Designed for configs that enable thinking through `extra_body.chat_template_kwargs.enable_thinking` on vLLM 0.19.0 Qwen reasoning models, while accepting the older `thinking` alias

### IM Channels System (`app/channels/`)

Bridges external messaging platforms (Feishu, Slack, Telegram) to the DeerFlow agent via the LangGraph Server.

**Architecture**: Channels communicate with the LangGraph Server through `langgraph-sdk` HTTP client (same as the frontend), ensuring threads are created and managed server-side.

**Components**:
- `message_bus.py` - Async pub/sub hub (`InboundMessage` → queue → dispatcher; `OutboundMessage` → callbacks → channels)
- `store.py` - JSON-file persistence mapping `channel_name:chat_id[:topic_id]` → `{thread_id, tenant_id, workspace_id, user_id, ...}` (keys are `channel:chat` for root conversations and `channel:chat:topic` for threaded conversations). When `ENABLE_IDENTITY` is off (or channel config omits the pair), `tenant_id`/`workspace_id` are stored as `null` and resolvers fall back to the legacy flat path.
- `manager.py` - Core dispatcher: creates threads via `client.threads.create()`, routes commands, keeps Slack/Telegram on `client.runs.wait()`, and uses `client.runs.stream(["messages-tuple", "values"])` for Feishu incremental outbound updates
- `base.py` - Abstract `Channel` base class (start/stop/send lifecycle)
- `service.py` - Manages lifecycle of all configured channels from `config.yaml`
- `slack.py` / `feishu.py` / `telegram.py` - Platform-specific implementations (`feishu.py` tracks the running card `message_id` in memory and patches the same card in place)

**Message Flow**:
1. External platform -> Channel impl -> `MessageBus.publish_inbound()`
2. `ChannelManager._dispatch_loop()` consumes from queue
3. For chat: look up/create thread on LangGraph Server
4. Feishu chat: `runs.stream()` → accumulate AI text → publish multiple outbound updates (`is_final=False`) → publish final outbound (`is_final=True`)
5. Slack/Telegram chat: `runs.wait()` → extract final response → publish outbound
6. Feishu channel sends one running reply card up front, then patches the same card for each outbound update (card JSON sets `config.update_multi=true` for Feishu's patch API requirement)
7. For commands (`/new`, `/status`, `/models`, `/memory`, `/help`): handle locally or query Gateway API
8. Outbound → channel callbacks → platform reply

**Configuration** (`config.yaml` -> `channels`):
- `langgraph_url` - LangGraph Server URL (default: `http://localhost:2024`)
- `gateway_url` - Gateway API URL for auxiliary commands (default: `http://localhost:8100`)
- In Docker Compose, IM channels run inside the `gateway` container, so `localhost` points back to that container. Use `http://langgraph:2024` / `http://gateway:8001`, or set `DEER_FLOW_CHANNELS_LANGGRAPH_URL` / `DEER_FLOW_CHANNELS_GATEWAY_URL`.
- Per-channel configs: `feishu` (app_id, app_secret), `slack` (bot_token, app_token), `telegram` (bot_token)

### Memory System (`packages/harness/deerflow/agents/memory/`)

**Components**:
- `updater.py` - LLM-based memory updates with fact extraction, whitespace-normalized fact deduplication (trims leading/trailing whitespace before comparing), and atomic file I/O
- `queue.py` - Debounced update queue (per-thread deduplication, configurable wait time)
- `prompt.py` - Prompt templates for memory updates

**Data Structure** (stored in `backend/.deer-flow/memory.json`):
- **User Context**: `workContext`, `personalContext`, `topOfMind` (1-3 sentence summaries)
- **History**: `recentMonths`, `earlierContext`, `longTermBackground`
- **Facts**: Discrete facts with `id`, `content`, `category` (preference/knowledge/context/behavior/goal), `confidence` (0-1), `createdAt`, `source`

**Workflow**:
1. `MemoryMiddleware` filters messages (user inputs + final AI responses) and queues conversation
2. Queue debounces (30s default), batches updates, deduplicates per-thread
3. Background thread invokes LLM to extract context updates and facts
4. Applies updates atomically (temp file + rename) with cache invalidation, skipping duplicate fact content before append
5. Next interaction injects top 15 facts + context into `<memory>` tags in system prompt

Focused regression coverage for the updater lives in `backend/tests/test_memory_updater.py`.

**Configuration** (`config.yaml` → `memory`):
- `enabled` / `injection_enabled` - Master switches
- `storage_path` - Path to memory.json
- `debounce_seconds` - Wait time before processing (default: 30)
- `model_name` - LLM for updates (null = default model)
- `max_facts` / `fact_confidence_threshold` - Fact storage limits (100 / 0.7)
- `max_injection_tokens` - Token limit for prompt injection (2000)

### Reflection System (`packages/harness/deerflow/reflection/`)

- `resolve_variable(path)` - Import module and return variable (e.g., `module.path:variable_name`)
- `resolve_class(path, base_class)` - Import and validate class against base class

### Config Schema

**`config.yaml`** key sections:
- `models[]` - LLM configs with `use` class path, `supports_thinking`, `supports_vision`, provider-specific fields
- vLLM reasoning models should use `deerflow.models.vllm_provider:VllmChatModel`; for Qwen-style parsers prefer `when_thinking_enabled.extra_body.chat_template_kwargs.enable_thinking`, and DeerFlow will also normalize the older `thinking` alias
- `tools[]` - Tool configs with `use` variable path and `group`
- `tool_groups[]` - Logical groupings for tools
- `sandbox.use` - Sandbox provider class path
- `skills.path` / `skills.container_path` - Host and container paths to skills directory
- `title` - Auto-title generation (enabled, max_words, max_chars, prompt_template)
- `summarization` - Context summarization (enabled, trigger conditions, keep policy)
- `subagents.enabled` - Master switch for subagent delegation
- `memory` - Memory system (enabled, storage_path, debounce_seconds, model_name, max_facts, fact_confidence_threshold, injection_enabled, max_injection_tokens)

**`extensions_config.json`**:
- `mcpServers` - Map of server name → config (enabled, type, command, args, env, url, headers, oauth, description)
- `skills` - Map of skill name → state (enabled)

Both can be modified at runtime via Gateway API endpoints or `DeerFlowClient` methods.

### Embedded Client (`packages/harness/deerflow/client.py`)

`DeerFlowClient` provides direct in-process access to all DeerFlow capabilities without HTTP services. All return types align with the Gateway API response schemas, so consumer code works identically in HTTP and embedded modes.

**Architecture**: Imports the same `deerflow` modules that LangGraph Server and Gateway API use. Shares the same config files and data directories. No FastAPI dependency.

**Agent Conversation** (replaces LangGraph Server):
- `chat(message, thread_id)` — synchronous, accumulates streaming deltas per message-id and returns the final AI text
- `stream(message, thread_id)` — subscribes to LangGraph `stream_mode=["values", "messages", "custom"]` and yields `StreamEvent`:
  - `"values"` — full state snapshot (title, messages, artifacts); AI text already delivered via `messages` mode is **not** re-synthesized here to avoid duplicate deliveries
  - `"messages-tuple"` — per-chunk update: for AI text this is a **delta** (concat per `id` to rebuild the full message); tool calls and tool results are emitted once each
  - `"custom"` — forwarded from `StreamWriter`
  - `"end"` — stream finished (carries cumulative `usage` counted once per message id)
- Agent created lazily via `create_agent()` + `_build_middlewares()`, same as `make_lead_agent`
- Supports `checkpointer` parameter for state persistence across turns
- `reset_agent()` forces agent recreation (e.g. after memory or skill changes)
- See [docs/STREAMING.md](docs/STREAMING.md) for the full design: why Gateway and DeerFlowClient are parallel paths, LangGraph's `stream_mode` semantics, the per-id dedup invariants, and regression testing strategy

**Gateway Equivalent Methods** (replaces Gateway API):

| Category | Methods | Return format |
|----------|---------|---------------|
| Models | `list_models()`, `get_model(name)` | `{"models": [...]}`, `{name, display_name, ...}` |
| MCP | `get_mcp_config()`, `update_mcp_config(servers)` | `{"mcp_servers": {...}}` |
| Skills | `list_skills()`, `get_skill(name)`, `update_skill(name, enabled)`, `install_skill(path)` | `{"skills": [...]}` |
| Memory | `get_memory()`, `reload_memory()`, `get_memory_config()`, `get_memory_status()` | dict |
| Uploads | `upload_files(thread_id, files)`, `list_uploads(thread_id)`, `delete_upload(thread_id, filename)` | `{"success": true, "files": [...]}`, `{"files": [...], "count": N}` |
| Artifacts | `get_artifact(thread_id, path)` → `(bytes, mime_type)` | tuple |

**Key difference from Gateway**: Upload accepts local `Path` objects instead of HTTP `UploadFile`, rejects directory paths before copying, and reuses a single worker when document conversion must run inside an active event loop. Artifact returns `(bytes, mime_type)` instead of HTTP Response. The new Gateway-only thread cleanup route deletes `.deer-flow/threads/{thread_id}` after LangGraph thread deletion; there is no matching `DeerFlowClient` method yet. `update_mcp_config()` and `update_skill()` automatically invalidate the cached agent.

**Tests**: `tests/test_client.py` (77 unit tests including `TestGatewayConformance`), `tests/test_client_live.py` (live integration tests, requires config.yaml)

**Gateway Conformance Tests** (`TestGatewayConformance`): Validate that every dict-returning client method conforms to the corresponding Gateway Pydantic response model. Each test parses the client output through the Gateway model — if Gateway adds a required field that the client doesn't provide, Pydantic raises `ValidationError` and CI catches the drift. Covers: `ModelsListResponse`, `ModelResponse`, `SkillsListResponse`, `SkillResponse`, `SkillInstallResponse`, `McpConfigResponse`, `UploadResponse`, `MemoryConfigResponse`, `MemoryStatusResponse`.

## Development Workflow

### Test-Driven Development (TDD) — MANDATORY

**Every new feature or bug fix MUST be accompanied by unit tests. No exceptions.**

- Write tests in `backend/tests/` following the existing naming convention `test_<feature>.py`
- Run the full suite before and after your change: `make test`
- Tests must pass before a feature is considered complete
- For lightweight config/utility modules, prefer pure unit tests with no external dependencies
- If a module causes circular import issues in tests, add a `sys.modules` mock in `tests/conftest.py` (see existing example for `deerflow.subagents.executor`)

```bash
# Run all tests
make test

# Run a specific test file
PYTHONPATH=. uv run pytest tests/test_<feature>.py -v
```

### Running the Full Application

From the **project root** directory:
```bash
make dev
```

This starts all services and makes the application available at `http://localhost:2026`.

**All startup modes:**

| | **Local Foreground** | **Local Daemon** | **Docker Dev** | **Docker Prod** |
|---|---|---|---|---|
| **Dev** | `./scripts/serve.sh --dev`<br/>`make dev` | `./scripts/serve.sh --dev --daemon`<br/>`make dev-daemon` | `./scripts/docker.sh start`<br/>`make docker-start` | — |
| **Dev + Gateway** | `./scripts/serve.sh --dev --gateway`<br/>`make dev-pro` | `./scripts/serve.sh --dev --gateway --daemon`<br/>`make dev-daemon-pro` | `./scripts/docker.sh start --gateway`<br/>`make docker-start-pro` | — |
| **Prod** | `./scripts/serve.sh --prod`<br/>`make start` | `./scripts/serve.sh --prod --daemon`<br/>`make start-daemon` | — | `./scripts/deploy.sh`<br/>`make up` |
| **Prod + Gateway** | `./scripts/serve.sh --prod --gateway`<br/>`make start-pro` | `./scripts/serve.sh --prod --gateway --daemon`<br/>`make start-daemon-pro` | — | `./scripts/deploy.sh --gateway`<br/>`make up-pro` |

| Action | Local | Docker Dev | Docker Prod |
|---|---|---|---|
| **Stop** | `./scripts/serve.sh --stop`<br/>`make stop` | `./scripts/docker.sh stop`<br/>`make docker-stop` | `./scripts/deploy.sh down`<br/>`make down` |
| **Restart** | `./scripts/serve.sh --restart [flags]` | `./scripts/docker.sh restart` | — |

Gateway mode embeds the agent runtime in Gateway, no LangGraph server.

**Nginx routing**:
- Standard mode: `/api/langgraph/*` → LangGraph Server (2024)
- Gateway mode: `/api/langgraph/*` → Gateway embedded runtime (8100) (via envsubst)
- `/api/*` (other) → Gateway API (8100)
- `/` (non-API) → Frontend (3110)

### Running Backend Services Separately

From the **backend** directory:

```bash
# Terminal 1: LangGraph server
make dev

# Terminal 2: Gateway API
make gateway
```

Direct access (without nginx):
- LangGraph: `http://localhost:2024`
- Gateway: `http://localhost:8100`

### Frontend Configuration

The frontend uses environment variables to connect to backend services:
- `NEXT_PUBLIC_LANGGRAPH_BASE_URL` - Defaults to `/api/langgraph` (through nginx)
- `NEXT_PUBLIC_BACKEND_BASE_URL` - Defaults to empty string (through nginx)

When using `make dev` from root, the frontend automatically connects through nginx.

## Key Features

### File Upload

Multi-file upload with automatic document conversion:
- Endpoint: `POST /api/threads/{thread_id}/uploads`
- Supports: PDF, PPT, Excel, Word documents (converted via `markitdown`)
- Rejects directory inputs before copying so uploads stay all-or-nothing
- Reuses one conversion worker per request when called from an active event loop
- Files stored in thread-isolated directories
- Agent receives uploaded file list via `UploadsMiddleware`

See [docs/FILE_UPLOAD.md](docs/FILE_UPLOAD.md) for details.

### Plan Mode

TodoList middleware for complex multi-step tasks:
- Controlled via runtime config: `config.configurable.is_plan_mode = True`
- Provides `write_todos` tool for task tracking
- One task in_progress at a time, real-time updates

See [docs/plan_mode_usage.md](docs/plan_mode_usage.md) for details.

### Context Summarization

Automatic conversation summarization when approaching token limits:
- Configured in `config.yaml` under `summarization` key
- Trigger types: tokens, messages, or fraction of max input
- Keeps recent messages while summarizing older ones

See [docs/summarization.md](docs/summarization.md) for details.

### Vision Support

For models with `supports_vision: true`:
- `ViewImageMiddleware` processes images in conversation
- `view_image_tool` added to agent's toolset
- Images automatically converted to base64 and injected into state

## Code Style

- Uses `ruff` for linting and formatting
- Line length: 240 characters
- Python 3.12+ with type hints
- Double quotes, space indentation

## Documentation

See `docs/` directory for detailed documentation:
- [CONFIGURATION.md](docs/CONFIGURATION.md) - Configuration options
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - Architecture details
- [API.md](docs/API.md) - API reference
- [SETUP.md](docs/SETUP.md) - Setup guide
- [FILE_UPLOAD.md](docs/FILE_UPLOAD.md) - File upload feature
- [PATH_EXAMPLES.md](docs/PATH_EXAMPLES.md) - Path types and usage
- [summarization.md](docs/summarization.md) - Context summarization
- [plan_mode_usage.md](docs/plan_mode_usage.md) - Plan mode with TodoList
