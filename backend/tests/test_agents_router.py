"""TestClient regressions for the agents router (M7a edit-page support)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.gateway.routers.agents as agents_router
import deerflow.config.paths as paths_module
from deerflow.config.agents_api_config import AgentsApiConfig
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_config import ToolGroupConfig


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agents_router.router)
    return app


@pytest.fixture
def enable_agents_api(monkeypatch):
    monkeypatch.setattr(
        "app.gateway.routers.agents.get_agents_api_config",
        lambda: AgentsApiConfig(enabled=True),
    )


@pytest.fixture
def stub_app_config(monkeypatch):
    """Provide a deterministic AppConfig.tool_groups list."""

    cfg = AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        tool_groups=[
            ToolGroupConfig(name="search"),
            ToolGroupConfig(name="python"),
            ToolGroupConfig(name="files"),
        ],
    )
    monkeypatch.setattr("app.gateway.routers.agents.get_app_config", lambda: cfg)
    return cfg


def test_list_tool_groups_returns_config_names(enable_agents_api, stub_app_config):
    with TestClient(_build_app()) as client:
        response = client.get("/api/tool-groups")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "tool_groups": [
            {"name": "search"},
            {"name": "python"},
            {"name": "files"},
        ]
    }


def test_list_tool_groups_returns_403_when_agents_api_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.gateway.routers.agents.get_agents_api_config",
        lambda: AgentsApiConfig(enabled=False),
    )

    with TestClient(_build_app()) as client:
        response = client.get("/api/tool-groups")

    assert response.status_code == 403
    assert "agents_api.enabled" in response.json()["detail"]


@pytest.fixture
def isolated_paths(monkeypatch, tmp_path):
    """Point every ``get_paths()`` caller at a tmp dir.

    Patches the module-level singleton in ``deerflow.config.paths`` so both
    the router and ``agents_config.load_agent_config`` (which imports
    ``get_paths`` from the same module) see the redirected ``Paths``.
    """
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths)
    return paths


def _seed_agent(paths: Paths, name: str, *, config: dict, soul: str = "") -> Path:
    agent_dir = paths.agent_dir(name)
    agent_dir.mkdir(parents=True, exist_ok=True)
    config = {"name": name, **config}
    (agent_dir / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")
    return agent_dir


def _read_yaml(agent_dir: Path) -> dict:
    return yaml.safe_load((agent_dir / "config.yaml").read_text(encoding="utf-8"))


def test_put_agent_tool_groups_three_state_transitions(
    enable_agents_api, isolated_paths
):
    """Round-trip every transition the edit page can produce.

    null  -> []       (turn off "use all", no selections)
    []    -> ["a"]    (add a selection)
    ["a"] -> null     (turn "use all" back on)
    """
    name = "edit-test-agent"
    agent_dir = _seed_agent(isolated_paths, name, config={})  # no tool_groups key = null

    client = TestClient(_build_app())

    # Transition 1: null -> []
    r1 = client.put(f"/api/agents/{name}", json={"tool_groups": []})
    assert r1.status_code == 200, r1.text
    assert r1.json()["tool_groups"] == []
    assert _read_yaml(agent_dir).get("tool_groups") == []

    # Transition 2: [] -> ["a"]
    r2 = client.put(f"/api/agents/{name}", json={"tool_groups": ["a"]})
    assert r2.status_code == 200, r2.text
    assert r2.json()["tool_groups"] == ["a"]
    assert _read_yaml(agent_dir).get("tool_groups") == ["a"]

    # Transition 3: ["a"] -> null
    # NOTE: existing handler only writes the key when value is not None,
    # so passing null in the JSON body should drop the key from the YAML.
    r3 = client.put(f"/api/agents/{name}", json={"tool_groups": None})
    assert r3.status_code == 200, r3.text
    assert r3.json()["tool_groups"] is None
    assert "tool_groups" not in _read_yaml(agent_dir)
