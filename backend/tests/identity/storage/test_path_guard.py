"""Tests for app.gateway.identity.storage.path_guard.

These tests create real files, directories and symlinks under ``tmp_path``
to exercise the guard functions end-to-end (including symlink resolution).
``DEER_FLOW_HOME`` is monkeypatched per test so ``tenant_root`` points into
``tmp_path``.

Note on macOS: ``/tmp`` is itself a symlink to ``/private/tmp``. The guard
functions route both sides of their containment checks through
``Path.resolve()``, and tests do the same on any expected value.
"""

from __future__ import annotations

import os

import pytest

from app.gateway.identity.storage.path_guard import (
    PathEscapeError,
    assert_symlink_parent_safe,
    assert_within_tenant_root,
    safe_join,
)
from app.gateway.identity.storage.paths import tenant_root

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_path_escape_error_is_value_error():
    """``PathEscapeError`` must be a ``ValueError`` subclass."""
    assert issubclass(PathEscapeError, ValueError)


# ---------------------------------------------------------------------------
# safe_join — happy path
# ---------------------------------------------------------------------------


def test_safe_join_single_segment_ok(tmp_path):
    out = safe_join(tmp_path, "foo")
    assert out == (tmp_path.resolve() / "foo")


def test_safe_join_multi_segment_ok(tmp_path):
    out = safe_join(tmp_path, "a", "b", "c.txt")
    assert out == (tmp_path.resolve() / "a" / "b" / "c.txt")


def test_safe_join_returns_absolute_resolved_path(tmp_path):
    out = safe_join(tmp_path, "x")
    # Must be absolute and go through resolve() on the root side
    assert out.is_absolute()
    assert out.parent == tmp_path.resolve()


def test_safe_join_no_segments_returns_root_resolved(tmp_path):
    # Zero segments — no traversal risk, should just return the resolved root
    out = safe_join(tmp_path)
    assert out == tmp_path.resolve()


# ---------------------------------------------------------------------------
# safe_join — rejection paths
# ---------------------------------------------------------------------------


def test_safe_join_rejects_parent_traversal_segment(tmp_path):
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, "..")


def test_safe_join_rejects_parent_traversal_inside_segment(tmp_path):
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, "foo/../bar")


def test_safe_join_rejects_backslash_parent_traversal(tmp_path):
    # Windows-style separator still gets split and checked
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, "foo\\..\\bar")


def test_safe_join_rejects_absolute_posix_segment(tmp_path):
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, "/etc/passwd")


def test_safe_join_rejects_absolute_backslash_segment(tmp_path):
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, "\\windows\\system32")


def test_safe_join_rejects_nul_character(tmp_path):
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, "foo\0bar")


def test_safe_join_rejects_empty_segment(tmp_path):
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, "")


def test_safe_join_rejects_empty_segment_among_valid(tmp_path):
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, "foo", "", "bar")


def test_safe_join_rejects_non_str_segment(tmp_path):
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, 123)  # type: ignore[arg-type]


def test_safe_join_rejects_deep_traversal_pattern(tmp_path):
    # subdir/../../../etc/passwd-style: contains '..' as a component
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, "subdir/../../../etc/passwd")


def test_safe_join_rejects_symlink_target_outside_root(tmp_path):
    """Even if all segments are clean, a pre-existing symlink inside ``root``
    that points outside it must trip the post-join resolve() check."""
    outside = tmp_path.parent / "outside_root"
    outside.mkdir()
    try:
        root = tmp_path / "root"
        root.mkdir()
        # Create a symlink inside root pointing outside
        (root / "escape").symlink_to(outside)
        with pytest.raises(PathEscapeError):
            safe_join(root, "escape", "secret.txt")
    finally:
        # best-effort cleanup of the sibling dir
        try:
            outside.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# assert_within_tenant_root
# ---------------------------------------------------------------------------


