"""Tests for app.gateway.identity.storage.paths.

These are pure unit tests: no directory creation, no I/O — only assertions
on constructed ``Path`` strings. ``DEER_FLOW_HOME`` is monkeypatched per test
to isolate the layout root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.gateway.identity.storage import paths as paths_mod
from app.gateway.identity.storage.paths import (
    audit_archive_path,
    audit_fallback_path,
    deerflow_home,
    migration_lock_path,
    migration_report_path,
    skills_public_root,
    skills_tenant_custom_root,
    skills_workspace_user_root,
    tenant_root,
    tenant_shared_root,
    thread_path,
    user_memory_path,
    workspace_root,
)

# ---------------------------------------------------------------------------
# Root resolution
# ---------------------------------------------------------------------------


def test_deerflow_home_uses_env_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    home = deerflow_home()
    assert home.is_absolute()
    assert home == tmp_path.resolve()


def test_deerflow_home_falls_back_to_backend_dot_deer_flow(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_HOME", raising=False)
    home = deerflow_home()
    assert home.is_absolute()
    # The fallback must resolve to a path that ends with "backend/.deer-flow"
    # and must exist *as a sibling of this test file*'s backend parent.
    # We don't create the dir — we just verify the path shape.
    assert home.name == ".deer-flow"
    assert home.parent.name == "backend"


def test_deerflow_home_empty_env_treated_as_unset(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", "")
    home = deerflow_home()
    # Empty string falls back to the default
    assert home.name == ".deer-flow"
    assert home.parent.name == "backend"


def test_deerflow_home_expands_user(tmp_path, monkeypatch):
    # Point $HOME at tmp_path so ~ expansion is deterministic
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DEER_FLOW_HOME", "~/customhome")
    home = deerflow_home()
    assert home == (tmp_path / "customhome").resolve()


# ---------------------------------------------------------------------------
# Tenant / workspace / thread
# ---------------------------------------------------------------------------


def test_tenant_root_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    assert tenant_root(7) == tmp_path.resolve() / "tenants" / "7"


def test_tenant_shared_root_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    assert tenant_shared_root(7) == tmp_path.resolve() / "tenants" / "7" / "shared"


def test_workspace_root_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    assert workspace_root(7, 42) == tmp_path.resolve() / "tenants" / "7" / "workspaces" / "42"


def test_thread_path_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    expected = tmp_path.resolve() / "tenants" / "7" / "workspaces" / "42" / "threads" / "thread-abc"
    assert thread_path(7, 42, "thread-abc") == expected


def test_paths_are_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    for p in [
        deerflow_home(),
        tenant_root(1),
        tenant_shared_root(1),
        workspace_root(1, 1),
        thread_path(1, 1, "t"),
        skills_public_root(),
        skills_tenant_custom_root(1),
        skills_workspace_user_root(1, 1),
        user_memory_path(1, 1),
        audit_fallback_path("20260422"),
        audit_archive_path(1, "2026-04"),
        migration_report_path("2026-04-22T00-00-00Z"),
        migration_lock_path(),
    ]:
        assert isinstance(p, Path)
        assert p.is_absolute()


# ---------------------------------------------------------------------------
# Skills layout — §7.2 loader priority: public -> tenant custom -> ws user
# ---------------------------------------------------------------------------


def test_skills_public_root_is_tenant_neutral(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # Must live at {home}/skills/public, NOT under tenants/
    assert skills_public_root() == tmp_path.resolve() / "skills" / "public"
    # Sanity: no tenants/ segment
    assert "tenants" not in skills_public_root().parts


def test_skills_tenant_custom_root_is_tenant_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    assert skills_tenant_custom_root(7) == tmp_path.resolve() / "tenants" / "7" / "custom"


def test_skills_workspace_user_root_is_workspace_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    assert skills_workspace_user_root(7, 42) == (tmp_path.resolve() / "tenants" / "7" / "workspaces" / "42" / "user")


def test_skills_roots_are_distinct(tmp_path, monkeypatch):
    """Verify the three scan roots in §7.2 are distinct paths."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    public = skills_public_root()
    custom = skills_tenant_custom_root(7)
    user = skills_workspace_user_root(7, 42)
    assert len({public, custom, user}) == 3


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def test_user_memory_path_layout(tmp_path, monkeypatch):
    """Spec §7.4: user memory lives under tenants/{tid}/users/{uid}/memory.json."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    expected = tmp_path.resolve() / "tenants" / "7" / "users" / "99" / "memory.json"
    assert user_memory_path(7, 99) == expected


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_audit_fallback_path_layout(tmp_path, monkeypatch):
    """Spec §9.3: fallback lives under _system/audit_fallback/{date}.jsonl."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    assert audit_fallback_path("20260422") == (tmp_path.resolve() / "_system" / "audit_fallback" / "20260422.jsonl")


