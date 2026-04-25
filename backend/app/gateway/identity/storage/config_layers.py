"""Layered identity config loader (spec §7.3).

Merges a global identity/agent configuration with optional tenant- and
workspace-level overlays, refusing any attempt by a lower layer to override
fields that the platform administrator reserves for the global file
(``SENSITIVE_GLOBAL_ONLY``).

Layering order (lowest -> highest precedence)::

    1. global config file (platform admin)
    2. {deerflow_home}/tenants/{tid}/config.yaml          (tenant overlay)
    3. {deerflow_home}/tenants/{tid}/workspaces/{wid}/config.yaml  (workspace)

Semantics
---------
* Nested dicts are deep-merged: higher layers add/replace keys inside, they
  do not wipe sibling keys.
* Lists are **replaced wholesale** at each layer — no element-level merge,
  no concat. This keeps overlay semantics predictable for list-valued
  configuration like ``models`` and ``tools``.
* Scalars (including ``None``) simply replace.
* Inputs are never mutated — ``merge_config`` deep-copies before merging
  and returns a fresh dict.
* Missing config files (tenant / workspace) are silently skipped. An empty
  file or one that parses to ``None`` is treated as ``{}``.

Sensitive fields
----------------
``SENSITIVE_GLOBAL_ONLY`` is a frozenset of dotted paths that tenant /
workspace overlays must not set. The DSL supports:

* ``a.b.c`` — literal dotted traversal
* ``a[*].b`` — iterate the list at ``a`` and check ``b`` on every element

Attempting to set any listed path from a non-global layer raises
:class:`SensitiveFieldViolation`. The authoritative list lives in this
module; ``config/identity.yaml.example`` carries a commented reference
copy.

Redis caching is deferred to the consumer layer (M5/M6 will likely cache
merged config keyed by :func:`load_layered_config`'s ``cache_key`` return
value with mtime invalidation, per spec §7.3). This module stays pure.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "SENSITIVE_GLOBAL_ONLY",
    "SensitiveFieldViolation",
    "load_layered_config",
    "merge_config",
]


class SensitiveFieldViolation(ValueError):
    """Raised when a tenant or workspace overlay tries to set a global-only field."""


# Paths that must only be set by the platform-admin global config. Tenant
# and workspace overlays attempting to set any of these trigger
# ``SensitiveFieldViolation``. Derived from ``config/identity.yaml.example``
# model_provider / sandbox keys. Keep this list extensible — if a new
# platform-only knob is introduced, add it here **and** update the
# commented reference block in ``config/identity.yaml.example``.
SENSITIVE_GLOBAL_ONLY: frozenset[str] = frozenset(
    {
        "models[*].api_key",
        "models[*].endpoint",
        "models[*].base_url",
        "sandbox.provisioner.api_key",
        "sandbox.provisioner.endpoint",
        "memory.storage_path",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_layered_config(
    global_path: Path,
    tenant_id: int | None,
    workspace_id: int | None,
    *,
    deerflow_home: Path,
) -> tuple[dict[str, Any], str]:
    """Load + deep-merge the three layers, returning ``(merged, cache_key)``.

    Parameters
    ----------
    global_path:
        Absolute path to the platform-admin global config YAML. Must exist;
        this is the base layer.
    tenant_id:
        Tenant identifier, or ``None`` to skip the tenant layer.
    workspace_id:
        Workspace identifier, or ``None`` to skip the workspace layer.
        Ignored if ``tenant_id`` is ``None``.
    deerflow_home:
        Absolute path to the DeerFlow home directory. Tenant and workspace
        overlays are looked up at
        ``{deerflow_home}/tenants/{tid}/config.yaml`` and
        ``{deerflow_home}/tenants/{tid}/workspaces/{wid}/config.yaml``.

    Returns
    -------
    (merged_dict, cache_key)
        ``cache_key`` is:

        * ``"global"``                    — neither tenant nor workspace set
        * ``f"global:{tenant_id}"``       — tenant only
        * ``f"{tenant_id}:{workspace_id}"`` — both set

    Raises
    ------
    SensitiveFieldViolation
        If any tenant / workspace overlay sets a path listed in
        :data:`SENSITIVE_GLOBAL_ONLY`.
    """

    if tenant_id is None and workspace_id is not None:
        raise ValueError("workspace_id requires tenant_id to be set")

    global_cfg = _load_yaml_or_empty(global_path)

    tenant_cfg: dict[str, Any] | None = None
    workspace_cfg: dict[str, Any] | None = None

    if tenant_id is not None:
        tenant_file = deerflow_home / "tenants" / str(tenant_id) / "config.yaml"
        if tenant_file.exists():
            tenant_cfg = _load_yaml_or_empty(tenant_file)

        if workspace_id is not None:
            workspace_file = deerflow_home / "tenants" / str(tenant_id) / "workspaces" / str(workspace_id) / "config.yaml"
            if workspace_file.exists():
                workspace_cfg = _load_yaml_or_empty(workspace_file)

    merged = merge_config(global_cfg, tenant_cfg, workspace_cfg)
    cache_key = _cache_key(tenant_id, workspace_id)
    return merged, cache_key


def merge_config(
    global_cfg: dict[str, Any],
    tenant_cfg: dict[str, Any] | None,
    workspace_cfg: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deep-merge three layers. Does **not** mutate inputs.

    Semantics:
    * nested dicts merge recursively;
    * lists are replaced whole (no element-level merge);
    * scalars replace.

    Raises
    ------
    SensitiveFieldViolation
        If ``tenant_cfg`` or ``workspace_cfg`` sets any path listed in
        :data:`SENSITIVE_GLOBAL_ONLY`. The error message names the
        offending layer ("tenant" or "workspace") and the violated path.
    """

    _check_sensitive_layer(tenant_cfg, layer="tenant")
    _check_sensitive_layer(workspace_cfg, layer="workspace")

    merged = copy.deepcopy(global_cfg) if global_cfg else {}
    if tenant_cfg:
        merged = _deep_merge(merged, tenant_cfg)
    if workspace_cfg:
        merged = _deep_merge(merged, workspace_cfg)
    return merged


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_yaml_or_empty(path: Path) -> dict[str, Any]:
    """Return parsed YAML as dict, or ``{}`` if file is empty / ``None``.

    Does not check ``exists()`` — callers are expected to gate optional
    files. For the mandatory global file, a missing file raises
    ``FileNotFoundError`` from ``read_text`` as usual.
    """

    text = path.read_text()
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"config file {path} must parse to a mapping at the top level, got {type(data).__name__}")
    return data


