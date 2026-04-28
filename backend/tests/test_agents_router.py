"""TestClient regressions for the agents router (M7a edit-page support)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.gateway.routers.agents as agents_router
from deerflow.config.agents_api_config import AgentsApiConfig
from deerflow.config.app_config import AppConfig
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
