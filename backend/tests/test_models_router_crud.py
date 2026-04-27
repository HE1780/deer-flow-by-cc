"""Integration tests for /api/models POST/PUT/DELETE.

Uses a temp config.yaml via DEER_FLOW_CONFIG_PATH so writes are isolated.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

SAMPLE_YAML = """\
# Top-of-file comment that must survive writes.
config_version: 8
log_level: info
token_usage:
  enabled: false
models:
- name: minimax-m2.7
  display_name: MiniMax M2.7
  use: langchain_openai:ChatOpenAI
  model: MiniMax-M2.7
  api_key: $MINIMAX_API_KEY
  base_url: https://api.minimaxi.com/v1
  supports_thinking: true
  when_thinking_enabled:
    extra_body:
      thinking:
        type: enabled
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
"""


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(SAMPLE_YAML, encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("ENABLE_IDENTITY", "false")
    # Drop the identity settings cache so the env flip takes effect.
    from app.gateway.identity.settings import get_identity_settings
    from deerflow.config.app_config import reset_app_config

    get_identity_settings.cache_clear()
    reset_app_config()
    yield cfg
    get_identity_settings.cache_clear()
    reset_app_config()


@pytest.fixture
def client(isolated_config: Path) -> TestClient:
    from app.gateway.routers import models as models_router

    app = FastAPI()
    app.include_router(models_router.router)
    return TestClient(app)


def test_list_returns_seeded_model(client: TestClient) -> None:
    resp = client.get("/api/models")
    assert resp.status_code == 200
    body = resp.json()
    names = [m["name"] for m in body["models"]]
    assert "minimax-m2.7" in names


def test_create_model_appends_and_persists(
    client: TestClient, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `reload_app_config()` after write resolves `$ENV` placeholders.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fixture")
    payload = {
        "name": "gpt-4o",
        "model": "gpt-4o",
        "use": "langchain_openai:ChatOpenAI",
        "display_name": "GPT-4o",
        "api_key": "$OPENAI_API_KEY",
        "supports_vision": True,
    }
    resp = client.post("/api/models", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "gpt-4o"

    # File on disk has the new entry and kept the original.
    raw = isolated_config.read_text(encoding="utf-8")
    assert "name: gpt-4o" in raw
    assert "name: minimax-m2.7" in raw
    # Top-of-file comment preserved.
    assert raw.startswith("# Top-of-file comment")


def test_create_duplicate_name_conflicts(client: TestClient) -> None:
    payload = {
        "name": "minimax-m2.7",
        "model": "x",
        "use": "x:Y",
    }
    resp = client.post("/api/models", json=payload)
    assert resp.status_code == 409


def test_update_model_preserves_nested_keys(client: TestClient, isolated_config: Path) -> None:
    payload = {
        "name": "minimax-m2.7",
        "model": "MiniMax-M2.7",
        "use": "langchain_openai:ChatOpenAI",
        "display_name": "MiniMax (renamed)",
        "api_key": "$MINIMAX_API_KEY",
        "supports_thinking": True,
    }
    resp = client.put("/api/models/minimax-m2.7", json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "MiniMax (renamed)"

    raw = isolated_config.read_text(encoding="utf-8")
    # Nested when_thinking_enabled block preserved.
    assert "when_thinking_enabled:" in raw
    assert "type: enabled" in raw
    assert "MiniMax (renamed)" in raw


def test_update_path_name_mismatch(client: TestClient) -> None:
    payload = {
        "name": "different-name",
        "model": "x",
        "use": "x:Y",
    }
    resp = client.put("/api/models/minimax-m2.7", json=payload)
    assert resp.status_code == 400


def test_update_missing_returns_404(client: TestClient) -> None:
    payload = {
        "name": "ghost",
        "model": "x",
        "use": "x:Y",
    }
    resp = client.put("/api/models/ghost", json=payload)
    assert resp.status_code == 404


def test_delete_model(client: TestClient, isolated_config: Path) -> None:
    resp = client.delete("/api/models/minimax-m2.7")
    assert resp.status_code == 204

    raw = isolated_config.read_text(encoding="utf-8")
    assert "name: minimax-m2.7" not in raw

    list_resp = client.get("/api/models")
    assert list_resp.json()["models"] == []


def test_delete_missing_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/models/ghost")
    assert resp.status_code == 404


def test_get_raw_returns_unresolved_env_placeholder(client: TestClient) -> None:
    """Raw endpoint must NOT resolve `$VAR` to the env value."""
    resp = client.get("/api/admin/models/minimax-m2.7/raw")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["api_key"] == "$MINIMAX_API_KEY"
    # Nested fields preserved.
    assert "when_thinking_enabled" in body


def test_get_raw_404_for_missing(client: TestClient) -> None:
    resp = client.get("/api/admin/models/ghost/raw")
    assert resp.status_code == 404


def test_admin_required_when_identity_enabled(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ENABLE_IDENTITY=true and caller is anonymous → 401."""
    monkeypatch.setenv("ENABLE_IDENTITY", "true")
    from app.gateway.identity.settings import get_identity_settings
    from app.gateway.routers import models as models_router

    get_identity_settings.cache_clear()
    app = FastAPI()
    app.include_router(models_router.router)
    with TestClient(app) as client:
        resp = client.post(
            "/api/models",
            json={"name": "x", "model": "x", "use": "x:Y"},
        )
    assert resp.status_code == 401
