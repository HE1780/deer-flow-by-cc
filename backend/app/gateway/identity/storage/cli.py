"""Tenant / workspace directory bootstrap helper (M4 task 8).

Creates the expected storage tree for a tenant (and optionally a workspace)
with the correct mode bits:

* ``{home}/tenants/{tid}/``                        0700
* ``{home}/tenants/{tid}/custom/``                 0700
* ``{home}/tenants/{tid}/shared/``                 0700
* ``{home}/tenants/{tid}/workspaces/{wid}/``       0700 (if workspace_id)
* ``{home}/tenants/{tid}/workspaces/{wid}/user/``  0700 (if workspace_id)
* ``{home}/tenants/{tid}/workspaces/{wid}/threads/`` 0700 (if workspace_id)

It also idempotently ensures the global, tenant-neutral dirs:

* ``{home}/skills/public/``  0755 (intentionally world-readable — shared)
* ``{home}/_system/``        0700

The helper is idempotent: running it a second time is a no-op for existing
directories, and chmod is re-applied to correct any drifted permissions.

Used by M7 migration and by manual tenant provisioning via::

    make identity-dirs TENANT_ID=1 WORKSPACE_ID=1

All path construction is delegated to
``app.gateway.identity.storage.paths`` — we never build paths inline.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.gateway.identity.storage.paths import (
    deerflow_home,
    skills_public_root,
    skills_tenant_custom_root,
    skills_workspace_user_root,
    tenant_root,
    tenant_shared_root,
    workspace_root,
)

# Mode for every tenant-scoped directory.
_TENANT_DIR_MODE = 0o700
# Mode for the shared public skills tree (readable by others is fine — it's
# explicitly the "global" layer of the skills loader).
_PUBLIC_SKILLS_MODE = 0o755
# Mode for _system — tenant-neutral but contains audit fallback / archive /
# migration artefacts, so keep it 0700.
_SYSTEM_DIR_MODE = 0o700


@dataclass
class BootstrapResult:
    """Summary of what the bootstrap did to each path."""

    home: Path
    created: list[tuple[Path, int]] = field(default_factory=list)
    preserved: list[tuple[Path, int]] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines = [f"home: {self.home}"]
        for path, mode in self.created:
            lines.append(f"  created   {oct(mode)} {path}")
        for path, mode in self.preserved:
            lines.append(f"  preserved {oct(mode)} {path}")
        return lines


def _ensure_dir(path: Path, mode: int, result: BootstrapResult) -> None:
    """Create ``path`` (parents included) and apply ``mode``.

    ``mkdir(mode=...)`` is subject to umask, so we always ``chmod`` after
    creation. Running this a second time is a no-op aside from the chmod,
    which re-asserts the intended permission bits.
    """
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    # Always chmod — tolerate drift from previous runs or mis-set umasks.
    path.chmod(mode)
    final_mode = path.stat().st_mode & 0o777
    if existed:
        result.preserved.append((path, final_mode))
    else:
        result.created.append((path, final_mode))


def run(
    tenant_id: int,
    workspace_id: int | None = None,
    home: Path | None = None,
) -> BootstrapResult:
    """Library entry point — create the expected storage tree.

    Args:
        tenant_id: Positive integer tenant id. Validated by
            ``paths.tenant_root()`` (rejects zero, negative, and booleans).
        workspace_id: Optional positive integer workspace id. When supplied,
            the workspace subtree is created too.
        home: Optional explicit home override. When provided, it takes
            precedence over ``$DEER_FLOW_HOME`` for the duration of this
            call by setting the env var; the previous value is restored
            before returning.

    Returns:
        A :class:`BootstrapResult` summarising which directories were
        created vs. preserved, each with their final mode.
    """
    # Allow the caller to pin an explicit home. We swap the env var rather
    # than duplicating path-construction logic here — this way the
    # ``paths`` helpers remain the single source of truth.
    previous_home = os.environ.get("DEER_FLOW_HOME")
    if home is not None:
        os.environ["DEER_FLOW_HOME"] = str(home)
    try:
        resolved_home = deerflow_home()
        result = BootstrapResult(home=resolved_home)

        # Global tenant-neutral directories (idempotent).
        _ensure_dir(skills_public_root(), _PUBLIC_SKILLS_MODE, result)
        _ensure_dir(resolved_home / "_system", _SYSTEM_DIR_MODE, result)

        # Tenant tree.
        _ensure_dir(tenant_root(tenant_id), _TENANT_DIR_MODE, result)
        _ensure_dir(skills_tenant_custom_root(tenant_id), _TENANT_DIR_MODE, result)
        _ensure_dir(tenant_shared_root(tenant_id), _TENANT_DIR_MODE, result)

        # Optional workspace tree.
        if workspace_id is not None:
            ws = workspace_root(tenant_id, workspace_id)
            _ensure_dir(ws, _TENANT_DIR_MODE, result)
            _ensure_dir(
                skills_workspace_user_root(tenant_id, workspace_id),
                _TENANT_DIR_MODE,
                result,
            )
            _ensure_dir(ws / "threads", _TENANT_DIR_MODE, result)

        return result
    finally:
        # Restore the env var to avoid leaking test-scoped overrides into
        # the wider process.
        if home is not None:
            if previous_home is None:
                os.environ.pop("DEER_FLOW_HOME", None)
            else:
                os.environ["DEER_FLOW_HOME"] = previous_home


def _positive_int(raw: str) -> int:
    """argparse type for strictly-positive integers."""
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a positive int, got {raw!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive int, got {value}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.gateway.identity.storage.cli",
        description=("Ensure the per-tenant (and optionally per-workspace) storage directory tree exists with 0700 permissions. Idempotent."),
    )
    parser.add_argument(
        "--tenant-id",
        type=_positive_int,
        required=True,
        help="Tenant id (positive integer).",
    )
    parser.add_argument(
        "--workspace-id",
        type=_positive_int,
        default=None,
        help="Optional workspace id (positive integer).",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help=("Override DeerFlow home root. Defaults to $DEER_FLOW_HOME or backend/.deer-flow."),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns an exit code (0 on success)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(
            tenant_id=args.tenant_id,
            workspace_id=args.workspace_id,
            home=args.home,
        )
    except (ValueError, PermissionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for line in result.summary_lines():
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via `python -m`
    raise SystemExit(main())
