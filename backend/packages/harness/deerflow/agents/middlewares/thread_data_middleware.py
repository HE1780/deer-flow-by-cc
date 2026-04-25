import logging
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._identity import extract_tenant_ids
from deerflow.agents.thread_state import ThreadDataState
from deerflow.config.paths import Paths, get_paths

logger = logging.getLogger(__name__)


class ThreadDataMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema.

    The ``identity`` field carries tenant/workspace context forwarded by the
    gateway (set by the M5 identity middleware). It is intentionally typed as
    an opaque ``Any`` here: the harness must remain decoupled from
    ``app.gateway.identity.auth.Identity`` (boundary enforced by
    ``tests/test_harness_boundary.py``). The middleware reads tenant_id and
    workspace_id defensively (via
    :func:`deerflow.agents.middlewares._identity.extract_tenant_ids`),
    supporting both a dict and an attribute-bearing object. When absent or
    incomplete, the middleware falls back to the legacy non-stratified path
    layout.
    """

    thread_data: NotRequired[ThreadDataState | None]
    identity: NotRequired[Any]


# Re-exported for any existing import sites; the implementation lives in
# ``_identity.py`` so the sandbox middleware can share it.
_extract_tenant_ids = extract_tenant_ids


class ThreadDataMiddleware(AgentMiddleware[ThreadDataMiddlewareState]):
    """Create thread data directories for each thread execution.

    Tenant-aware layout (M4 storage isolation):
    - {base_dir}/tenants/{tid}/workspaces/{wid}/threads/{thread_id}/user-data/{workspace,uploads,outputs}

    Legacy layout (flag-off / no identity on state):
    - {base_dir}/threads/{thread_id}/user-data/{workspace,uploads,outputs}

    The sandbox virtual prefix (``/mnt/user-data/...``) is unchanged by either
    mode — only the host-side layout differs.

    Lifecycle Management:
    - With lazy_init=True (default): Only compute paths, directories created on-demand.
    - With lazy_init=False: Eagerly create directories in before_agent().
    """

    state_schema = ThreadDataMiddlewareState

    def __init__(self, base_dir: str | None = None, lazy_init: bool = True):
        """Initialize the middleware.

        Args:
            base_dir: Base directory for thread data. Defaults to Paths resolution.
            lazy_init: If True, defer directory creation until needed.
                      If False, create directories eagerly in before_agent().
                      Default is True for optimal performance.
        """
        super().__init__()
        self._paths = Paths(base_dir) if base_dir else get_paths()
        self._lazy_init = lazy_init

    def _get_thread_paths(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> dict[str, str]:
        """Compute the paths for a thread's data directories.

        Delegates to the tenant-aware ``resolve_*`` helpers on ``Paths``,
        which transparently fall back to the legacy layout when either id
        is missing or non-positive.
        """
        return {
            "workspace_path": str(self._paths.resolve_sandbox_work_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id)),
            "uploads_path": str(self._paths.resolve_sandbox_uploads_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id)),
            "outputs_path": str(self._paths.resolve_sandbox_outputs_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id)),
        }

    def _create_thread_directories(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> dict[str, str]:
        """Eagerly create the thread data directories, then return their paths."""
        self._paths.ensure_thread_dirs_for(thread_id, tenant_id=tenant_id, workspace_id=workspace_id)
        return self._get_thread_paths(thread_id, tenant_id=tenant_id, workspace_id=workspace_id)

    @override
    def before_agent(self, state: ThreadDataMiddlewareState, runtime: Runtime) -> dict | None:
        context = runtime.context or {}
        thread_id = context.get("thread_id")
        if thread_id is None:
            config = get_config()
            thread_id = config.get("configurable", {}).get("thread_id")

        if thread_id is None:
            raise ValueError("Thread ID is required in runtime context or config.configurable")

        # Identity is opaque (may be a dict, dataclass, or None) — read
        # defensively. In flag-off mode (pre-M5) ``state["identity"]`` is
        # absent and both ids end up None, which keeps the legacy path.
        identity = state.get("identity") if hasattr(state, "get") else None
        tenant_id, workspace_id = extract_tenant_ids(identity)

        if self._lazy_init:
            # Lazy initialization: only compute paths, don't create directories.
            paths = self._get_thread_paths(thread_id, tenant_id=tenant_id, workspace_id=workspace_id)
        else:
            # Eager initialization: create directories immediately.
            paths = self._create_thread_directories(thread_id, tenant_id=tenant_id, workspace_id=workspace_id)
            logger.debug(
                "Created thread data directories for thread %s (tenant=%s workspace=%s)",
                thread_id,
                tenant_id,
                workspace_id,
            )

        return {
            "thread_data": {
                **paths,
            }
        }
