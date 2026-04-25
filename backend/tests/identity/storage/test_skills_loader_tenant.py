"""Tests for the tenant-aware skills loader (M4 task 3).

Each test constructs a fake ``skills_path`` tree under ``tmp_path`` and
verifies the loader's scan priority, collision/override rules, symlink
guard, and extensions_config layering.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from deerflow.skills.loader import load_skills


def _write_skill(skill_dir: Path, name: str, description: str) -> None:
    """Write a minimal SKILL.md file with valid frontmatter."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolate_global_extensions_config(tmp_path, monkeypatch):
    """Point the global extensions config at a non-existent path per test.

    ``ExtensionsConfig.resolve_config_path`` walks back to the repo root, so
    without isolation each test would accidentally load the project's real
    extensions_config.json. We redirect it to an empty file inside tmp_path.
    """
    empty = tmp_path / "_global_extensions_config.json"
    empty.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(empty))


# ---------------------------------------------------------------------------
# Basic layout / scan priority
# ---------------------------------------------------------------------------


def test_flat_legacy_layout_no_tenant(tmp_path: Path) -> None:
    """Flat public/custom/user layout with tenant_id=None returns all 3."""
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "alpha", "alpha", "Alpha skill")
    _write_skill(skills_root / "custom" / "beta", "beta", "Beta skill")
    _write_skill(skills_root / "user" / "gamma", "gamma", "Gamma skill")

    skills = load_skills(skills_path=skills_root, use_config=False)
    by_name = {s.name: s for s in skills}

    assert set(by_name) == {"alpha", "beta", "gamma"}
    assert by_name["alpha"].category == "public"
    assert by_name["beta"].category == "custom"
    assert by_name["gamma"].category == "user"


def test_stratified_layout_tenant_and_workspace(tmp_path: Path) -> None:
    """Stratified layout with tenant+workspace returns all 3 tiers."""
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "alpha", "alpha", "Alpha")
    _write_skill(skills_root / "tenants" / "5" / "custom" / "beta", "beta", "Beta")
    _write_skill(
        skills_root / "tenants" / "5" / "workspaces" / "7" / "user" / "gamma",
        "gamma",
        "Gamma",
    )

    skills = load_skills(
        skills_path=skills_root,
        use_config=False,
        tenant_id=5,
        workspace_id=7,
    )
    by_name = {s.name: s for s in skills}

    assert set(by_name) == {"alpha", "beta", "gamma"}
    assert by_name["alpha"].category == "public"
    assert by_name["beta"].category == "custom"
    assert by_name["gamma"].category == "user"


# ---------------------------------------------------------------------------
# Collision / override semantics
# ---------------------------------------------------------------------------


def test_workspace_user_overrides_public(tmp_path: Path, caplog) -> None:
    """Same skill name in public/ and workspace/user/ — workspace wins."""
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "shared", "shared", "Public version")
    _write_skill(
        skills_root / "tenants" / "5" / "workspaces" / "7" / "user" / "shared",
        "shared",
        "Workspace version",
    )

    caplog.set_level(logging.WARNING, logger="deerflow.skills.loader")
    skills = load_skills(
        skills_path=skills_root,
        use_config=False,
        tenant_id=5,
        workspace_id=7,
    )

    shared = next(s for s in skills if s.name == "shared")
    assert shared.category == "user"
    assert shared.description == "Workspace version"
    assert any("Skill shared overridden by" in rec.message for rec in caplog.records)


def test_tenant_custom_overrides_public(tmp_path: Path, caplog) -> None:
    """Tenant custom beats public on name collision."""
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "shared", "shared", "Public version")
    _write_skill(
        skills_root / "tenants" / "5" / "custom" / "shared",
        "shared",
        "Tenant version",
    )

    caplog.set_level(logging.WARNING, logger="deerflow.skills.loader")
    skills = load_skills(
        skills_path=skills_root,
        use_config=False,
        tenant_id=5,
    )

    shared = next(s for s in skills if s.name == "shared")
    assert shared.category == "custom"
    assert shared.description == "Tenant version"
    assert any("Skill shared overridden by" in rec.message for rec in caplog.records)