def _mk_tenant(tmp_path, tenant_id: int):
    """Materialise the tenant root directory under tmp_path."""
    root = tenant_root(tenant_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_assert_within_tenant_root_path_inside_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    root = _mk_tenant(tmp_path, 7)
    inside = root / "workspaces" / "1" / "threads" / "abc"
    # No need to create it — resolve(strict=False) handles non-existent paths.
    assert_within_tenant_root(inside, 7)


def test_assert_within_tenant_root_existing_file_inside_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    root = _mk_tenant(tmp_path, 7)
    f = root / "foo.txt"
    f.write_text("x")
    assert_within_tenant_root(f, 7)


def test_assert_within_tenant_root_sibling_tenant_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    _mk_tenant(tmp_path, 7)
    sibling = _mk_tenant(tmp_path, 8) / "secret.txt"
    with pytest.raises(PathEscapeError) as excinfo:
        assert_within_tenant_root(sibling, 7)
    # Error message must be actionable
    assert "tenant" in str(excinfo.value)
    assert "7" in str(excinfo.value)


def test_assert_within_tenant_root_parent_traversal_normalised_inside(tmp_path, monkeypatch):
    """A path with '..' that resolves back inside the tenant root is OK."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    root = _mk_tenant(tmp_path, 7)
    tricky = root / "workspaces" / ".." / "custom" / "x.py"
    # Resolves to root / "custom" / "x.py" which is still inside root.
    assert_within_tenant_root(tricky, 7)


def test_assert_within_tenant_root_parent_traversal_escapes(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    root = _mk_tenant(tmp_path, 7)
    # Walk out of the tenant via ..
    escape = root / ".." / ".." / "outside.txt"
    with pytest.raises(PathEscapeError):
        assert_within_tenant_root(escape, 7)


def test_assert_within_tenant_root_nonexistent_inside_ok(tmp_path, monkeypatch):
    """resolve(strict=False) works lexically on non-existent paths."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    root = _mk_tenant(tmp_path, 7)
    assert_within_tenant_root(root / "does" / "not" / "exist.txt", 7)


def test_assert_within_tenant_root_nonexistent_outside_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    _mk_tenant(tmp_path, 7)
    bogus = tmp_path / "not_a_tenant" / "file.txt"
    with pytest.raises(PathEscapeError):
        assert_within_tenant_root(bogus, 7)


def test_assert_within_tenant_root_does_not_mutate_input(tmp_path, monkeypatch):
    """The function must not replace/rebind the caller's Path object
    (Path is immutable anyway; this guards against accidental resolve()
    swap-in-place via object identity)."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    root = _mk_tenant(tmp_path, 7)
    p = root / "x"
    before = str(p)
    assert_within_tenant_root(p, 7)
    assert str(p) == before


# ---------------------------------------------------------------------------
# assert_symlink_parent_safe
# ---------------------------------------------------------------------------


def test_assert_symlink_parent_safe_regular_file_is_noop(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    f = allowed / "plain.txt"
    f.write_text("data")
    # Not a symlink -> no raise
    assert_symlink_parent_safe(f, allowed)


def test_assert_symlink_parent_safe_directory_is_noop(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    d = allowed / "sub"
    d.mkdir()
    assert_symlink_parent_safe(d, allowed)


def test_assert_symlink_parent_safe_nonexistent_is_noop(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    # Path doesn't exist at all -> is_symlink() is False -> no raise
    assert_symlink_parent_safe(allowed / "ghost", allowed)


def test_assert_symlink_parent_safe_symlink_inside_ok(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "real.txt"
    target.write_text("x")
    link = allowed / "link.txt"
    link.symlink_to(target)
    assert_symlink_parent_safe(link, allowed)


def test_assert_symlink_parent_safe_symlink_outside_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret.txt"
    target.write_text("s")
    link = allowed / "escape.txt"
    link.symlink_to(target)
    with pytest.raises(PathEscapeError) as excinfo:
        assert_symlink_parent_safe(link, allowed)
    # Error message mentions the link and the boundary
    assert str(link) in str(excinfo.value) or "escape" in str(excinfo.value)


def test_assert_symlink_parent_safe_follows_chain(tmp_path):
    """resolve() follows multi-hop symlink chains — if the final target
    leaves allowed_root the guard must still fire."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    real = outside / "real.txt"
    real.write_text("s")

    # a -> b -> outside/real.txt
    b = allowed / "b"
    b.symlink_to(real)
    a = allowed / "a"
    a.symlink_to(b)

    with pytest.raises(PathEscapeError):
        assert_symlink_parent_safe(a, allowed)


def test_assert_symlink_parent_safe_absolute_symlink_target(tmp_path):
    """A symlink whose target is an absolute path outside allowed_root
    must be rejected."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    # Point at /etc (guaranteed to exist on Linux+macOS, outside tmp_path)
    link = allowed / "etc_link"
    link.symlink_to("/etc")
    assert os.path.isabs(os.readlink(link))
    with pytest.raises(PathEscapeError):
        assert_symlink_parent_safe(link, allowed)
