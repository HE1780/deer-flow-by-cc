import os
import re
import shutil
import warnings
from pathlib import Path, PureWindowsPath

_LEGACY_DEPRECATION_MSG = (
    "Paths.{name}() is deprecated; use {replacement}(thread_id, "
    "tenant_id=..., workspace_id=...) which falls back to the legacy "
    "single-tenant layout when ids are absent or non-positive."
)


def _warn_legacy(name: str, replacement: str) -> None:
    """Emit a ``DeprecationWarning`` for a legacy ``Paths`` method.

    ``stacklevel=3`` points the warning at the caller of the legacy method
    (caller -> legacy method -> ``_warn_legacy``).
    """
    warnings.warn(
        _LEGACY_DEPRECATION_MSG.format(name=name, replacement=replacement),
        DeprecationWarning,
        stacklevel=3,
    )

# Virtual path prefix seen by agents inside the sandbox
VIRTUAL_PATH_PREFIX = "/mnt/user-data"

_SAFE_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _require_positive_tenant_or_workspace(name: str, value: int) -> None:
    """Raise ``ValueError`` unless ``value`` is a positive ``int``.

    Mirrors the rigor used by ``app.gateway.identity.storage.paths`` (kept
    duplicated here deliberately — the harness boundary forbids importing the
    app-side module). ``bool`` is rejected because ``True`` would otherwise
    pass as ``1``.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive int, got {value!r}")


def _is_tenant_scoped(tenant_id: int | None, workspace_id: int | None) -> bool:
    """Return True iff both tenant_id and workspace_id are positive ints.

    Any other combination (either value ``None``, zero, negative, or a
    non-int like ``bool``) means the caller should fall back to the legacy
    non-stratified path. Both values must be present to form a tenant-aware
    path — a tenant id alone is insufficient.
    """
    if tenant_id is None or workspace_id is None:
        return False
    if isinstance(tenant_id, bool) or isinstance(workspace_id, bool):
        return False
    if not isinstance(tenant_id, int) or not isinstance(workspace_id, int):
        return False
    return tenant_id > 0 and workspace_id > 0


def _default_local_base_dir() -> Path:
    """Return the repo-local DeerFlow state directory without relying on cwd."""
    backend_dir = Path(__file__).resolve().parents[4]
    return backend_dir / ".deer-flow"


def _validate_thread_id(thread_id: str) -> str:
    """Validate a thread ID before using it in filesystem paths."""
    if not _SAFE_THREAD_ID_RE.match(thread_id):
        raise ValueError(f"Invalid thread_id {thread_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
    return thread_id


def _join_host_path(base: str, *parts: str) -> str:
    """Join host filesystem path segments while preserving native style.

    Docker Desktop on Windows expects bind mount sources to stay in Windows
    path form (for example ``C:\\repo\\backend\\.deer-flow``).  Using
    ``Path(base) / ...`` on a POSIX host can accidentally rewrite those paths
    with mixed separators, so this helper preserves the original style.
    """
    if not parts:
        return base

    if re.match(r"^[A-Za-z]:[\\/]", base) or base.startswith("\\\\") or "\\" in base:
        result = PureWindowsPath(base)
        for part in parts:
            result /= part
        return str(result)

    result = Path(base)
    for part in parts:
        result /= part
    return str(result)


def join_host_path(base: str, *parts: str) -> str:
    """Join host filesystem path segments while preserving native style."""
    return _join_host_path(base, *parts)


class Paths:
    """
    Centralized path configuration for DeerFlow application data.

    Directory layout (host side):
        {base_dir}/
        ├── memory.json
        ├── USER.md          <-- global user profile (injected into all agents)
        ├── agents/
        │   └── {agent_name}/
        │       ├── config.yaml
        │       ├── SOUL.md  <-- agent personality/identity (injected alongside lead prompt)
        │       └── memory.json
        └── threads/
            └── {thread_id}/
                └── user-data/         <-- mounted as /mnt/user-data/ inside sandbox
                    ├── workspace/     <-- /mnt/user-data/workspace/
                    ├── uploads/       <-- /mnt/user-data/uploads/
                    └── outputs/       <-- /mnt/user-data/outputs/

    BaseDir resolution (in priority order):
        1. Constructor argument `base_dir`
        2. DEER_FLOW_HOME environment variable
        3. Repo-local fallback derived from this module path: `{backend_dir}/.deer-flow`
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    @property
    def host_base_dir(self) -> Path:
        """Host-visible base dir for Docker volume mount sources.

        When running inside Docker with a mounted Docker socket (DooD), the Docker
        daemon runs on the host and resolves mount paths against the host filesystem.
        Set DEER_FLOW_HOST_BASE_DIR to the host-side path that corresponds to this
        container's base_dir so that sandbox container volume mounts work correctly.

        Falls back to base_dir when the env var is not set (native/local execution).
        """
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return Path(env)
        return self.base_dir

    def _host_base_dir_str(self) -> str:
        """Return the host base dir as a raw string for bind mounts."""
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return env
        return str(self.base_dir)

    @property
    def base_dir(self) -> Path:
        """Root directory for all application data."""
        if self._base_dir is not None:
            return self._base_dir

        if env_home := os.getenv("DEER_FLOW_HOME"):
            return Path(env_home).resolve()

        return _default_local_base_dir()

    @property
    def memory_file(self) -> Path:
        """Path to the persisted memory file: `{base_dir}/memory.json`."""
        return self.base_dir / "memory.json"

    @property
    def user_md_file(self) -> Path:
        """Path to the global user profile file: `{base_dir}/USER.md`."""
        return self.base_dir / "USER.md"

    @property
    def agents_dir(self) -> Path:
        """Root directory for all custom agents: `{base_dir}/agents/`."""
        return self.base_dir / "agents"

    def agent_dir(self, name: str) -> Path:
        """Directory for a specific agent: `{base_dir}/agents/{name}/`."""
        return self.agents_dir / name.lower()

    def agent_memory_file(self, name: str) -> Path:
        """Per-agent memory file: `{base_dir}/agents/{name}/memory.json`."""
        return self.agent_dir(name) / "memory.json"

    def thread_dir(self, thread_id: str) -> Path:
        """DEPRECATED: use :meth:`resolve_thread_dir` instead.

        Host path for a thread's data (legacy single-tenant layout).

        Raises:
            ValueError: If `thread_id` contains unsafe characters (path separators
                        or `..`) that could cause directory traversal.
        """
        _warn_legacy("thread_dir", "resolve_thread_dir")
        return self.resolve_thread_dir(thread_id)

    def sandbox_work_dir(self, thread_id: str) -> Path:
        """DEPRECATED: use :meth:`resolve_sandbox_work_dir` instead.

        Host path for the agent's workspace directory (legacy layout).
        Sandbox: `/mnt/user-data/workspace/`
        """
        _warn_legacy("sandbox_work_dir", "resolve_sandbox_work_dir")
        return self.resolve_sandbox_work_dir(thread_id)

    def sandbox_uploads_dir(self, thread_id: str) -> Path:
        """DEPRECATED: use :meth:`resolve_sandbox_uploads_dir` instead.

        Host path for user-uploaded files (legacy layout).
        Sandbox: `/mnt/user-data/uploads/`
        """
        _warn_legacy("sandbox_uploads_dir", "resolve_sandbox_uploads_dir")
        return self.resolve_sandbox_uploads_dir(thread_id)

    def sandbox_outputs_dir(self, thread_id: str) -> Path:
        """DEPRECATED: use :meth:`resolve_sandbox_outputs_dir` instead.

        Host path for agent-generated artifacts (legacy layout).
        Sandbox: `/mnt/user-data/outputs/`
        """
        _warn_legacy("sandbox_outputs_dir", "resolve_sandbox_outputs_dir")
        return self.resolve_sandbox_outputs_dir(thread_id)

    def acp_workspace_dir(self, thread_id: str) -> Path:
        """DEPRECATED: use :meth:`resolve_acp_workspace_dir` instead.

        Host path for the ACP workspace of a specific thread (legacy layout).
        Sandbox: `/mnt/acp-workspace/`
        """
        _warn_legacy("acp_workspace_dir", "resolve_acp_workspace_dir")
        return self.resolve_acp_workspace_dir(thread_id)

    def sandbox_user_data_dir(self, thread_id: str) -> Path:
        """DEPRECATED: use :meth:`resolve_sandbox_user_data_dir` instead.

        Host path for the user-data root (legacy layout).
        Sandbox: `/mnt/user-data/`
        """
        _warn_legacy("sandbox_user_data_dir", "resolve_sandbox_user_data_dir")
        return self.resolve_sandbox_user_data_dir(thread_id)

    def host_thread_dir(self, thread_id: str) -> str:
        """Host path for a thread directory, preserving Windows path syntax."""
        return _join_host_path(self._host_base_dir_str(), "threads", _validate_thread_id(thread_id))

    def host_sandbox_user_data_dir(self, thread_id: str) -> str:
        """Host path for a thread's user-data root."""
        return _join_host_path(self.host_thread_dir(thread_id), "user-data")

    def host_sandbox_work_dir(self, thread_id: str) -> str:
        """Host path for the workspace mount source."""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id), "workspace")

    def host_sandbox_uploads_dir(self, thread_id: str) -> str:
        """Host path for the uploads mount source."""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id), "uploads")

    def host_sandbox_outputs_dir(self, thread_id: str) -> str:
        """Host path for the outputs mount source."""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id), "outputs")

    def host_acp_workspace_dir(self, thread_id: str) -> str:
        """Host path for the ACP workspace mount source."""
        return _join_host_path(self.host_thread_dir(thread_id), "acp-workspace")

    def ensure_thread_dirs(self, thread_id: str) -> None:
        """DEPRECATED: use :meth:`ensure_thread_dirs_for` instead.

        Create all standard sandbox directories for a thread (legacy layout).
        """
        _warn_legacy("ensure_thread_dirs", "ensure_thread_dirs_for")
        self.ensure_thread_dirs_for(thread_id)

    def delete_thread_dir(self, thread_id: str) -> None:
        """DEPRECATED: use :meth:`delete_thread_dir_for` instead.

        Delete all persisted data for a thread (legacy layout). Idempotent.
        """
        _warn_legacy("delete_thread_dir", "delete_thread_dir_for")
        self.delete_thread_dir_for(thread_id)

    def delete_thread_dir_for(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> None:
        """Tenant-aware thread-data deletion.

        Mirrors :meth:`delete_thread_dir` (idempotent when the directory is
        already absent), but routes through :meth:`resolve_thread_dir` so that
        identity-aware callers physically remove the tenant-stratified
        directory. Falls back to the legacy layout when either id is missing
        or non-positive.
        """
        target = self.resolve_thread_dir(
            thread_id, tenant_id=tenant_id, workspace_id=workspace_id
        )
        if target.exists():
            shutil.rmtree(target)

    # ── Tenant-stratified paths (M4 storage isolation) ──────────────────
    #
    # The methods below layer tenant/workspace isolation on top of the legacy
    # single-tenant layout. They **never** replace the legacy helpers — flag-off
    # callers keep the old behavior verbatim, while identity-aware callers
    # (middlewares reading `state["identity"]`) get stratified paths.
    #
    # Layout (host side) when tenant_id + workspace_id are both supplied:
    #     {base_dir}/tenants/{tenant_id}/workspaces/{workspace_id}/threads/{thread_id}/
    #         └── user-data/                  <-- mounted as /mnt/user-data/
    #             ├── workspace/              <-- /mnt/user-data/workspace/
    #             ├── uploads/                <-- /mnt/user-data/uploads/
    #             └── outputs/                <-- /mnt/user-data/outputs/
    #         └── acp-workspace/              <-- /mnt/acp-workspace/
    #
    # The sandbox virtual prefix (``/mnt/user-data``) is unchanged — only the
    # host side gets the tenant/workspace nesting.

    def tenant_thread_dir(self, tenant_id: int, workspace_id: int, thread_id: str) -> Path:
        """Host path for a tenant/workspace-stratified thread directory.

        Layout: ``{base_dir}/tenants/{tenant_id}/workspaces/{workspace_id}/threads/{thread_id}/``

        Raises:
            ValueError: If ``tenant_id`` or ``workspace_id`` is not a positive
                        ``int``, or if ``thread_id`` contains unsafe characters.
        """
        _require_positive_tenant_or_workspace("tenant_id", tenant_id)
        _require_positive_tenant_or_workspace("workspace_id", workspace_id)
        return self.base_dir / "tenants" / str(tenant_id) / "workspaces" / str(workspace_id) / "threads" / _validate_thread_id(thread_id)

    def resolve_thread_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> Path:
        """Return the tenant-stratified thread dir when both ids are supplied.

        Falls back to the legacy :meth:`thread_dir` when either ``tenant_id``
        or ``workspace_id`` is missing / non-positive. Keeping the fallback
        inline (rather than raising) lets middleware code use one resolver
        regardless of whether identity is populated.
        """
        if _is_tenant_scoped(tenant_id, workspace_id):
            return self.tenant_thread_dir(tenant_id, workspace_id, thread_id)  # type: ignore[arg-type]
        # Inlined legacy fallback (matches :meth:`thread_dir` body) so that
        # ``thread_dir`` itself can become a thin delegate to this method
        # without recursing back through us.
        return self.base_dir / "threads" / _validate_thread_id(thread_id)

    def resolve_sandbox_user_data_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> Path:
        """Tenant-aware host path for the ``user-data`` root."""
        return self.resolve_thread_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id) / "user-data"

    def resolve_sandbox_work_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> Path:
        """Tenant-aware host path for ``user-data/workspace``."""
        return self.resolve_sandbox_user_data_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id) / "workspace"

    def resolve_sandbox_uploads_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> Path:
        """Tenant-aware host path for ``user-data/uploads``."""
        return self.resolve_sandbox_user_data_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id) / "uploads"

    def resolve_sandbox_outputs_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> Path:
        """Tenant-aware host path for ``user-data/outputs``."""
        return self.resolve_sandbox_user_data_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id) / "outputs"

    def resolve_acp_workspace_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> Path:
        """Tenant-aware host path for the ACP workspace root."""
        return self.resolve_thread_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id) / "acp-workspace"

    def ensure_thread_dirs_for(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> None:
        """Create the tenant-aware thread directories (or legacy if no identity).

        Mirrors :meth:`ensure_thread_dirs` — directories are created with
        mode 0o777 so that sandbox containers running as a different UID can
        still write to volume-mounted paths.
        """
        for d in [
            self.resolve_sandbox_work_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id),
            self.resolve_sandbox_uploads_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id),
            self.resolve_sandbox_outputs_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id),
            self.resolve_acp_workspace_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id),
        ]:
            d.mkdir(parents=True, exist_ok=True)
            d.chmod(0o777)

    # ── Host-side (raw string) variants for Docker bind mounts ──────────

    def host_tenant_thread_dir(self, tenant_id: int, workspace_id: int, thread_id: str) -> str:
        """Host-side raw string form of :meth:`tenant_thread_dir`.

        Preserves Windows path syntax for Docker Desktop on Windows, matching
        the behaviour of :meth:`host_thread_dir`.
        """
        _require_positive_tenant_or_workspace("tenant_id", tenant_id)
        _require_positive_tenant_or_workspace("workspace_id", workspace_id)
        return _join_host_path(
            self._host_base_dir_str(),
            "tenants",
            str(tenant_id),
            "workspaces",
            str(workspace_id),
            "threads",
            _validate_thread_id(thread_id),
        )

    def resolve_host_thread_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> str:
        """Tenant-aware host string path for a thread directory."""
        if _is_tenant_scoped(tenant_id, workspace_id):
            return self.host_tenant_thread_dir(tenant_id, workspace_id, thread_id)  # type: ignore[arg-type]
        return self.host_thread_dir(thread_id)

    def resolve_host_sandbox_user_data_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> str:
        """Tenant-aware host string path for the ``user-data`` mount source."""
        return _join_host_path(
            self.resolve_host_thread_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id),
            "user-data",
        )

    def resolve_host_sandbox_work_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> str:
        """Tenant-aware host string path for the ``workspace`` mount source."""
        return _join_host_path(
            self.resolve_host_sandbox_user_data_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id),
            "workspace",
        )

    def resolve_host_sandbox_uploads_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> str:
        """Tenant-aware host string path for the ``uploads`` mount source."""
        return _join_host_path(
            self.resolve_host_sandbox_user_data_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id),
            "uploads",
        )

    def resolve_host_sandbox_outputs_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> str:
        """Tenant-aware host string path for the ``outputs`` mount source."""
        return _join_host_path(
            self.resolve_host_sandbox_user_data_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id),
            "outputs",
        )

    def resolve_host_acp_workspace_dir(
        self,
        thread_id: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> str:
        """Tenant-aware host string path for the ACP workspace mount source."""
        return _join_host_path(
            self.resolve_host_thread_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id),
            "acp-workspace",
        )

    def resolve_virtual_path(
        self,
        thread_id: str,
        virtual_path: str,
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> Path:
        """Resolve a sandbox virtual path to the actual host filesystem path.

        Args:
            thread_id: The thread ID.
            virtual_path: Virtual path as seen inside the sandbox, e.g.
                          ``/mnt/user-data/outputs/report.pdf``.
                          Leading slashes are stripped before matching.
            tenant_id: Optional tenant ID (M4 storage isolation). Combined with
                ``workspace_id``, routes the resolved path under
                ``tenants/{tenant_id}/workspaces/{workspace_id}/threads/.../user-data``.
                When either id is missing, falls back to the legacy
                ``threads/{thread_id}/user-data`` base so flag-off callers see
                unchanged behaviour.
            workspace_id: Optional workspace ID (pair with ``tenant_id``).

        Returns:
            The resolved absolute host filesystem path.

        Raises:
            ValueError: If the path does not start with the expected virtual
                        prefix or a path-traversal attempt is detected.
        """
        stripped = virtual_path.lstrip("/")
        prefix = VIRTUAL_PATH_PREFIX.lstrip("/")

        # Require an exact segment-boundary match to avoid prefix confusion
        # (e.g. reject paths like "mnt/user-dataX/...").
        if stripped != prefix and not stripped.startswith(prefix + "/"):
            raise ValueError(f"Path must start with /{prefix}")

        relative = stripped[len(prefix) :].lstrip("/")
        base = self.resolve_sandbox_user_data_dir(thread_id, tenant_id=tenant_id, workspace_id=workspace_id).resolve()
        actual = (base / relative).resolve()

        try:
            actual.relative_to(base)
        except ValueError:
            raise ValueError("Access denied: path traversal detected")

        return actual


# ── Singleton ────────────────────────────────────────────────────────────

_paths: Paths | None = None


def get_paths() -> Paths:
    """Return the global Paths singleton (lazy-initialized)."""
    global _paths
    if _paths is None:
        _paths = Paths()
    return _paths


def resolve_path(path: str) -> Path:
    """Resolve *path* to an absolute ``Path``.

    Relative paths are resolved relative to the application base directory.
    Absolute paths are returned as-is (after normalisation).
    """
    p = Path(path)
    if not p.is_absolute():
        p = get_paths().base_dir / path
    return p.resolve()