def _cache_key(tenant_id: int | None, workspace_id: int | None) -> str:
    if tenant_id is None:
        return "global"
    if workspace_id is None:
        return f"global:{tenant_id}"
    return f"{tenant_id}:{workspace_id}"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict = ``base`` deep-merged with ``overlay``.

    ``base`` is assumed to already be an independent deep-copy (owned by
    the caller); ``overlay`` is deep-copied on write so callers retain
    ownership of their input.
    """

    result = base  # caller owns ``base``; we mutate the local copy
    for key, overlay_val in overlay.items():
        base_val = result.get(key)
        if isinstance(base_val, dict) and isinstance(overlay_val, dict):
            result[key] = _deep_merge(base_val, overlay_val)
        else:
            # scalar / list / mismatched-type: replace wholesale with a
            # deep copy so later mutations don't leak back into ``overlay``
            result[key] = copy.deepcopy(overlay_val)
    return result


# ---------------------------------------------------------------------------
# Sensitive-path detection
# ---------------------------------------------------------------------------


def _check_sensitive_layer(cfg: dict[str, Any] | None, *, layer: str) -> None:
    """Raise :class:`SensitiveFieldViolation` if ``cfg`` sets any sensitive path."""

    if not cfg:
        return
    for path in SENSITIVE_GLOBAL_ONLY:
        if _any_layer_sets_sensitive_path(cfg, path):
            raise SensitiveFieldViolation(f"{layer} config layer attempts to set platform-only field {path!r}; this field may only be set in the global config.")


def _any_layer_sets_sensitive_path(cfg: dict[str, Any], path: str) -> bool:
    """Return True if ``cfg`` sets the sensitive path ``path``.

    Supports the minimal DSL documented at the top of this module:

    * ``a.b.c`` — dotted traversal, True if ``cfg["a"]["b"]["c"]`` is set
    * ``a[*].b`` — iterate list at ``a``, True if any element has ``b`` set

    Non-dict intermediates produce ``False`` rather than raising — a
    malformed overlay will fail somewhere else (YAML load, agent startup);
    this guard is only asserting "the forbidden path is not set here".
    """

    segments = _parse_path(path)
    return _walk(cfg, segments)


def _parse_path(path: str) -> list[tuple[str, bool]]:
    """Parse ``"a[*].b.c"`` into a list of (key, is_list_wildcard) pairs.

    Each pair names a dict key; if ``is_list_wildcard`` is True the value
    at that key is expected to be a list and we recurse into every
    element.
    """

    out: list[tuple[str, bool]] = []
    for raw in path.split("."):
        if raw.endswith("[*]"):
            out.append((raw[:-3], True))
        else:
            out.append((raw, False))
    return out


def _walk(node: Any, segments: list[tuple[str, bool]]) -> bool:
    """Return True if following ``segments`` from ``node`` reaches a set value."""

    if not segments:
        # We consumed the whole path and landed on a value — the contract
        # is "tenant must not TOUCH these keys", so mere presence counts
        # as a violation regardless of the value (including explicit
        # ``None`` / ``~``). This matters because a tenant overlay like
        # ``api_key: null`` would otherwise clobber the global secret
        # with ``None`` through deep-merge.
        return True

    key, is_list = segments[0]
    rest = segments[1:]

    if not isinstance(node, dict):
        return False
    if key not in node:
        return False
    sub = node[key]

    if is_list:
        if not isinstance(sub, list):
            return False
        return any(_walk(elem, rest) for elem in sub)

    return _walk(sub, rest)
