# backend/app/gateway/auth_baseline.py
"""Gateway-level authentication baseline.

Default-deny dependency for legacy gateway routers. Every legacy
``/api/*`` route refuses anonymous callers unless the path matches a
short documented allowlist of genuinely public endpoints.

Why: the legacy gateway routers (models, memory, skills, threads,
artifacts, uploads, agents, mcp, suggestions, channels, runs, thread_runs,
thread_skills, assistants_compat) do not individually call
``Depends(require_authenticated)``. They were written before the identity
subsystem landed and silently fall through to the legacy single-tenant
filesystem layout for anonymous callers. With ``ENABLE_IDENTITY=true``
this leaks data. The fix is a single global dep wired at
``include_router`` time.

When ``ENABLE_IDENTITY=false`` (legacy mode) the dep is a no-op so the
legacy single-tenant deployment story is unchanged.

See: docs/superpowers/specs/2026-05-02-gateway-routes-authn-baseline-design.md
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.gateway.identity.auth.dependencies import get_current_identity
from app.gateway.identity.settings import get_identity_settings


# Path prefixes that are intentionally public. Order does not matter for
# correctness; the function does an O(n) scan with startswith().
PUBLIC_PREFIXES: tuple[str, ...] = (
    # OIDC + password + bootstrap auth flows
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",       # 401s on its own when sid missing
    "/api/auth/logout",        # idempotent, anonymous logout is a harmless no-op
    "/api/auth/providers",     # discovery endpoint, by design
    "/api/auth/oidc",          # /oidc/{provider}/login + /oidc/{provider}/callback
    "/api/auth/set-password",  # bootstrap flow, has its own gating logic
    # Operational
    "/health",
    "/metrics",                # Prometheus scrape, network-gated externally
    "/internal/audit",         # HMAC-signed, has its own verify
)


def require_authenticated_global(request: Request) -> None:
    """FastAPI dep: enforce authentication for legacy gateway routes.

    Allowlist-aware: requests whose path matches any entry in
    ``PUBLIC_PREFIXES`` (via ``startswith``) skip the check.

    Flag-aware: when ``ENABLE_IDENTITY=false`` the dep returns immediately
    so the legacy single-tenant deployment behaves as it did before the
    identity subsystem landed.

    Raises:
        HTTPException(401) when the caller is anonymous on a protected
        path.
    """
    if not get_identity_settings().enabled:
        return

    path = request.url.path
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return

    ident = get_current_identity(request)
    if not ident.is_authenticated:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
