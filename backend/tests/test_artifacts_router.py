import asyncio
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import FileResponse

import app.gateway.routers.artifacts as artifacts_router

ACTIVE_ARTIFACT_CASES = [
    ("poc.html", "<html><body><script>alert('xss')</script></body></html>"),
    ("page.xhtml", '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>hello</body></html>'),
    ("image.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script>alert("xss")</script></svg>'),
]


def _make_request(query_string: bytes = b"") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": query_string})


def test_get_artifact_reads_utf8_text_file_on_windows_locale(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    text = "Curly quotes: \u201cutf8\u201d"
    artifact_path.write_text(text, encoding="utf-8")

    original_read_text = Path.read_text

    def read_text_with_gbk_default(self, *args, **kwargs):
        kwargs.setdefault("encoding", "gbk")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text_with_gbk_default)
    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path: artifact_path)

    request = _make_request()
    response = asyncio.run(artifacts_router.get_artifact("thread-1", "mnt/user-data/outputs/note.txt", request))

    assert bytes(response.body).decode("utf-8") == text
    assert response.media_type == "text/plain"


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content(tmp_path, monkeypatch, filename: str, content: str) -> None:
    artifact_path = tmp_path / filename
    artifact_path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path: artifact_path)

    response = asyncio.run(artifacts_router.get_artifact("thread-1", f"mnt/user-data/outputs/{filename}", _make_request()))

    assert isinstance(response, FileResponse)
    assert response.headers.get("content-disposition", "").startswith("attachment;")


@pytest.mark.parametrize(("filename", "content"), ACTIVE_ARTIFACT_CASES)
def test_get_artifact_forces_download_for_active_content_in_skill_archive(tmp_path, monkeypatch, filename: str, content: str) -> None:
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr(filename, content)

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path: skill_path)

    response = asyncio.run(artifacts_router.get_artifact("thread-1", f"mnt/user-data/outputs/sample.skill/{filename}", _make_request()))

    assert response.headers.get("content-disposition", "").startswith("attachment;")
    assert bytes(response.body) == content.encode("utf-8")


def test_get_artifact_download_false_does_not_force_attachment(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "note.txt"
    artifact_path.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path: artifact_path)

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/note.txt?download=false")

    assert response.status_code == 200
    assert response.text == "hello"
    assert "content-disposition" not in response.headers


def test_legacy_tenant_fallback_finds_post_m4_thread(tmp_path, monkeypatch) -> None:
    """Anonymous request for a thread that only lives under tenants/* should
    resolve via the fallback walker — covers the M4 regression where new
    threads no longer have a legacy symlink under {home}/threads/.
    """
    thread_id = "tenant-only-thread"
    tenant_thread = tmp_path / "tenants" / "1" / "workspaces" / "1" / "threads" / thread_id / "user-data" / "outputs"
    tenant_thread.mkdir(parents=True)
    (tenant_thread / "result.txt").write_text("hi", encoding="utf-8")

    class _Paths:
        base_dir = tmp_path

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: _Paths())
    # Legacy resolver returns a non-existent path so the fallback runs.
    legacy_dir = tmp_path / "threads" / thread_id / "user-data" / "outputs"

    def _resolver(tid: str, vpath: str, *, tenant_id=None, workspace_id=None):
        rel = vpath.lstrip("/").removeprefix("mnt/user-data/")
        if tenant_id and workspace_id:
            return tmp_path / "tenants" / str(tenant_id) / "workspaces" / str(workspace_id) / "threads" / tid / "user-data" / rel
        return legacy_dir.parent.parent / "user-data" / rel

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", _resolver)

    response = asyncio.run(
        artifacts_router.get_artifact(thread_id, "mnt/user-data/outputs/result.txt", _make_request())
    )
    assert bytes(response.body).decode("utf-8") == "hi"


def test_legacy_tenant_fallback_rejects_ambiguous_match(tmp_path, monkeypatch) -> None:
    """Two tenants both contain the same thread_id → fallback refuses to pick
    one, so the caller gets a 404 instead of cross-tenant leakage.
    """
    thread_id = "ambig-thread"
    for tid in ("1", "2"):
        outputs = tmp_path / "tenants" / tid / "workspaces" / "1" / "threads" / thread_id / "user-data" / "outputs"
        outputs.mkdir(parents=True)
        (outputs / "f.txt").write_text("x", encoding="utf-8")

    class _Paths:
        base_dir = tmp_path

    monkeypatch.setattr(artifacts_router, "get_paths", lambda: _Paths())

    def _resolver(tid: str, vpath: str, *, tenant_id=None, workspace_id=None):
        # Legacy path that does not exist; tenant branch should never be taken
        # because the fallback aborts on ambiguity.
        return tmp_path / "threads" / tid / "user-data" / vpath.removeprefix("/mnt/user-data/")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", _resolver)

    with pytest.raises(artifacts_router.HTTPException) as exc:
        asyncio.run(
            artifacts_router.get_artifact(thread_id, "mnt/user-data/outputs/f.txt", _make_request())
        )
    assert exc.value.status_code == 404


def test_get_artifact_download_true_forces_attachment_for_skill_archive(tmp_path, monkeypatch) -> None:
    skill_path = tmp_path / "sample.skill"
    with zipfile.ZipFile(skill_path, "w") as zip_ref:
        zip_ref.writestr("notes.txt", "hello")

    monkeypatch.setattr(artifacts_router, "resolve_thread_virtual_path", lambda _thread_id, _path: skill_path)

    app = FastAPI()
    app.include_router(artifacts_router.router)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/artifacts/mnt/user-data/outputs/sample.skill/notes.txt?download=true")

    assert response.status_code == 200
    assert response.text == "hello"
    assert response.headers.get("content-disposition", "").startswith("attachment;")
