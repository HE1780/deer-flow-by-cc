"""Atomic YAML editor for `config.yaml` with comment preservation.

Used by admin endpoints (e.g. /api/models CRUD) to edit on-disk config without
losing top-of-file comments, key order, or sibling sections.

Design notes
------------
- Uses ruamel.yaml round-trip mode so comments and structure survive a write.
- Uses a coarse-grained, in-process asyncio lock per absolute path. Multiple
  workers in the same process serialize on this lock; multi-process deploys
  are not currently supported (single-instance assumption — see CLAUDE.md).
- Writes go through a temp file in the same directory, then `os.replace()`,
  so partial writes never appear at the canonical path.
- After a successful write we call `reload_app_config()` so subsequent reads
  in this process see the new state without waiting for mtime polling.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from deerflow.config.app_config import AppConfig, reload_app_config

_yaml = YAML(typ="rt")
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=2, offset=0)
_yaml.width = 4096

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(path: Path) -> asyncio.Lock:
    key = str(path.resolve())
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def _resolve_path() -> Path:
    return AppConfig.resolve_config_path()


def _atomic_write(path: Path, data: Any) -> None:
    tmp_dir = path.parent
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=tmp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _yaml.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


async def edit_config(mutator: Callable[[Any], Awaitable[None] | None]) -> None:
    """Read config.yaml, run mutator on the parsed structure, write atomically.

    The mutator receives the round-trip-parsed root object (a CommentedMap)
    and mutates it in place. After write, `reload_app_config()` is invoked.
    """
    path = _resolve_path()
    async with _lock_for(path):
        with path.open("r", encoding="utf-8") as f:
            data = _yaml.load(f)
        if data is None:
            data = {}
        result = mutator(data)
        if asyncio.iscoroutine(result):
            await result
        _atomic_write(path, data)
        reload_app_config(str(path))
