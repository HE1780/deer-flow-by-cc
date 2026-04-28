"""Tests for tenant-aware Paths helpers (M4 storage isolation).

These tests exercise the new ``resolve_*`` / ``tenant_thread_dir`` / host-side
variants added in M4 Task 5. The legacy helpers are covered indirectly by the
existing middleware suite; here we focus on the new identity-driven routing
and the positive-int validation contract.
"""

import warnings
from pathlib import Path

import pytest

from deerflow.config.paths import Paths


def _as_posix(path: str | Path) -> str:
    return str(path).replace("\\", "/")


class TestTenantThreadDir:
    def test_returns_stratified_path(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))

        result = paths.tenant_thread_dir(5, 7, "thread-abc")

        expected = Path(tmp_path) / "tenants" / "5" / "workspaces" / "7" / "threads" / "thread-abc"
        assert result == expected

    @pytest.mark.parametrize(
        "tenant_id,workspace_id",
        [
            (0, 7),
            (-1, 7),
            (5, 0),
            (5, -1),
            (True, 7),
            (5, False),
            ("5", 7),
            (5, 7.0),
            (None, 7),
            (5, None),
        ],
    )
    def test_rejects_invalid_ids(self, tmp_path, tenant_id, workspace_id):
        paths = Paths(base_dir=str(tmp_path))
        with pytest.raises(ValueError):
            paths.tenant_thread_dir(tenant_id, workspace_id, "thread-abc")  # type: ignore[arg-type]

    def test_rejects_unsafe_thread_id(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        with pytest.raises(ValueError):
            paths.tenant_thread_dir(5, 7, "../escape")


class TestResolveThreadDir:
    def test_with_identity_returns_tenant_path(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))

        result = paths.resolve_thread_dir("t1", tenant_id=5, workspace_id=7)

        assert _as_posix(result).endswith("tenants/5/workspaces/7/threads/t1")

    def test_without_identity_returns_legacy_path(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))

        result = paths.resolve_thread_dir("t1")

        assert _as_posix(result).endswith("threads/t1")
        assert "tenants/" not in _as_posix(result)

    def test_partial_identity_falls_back(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))

        # tenant only → legacy
        assert _as_posix(paths.resolve_thread_dir("t1", tenant_id=5)).endswith("threads/t1")
        # workspace only → legacy
        assert _as_posix(paths.resolve_thread_dir("t1", workspace_id=7)).endswith("threads/t1")
        # zero values → legacy (treated as unset)
        assert _as_posix(paths.resolve_thread_dir("t1", tenant_id=0, workspace_id=7)).endswith("threads/t1")
        assert _as_posix(paths.resolve_thread_dir("t1", tenant_id=5, workspace_id=0)).endswith("threads/t1")


class TestResolveSandboxDirs:
    def test_tenant_aware_sandbox_layout(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))

        work = paths.resolve_sandbox_work_dir("t1", tenant_id=5, workspace_id=7)
        uploads = paths.resolve_sandbox_uploads_dir("t1", tenant_id=5, workspace_id=7)
        outputs = paths.resolve_sandbox_outputs_dir("t1", tenant_id=5, workspace_id=7)
        user_data = paths.resolve_sandbox_user_data_dir("t1", tenant_id=5, workspace_id=7)
        acp = paths.resolve_acp_workspace_dir("t1", tenant_id=5, workspace_id=7)

        assert _as_posix(work).endswith("tenants/5/workspaces/7/threads/t1/user-data/workspace")
        assert _as_posix(uploads).endswith("tenants/5/workspaces/7/threads/t1/user-data/uploads")
        assert _as_posix(outputs).endswith("tenants/5/workspaces/7/threads/t1/user-data/outputs")
        assert _as_posix(user_data).endswith("tenants/5/workspaces/7/threads/t1/user-data")
        assert _as_posix(acp).endswith("tenants/5/workspaces/7/threads/t1/acp-workspace")

    def test_legacy_sandbox_layout_when_no_identity(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))

        work = paths.resolve_sandbox_work_dir("t1")

        assert _as_posix(work).endswith("threads/t1/user-data/workspace")
        assert "tenants/" not in _as_posix(work)


class TestEnsureThreadDirsFor:
    def test_creates_tenant_stratified_directories(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))

        paths.ensure_thread_dirs_for("t1", tenant_id=5, workspace_id=7)

        for sub in ("user-data/workspace", "user-data/uploads", "user-data/outputs", "acp-workspace"):
            assert (tmp_path / "tenants" / "5" / "workspaces" / "7" / "threads" / "t1" / sub).is_dir()

    def test_creates_legacy_directories_when_no_identity(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))

        paths.ensure_thread_dirs_for("t1")

        for sub in ("user-data/workspace", "user-data/uploads", "user-data/outputs", "acp-workspace"):
            assert (tmp_path / "threads" / "t1" / sub).is_dir()


