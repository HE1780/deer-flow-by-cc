"""Tests for the uploads router tenant/workspace authz guard (M4 task 7).

Like ``test_artifacts_authz.py``, these tests build a minimal FastAPI app,
inject a synthetic identity via middleware, and exercise the resolve /
guard path against a real tenant-stratified filesystem in ``tmp_path``.
They purposely avoid Postgres/Redis — full identity stack coverage is in
``tests/identity/auth/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

import app.gateway.routers.uploads as uploads_router
from app.gateway.identity.settings import get_identity_settings
from deerflow.config import paths as paths_mod


@dataclass
class FakeIdentity:
    tenant_id: int | None
    workspace_ids: tuple[int, ...]
    is_authenticated: bool = True


def _inject_identity_middleware(app: FastAPI, identity: FakeIdentity | None):
    class _Inject(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.identity = identity
            return await call_next(request)

    app.add_middleware(_Inject)


class _NoopSandboxProvider:
    """Sandbox provider stub that uses thread-data mounts (so no sync path)."""

    uses_thread_data_mounts = True

    def acquire(self, thread_id, *, tenant_id=None, workspace_id=None):
        return "noop"

    def get(self, sandbox_id):
        return None

    def release(self, sandbox_id):  # pragma: no cover
        pass


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_mod, "_paths", None)
    # Force uploads router to always take the "thread-data mounts" branch so
    # the sandbox provider is never consulted.
    monkeypatch.setattr(uploads_router, "get_sandbox_provider", lambda: _NoopSandboxProvider())
    yield tmp_path
    monkeypatch.setattr(paths_mod, "_paths", None)


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setenv("ENABLE_IDENTITY", "false")
    get_identity_settings.cache_clear()
    yield
    get_identity_settings.cache_clear()


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("ENABLE_IDENTITY", "true")
    get_identity_settings.cache_clear()
    yield
    get_identity_settings.cache_clear()


def _make_app(identity: FakeIdentity | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(uploads_router.router)
    _inject_identity_middleware(app, identity)
    return app


def _upload(client: TestClient, thread_id: str, filename: str, content: bytes):
    return client.post(
        f"/api/threads/{thread_id}/uploads",
        files={"files": (filename, BytesIO(content), "text/plain")},
    )


# ---------------------------------------------------------------------------
# Flag OFF — legacy layout preserved.
# ---------------------------------------------------------------------------


def test_flag_off_upload_uses_legacy_layout(isolated_home, flag_off):
    app = _make_app(identity=FakeIdentity(tenant_id=5, workspace_ids=(7,)))

    with TestClient(app) as client:
        r = _upload(client, "t1", "hello.txt", b"legacy")
    assert r.status_code == 200, r.text

    legacy_file = isolated_home / "threads" / "t1" / "user-data" / "uploads" / "hello.txt"
    assert legacy_file.exists()
    assert legacy_file.read_bytes() == b"legacy"
    # Tenant tree must NOT exist when flag is off.
    assert not (isolated_home / "tenants").exists()


def test_flag_off_list_and_delete_use_legacy_layout(isolated_home, flag_off):
    app = _make_app(identity=FakeIdentity(tenant_id=5, workspace_ids=(7,)))
    with TestClient(app) as client:
        _upload(client, "t1", "hello.txt", b"legacy")
        r_list = client.get("/api/threads/t1/uploads/list")
        r_del = client.delete("/api/threads/t1/uploads/hello.txt")

    assert r_list.status_code == 200
    assert r_list.json()["count"] == 1
    assert r_del.status_code == 200

    legacy_file = isolated_home / "threads" / "t1" / "user-data" / "uploads" / "hello.txt"
    assert not legacy_file.exists()


# ---------------------------------------------------------------------------
# Flag ON — same-tenant uploads land under tenants/{tid}/workspaces/{wid}/.
# ---------------------------------------------------------------------------


def test_flag_on_same_tenant_upload_lands_in_tenant_path(isolated_home, flag_on):
    app = _make_app(identity=FakeIdentity(tenant_id=5, workspace_ids=(7,)))

    with TestClient(app) as client:
        r = _upload(client, "t1", "hello.txt", b"scoped")
    assert r.status_code == 200, r.text

    tenant_file = isolated_home / "tenants" / "5" / "workspaces" / "7" / "threads" / "t1" / "user-data" / "uploads" / "hello.txt"
    assert tenant_file.exists()
    assert tenant_file.read_bytes() == b"scoped"
    # Legacy tree must NOT be created.
    assert not (isolated_home / "threads").exists()


def test_flag_on_same_tenant_list_shows_only_tenant_files(isolated_home, flag_on):
    """LIST for tenant A does not leak tenant B's uploads."""
    app_a = _make_app(identity=FakeIdentity(tenant_id=5, workspace_ids=(7,)))
    app_b = _make_app(identity=FakeIdentity(tenant_id=99, workspace_ids=(1,)))

    with TestClient(app_a) as c_a:
        _upload(c_a, "t1", "mine.txt", b"a")

    with TestClient(app_b) as c_b:
        _upload(c_b, "t1", "other.txt", b"b")
        r = c_b.get("/api/threads/t1/uploads/list")

    assert r.status_code == 200, r.text
    files = r.json()["files"]
    names = {f["filename"] for f in files}
    # Tenant B sees ONLY its own file — mine.txt belongs to tenant A's tree.
    assert names == {"other.txt"}