def test_workspace_user_overrides_tenant_custom(tmp_path: Path, caplog) -> None:
    """Workspace version overrides tenant custom."""
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root / "tenants" / "5" / "custom" / "shared",
        "shared",
        "Tenant version",
    )
    _write_skill(
        skills_root / "tenants" / "5" / "workspaces" / "7" / "user" / "shared",
        "shared",
        "Workspace version",
    )

    caplog.set_level(logging.WARNING, logger="deerflow.skills.loader")
    skills = load_skills(
        skills_path=skills_root,
        use_config=False,
        tenant_id=5,
        workspace_id=7,
    )

    shared = next(s for s in skills if s.name == "shared")
    assert shared.category == "user"
    assert shared.description == "Workspace version"
    assert any("Skill shared overridden by" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Symlink guard
# ---------------------------------------------------------------------------


def test_symlink_to_other_tenant_is_skipped(tmp_path: Path, caplog) -> None:
    """A symlink in tenant 5's custom/ pointing into tenant 99's tree is skipped."""
    skills_root = tmp_path / "skills"
    # Real skill in a different tenant
    _write_skill(
        skills_root / "tenants" / "99" / "custom" / "other_skill",
        "other_skill",
        "Other tenant's skill",
    )
    # Tenant 5 has its own legit custom skill so we can assert it still loads
    _write_skill(
        skills_root / "tenants" / "5" / "custom" / "legit_skill",
        "legit_skill",
        "Legitimate tenant 5 skill",
    )

    # Symlink: tenant 5 custom/malicious -> tenant 99's skill directory
    malicious_link = skills_root / "tenants" / "5" / "custom" / "malicious"
    target = skills_root / "tenants" / "99" / "custom" / "other_skill"
    os.symlink(target, malicious_link, target_is_directory=True)

    caplog.set_level(logging.WARNING, logger="deerflow.skills.loader")
    skills = load_skills(
        skills_path=skills_root,
        use_config=False,
        tenant_id=5,
    )
    names = {s.name for s in skills}

    # The malicious symlink's realpath lives under tenants/99, which is
    # outside tenant 5's allowed subtree — it must be skipped.
    assert "other_skill" not in names
    assert "legit_skill" in names
    assert any("escapes allowed root" in rec.message for rec in caplog.records)


def test_symlink_within_tenant_subtree_is_allowed(tmp_path: Path, caplog) -> None:
    """A symlink inside the tenant's own subtree resolves cleanly — no warning."""
    skills_root = tmp_path / "skills"
    # Real skill under workspace 7 user/
    _write_skill(
        skills_root / "tenants" / "5" / "workspaces" / "7" / "user" / "real_skill",
        "real_skill",
        "Real workspace skill",
    )

    # Alias inside tenant 5's custom/ pointing at the workspace-user skill dir
    alias_link = skills_root / "tenants" / "5" / "custom" / "alias"
    target = skills_root / "tenants" / "5" / "workspaces" / "7" / "user" / "real_skill"
    alias_link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, alias_link, target_is_directory=True)

    caplog.set_level(logging.WARNING, logger="deerflow.skills.loader")
    # Scan with tenant_id=5 only so we don't scan the workspace tier directly.
    skills = load_skills(
        skills_path=skills_root,
        use_config=False,
        tenant_id=5,
    )
    by_name = {s.name: s for s in skills}

    # The custom/ scan should pick up the symlinked skill (realpath under tenants/5).
    assert "real_skill" in by_name
    assert by_name["real_skill"].category == "custom"
    assert not any("escapes allowed root" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Extensions config layering
# ---------------------------------------------------------------------------


def test_tenant_config_disables_globally_enabled_skill(tmp_path: Path, monkeypatch) -> None:
    """Tenant-level config with enabled=false hides a globally-enabled skill."""
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "my_skill", "my_skill", "My skill")

    # Global config enables my_skill explicitly (it would be enabled anyway,
    # but be explicit for clarity).
    global_cfg = tmp_path / "global_extensions_config.json"
    global_cfg.write_text(
        json.dumps({"mcpServers": {}, "skills": {"my_skill": {"enabled": True}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(global_cfg))

    # Tenant config disables my_skill.
    tenant_dir = skills_root / "tenants" / "5"
    tenant_dir.mkdir(parents=True, exist_ok=True)
    (tenant_dir / "extensions_config.json").write_text(
        json.dumps({"mcpServers": {}, "skills": {"my_skill": {"enabled": False}}}),
        encoding="utf-8",
    )

    skills = load_skills(
        skills_path=skills_root,
        use_config=False,
        enabled_only=True,
        tenant_id=5,
    )
    assert "my_skill" not in {s.name for s in skills}


def test_tenant_config_cannot_reenable_globally_disabled_skill(tmp_path: Path, monkeypatch) -> None:
    """Global disable wins — tenant cannot re-enable a globally-disabled skill."""
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "other_skill", "other_skill", "Other skill")

    # Global config disables other_skill.
    global_cfg = tmp_path / "global_extensions_config.json"
    global_cfg.write_text(
        json.dumps({"mcpServers": {}, "skills": {"other_skill": {"enabled": False}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(global_cfg))

    # Tenant config tries to enable it.
    tenant_dir = skills_root / "tenants" / "5"
    tenant_dir.mkdir(parents=True, exist_ok=True)
    (tenant_dir / "extensions_config.json").write_text(
        json.dumps({"mcpServers": {}, "skills": {"other_skill": {"enabled": True}}}),
        encoding="utf-8",
    )

    skills = load_skills(
        skills_path=skills_root,
        use_config=False,
        enabled_only=True,
        tenant_id=5,
    )
    assert "other_skill" not in {s.name for s in skills}


# ---------------------------------------------------------------------------
# Workspace-absent mode
# ---------------------------------------------------------------------------


def test_tenant_only_skips_workspace_user_tier(tmp_path: Path) -> None:
    """tenant_id=5 + workspace_id=None skips the workspace user/ tier."""
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "alpha", "alpha", "Alpha")
    _write_skill(
        skills_root / "tenants" / "5" / "custom" / "beta",
        "beta",
        "Beta",
    )
    # This workspace-user skill should NOT be returned when workspace_id is None.
    _write_skill(
        skills_root / "tenants" / "5" / "workspaces" / "7" / "user" / "gamma",
        "gamma",
        "Gamma",
    )

    skills = load_skills(
        skills_path=skills_root,
        use_config=False,
        tenant_id=5,
    )
    names = {s.name for s in skills}
    assert names == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# Harness boundary
# ---------------------------------------------------------------------------


def test_harness_boundary_still_clean() -> None:
    """Loader must not import from app.* — duplicate the import firewall check here."""
    import ast

    loader_path = Path(__file__).resolve().parents[3] / "packages" / "harness" / "deerflow" / "skills" / "loader.py"
    tree = ast.parse(loader_path.read_text(encoding="utf-8"), filename=str(loader_path))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app" or alias.name.startswith("app."):
                    offenders.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app" or module.startswith("app."):
                offenders.append(f"line {node.lineno}: from {module}")

    assert not offenders, "loader.py imports from app.*: " + "; ".join(offenders)
