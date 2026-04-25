"""Pure path-construction helpers for the tenant/workspace storage layout.

This module intentionally has **no runtime dependencies** beyond the standard
library. In particular it does *not* import
``app.gateway.identity.settings`` or any DB / Redis machinery — the helpers
are meant to be callable from very early startup code (lifespan, bootstrap)
and from the harness-side bridge that runs before the identity subsystem is
fully wired up.

Root resolution
---------------

The filesystem root is resolved in this order:

1. ``$DEER_FLOW_HOME`` environment variable, if set and non-empty.
2. Repo-local fallback ``{backend_dir}/.deer-flow``, computed from this
   module's own path — so it works regardless of the current working
   directory.

Note on env-var name: we deliberately use ``DEER_FLOW_HOME`` (with an
underscore) to stay aligned with the rest of the project
(``docker/docker-compose.yaml``, ``scripts/deploy.sh``, and
``packages/harness/deerflow/config/paths.py`` all use this name). A separate
legacy ``DEERFLOW_HOME`` variable exists in ``identity.settings`` for the M2
JWT key-material paths; that variable is **not** consulted here.

Layout (spec §7.1 / §7.2 / §7.4 / §9.3 / §9.6 / §10.2)
------------------------------------------------------

Every path returned by this module is **absolute** and **not created** by
these helpers — the caller is responsible for materialising directories when
appropriate::

    {home}/
      tenants/{tenant_id}/
        custom/                                       # skills_tenant_custom_root
        shared/                                       # tenant_shared_root
        users/{user_id}/memory.json                   # user_memory_path
        workspaces/{workspace_id}/
          user/                                       # skills_workspace_user_root
          threads/{thread_id}/                        # thread_path
      skills/
        public/                                       # skills_public_root (shared)
      _system/                                        # migration temp / audit fallback / archive
        audit_fallback/{YYYYMMDD}.jsonl               # audit_fallback_path
        audit_archive/{tenant_id}/{YYYY-MM}.jsonl.gz  # audit_archive_path (FILE)
        migration_report_{ts}.json                    # migration_report_path
        migration.lock                                # migration_lock_path

Design decisions
~~~~~~~~~~~~~~~~

* ``skills_public_root`` lives at ``{home}/skills/public/`` rather than
  under ``tenants/``. The M4 skills loader (Task 3) scans
  ``public/ -> tenants/{tid}/custom/ -> tenants/{tid}/workspaces/{wid}/user/``
  in priority order; ``public/`` must be tenant-neutral because it is shared
  across all tenants.
* ``custom`` skills are a **tenant-level** concept (scoped to a tenant, shared
  across that tenant's workspaces), while ``user`` skills are
  **workspace-level**. This mirrors the loader's scan priority and matches
  the design in the M3/M4 specs.
* Positional validation is done via ``ValueError`` rather than ``assert``:
  asserts can be stripped by ``python -O`` and we do not want silent
  corruption of tenant-isolated layouts in optimised builds.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Root resolution
# ---------------------------------------------------------------------------

# Environment variable that, when set, overrides the default home directory.
_ENV_HOME = "DEER_FLOW_HOME"


def _default_home() -> Path:
    """Return the repo-local fallback home, independent of CWD.

    Resolves to ``{backend_dir}/.deer-flow``. The walk is five ``parents[]``
    hops up from this file::

        backend/app/gateway/identity/storage/paths.py
         parents[0]  storage
         parents[1]  identity
         parents[2]  gateway
         parents[3]  app
         parents[4]  backend
    """

    backend_dir = Path(__file__).resolve().parents[4]
    return backend_dir / ".deer-flow"


def deerflow_home() -> Path:
    """Return the absolute DeerFlow home directory.

    Resolution order:

    1. ``$DEER_FLOW_HOME`` if set and non-empty.
    2. ``{backend_dir}/.deer-flow`` fallback.

    The returned path is always absolute; the directory is **not** created.
    """

    env = os.environ.get(_ENV_HOME)
    if env:
        return Path(env).expanduser().resolve()
    return _default_home().resolve()


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def _require_positive(name: str, value: int) -> None:
    """Raise ``ValueError`` unless ``value`` is a positive ``int``.

    Uses a plain ``isinstance`` check rather than ``assert`` so the guard
    survives ``python -O``. ``bool`` is explicitly rejected because
    ``True`` would otherwise pass as ``1``.
    """

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive int, got {value!r}")


# ---------------------------------------------------------------------------
# Tenant / workspace / thread paths
# ---------------------------------------------------------------------------


def tenant_root(tenant_id: int) -> Path:
    """Return ``{home}/tenants/{tenant_id}``."""

    _require_positive("tenant_id", tenant_id)
    return deerflow_home() / "tenants" / str(tenant_id)


def tenant_shared_root(tenant_id: int) -> Path:
    """Return ``{home}/tenants/{tenant_id}/shared``.

    Tenant-scoped shared area (artifacts, shared reports, etc.) — distinct
    from the tenant's ``custom/`` skills folder.
    """

    _require_positive("tenant_id", tenant_id)
    return tenant_root(tenant_id) / "shared"


def workspace_root(tenant_id: int, workspace_id: int) -> Path:
    """Return ``{home}/tenants/{tenant_id}/workspaces/{workspace_id}``."""

    _require_positive("tenant_id", tenant_id)
    _require_positive("workspace_id", workspace_id)
    return tenant_root(tenant_id) / "workspaces" / str(workspace_id)


def thread_path(tenant_id: int, workspace_id: int, thread_id: str) -> Path:
    """Return ``{home}/tenants/{tid}/workspaces/{wid}/threads/{thread_id}``.

    Per-thread storage (agent work dir, uploads, outputs live *under* this
    directory in later tasks). ``thread_id`` is treated as an opaque string
    here; Task 2's ``path_guard`` remains the primary defence. This helper
    applies a minimal defensive check — rejecting ``thread_id`` that contains
    path separators (``/`` or ``\\``), parent traversal (``..``) or a NUL
    byte — for consistency with the rest of this module.
    """

    _require_positive("tenant_id", tenant_id)
    _require_positive("workspace_id", workspace_id)
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError(f"thread_id must be a non-empty str, got {thread_id!r}")
    for bad in ("/", "\\", "..", "\0"):
        if bad in thread_id:
            raise ValueError(f"thread_id must not contain {bad!r}, got {thread_id!r}")
    return workspace_root(tenant_id, workspace_id) / "threads" / thread_id


# ---------------------------------------------------------------------------
# Skills paths (§7.2 loader priority: public -> tenant custom -> ws user)
# ---------------------------------------------------------------------------


def skills_public_root() -> Path:
    """Return ``{home}/skills/public``.

    Tenant-neutral: this tree is shared across all tenants and is **not**
    nested under ``tenants/``. The M4 skills loader scans this first, then
    layers tenant-custom and workspace-user skills on top.
    """

    return deerflow_home() / "skills" / "public"


def skills_tenant_custom_root(tenant_id: int) -> Path:
    """Return ``{home}/tenants/{tenant_id}/custom``.

    Tenant-level custom skills — scoped to a single tenant, shared across
    all of that tenant's workspaces.
    """

    _require_positive("tenant_id", tenant_id)
    return tenant_root(tenant_id) / "custom"


def skills_workspace_user_root(tenant_id: int, workspace_id: int) -> Path:
    """Return ``{home}/tenants/{tid}/workspaces/{wid}/user``.

    Workspace-level user skills — scoped to a single workspace. Highest
    priority in the loader's scan order; overrides tenant-custom or public
    skills on name collision.
    """

    _require_positive("tenant_id", tenant_id)
    _require_positive("workspace_id", workspace_id)
    return workspace_root(tenant_id, workspace_id) / "user"


# ---------------------------------------------------------------------------
# Memory / audit / migrations
# ---------------------------------------------------------------------------


def user_memory_path(tenant_id: int, user_id: int) -> Path:
    """Return ``{home}/tenants/{tid}/users/{uid}/memory.json`` (spec §7.4).

    The per-user memory file path. The caller is responsible for creating
    parent directories.
    """

    _require_positive("tenant_id", tenant_id)
    _require_positive("user_id", user_id)
    return tenant_root(tenant_id) / "users" / str(user_id) / "memory.json"


def audit_fallback_path(date_yyyymmdd: str) -> Path:
    """Return ``{home}/_system/audit_fallback/{YYYYMMDD}.jsonl`` (spec §9.3).

    Fallback audit log used when the primary audit sink (Postgres) is
    unavailable. ``date_yyyymmdd`` must be exactly 8 ASCII digits.
    """

    if not isinstance(date_yyyymmdd, str) or len(date_yyyymmdd) != 8 or not date_yyyymmdd.isdigit():
        raise ValueError(f"date_yyyymmdd must be 8 digits (YYYYMMDD), got {date_yyyymmdd!r}")
    return deerflow_home() / "_system" / "audit_fallback" / f"{date_yyyymmdd}.jsonl"


def audit_archive_path(tenant_id: int, yyyy_mm: str) -> Path:
    """Return ``{home}/_system/audit_archive/{tenant_id}/{YYYY-MM}.jsonl.gz`` (spec §9.6).

    **File** path written by the monthly archiver job (gzip-compressed JSON
    Lines). ``yyyy_mm`` must be ``YYYY-MM`` (seven characters, digits + a
    hyphen at index 4).
    """

    _require_positive("tenant_id", tenant_id)
    if not isinstance(yyyy_mm, str) or len(yyyy_mm) != 7 or yyyy_mm[4] != "-" or not yyyy_mm[:4].isdigit() or not yyyy_mm[5:].isdigit():
        raise ValueError(f"yyyy_mm must be 'YYYY-MM', got {yyyy_mm!r}")
    return deerflow_home() / "_system" / "audit_archive" / str(tenant_id) / f"{yyyy_mm}.jsonl.gz"


def migration_report_path(ts: str) -> Path:
    """Return ``{home}/_system/migration_report_{ts}.json`` (spec §10.2).

    ``ts`` is treated as an opaque, non-empty identifier (typically an
    ISO-8601-ish timestamp chosen by the migration runner).
    """

    if not isinstance(ts, str) or not ts:
        raise ValueError(f"ts must be a non-empty str, got {ts!r}")
    return deerflow_home() / "_system" / f"migration_report_{ts}.json"


def migration_lock_path() -> Path:
    """Return ``{home}/_system/migration.lock`` (spec §7.1 / §10.2).

    Advisory lock file used to prevent concurrent migrations. Kept under
    ``_system/`` alongside the migration report files.
    """

    return deerflow_home() / "_system" / "migration.lock"