def test_flag_on_same_tenant_delete_only_removes_own_file(isolated_home, flag_on):
    """DELETE targets the caller's tenant tree; the other tenant's file survives."""
    app_a = _make_app(identity=FakeIdentity(tenant_id=5, workspace_ids=(7,)))
    app_b = _make_app(identity=FakeIdentity(tenant_id=99, workspace_ids=(1,)))

    with TestClient(app_a) as c_a:
        _upload(c_a, "t1", "shared_name.txt", b"owner-A")
    with TestClient(app_b) as c_b:
        _upload(c_b, "t1", "shared_name.txt", b"owner-B")
        # Tenant B deletes.
        r_del = c_b.delete("/api/threads/t1/uploads/shared_name.txt")
    assert r_del.status_code == 200, r_del.text

    file_a = isolated_home / "tenants" / "5" / "workspaces" / "7" / "threads" / "t1" / "user-data" / "uploads" / "shared_name.txt"
    file_b = isolated_home / "tenants" / "99" / "workspaces" / "1" / "threads" / "t1" / "user-data" / "uploads" / "shared_name.txt"
    # Tenant A's file survives.
    assert file_a.exists()
    assert file_a.read_bytes() == b"owner-A"
    # Tenant B's file is gone.
    assert not file_b.exists()


# ---------------------------------------------------------------------------
# Flag ON, cross-tenant DELETE via path traversal in filename.
# ---------------------------------------------------------------------------


def test_flag_on_delete_traversal_filename_rejected(isolated_home, flag_on):
    """The delete route must reject a traversal-style filename component.

    ``/uploads/..%2F..%2Fsecret`` gets routed through FastAPI's path parser,
    but the downstream ``normalize_filename`` + tenant-root guard reject it
    with a 400 or 403 — no file from another tenant should ever be touched.
    """
    app = _make_app(identity=FakeIdentity(tenant_id=5, workspace_ids=(7,)))

    # Create the "other" tenant's file that the traversal would target.
    other_uploads = isolated_home / "tenants" / "99" / "workspaces" / "1" / "threads" / "t1" / "user-data" / "uploads"
    other_uploads.mkdir(parents=True, exist_ok=True)
    (other_uploads / "loot.txt").write_bytes(b"tenant-99-secret")

    with TestClient(app) as client:
        # FastAPI treats ``..`` in the path as a single segment; the handler
        # runs ``normalize_filename`` which reduces it to ``..`` and rejects.
        r = client.delete("/api/threads/t1/uploads/..%2F..%2F..%2F..%2Ftenants%2F99%2Fworkspaces%2F1%2Fthreads%2Ft1%2Fuser-data%2Fuploads%2Floot.txt")

    # Either 400 (unsafe filename) or 404 (basename didn't match any file).
    # The critical invariant is the other tenant's file is untouched.
    assert r.status_code in (400, 403, 404), r.text
    assert (other_uploads / "loot.txt").exists()
