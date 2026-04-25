"""Filesystem path validation for the tenant/workspace storage layout.

This module is the *validation* counterpart to ``paths.py``. While
``paths.py`` constructs layout paths from trusted arguments, ``path_guard``
ensures that paths derived from **untrusted input** (thread ids from the
harness bridge, skill filenames read off disk, artifact references from API
callers, etc.) cannot escape the tenant root they are supposed to live
under.

Scope
-----

Strictly validation. No mkdir, no chmod, no I/O that mutates the
filesystem. The only syscalls are the symlink / resolve probes that the
stdlib performs on our behalf via :meth:`pathlib.Path.resolve` and
:meth:`pathlib.Path.is_symlink`.

The module exports exactly four names:

* :class:`PathEscapeError` — the single error type for every check.
* :func:`assert_within_tenant_root` — assert an absolute path is inside
  ``tenants/{tid}``.
* :func:`safe_join` — normalise ``root + segments`` and reject traversal.
* :func:`assert_symlink_parent_safe` — reject skills-loader symlinks whose
  realpath leaves an allowed subtree.

Semantics
~~~~~~~~~

* :meth:`Path.resolve` (with ``strict=False``, the default since 3.6)
  follows symlinks AND normalises ``..``. It works on non-existent paths
  too, so the validators give consistent results whether the caller is
  about to create a file or is reading an already-on-disk entry.
* All checks compare ``.resolve()``-ed paths via
  :meth:`Path.is_relative_to`, so macOS's ``/tmp → /private/tmp`` symlink
  indirection does not produce spurious failures — both sides of the
  comparison go through ``resolve()``.
* Error messages always include the offending path and the boundary that
  was crossed, to make forensic logs useful without a source dive.
"""

from __future__ import annotations

from pathlib import Path

from .paths import tenant_root

__all__ = [
    "PathEscapeError",
    "assert_symlink_parent_safe",
    "assert_within_tenant_root",
    "safe_join",
]


class PathEscapeError(ValueError):
    """Raised when a path would escape its allowed root.

    Subclass of :class:`ValueError` so callers that already catch
    ``ValueError`` for malformed input keep working, but can also catch
    the narrower type when they specifically want to distinguish escape
    attempts from other argument errors.
    """


def assert_within_tenant_root(p: Path, tenant_id: int) -> None:
    """Raise :class:`PathEscapeError` if ``p`` is not inside ``tenant_root(tenant_id)``.

    The function resolves ``p`` via :meth:`Path.resolve` (which normalises
    ``..`` and follows symlinks) and checks that the result is
    ``is_relative_to`` the resolved tenant root. ``p`` itself is **not
    mutated** — ``Path`` is immutable and only the resolved copy is used
    for the check.

    Non-existent paths are allowed: ``resolve(strict=False)`` handles them
    lexically and the containment check still works, so callers can
    validate a target path **before** creating a file.
    """

    root = tenant_root(tenant_id).resolve()
    resolved = Path(p).resolve()
    if not resolved.is_relative_to(root):
        raise PathEscapeError(f"path {resolved!s} escapes tenant {tenant_id} root {root!s}")


def safe_join(root: Path, *segments: str) -> Path:
    """Join ``segments`` onto ``root`` and assert the result stays inside ``root``.

    Each segment is validated *before* joining:

    * must be a non-empty :class:`str`
    * must not contain a NUL byte (``\\x00``)
    * must not be absolute (neither POSIX ``/foo`` nor Windows ``C:\\foo``)
    * must not contain ``..`` as a path component (plain ``..``, ``a/..``,
      etc.) — checked against both ``/`` and ``\\`` separators for
      Windows-style inputs

    After joining, the result is resolved and re-checked against
    ``root.resolve()`` as defence in depth (so a symlink already sitting
    inside ``root`` that points outside still trips the guard).

    Returns the resolved :class:`Path`.
    """

    root_resolved = Path(root).resolve()

    for seg in segments:
        if not isinstance(seg, str):
            raise PathEscapeError(f"segment must be str, got {type(seg).__name__}: {seg!r}")
        if seg == "":
            raise PathEscapeError("segment must not be empty")
        if "\0" in seg:
            raise PathEscapeError(f"segment must not contain NUL, got {seg!r}")
        if seg.startswith("/") or seg.startswith("\\") or Path(seg).is_absolute():
            raise PathEscapeError(f"segment must not be absolute, got {seg!r}")
        # Split on BOTH separators so Windows-style inputs like
        # "foo\\..\\bar" are caught even on POSIX hosts.
        parts = seg.replace("\\", "/").split("/")
        if any(part == ".." for part in parts):
            raise PathEscapeError(f"segment must not contain '..', got {seg!r}")

    joined = root_resolved.joinpath(*segments).resolve()
    if not joined.is_relative_to(root_resolved):
        raise PathEscapeError(f"joined path {joined!s} escapes root {root_resolved!s}")
    return joined


def assert_symlink_parent_safe(symlink: Path, allowed_root: Path) -> None:
    """Reject a symlink whose target leaves ``allowed_root``.

    Intended for the M4 skills loader: when the loader walks a tenant's
    skills tree and encounters a symlink, it must refuse to follow links
    that point outside the tenant subtree (which would otherwise leak
    another tenant's skills into the bind mount or, worse, host binaries).

    Despite the ``parent`` in the name, the actual check is on the
    symlink's **target**: :meth:`Path.resolve` follows the full symlink
    chain, so even a multi-hop ``a -> b -> /etc/passwd`` link is caught.

    Semantics:

    * if ``symlink`` is not a symlink (regular file, directory, or
      non-existent path), this is a **no-op** — the caller is expected to
      handle those through other means.
    * if ``symlink`` is a symlink whose resolved target is inside
      ``allowed_root``, returns normally.
    * otherwise raises :class:`PathEscapeError`.
    """

    symlink = Path(symlink)
    if not symlink.is_symlink():
        return
    resolved = symlink.resolve()
    root_resolved = Path(allowed_root).resolve()
    if not resolved.is_relative_to(root_resolved):
        raise PathEscapeError(f"symlink {symlink!s} -> {resolved!s} escapes allowed root {root_resolved!s}")
