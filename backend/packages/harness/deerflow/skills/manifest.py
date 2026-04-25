"""Optional manifest.yaml loader for skill dependency declarations."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class EnvDeclaration:
    name: str
    source: str        # 'org_key' | 'env_var' | literal value
    required: bool = False


@dataclass
class SkillManifest:
    name: str
    version: str
    scope: str = "public"          # 'public' | 'org' | 'private'
    description: str = ""
    requires_tools: list[str] = field(default_factory=list)
    requires_mcp: list[str] = field(default_factory=list)
    env: list[EnvDeclaration] = field(default_factory=list)
    changelog: str = ""


def parse_skill_spec(spec: str) -> tuple[str, str | None]:
    """Parse 'skill-name@version' into (name, version).

    'data-analyst@v1.2.0' -> ('data-analyst', '1.2.0')
    'data-analyst@1.2.0'  -> ('data-analyst', '1.2.0')
    'data-analyst'         -> ('data-analyst', None)
    """
    if "@" not in spec:
        return spec, None
    name, version = spec.split("@", 1)
    version = version.lstrip("v")
    return name.strip(), version.strip() or None


def load_skill_manifest(skill_dir: Path) -> "SkillManifest | None":
    """Load and parse manifest.yaml from a skill directory.

    Returns None if the file does not exist or cannot be parsed.
    """
    manifest_path = skill_dir / "manifest.yaml"
    if not manifest_path.exists():
        return None

    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.warning("Invalid manifest.yaml at %s: %s", manifest_path, exc)
        return None

    if not isinstance(raw, dict):
        logger.warning("manifest.yaml at %s is not a mapping", manifest_path)
        return None

    name = raw.get("name")
    version = raw.get("version")
    if not name or not version:
        logger.warning("manifest.yaml at %s missing required name/version", manifest_path)
        return None

    env_list: list[EnvDeclaration] = []
    for entry in raw.get("env") or []:
        if isinstance(entry, dict) and "name" in entry and "source" in entry:
            env_list.append(
                EnvDeclaration(
                    name=entry["name"],
                    source=entry["source"],
                    required=bool(entry.get("required", False)),
                )
            )

    return SkillManifest(
        name=str(name),
        version=str(version),
        scope=str(raw.get("scope", "public")),
        description=str(raw.get("description", "")),
        requires_tools=list(raw.get("requires_tools") or []),
        requires_mcp=list(raw.get("requires_mcp") or []),
        env=env_list,
        changelog=str(raw.get("changelog", "")),
    )


def load_skill_manifest_by_name(
    name: str,
    version: str | None = None,
    skills_path: Path | None = None,
) -> "SkillManifest | None":
    """Look up a skill directory by name and load its manifest.yaml.

    Searches public/, custom/, and user/ roots (in that order) under skills_path.
    If version is specified, looks for a versioned subdirectory v{version}/
    inside the skill dir first, then falls back to the flat skill dir.
    """
    from deerflow.skills.loader import get_skills_root_path

    if skills_path is None:
        try:
            from deerflow.config import get_app_config
            skills_path = get_app_config().skills.get_skills_path()
        except Exception:
            skills_path = get_skills_root_path()

    for category in ("public", "custom", "user"):
        skill_dir = skills_path / category / name
        if not skill_dir.exists():
            continue
        if version:
            versioned = skill_dir / f"v{version}"
            if versioned.exists():
                manifest = load_skill_manifest(versioned)
                if manifest:
                    return manifest
        return load_skill_manifest(skill_dir)

    return None
