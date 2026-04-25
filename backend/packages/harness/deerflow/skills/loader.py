import logging
import os
from pathlib import Path

from .parser import parse_skill_file
from .types import Skill

logger = logging.getLogger(__name__)


def get_skills_root_path() -> Path:
    """
    Get the root path of the skills directory.

    Returns:
        Path to the skills directory (deer-flow/skills)
    """
    # loader.py lives at packages/harness/deerflow/skills/loader.py — 5 parents up reaches backend/
    backend_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    # skills directory is sibling to backend directory
    skills_dir = backend_dir.parent / "skills"
    return skills_dir


def _build_scan_plan(
    skills_path: Path,
    tenant_id: int | None,
    workspace_id: int | None,
) -> list[tuple[Path, str, Path]]:
    """Build an ordered scan plan for ``load_skills``.

    Each entry is a tuple ``(scan_root, category, allowed_realpath_root)``:

    * ``scan_root`` — directory that ``os.walk`` descends.
    * ``category`` — value stored on ``Skill.category`` (``"public" | "custom" | "user"``).
    * ``allowed_realpath_root`` — tree that ``SKILL.md`` realpaths must stay
      within. Symlinks pointing outside this root are rejected by the caller.
    """
    plan: list[tuple[Path, str, Path]] = []

    if tenant_id is not None and workspace_id is not None:
        # Multi-tenant mode with workspace. Workspace user skills override
        # tenant-custom, which in turn override public.
        tenant_subtree = skills_path / "tenants" / str(tenant_id)
        plan.append((skills_path / "public", "public", skills_path / "public"))
        plan.append((tenant_subtree / "custom", "custom", tenant_subtree))
        plan.append(
            (
                tenant_subtree / "workspaces" / str(workspace_id) / "user",
                "user",
                tenant_subtree,
            )
        )
    elif tenant_id is not None:
        # Tenant-only mode: no workspace-user layer.
        tenant_subtree = skills_path / "tenants" / str(tenant_id)
        plan.append((skills_path / "public", "public", skills_path / "public"))
        plan.append((tenant_subtree / "custom", "custom", tenant_subtree))
    else:
        # Legacy flag-off mode: flat ``public/custom/user`` layout.
        plan.append((skills_path / "public", "public", skills_path / "public"))
        plan.append((skills_path / "custom", "custom", skills_path / "custom"))
        plan.append((skills_path / "user", "user", skills_path / "user"))

    return plan


def _is_under(child: Path, parent: Path) -> bool:
    """Return True if the resolved ``child`` is inside the resolved ``parent``.

    Uses ``resolve(strict=False)`` so that a non-existent ``parent`` still
    yields a stable comparison — we simply fail closed (return ``False``)
    when the parent cannot be resolved.
    """
    try:
        child_resolved = child.resolve(strict=False)
        parent_resolved = parent.resolve(strict=False)
    except OSError:
        return False

    try:
        return child_resolved.is_relative_to(parent_resolved)
    except AttributeError:  # pragma: no cover — Python <3.9 fallback
        try:
            child_resolved.relative_to(parent_resolved)
            return True
        except ValueError:
            return False


def _scan_root(
    scan_root: Path,
    category: str,
    allowed_realpath_root: Path,
    skills_by_name: dict[str, Skill],
) -> None:
    """Walk ``scan_root`` and add any discovered SKILL.md files to ``skills_by_name``.

    Later calls override earlier entries on name collision (with a warning).
    Skill files whose realpath escapes ``allowed_realpath_root`` are skipped.
    """
    logger.debug("Scanning skills root: %s (category=%s)", scan_root, category)
    if not scan_root.exists() or not scan_root.is_dir():
        return

    for current_root, dir_names, file_names in os.walk(scan_root, followlinks=True):
        # Keep traversal deterministic and skip hidden directories.
        dir_names[:] = sorted(name for name in dir_names if not name.startswith("."))
        if "SKILL.md" not in file_names:
            continue

        skill_file = Path(current_root) / "SKILL.md"

        # Symlink guard: realpath must stay within the allowed subtree.
        if not _is_under(skill_file, allowed_realpath_root):
            logger.warning(
                "Skipping skill at %s: symlink target %s escapes allowed root %s",
                skill_file,
                skill_file.resolve(strict=False),
                allowed_realpath_root,
            )
            continue

        relative_path = skill_file.parent.relative_to(scan_root)
        skill = parse_skill_file(skill_file, category=category, relative_path=relative_path)
        if skill is None:
            continue

        existing = skills_by_name.get(skill.name)
        if existing is not None:
            logger.warning(
                "Skill %s overridden by %s (was %s)",
                skill.name,
                skill.skill_file,
                existing.skill_file,
            )
        skills_by_name[skill.name] = skill