class TestHostVariants:
    def test_host_tenant_thread_dir_string_form(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_HOST_BASE_DIR", raising=False)
        paths = Paths(base_dir=str(tmp_path))

        result = paths.host_tenant_thread_dir(5, 7, "thread-xyz")

        assert _as_posix(result).endswith("tenants/5/workspaces/7/threads/thread-xyz")
        assert isinstance(result, str)

    def test_resolve_host_thread_dir_with_identity(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_HOST_BASE_DIR", raising=False)
        paths = Paths(base_dir=str(tmp_path))

        assert _as_posix(paths.resolve_host_thread_dir("t1", tenant_id=5, workspace_id=7)).endswith("tenants/5/workspaces/7/threads/t1")
        assert _as_posix(paths.resolve_host_thread_dir("t1")).endswith("threads/t1")

    def test_host_dir_honors_host_base_dir_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_HOST_BASE_DIR", "/host/mount/point")
        paths = Paths(base_dir=str(tmp_path))

        result = paths.resolve_host_thread_dir("t1", tenant_id=5, workspace_id=7)

        assert result.startswith("/host/mount/point/")
        assert _as_posix(result).endswith("tenants/5/workspaces/7/threads/t1")

    def test_resolve_host_sandbox_variants_compose_correctly(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_HOST_BASE_DIR", raising=False)
        paths = Paths(base_dir=str(tmp_path))

        for method_name, suffix in [
            ("resolve_host_sandbox_user_data_dir", "tenants/5/workspaces/7/threads/t1/user-data"),
            ("resolve_host_sandbox_work_dir", "tenants/5/workspaces/7/threads/t1/user-data/workspace"),
            ("resolve_host_sandbox_uploads_dir", "tenants/5/workspaces/7/threads/t1/user-data/uploads"),
            ("resolve_host_sandbox_outputs_dir", "tenants/5/workspaces/7/threads/t1/user-data/outputs"),
            ("resolve_host_acp_workspace_dir", "tenants/5/workspaces/7/threads/t1/acp-workspace"),
        ]:
            method = getattr(paths, method_name)
            assert _as_posix(method("t1", tenant_id=5, workspace_id=7)).endswith(suffix)


class TestDeleteThreadDirFor:
    def test_removes_tenant_thread_dir_when_ids_present(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        thread_dir = paths.tenant_thread_dir(5, 7, "thread-x")
        thread_dir.mkdir(parents=True)
        (thread_dir / "marker.txt").write_text("hi")
        assert thread_dir.exists()

        paths.delete_thread_dir_for("thread-x", tenant_id=5, workspace_id=7)

        assert not thread_dir.exists()

    def test_falls_back_to_legacy_thread_dir_when_ids_absent(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        legacy = Path(tmp_path) / "threads" / "thread-y"
        legacy.mkdir(parents=True)
        (legacy / "marker.txt").write_text("hi")
        assert legacy.exists()

        paths.delete_thread_dir_for("thread-y")

        assert not legacy.exists()

    def test_idempotent_when_directory_absent(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        # Must not raise.
        paths.delete_thread_dir_for("ghost", tenant_id=1, workspace_id=1)
        paths.delete_thread_dir_for("ghost")  # legacy fallback path

    def test_partial_ids_falls_back_to_legacy(self, tmp_path):
        """workspace_id missing → legacy path used."""
        paths = Paths(base_dir=str(tmp_path))
        legacy = Path(tmp_path) / "threads" / "thread-p"
        legacy.mkdir(parents=True)

        paths.delete_thread_dir_for("thread-p", tenant_id=5, workspace_id=None)

        assert not legacy.exists()


class TestLegacyMethodDeprecation:
    """Eight legacy Paths methods must emit DeprecationWarning when called
    directly, while still returning the same legacy-layout values they always did."""

    def test_each_legacy_method_warns_and_returns_legacy_path(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        thread_id = "thread-dep"

        cases = [
            ("thread_dir", lambda: paths.thread_dir(thread_id),
             tmp_path / "threads" / thread_id),
            ("sandbox_work_dir", lambda: paths.sandbox_work_dir(thread_id),
             tmp_path / "threads" / thread_id / "user-data" / "workspace"),
            ("sandbox_uploads_dir", lambda: paths.sandbox_uploads_dir(thread_id),
             tmp_path / "threads" / thread_id / "user-data" / "uploads"),
            ("sandbox_outputs_dir", lambda: paths.sandbox_outputs_dir(thread_id),
             tmp_path / "threads" / thread_id / "user-data" / "outputs"),
            ("acp_workspace_dir", lambda: paths.acp_workspace_dir(thread_id),
             tmp_path / "threads" / thread_id / "acp-workspace"),
            ("sandbox_user_data_dir", lambda: paths.sandbox_user_data_dir(thread_id),
             tmp_path / "threads" / thread_id / "user-data"),
        ]
        for name, fn, expected in cases:
            with pytest.warns(DeprecationWarning, match=name):
                result = fn()
            assert result == expected, f"{name} returned {result}, expected {expected}"

    def test_ensure_thread_dirs_warns_and_creates_legacy_layout(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))

        with pytest.warns(DeprecationWarning, match="ensure_thread_dirs"):
            paths.ensure_thread_dirs("thread-e")

        assert (tmp_path / "threads" / "thread-e" / "user-data" / "uploads").is_dir()

    def test_delete_thread_dir_warns_and_removes_legacy(self, tmp_path):
        paths = Paths(base_dir=str(tmp_path))
        legacy = tmp_path / "threads" / "thread-d"
        legacy.mkdir(parents=True)

        with pytest.warns(DeprecationWarning, match="delete_thread_dir"):
            paths.delete_thread_dir("thread-d")

        assert not legacy.exists()

    def test_resolve_helpers_do_not_warn(self, tmp_path):
        """resolve_* / *_for methods (the new API) MUST NOT emit DeprecationWarning."""
        paths = Paths(base_dir=str(tmp_path))
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            paths.resolve_thread_dir("t1")
            paths.resolve_sandbox_uploads_dir("t1")
            paths.resolve_sandbox_outputs_dir("t1")
            paths.resolve_sandbox_work_dir("t1")
            paths.resolve_acp_workspace_dir("t1")
            paths.resolve_sandbox_user_data_dir("t1")
            paths.ensure_thread_dirs_for("t1")
            paths.delete_thread_dir_for("t1")
            # With ids:
            paths.resolve_thread_dir("t1", tenant_id=1, workspace_id=1)
            paths.delete_thread_dir_for("t1", tenant_id=1, workspace_id=1)
