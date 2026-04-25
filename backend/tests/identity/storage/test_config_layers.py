"""Tests for app.gateway.identity.storage.config_layers.

These tests write real YAML files to ``tmp_path`` and exercise
:func:`load_layered_config` end-to-end. The pure merge primitive
(:func:`merge_config`) is exercised directly where convenient.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.gateway.identity.storage.config_layers import (
    SENSITIVE_GLOBAL_ONLY,
    SensitiveFieldViolation,
    load_layered_config,
    merge_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))
    return path


def _tenant_cfg_path(home: Path, tid: int) -> Path:
    return home / "tenants" / str(tid) / "config.yaml"


def _workspace_cfg_path(home: Path, tid: int, wid: int) -> Path:
    return home / "tenants" / str(tid) / "workspaces" / str(wid) / "config.yaml"


# ---------------------------------------------------------------------------
# 1. global-only
# ---------------------------------------------------------------------------


def test_global_only_returns_global_dict_and_global_cache_key(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"foo": 1, "nested": {"x": 10}})

    merged, key = load_layered_config(
        global_path,
        tenant_id=None,
        workspace_id=None,
        deerflow_home=tmp_path,
    )

    assert merged == {"foo": 1, "nested": {"x": 10}}
    assert key == "global"


# ---------------------------------------------------------------------------
# 2. tenant overlay merges non-sensitive key
# ---------------------------------------------------------------------------


def test_tenant_overlay_merges_nested_dict(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"foo": 1, "bar": {"x": 10}})
    _write_yaml(_tenant_cfg_path(tmp_path, 5), {"bar": {"y": 20}})

    merged, key = load_layered_config(global_path, tenant_id=5, workspace_id=None, deerflow_home=tmp_path)

    assert merged == {"foo": 1, "bar": {"x": 10, "y": 20}}
    assert key == "global:5"


# ---------------------------------------------------------------------------
# 3. workspace overlay wins over tenant and global
# ---------------------------------------------------------------------------


def test_workspace_overlay_wins_over_lower_layers(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"scalar": "global"})
    _write_yaml(_tenant_cfg_path(tmp_path, 5), {"scalar": "tenant"})
    _write_yaml(_workspace_cfg_path(tmp_path, 5, 7), {"scalar": "workspace"})

    merged, key = load_layered_config(global_path, tenant_id=5, workspace_id=7, deerflow_home=tmp_path)

    assert merged["scalar"] == "workspace"
    assert key == "5:7"


# ---------------------------------------------------------------------------
# 4. tenant sets models[0].api_key -> violation
# ---------------------------------------------------------------------------


def test_tenant_setting_model_api_key_raises(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"models": [{"name": "gpt-4", "api_key": "SECRET"}]})
    _write_yaml(
        _tenant_cfg_path(tmp_path, 5),
        {"models": [{"name": "gpt-4", "api_key": "OVERRIDE"}]},
    )

    with pytest.raises(SensitiveFieldViolation) as exc_info:
        load_layered_config(global_path, tenant_id=5, workspace_id=None, deerflow_home=tmp_path)

    msg = str(exc_info.value)
    assert "tenant" in msg
    assert "models[*].api_key" in msg


# ---------------------------------------------------------------------------
# 5. workspace sets sandbox.provisioner.api_key -> violation
# ---------------------------------------------------------------------------


def test_workspace_setting_sandbox_provisioner_api_key_raises(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"sandbox": {"provisioner": {"api_key": "SECRET"}}})
    _write_yaml(_tenant_cfg_path(tmp_path, 5), {"other": 1})
    _write_yaml(
        _workspace_cfg_path(tmp_path, 5, 7),
        {"sandbox": {"provisioner": {"api_key": "OVERRIDE"}}},
    )

    with pytest.raises(SensitiveFieldViolation) as exc_info:
        load_layered_config(global_path, tenant_id=5, workspace_id=7, deerflow_home=tmp_path)

    msg = str(exc_info.value)
    assert "workspace" in msg
    assert "sandbox.provisioner.api_key" in msg


# ---------------------------------------------------------------------------
# 6. tenant sets non-sensitive field inside models[0] (temperature) -> OK
# ---------------------------------------------------------------------------


def test_tenant_may_set_non_sensitive_field_in_model_element(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(
        global_path,
        {"models": [{"name": "gpt-4", "api_key": "SECRET", "temperature": 0.1}]},
    )
    _write_yaml(
        _tenant_cfg_path(tmp_path, 5),
        {"models": [{"name": "gpt-4", "temperature": 0.7}]},
    )

    merged, _ = load_layered_config(global_path, tenant_id=5, workspace_id=None, deerflow_home=tmp_path)

    # list-replace semantics: tenant models list wins wholesale, but since
    # that list doesn't contain api_key, no violation raised.
    assert merged["models"] == [{"name": "gpt-4", "temperature": 0.7}]


# ---------------------------------------------------------------------------
# 7. list-merge semantics: tenant replaces global list wholesale
# ---------------------------------------------------------------------------


def test_tenant_list_replaces_global_list(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"tools": ["x"]})
    _write_yaml(_tenant_cfg_path(tmp_path, 5), {"tools": ["a", "b"]})

    merged, _ = load_layered_config(global_path, tenant_id=5, workspace_id=None, deerflow_home=tmp_path)

    assert merged["tools"] == ["a", "b"]


# ---------------------------------------------------------------------------
# 8. Missing tenant file: only global returned, no error
# ---------------------------------------------------------------------------


def test_missing_tenant_file_is_silently_skipped(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"foo": 1})

    merged, key = load_layered_config(global_path, tenant_id=5, workspace_id=None, deerflow_home=tmp_path)

    assert merged == {"foo": 1}
    assert key == "global:5"


# ---------------------------------------------------------------------------
# 9. Empty tenant file (empty YAML) -> treated as {}
# ---------------------------------------------------------------------------


def test_empty_tenant_file_is_treated_as_empty_dict(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"foo": 1, "bar": 2})

    tenant_file = _tenant_cfg_path(tmp_path, 5)
    tenant_file.parent.mkdir(parents=True, exist_ok=True)
    tenant_file.write_text("")  # empty file

    merged, _ = load_layered_config(global_path, tenant_id=5, workspace_id=None, deerflow_home=tmp_path)

    assert merged == {"foo": 1, "bar": 2}


def test_yaml_null_tenant_file_is_treated_as_empty_dict(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"foo": 1})

    tenant_file = _tenant_cfg_path(tmp_path, 5)
    tenant_file.parent.mkdir(parents=True, exist_ok=True)
    tenant_file.write_text("# just a comment, no data\n")

    merged, _ = load_layered_config(global_path, tenant_id=5, workspace_id=None, deerflow_home=tmp_path)

    assert merged == {"foo": 1}


# ---------------------------------------------------------------------------
# 10. Cache-key shape (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tid,wid,expected",
    [
        (None, None, "global"),
        (5, None, "global:5"),
        (5, 7, "5:7"),
    ],
)
def test_cache_key_shape(tmp_path: Path, tid: int | None, wid: int | None, expected: str) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"foo": 1})

    _, key = load_layered_config(global_path, tenant_id=tid, workspace_id=wid, deerflow_home=tmp_path)
    assert key == expected


# ---------------------------------------------------------------------------
# 11. merge_config does not mutate inputs
# ---------------------------------------------------------------------------


def test_merge_config_does_not_mutate_inputs() -> None:
    global_cfg = {"foo": 1, "nested": {"x": 10, "list": [1, 2]}}
    tenant_cfg = {"nested": {"y": 20}}
    workspace_cfg = {"extra": True}

    global_snapshot = {"foo": 1, "nested": {"x": 10, "list": [1, 2]}}
    tenant_snapshot = {"nested": {"y": 20}}
    workspace_snapshot = {"extra": True}

    merged = merge_config(global_cfg, tenant_cfg, workspace_cfg)

    assert global_cfg == global_snapshot
    assert tenant_cfg == tenant_snapshot
    assert workspace_cfg == workspace_snapshot

    # Mutating the result must not reach back into inputs.
    merged["nested"]["x"] = 999
    merged["nested"]["list"].append(99)
    assert global_cfg["nested"]["x"] == 10
    assert global_cfg["nested"]["list"] == [1, 2]


# ---------------------------------------------------------------------------
# Extra sanity checks
# ---------------------------------------------------------------------------


def test_sensitive_global_only_contains_expected_paths() -> None:
    # Safety net: if someone narrows the set, the caller wiring will
    # silently lose protection. This test is the tripwire.
    for required in (
        "models[*].api_key",
        "models[*].endpoint",
        "models[*].base_url",
        "sandbox.provisioner.api_key",
        "sandbox.provisioner.endpoint",
        "memory.storage_path",
    ):
        assert required in SENSITIVE_GLOBAL_ONLY


def test_workspace_layer_sets_memory_storage_path_raises(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"memory": {"storage_path": "/safe/path"}})
    _write_yaml(
        _workspace_cfg_path(tmp_path, 5, 7),
        {"memory": {"storage_path": "/evil/../path"}},
    )

    with pytest.raises(SensitiveFieldViolation) as exc_info:
        load_layered_config(global_path, tenant_id=5, workspace_id=7, deerflow_home=tmp_path)

    msg = str(exc_info.value)
    assert "workspace" in msg
    assert "memory.storage_path" in msg


def test_tenant_may_add_new_model_without_api_key(tmp_path: Path) -> None:
    """A tenant that adds a new entry to ``models`` without setting api_key is fine."""

    global_path = tmp_path / "global.yaml"
    _write_yaml(
        global_path,
        {"models": [{"name": "gpt-4", "api_key": "SECRET"}]},
    )
    _write_yaml(
        _tenant_cfg_path(tmp_path, 5),
        {"models": [{"name": "custom-local", "temperature": 0.5}]},
    )

    merged, _ = load_layered_config(global_path, tenant_id=5, workspace_id=None, deerflow_home=tmp_path)
    assert merged["models"] == [{"name": "custom-local", "temperature": 0.5}]


def test_merge_config_handles_none_layers() -> None:
    merged = merge_config({"a": 1}, None, None)
    assert merged == {"a": 1}
    merged = merge_config({}, None, None)
    assert merged == {}


def test_merge_config_with_non_mapping_yaml_raises(tmp_path: Path) -> None:
    """Top-level YAML must be a mapping; a top-level list / string is rejected."""

    global_path = tmp_path / "global.yaml"
    global_path.write_text("- just\n- a\n- list\n")

    with pytest.raises(ValueError, match="must parse to a mapping"):
        load_layered_config(global_path, tenant_id=None, workspace_id=None, deerflow_home=tmp_path)


def test_sensitive_field_null_value_also_raises() -> None:
    """A tenant overlay that sets a sensitive field to YAML null still violates.

    The contract is "tenant must not TOUCH these keys", not "tenant must
    not set a truthy value". Without this guard, ``api_key: ~`` would
    clobber the global secret with ``None`` through deep-merge.
    """

    with pytest.raises(SensitiveFieldViolation) as exc_info:
        merge_config(
            {"sandbox": {"provisioner": {"api_key": "SECRET"}}},
            {"sandbox": {"provisioner": {"api_key": None}}},
            None,
        )

    msg = str(exc_info.value)
    assert "tenant" in msg
    assert "sandbox.provisioner.api_key" in msg


def test_workspace_id_without_tenant_raises(tmp_path: Path) -> None:
    """``workspace_id`` without ``tenant_id`` is an invalid arg combination."""

    global_path = tmp_path / "global.yaml"
    _write_yaml(global_path, {"foo": 1})

    with pytest.raises(ValueError, match="workspace_id requires tenant_id"):
        load_layered_config(global_path, tenant_id=None, workspace_id=7, deerflow_home=tmp_path)