def _load_tenant_extensions_config(skills_path: Path, tenant_id: int):
    """Load the tenant-level ``extensions_config.json`` if present.

    Returns ``None`` when the file does not exist. Any loader error is
    logged and also returns ``None`` so that a malformed tenant file cannot
    break global skill loading.
    """
    tenant_cfg_path = skills_path / "tenants" / str(tenant_id) / "extensions_config.json"
    if not tenant_cfg_path.exists():
        return None
    try:
        from deerflow.config.extensions_config import ExtensionsConfig

        return ExtensionsConfig.from_file(config_path=str(tenant_cfg_path))
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Failed to load tenant extensions config at %s: %s", tenant_cfg_path, exc)
        return None


def _resolve_enabled_state(skill_name: str, skill_category: str, global_cfg, tenant_cfg) -> bool:
    """Return whether ``skill_name`` is enabled under layered configs.

    Tenants can disable a globally-enabled skill, but cannot re-enable a skill
    that the global layer has explicitly disabled (effective set is the
    intersection of enabled sets).
    """
    globally_enabled = global_cfg.is_skill_enabled(skill_name, skill_category)
    if tenant_cfg is None:
        return globally_enabled
    if not globally_enabled:
        # Global disable wins — tenant cannot re-enable.
        return False
    tenant_entry = tenant_cfg.skills.get(skill_name)
    if tenant_entry is None:
        return globally_enabled
    return bool(tenant_entry.enabled)


def load_skills(
    skills_path: Path | None = None,
    *,
    use_config: bool = True,
    enabled_only: bool = False,
    tenant_id: int | None = None,
    workspace_id: int | None = None,
) -> list[Skill]:
    """
    Load all skills from the skills directory.

    Scan priority (later-in-order wins on name collision):

    * When both ``tenant_id`` and ``workspace_id`` are provided:
        1. ``skills_path/public/``
        2. ``skills_path/tenants/{tenant_id}/custom/``
        3. ``skills_path/tenants/{tenant_id}/workspaces/{workspace_id}/user/``

    * When only ``tenant_id`` is provided:
        1. ``skills_path/public/``
        2. ``skills_path/tenants/{tenant_id}/custom/``

    * Legacy flag-off mode (both absent):
        1. ``skills_path/public/``
        2. ``skills_path/custom/``
        3. ``skills_path/user/``

    Args:
        skills_path: Optional custom path to skills directory.
                     If not provided and use_config is True, uses path from config.
                     Otherwise defaults to deer-flow/skills.
        use_config: Whether to load skills path from config (default: True).
        enabled_only: If True, only return enabled skills (default: False).
        tenant_id: Optional tenant identifier used to scope the scan to
                   ``skills_path/tenants/{tenant_id}/...``.
        workspace_id: Optional workspace identifier (requires ``tenant_id``)
                      used to scope the workspace-user layer.

    Returns:
        List of Skill objects, sorted by name.
    """
    if skills_path is None:
        if use_config:
            try:
                from deerflow.config import get_app_config

                config = get_app_config()
                skills_path = config.skills.get_skills_path()
            except Exception:
                # Fallback to default if config fails
                skills_path = get_skills_root_path()
        else:
            skills_path = get_skills_root_path()

    if not skills_path.exists():
        return []

    skills_by_name: dict[str, Skill] = {}

    for scan_root, category, allowed_realpath_root in _build_scan_plan(skills_path, tenant_id, workspace_id):
        _scan_root(scan_root, category, allowed_realpath_root, skills_by_name)

    skills = list(skills_by_name.values())

    # Load extensions config (global, and tenant-level when tenant_id set) and
    # update each skill's enabled state. We use ``ExtensionsConfig.from_file()``
    # instead of ``get_extensions_config()`` so that changes made through the
    # Gateway API (running in a separate process) are picked up immediately.
    try:
        from deerflow.config.extensions_config import ExtensionsConfig

        global_cfg = ExtensionsConfig.from_file()
        tenant_cfg = _load_tenant_extensions_config(skills_path, tenant_id) if tenant_id is not None else None
        for skill in skills:
            skill.enabled = _resolve_enabled_state(skill.name, skill.category, global_cfg, tenant_cfg)
    except Exception as e:
        # If config loading fails, default to all enabled.
        logger.warning("Failed to load extensions config: %s", e)

    if enabled_only:
        skills = [skill for skill in skills if skill.enabled]

    skills.sort(key=lambda s: s.name)
    logger.debug("Loaded %d skills (tenant_id=%s workspace_id=%s)", len(skills), tenant_id, workspace_id)

    return skills
