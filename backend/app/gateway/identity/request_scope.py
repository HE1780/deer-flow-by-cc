"""Single source of truth for reading (tenant_id, workspace_id) off a FastAPI request.

Lifted from app.gateway.routers.uploads._extract_scope and
app.gateway.routers.artifacts._extract_scope (which were previously duplicated).
Routers now import :func:`extract_scope` from here.
"""

from fastapi import Request

from app.gateway.identity.settings import get_identity_settings


def extract_scope(request: Request | None) -> tuple[int | None, int | None]:
    """Return ``(tenant_id, workspace_id)`` from ``request.state.identity``.

    Returns ``(None, None)`` whenever:

    * ``request`` is ``None`` (direct unit-test invocation),
    * the identity feature flag is off,
    * the caller is anonymous (``identity.is_authenticated`` falsy),
    * the identity attribute is missing,
    * either id is missing, non-positive, or a non-int (incl. ``bool``).

    All callers must treat the all-or-nothing pair as "fall back to legacy
    single-tenant layout" — every tenant-aware ``Paths`` helper already does so.
    """
    if request is None:
        return None, None
    if not get_identity_settings().enabled:
        return None, None

    identity = getattr(request.state, "identity", None)
    if identity is None:
        return None, None
    if getattr(identity, "is_authenticated", True) is False:
        return None, None

    def _read(attr: str) -> object:
        value = getattr(identity, attr, None)
        if value is None and hasattr(identity, "get"):
            try:
                value = identity.get(attr)  # type: ignore[attr-defined]
            except Exception:
                value = None
        return value

    tid_raw = _read("tenant_id")
    wid_raw = _read("workspace_id")
    if wid_raw is None:
        wids = _read("workspace_ids") or ()
        if isinstance(wids, (list, tuple)) and wids:
            wid_raw = wids[0]

    def _coerce(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    tid = _coerce(tid_raw)
    wid = _coerce(wid_raw)
    # All-or-nothing: if either id is missing/invalid, fall back to legacy.
    if tid is None or wid is None:
        return None, None
    return tid, wid
