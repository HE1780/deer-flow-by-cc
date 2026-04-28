"""Tests for tenant-aware sandbox bind-mounts and path translation (M4 task 6).

These tests verify:
- ``LocalSandboxProvider.acquire`` accepts tenant/workspace kwargs and creates
  per-tenant directories under ``tenants/{tid}/workspaces/{wid}/threads/...``
  without changing the sandbox virtual paths.
- ``AioSandboxProvider._get_thread_mounts`` routes bind-mount *sources* through
  the tenant-stratified layout while keeping *destinations* at the legacy
  virtual prefix (``/mnt/user-data/...``). The sandbox itself never sees a
  tenant id in its mount-point name.
- ``Paths.resolve_virtual_path`` routes virtual paths to the tenant-stratified
  host path when identity is in scope, and falls back to legacy otherwise.
- Cross-tenant escapes via ``../../tenants/OTHER_TID/...`` are rejected with
  ``ValueError`` or ``PermissionError``.
- The shared identity helper ``extract_tenant_ids`` supports the same
  attribute / dict shapes that ``ThreadDataMiddleware`` expects.

The tests use real filesystem fixtures (``tmp_path``) rather than mocks
wherever possible so they exercise the full path-resolution code path.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import deerflow.sandbox.local.local_sandbox_provider as local_provider_mod
from deerflow.agents.middlewares._identity import extract_tenant_ids
from deerflow.config.paths import Paths
from deerflow.sandbox import local as local_pkg  # noqa: F401  # ensure subpackage importable
from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_local_singleton():
    """Reset ``LocalSandboxProvider``'s module-level singleton between tests.

    Without this, the first test's ``LocalSandbox`` instance leaks into the
    next test and skews assertions about per-test path mappings.
    """
    local_provider_mod._singleton = None
    yield
    local_provider_mod._singleton = None


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Point ``DEER_FLOW_HOME`` at ``tmp_path`` and reset the Paths singleton."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # Reset the module-level singleton so ``get_paths()`` picks up the env var.
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)
    yield tmp_path


# ---------------------------------------------------------------------------
# extract_tenant_ids — shared identity helper
# ---------------------------------------------------------------------------


def test_extract_tenant_ids_attribute_shape():
    identity = SimpleNamespace(tenant_id=5, workspace_id=7)
    assert extract_tenant_ids(identity) == (5, 7)


def test_extract_tenant_ids_dict_shape():
    identity = {"tenant_id": 5, "workspace_id": 7}
    assert extract_tenant_ids(identity) == (5, 7)


def test_extract_tenant_ids_none():
    assert extract_tenant_ids(None) == (None, None)


def test_extract_tenant_ids_partial():
    # Missing workspace_id → caller must see (tid, None) and fall back to legacy.
    assert extract_tenant_ids(SimpleNamespace(tenant_id=5)) == (5, None)


def test_extract_tenant_ids_empty_dict():
    assert extract_tenant_ids({}) == (None, None)


# ---------------------------------------------------------------------------
# LocalSandboxProvider.acquire — directory allocation
# ---------------------------------------------------------------------------


def test_local_acquire_without_identity_uses_legacy_layout(isolated_paths):
    """Flag-off callers get the legacy ``threads/{thread_id}/`` layout."""
    provider = LocalSandboxProvider()
    sandbox_id = provider.acquire("thread-legacy")
    assert sandbox_id == "local"

    # Legacy layout exists
    assert (isolated_paths / "threads" / "thread-legacy" / "user-data" / "workspace").exists()
    assert (isolated_paths / "threads" / "thread-legacy" / "user-data" / "uploads").exists()
    assert (isolated_paths / "threads" / "thread-legacy" / "user-data" / "outputs").exists()
    # Tenant layout does NOT exist
    assert not (isolated_paths / "tenants").exists()


def test_local_acquire_with_identity_uses_tenant_layout(isolated_paths):
    """With tenant_id+workspace_id, dirs land under tenants/{tid}/workspaces/{wid}/."""
    provider = LocalSandboxProvider()
    provider.acquire("thread-scoped", tenant_id=5, workspace_id=7)

    base = isolated_paths / "tenants" / "5" / "workspaces" / "7" / "threads" / "thread-scoped"
    assert (base / "user-data" / "workspace").exists()
    assert (base / "user-data" / "uploads").exists()
    assert (base / "user-data" / "outputs").exists()
    assert (base / "acp-workspace").exists()

    # Legacy layout NOT created
    assert not (isolated_paths / "threads" / "thread-scoped").exists()


def test_local_acquire_partial_identity_falls_back(isolated_paths):
    """Missing workspace_id must fall back to legacy layout."""
    provider = LocalSandboxProvider()
    provider.acquire("thread-partial", tenant_id=5, workspace_id=None)

    assert (isolated_paths / "threads" / "thread-partial" / "user-data" / "workspace").exists()
    assert not (isolated_paths / "tenants").exists()


def test_local_acquire_rejects_bad_thread_id(isolated_paths):
    provider = LocalSandboxProvider()
    with pytest.raises(ValueError, match="thread"):
        provider.acquire("../escape", tenant_id=5, workspace_id=7)


def test_local_acquire_sandbox_id_is_constant(isolated_paths):
    """LocalSandbox is a singleton — id must be ``"local"`` regardless of identity."""
    provider = LocalSandboxProvider()
    assert provider.acquire("t1") == "local"
    assert provider.acquire("t2", tenant_id=1, workspace_id=1) == "local"


# ---------------------------------------------------------------------------
# AioSandboxProvider._get_thread_mounts — bind-mount sources
# ---------------------------------------------------------------------------


def _aio_mod():
    return importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")


def test_aio_thread_mounts_legacy_when_identity_absent(tmp_path, monkeypatch):
    aio_mod = _aio_mod()
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-legacy")
    by_container = {container: (host, ro) for host, container, ro in mounts}

    # Legacy layout: .../threads/thread-legacy/user-data/...
    assert by_container["/mnt/user-data/workspace"][0] == str(tmp_path / "threads" / "thread-legacy" / "user-data" / "workspace")
    assert by_container["/mnt/user-data/uploads"][0] == str(tmp_path / "threads" / "thread-legacy" / "user-data" / "uploads")
    assert by_container["/mnt/user-data/outputs"][0] == str(tmp_path / "threads" / "thread-legacy" / "user-data" / "outputs")
    # Destinations never include tenant ids
    assert all("tenants" not in cp for cp in by_container)


def test_aio_thread_mounts_tenant_aware_sources(tmp_path, monkeypatch):
    aio_mod = _aio_mod()
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-scoped", tenant_id=5, workspace_id=7)
    by_container = {container: (host, ro) for host, container, ro in mounts}

    base = tmp_path / "tenants" / "5" / "workspaces" / "7" / "threads" / "thread-scoped"

    # Sources are tenant-stratified
    assert by_container["/mnt/user-data/workspace"][0] == str(base / "user-data" / "workspace")
    assert by_container["/mnt/user-data/uploads"][0] == str(base / "user-data" / "uploads")
    assert by_container["/mnt/user-data/outputs"][0] == str(base / "user-data" / "outputs")
    assert by_container["/mnt/acp-workspace"][0] == str(base / "acp-workspace")

    # Destinations NEVER include the tenant id — this is the in-sandbox
    # visibility invariant. ``ls /mnt/`` inside the container must not reveal
    # any tenant identifier.
    for container_path in by_container:
        assert "tenants" not in container_path
        assert "5" not in container_path.split("/")
        assert "7" not in container_path.split("/")

    # ACP workspace stays read-only.
    assert by_container["/mnt/acp-workspace"][1] is True


def test_aio_thread_mounts_ensure_dirs_created(tmp_path, monkeypatch):
    """After calling _get_thread_mounts, the tenant-aware host dirs must exist."""
    aio_mod = _aio_mod()
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))

    aio_mod.AioSandboxProvider._get_thread_mounts("thread-ensure", tenant_id=3, workspace_id=4)

    base = tmp_path / "tenants" / "3" / "workspaces" / "4" / "threads" / "thread-ensure"
    assert (base / "user-data" / "workspace").is_dir()
    assert (base / "user-data" / "uploads").is_dir()
    assert (base / "user-data" / "outputs").is_dir()
    assert (base / "acp-workspace").is_dir()


def test_aio_thread_mounts_partial_identity_falls_back(tmp_path, monkeypatch):
    aio_mod = _aio_mod()
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("thread-partial", tenant_id=5, workspace_id=None)
    by_container = {container: host for host, container, _ in mounts}
    assert by_container["/mnt/user-data/workspace"] == str(tmp_path / "threads" / "thread-partial" / "user-data" / "workspace")


# ---------------------------------------------------------------------------
# Paths.resolve_virtual_path — tenant-aware resolution
# ---------------------------------------------------------------------------


def test_resolve_virtual_path_legacy_fallback(tmp_path):
    paths = Paths(base_dir=tmp_path)
    paths.ensure_thread_dirs_for("t1")

    actual = paths.resolve_virtual_path("t1", "/mnt/user-data/outputs/report.pdf")
    assert actual == (tmp_path / "threads" / "t1" / "user-data" / "outputs" / "report.pdf").resolve()


def test_resolve_virtual_path_tenant_aware(tmp_path):
    paths = Paths(base_dir=tmp_path)
    paths.ensure_thread_dirs_for("t1", tenant_id=5, workspace_id=7)

    actual = paths.resolve_virtual_path("t1", "/mnt/user-data/outputs/report.pdf", tenant_id=5, workspace_id=7)
    expected = (tmp_path / "tenants" / "5" / "workspaces" / "7" / "threads" / "t1" / "user-data" / "outputs" / "report.pdf").resolve()
    assert actual == expected


def test_resolve_virtual_path_rejects_traversal(tmp_path):
    paths = Paths(base_dir=tmp_path)
    paths.ensure_thread_dirs_for("t1", tenant_id=5, workspace_id=7)

    # Attempt to escape into another tenant via ../ segments. Must raise.
    with pytest.raises(ValueError, match="traversal"):
        paths.resolve_virtual_path(
            "t1",
            "/mnt/user-data/../../../../../tenants/99/workspaces/1/threads/t1/user-data/outputs/secret.txt",
            tenant_id=5,
            workspace_id=7,
        )


def test_resolve_virtual_path_rejects_wrong_prefix(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with pytest.raises(ValueError, match="Path must start with"):
        paths.resolve_virtual_path("t1", "/etc/passwd", tenant_id=5, workspace_id=7)


# ---------------------------------------------------------------------------
# LocalSandbox — end-to-end file write via /mnt/user-data
# ---------------------------------------------------------------------------


def test_local_sandbox_write_lands_in_tenant_path_via_tools(isolated_paths):
    """Writing /mnt/user-data/workspace/file.txt with tenant-aware thread_data
    lands at the tenant-stratified host path, and the resolver rejects any
    path that tries to escape the allowed roots.

    This exercises ``tools.py::_resolve_and_validate_user_data_path`` which
    is the real validation gate for local-sandbox tool calls.
    """
    from deerflow.sandbox.tools import _resolve_and_validate_user_data_path

    paths = Paths(base_dir=isolated_paths)
    paths.ensure_thread_dirs_for("t1", tenant_id=5, workspace_id=7)

    base = isolated_paths / "tenants" / "5" / "workspaces" / "7" / "threads" / "t1" / "user-data"

    thread_data = {
        "workspace_path": str(base / "workspace"),
        "uploads_path": str(base / "uploads"),
        "outputs_path": str(base / "outputs"),
    }

    # Happy path: resolves to the tenant-scoped host path.
    resolved = _resolve_and_validate_user_data_path("/mnt/user-data/workspace/hello.txt", thread_data)
    assert Path(resolved).parent == (base / "workspace").resolve()


def test_local_sandbox_cross_tenant_escape_rejected(isolated_paths):
    """Cross-tenant escape via ../ in the virtual path is rejected by the
    host-path validator.

    Scenario: tenant=5/workspace=7 tries to write into tenant=99's workspace
    via ``/mnt/user-data/../../../../tenants/99/...``. The validator must
    detect the resolved host path is outside the caller's allowed roots
    and raise ``PermissionError``.
    """
    from deerflow.sandbox.tools import (
        _resolve_and_validate_user_data_path,
        validate_local_tool_path,
    )

    paths = Paths(base_dir=isolated_paths)
    paths.ensure_thread_dirs_for("t1", tenant_id=5, workspace_id=7)
    # Create the "other" tenant tree so the traversal target actually exists.
    paths.ensure_thread_dirs_for("t1", tenant_id=99, workspace_id=1)

    base = isolated_paths / "tenants" / "5" / "workspaces" / "7" / "threads" / "t1" / "user-data"
    thread_data = {
        "workspace_path": str(base / "workspace"),
        "uploads_path": str(base / "uploads"),
        "outputs_path": str(base / "outputs"),
    }

    # The virtual-path validator catches ``..`` segments first (cheap guard).
    with pytest.raises(PermissionError, match="traversal"):
        validate_local_tool_path(
            "/mnt/user-data/workspace/../../../../tenants/99/workspaces/1/threads/t1/user-data/outputs/loot.txt",
            thread_data,
        )

    # Even if the traversal check were bypassed, the post-resolve validator
    # rejects because the resolved host path is outside allowed roots.
    evil = isolated_paths / "tenants" / "99" / "workspaces" / "1" / "threads" / "t1" / "user-data" / "outputs" / "loot.txt"
    from deerflow.sandbox.tools import _validate_resolved_user_data_path

    with pytest.raises(PermissionError, match="traversal"):
        _validate_resolved_user_data_path(evil.resolve(), thread_data)

    # And the higher-level helper rejects too.
    with pytest.raises((PermissionError, ValueError)):
        _resolve_and_validate_user_data_path(
            "/mnt/user-data/workspace/../../99/workspaces/1/threads/t1/user-data/outputs/loot.txt",
            thread_data,
        )


# ---------------------------------------------------------------------------
# SandboxMiddleware — identity forwarding
# ---------------------------------------------------------------------------


def test_sandbox_middleware_forwards_identity_to_provider(isolated_paths):
    """``SandboxMiddleware.before_agent`` must read state["identity"] and pass
    tenant_id / workspace_id through ``provider.acquire(...)``.
    """
    from deerflow.sandbox.middleware import SandboxMiddleware

    middleware = SandboxMiddleware(lazy_init=False)

    captured: dict[str, object] = {}

    class _FakeProvider:
        def acquire(self, thread_id, *, tenant_id=None, workspace_id=None):
            captured["thread_id"] = thread_id
            captured["tenant_id"] = tenant_id
            captured["workspace_id"] = workspace_id
            return "sbx-1"

        def release(self, sandbox_id):  # pragma: no cover — not exercised here
            pass

    state = {"identity": SimpleNamespace(tenant_id=5, workspace_id=7)}
    runtime = SimpleNamespace(context={"thread_id": "t1"})

    with patch("deerflow.sandbox.middleware.get_sandbox_provider", return_value=_FakeProvider()):
        result = middleware.before_agent(state, runtime)

    assert result == {"sandbox": {"sandbox_id": "sbx-1"}}
    assert captured == {"thread_id": "t1", "tenant_id": 5, "workspace_id": 7}


def test_sandbox_middleware_no_identity_passes_none(isolated_paths):
    from deerflow.sandbox.middleware import SandboxMiddleware

    middleware = SandboxMiddleware(lazy_init=False)
    captured: dict[str, object] = {}

    class _FakeProvider:
        def acquire(self, thread_id, *, tenant_id=None, workspace_id=None):
            captured["tenant_id"] = tenant_id
            captured["workspace_id"] = workspace_id
            return "sbx-legacy"

        def release(self, sandbox_id):  # pragma: no cover
            pass

    state: dict[str, object] = {}  # no identity
    runtime = SimpleNamespace(context={"thread_id": "t1"})

    with patch("deerflow.sandbox.middleware.get_sandbox_provider", return_value=_FakeProvider()):
        middleware.before_agent(state, runtime)

    assert captured == {"tenant_id": None, "workspace_id": None}


# ---------------------------------------------------------------------------
# AioSandboxProvider.acquire — end-to-end (no container) with mocked backend
# ---------------------------------------------------------------------------


def _make_aio_provider_no_backend(tmp_path, monkeypatch):
    """Instantiate an AioSandboxProvider without starting idle/backend threads.

    The returned provider has a mocked backend whose ``create`` call captures
    the mounts argument so tests can assert on bind-mount specs.
    """
    aio_mod = _aio_mod()

    # Redirect paths to tmp_path so directory creation is isolated.
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))

    with (
        patch.object(aio_mod.AioSandboxProvider, "_start_idle_checker"),
        patch.object(aio_mod.AioSandboxProvider, "_reconcile_orphans"),
        patch.object(aio_mod.AioSandboxProvider, "_register_signal_handlers"),
        patch.object(aio_mod.AioSandboxProvider, "_load_config", return_value={"replicas": 3, "idle_timeout": 0}),
        patch.object(aio_mod.AioSandboxProvider, "_create_backend") as mock_backend_factory,
    ):
        backend = MagicMock()
        backend.list_running.return_value = []
        backend.discover.return_value = None

        from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo

        def _fake_create(thread_id, sandbox_id, extra_mounts=None):
            info = SandboxInfo(sandbox_id=sandbox_id, sandbox_url="http://127.0.0.1:0")
            backend.last_create_call = (thread_id, sandbox_id, extra_mounts)
            return info

        backend.create.side_effect = _fake_create
        mock_backend_factory.return_value = backend

        provider = aio_mod.AioSandboxProvider()

    # Stub out readiness polling so ``_create_sandbox`` returns immediately.
    monkeypatch.setattr(aio_mod, "wait_for_sandbox_ready", lambda url, timeout=60: True)
    monkeypatch.setattr(aio_mod, "AioSandbox", lambda id, base_url: SimpleNamespace(id=id, base_url=base_url))

    return provider, backend


def test_aio_acquire_with_identity_uses_tenant_bind_mounts(tmp_path, monkeypatch):
    """End-to-end: ``AioSandboxProvider.acquire`` with tenant_id+workspace_id
    must produce bind-mount sources under the tenant-stratified layout.
    """
    provider, backend = _make_aio_provider_no_backend(tmp_path, monkeypatch)

    provider.acquire("t1", tenant_id=5, workspace_id=7)
    thread_id, sandbox_id, extra_mounts = backend.last_create_call
    assert thread_id == "t1"
    assert extra_mounts is not None

    by_container = {container: (host, ro) for host, container, ro in extra_mounts}
    base = tmp_path / "tenants" / "5" / "workspaces" / "7" / "threads" / "t1"
    assert by_container["/mnt/user-data/workspace"][0] == str(base / "user-data" / "workspace")
    assert by_container["/mnt/acp-workspace"][0] == str(base / "acp-workspace")

    # Agent-visible mount destinations never reveal the tenant id.
    for cp in by_container:
        assert "tenants" not in cp


def test_aio_acquire_without_identity_uses_legacy(tmp_path, monkeypatch):
    provider, backend = _make_aio_provider_no_backend(tmp_path, monkeypatch)

    provider.acquire("t1")
    _, _, extra_mounts = backend.last_create_call
    by_container = {container: host for host, container, _ in extra_mounts}
    assert by_container["/mnt/user-data/workspace"] == str(tmp_path / "threads" / "t1" / "user-data" / "workspace")
    assert not (tmp_path / "tenants").exists()


# ---------------------------------------------------------------------------
# In-sandbox visibility invariant
# ---------------------------------------------------------------------------


def test_bind_mount_destinations_contain_no_tenant_id(tmp_path, monkeypatch):
    """White-box assertion: every mount destination emitted by the docker
    provider must start with ``/mnt/`` and must not contain any numeric path
    segment that could leak the tenant id.
    """
    aio_mod = _aio_mod()
    monkeypatch.setattr(aio_mod, "get_paths", lambda: Paths(base_dir=tmp_path))

    mounts = aio_mod.AioSandboxProvider._get_thread_mounts("t-invariant", tenant_id=12345, workspace_id=67890)
    for _, container_path, _ in mounts:
        assert container_path.startswith("/mnt/")
        # The only digits that may appear are inside the names of static
        # sub-directories — none exist today. Guard anyway.
        segments = [s for s in container_path.split("/") if s]
        assert "12345" not in segments
        assert "67890" not in segments
        assert "tenants" not in segments
        assert "workspaces" not in segments


# ---------------------------------------------------------------------------
# LocalSandbox provider path mappings still intact for skills
# ---------------------------------------------------------------------------


def test_local_sandbox_singleton_kept_across_identity(isolated_paths):
    """Tenant-aware acquire does not invalidate the shared LocalSandbox."""
    provider = LocalSandboxProvider()
    sid1 = provider.acquire("t1", tenant_id=5, workspace_id=7)
    sid2 = provider.acquire("t2")
    sid3 = provider.acquire("t3", tenant_id=99, workspace_id=1)
    assert sid1 == sid2 == sid3 == "local"
    # Both tenant paths exist independently; the legacy path exists for t2.
    assert (isolated_paths / "tenants" / "5" / "workspaces" / "7" / "threads" / "t1" / "user-data" / "workspace").exists()
    assert (isolated_paths / "threads" / "t2" / "user-data" / "workspace").exists()
    assert (isolated_paths / "tenants" / "99" / "workspaces" / "1" / "threads" / "t3" / "user-data" / "workspace").exists()


def test_local_sandbox_instance_reused(isolated_paths):
    provider = LocalSandboxProvider()
    provider.acquire("t1", tenant_id=5, workspace_id=7)
    first = provider.get("local")
    assert isinstance(first, LocalSandbox)
    provider.acquire("t1", tenant_id=5, workspace_id=7)
    second = provider.get("local")
    assert first is second


# ---------------------------------------------------------------------------
# Paths API surface — symmetry guard
# ---------------------------------------------------------------------------


def test_resolve_virtual_path_signature_accepts_keyword_only_ids():
    """The tenant/workspace kwargs must be keyword-only to prevent positional
    call sites from silently passing ``thread_id`` into the wrong slot.
    """
    import inspect

    sig = inspect.signature(Paths.resolve_virtual_path)
    tenant_param = sig.parameters["tenant_id"]
    workspace_param = sig.parameters["workspace_id"]
    assert tenant_param.kind is inspect.Parameter.KEYWORD_ONLY
    assert workspace_param.kind is inspect.Parameter.KEYWORD_ONLY
    assert tenant_param.default is None
    assert workspace_param.default is None


def test_sandbox_provider_acquire_signature_is_backward_compat():
    """``SandboxProvider.acquire`` must still accept the single-arg form."""
    import inspect

    from deerflow.sandbox.sandbox_provider import SandboxProvider

    sig = inspect.signature(SandboxProvider.acquire)
    params = list(sig.parameters.values())
    # params[0] == self. params[1] must be the optional thread_id positional.
    assert params[1].name == "thread_id"
    assert params[1].default is None
    # The tenant/workspace kwargs must be keyword-only for explicitness.
    tenant_param = sig.parameters["tenant_id"]
    workspace_param = sig.parameters["workspace_id"]
    assert tenant_param.kind is inspect.Parameter.KEYWORD_ONLY
    assert workspace_param.kind is inspect.Parameter.KEYWORD_ONLY