def test_audit_fallback_path_rejects_malformed_date():
    for bad in ["", "2026-04-22", "20260422X", "2026042", "abcdefgh", "2026042200"]:
        with pytest.raises(ValueError):
            audit_fallback_path(bad)


def test_audit_archive_path_layout(tmp_path, monkeypatch):
    """Spec §9.6: archive is a FILE at _system/audit_archive/{tid}/{yyyy-mm}.jsonl.gz."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    assert audit_archive_path(7, "2026-04") == (tmp_path.resolve() / "_system" / "audit_archive" / "7" / "2026-04.jsonl.gz")


def test_audit_archive_path_is_file_not_directory(tmp_path, monkeypatch):
    """The archive path includes the .jsonl.gz suffix — it is a file, not a dir."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    p = audit_archive_path(7, "2026-04")
    assert p.suffix == ".gz"
    assert p.name.endswith(".jsonl.gz")


def test_audit_archive_path_rejects_malformed_month():
    for bad in ["", "202604", "2026/04", "2026-4", "26-04", "abcd-ef"]:
        with pytest.raises(ValueError):
            audit_archive_path(1, bad)


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


def test_migration_report_path_layout(tmp_path, monkeypatch):
    """Spec §10.2: reports live at _system/migration_report_{ts}.json."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    assert migration_report_path("2026-04-22T12-00-00Z") == (tmp_path.resolve() / "_system" / "migration_report_2026-04-22T12-00-00Z.json")


def test_migration_report_path_rejects_empty():
    with pytest.raises(ValueError):
        migration_report_path("")


def test_migration_lock_path_layout(tmp_path, monkeypatch):
    """Spec §7.1 / §10.2: the lock file lives under _system/."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    assert migration_lock_path() == tmp_path.resolve() / "_system" / "migration.lock"


# ---------------------------------------------------------------------------
# Defensive validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", [0, -1, -999])
def test_tenant_id_non_positive_rejected(bad_id, tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        tenant_root(bad_id)
    with pytest.raises(ValueError):
        tenant_shared_root(bad_id)
    with pytest.raises(ValueError):
        workspace_root(bad_id, 1)
    with pytest.raises(ValueError):
        thread_path(bad_id, 1, "t")
    with pytest.raises(ValueError):
        skills_tenant_custom_root(bad_id)
    with pytest.raises(ValueError):
        skills_workspace_user_root(bad_id, 1)
    with pytest.raises(ValueError):
        user_memory_path(bad_id, 1)
    with pytest.raises(ValueError):
        audit_archive_path(bad_id, "2026-04")


@pytest.mark.parametrize("bad_id", [0, -1, -999])
def test_workspace_id_non_positive_rejected(bad_id, tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        workspace_root(1, bad_id)
    with pytest.raises(ValueError):
        thread_path(1, bad_id, "t")
    with pytest.raises(ValueError):
        skills_workspace_user_root(1, bad_id)


@pytest.mark.parametrize("bad_id", [0, -1])
def test_user_id_non_positive_rejected(bad_id, tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        user_memory_path(1, bad_id)


def test_bool_rejected_even_though_it_is_an_int(tmp_path, monkeypatch):
    """``True``/``False`` pass ``isinstance(..., int)`` but must be rejected."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        tenant_root(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        tenant_root(False)  # type: ignore[arg-type]


def test_thread_id_must_be_non_empty_str(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        thread_path(1, 1, "")
    with pytest.raises(ValueError):
        thread_path(1, 1, 123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_id",
    [
        "../escape",
        "a/b",
        "a\\b",
        "..",
        "foo/../bar",
        "has\0nul",
    ],
)
def test_thread_id_rejects_path_traversal_chars(bad_id, tmp_path, monkeypatch):
    """Defence-in-depth: reject thread_id containing '/', '\\', '..', or NUL.

    Task 2's ``path_guard`` remains the primary defence, but consistency
    with the rest of this module (``_require_positive`` etc.) matters.
    """

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        thread_path(1, 1, bad_id)


# ---------------------------------------------------------------------------
# No side effects
# ---------------------------------------------------------------------------


def test_helpers_do_not_create_directories(tmp_path, monkeypatch):
    """Constructing paths must never touch the filesystem."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # Capture what already exists under tmp_path before any calls
    before = {p for p in tmp_path.rglob("*")}

    deerflow_home()
    tenant_root(1)
    tenant_shared_root(1)
    workspace_root(1, 1)
    thread_path(1, 1, "t")
    skills_public_root()
    skills_tenant_custom_root(1)
    skills_workspace_user_root(1, 1)
    user_memory_path(1, 1)
    audit_fallback_path("20260422")
    audit_archive_path(1, "2026-04")
    migration_report_path("ts")
    migration_lock_path()

    after = {p for p in tmp_path.rglob("*")}
    assert before == after


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_env_var_name_is_deer_flow_home_with_underscore():
    """Guard against a typo that would silently fall back to the default."""
    assert paths_mod._ENV_HOME == "DEER_FLOW_HOME"
