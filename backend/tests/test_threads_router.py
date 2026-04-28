from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.gateway.routers import threads
from deerflow.config.paths import Paths


def test_delete_thread_data_removes_thread_directory(tmp_path):
    paths = Paths(tmp_path)
    thread_dir = paths.resolve_thread_dir("thread-cleanup")
    workspace = paths.resolve_sandbox_work_dir("thread-cleanup")
    uploads = paths.resolve_sandbox_uploads_dir("thread-cleanup")
    outputs = paths.resolve_sandbox_outputs_dir("thread-cleanup")

    for directory in [workspace, uploads, outputs]:
        directory.mkdir(parents=True, exist_ok=True)
    (workspace / "notes.txt").write_text("hello", encoding="utf-8")
    (uploads / "report.pdf").write_bytes(b"pdf")
    (outputs / "result.json").write_text("{}", encoding="utf-8")

    assert thread_dir.exists()

    response = threads._delete_thread_data("thread-cleanup", paths=paths)

    assert response.success is True
    assert not thread_dir.exists()


def test_delete_thread_data_is_idempotent_for_missing_directory(tmp_path):
    paths = Paths(tmp_path)

    response = threads._delete_thread_data("missing-thread", paths=paths)

    assert response.success is True
    assert not paths.resolve_thread_dir("missing-thread").exists()


def test_delete_thread_data_rejects_invalid_thread_id(tmp_path):
    paths = Paths(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        threads._delete_thread_data("../escape", paths=paths)

    assert exc_info.value.status_code == 422
    assert "Invalid thread_id" in exc_info.value.detail


def test_delete_thread_route_cleans_thread_directory(tmp_path):
    paths = Paths(tmp_path)
    thread_dir = paths.resolve_thread_dir("thread-route")
    paths.resolve_sandbox_work_dir("thread-route").mkdir(parents=True, exist_ok=True)
    (paths.resolve_sandbox_work_dir("thread-route") / "notes.txt").write_text("hello", encoding="utf-8")

    app = FastAPI()
    app.include_router(threads.router)

    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/thread-route")

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Deleted local thread data for thread-route"}
    assert not thread_dir.exists()


def test_delete_thread_route_rejects_invalid_thread_id(tmp_path):
    paths = Paths(tmp_path)

    app = FastAPI()
    app.include_router(threads.router)

    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/../escape")

    assert response.status_code == 404


def test_delete_thread_route_returns_422_for_route_safe_invalid_id(tmp_path):
    paths = Paths(tmp_path)

    app = FastAPI()
    app.include_router(threads.router)

    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/thread.with.dot")

    assert response.status_code == 422
    assert "Invalid thread_id" in response.json()["detail"]


def test_delete_thread_data_returns_generic_500_error(tmp_path):
    paths = Paths(tmp_path)

    with (
        patch.object(paths, "delete_thread_dir_for", side_effect=OSError("/secret/path")),
        patch.object(threads.logger, "exception") as log_exception,
    ):
        with pytest.raises(HTTPException) as exc_info:
            threads._delete_thread_data("thread-cleanup", paths=paths)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to delete local thread data."
    assert "/secret/path" not in exc_info.value.detail
    log_exception.assert_called_once_with("Failed to delete thread data for %s", "thread-cleanup")


class TestDeleteThreadDataTenantAware:
    def test_delete_removes_tenant_directory_when_identity_present(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=str(tmp_path))
        tenant_dir = paths.tenant_thread_dir(1, 1, "thread-tenant")
        tenant_dir.mkdir(parents=True)
        (tenant_dir / "marker.txt").write_text("hi")

        response = threads._delete_thread_data(
            "thread-tenant",
            tenant_id=1,
            workspace_id=1,
            paths=paths,
        )

        assert response.success is True
        assert not tenant_dir.exists()

    def test_delete_falls_back_to_legacy_when_anonymous(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=str(tmp_path))
        legacy = tmp_path / "threads" / "thread-anon"
        legacy.mkdir(parents=True)
        (legacy / "marker.txt").write_text("x")

        response = threads._delete_thread_data(
            "thread-anon",
            tenant_id=None,
            workspace_id=None,
            paths=paths,
        )

        assert response.success is True
        assert not legacy.exists()

    def test_delete_route_reads_identity_and_forwards(self, tmp_path):
        """End-to-end via TestClient: route handler reads request.state.identity
        and passes ids to _delete_thread_data."""
        from types import SimpleNamespace

        from deerflow.config.paths import Paths

        paths = Paths(base_dir=str(tmp_path))
        tenant_dir = paths.tenant_thread_dir(1, 1, "thread-route-t")
        tenant_dir.mkdir(parents=True)

        app = FastAPI()
        app.include_router(threads.router)

        @app.middleware("http")
        async def _stub_identity(request, call_next):
            request.state.identity = SimpleNamespace(
                tenant_id=1, workspace_id=1, is_authenticated=True
            )
            return await call_next(request)

        with (
            patch("app.gateway.identity.request_scope.get_identity_settings") as ms,
            patch("app.gateway.routers.threads.get_paths", return_value=paths),
        ):
            ms.return_value.enabled = True
            with TestClient(app) as client:
                response = client.delete("/api/threads/thread-route-t")

        assert response.status_code == 200
        assert not tenant_dir.exists()
