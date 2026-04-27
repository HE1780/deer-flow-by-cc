# M2: Authentication (OIDC + JWT + API Token + Session) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Detail level: **signature-level TDD** (function signatures + test cases are complete; bodies give algorithm sketches that must be expanded during implementation).

**Goal:** Add authentication — OIDC login (Authlib, multi-provider), internal JWT signing (access + refresh), API token with bcrypt-hashed secret + scopes, Redis-backed sessions, login failure lockout, forced logout. Provide `/auth/*` and `/me` routes. Does NOT yet enforce permissions on business routes (that's M3).

**Architecture:** FastAPI routes under `app/gateway/identity/auth/`. Authlib OIDC client for Okta/Azure AD/Keycloak. Internal JWT (RS256) with 15 min access + 7 day refresh stored in Redis. API token format `dft_<prefix>_<random>` with bcrypt hash. IdentityMiddleware (global) reads `Authorization` header or `deerflow_session` cookie, resolves to `Identity` object, sets `request.state.identity` and ContextVars.

**Tech Stack:** authlib, python-jose[cryptography], passlib[bcrypt], redis, fastapi.

**Prerequisites:** M1 merged. Branch `feat/m2-authentication` off `main`.

**Spec reference:** §5 (Authentication flow), §3.3 (deps), §10.10 (release note).

**Non-goals:** no route enforcement (M3 decorator wraps this); no token refresh on every request (M2 only exposes endpoint); no admin UI (M7).

---

## File Structure

### Created

```
backend/app/gateway/identity/auth/
  __init__.py
  config.py                 # load OIDC providers from config/identity.yaml
  oidc.py                   # AuthlibOIDCClient per provider, login/callback handlers
  jwt.py                    # sign/verify internal JWT (RS256), issue_access, issue_refresh
  api_token.py              # create/verify dft_* tokens with bcrypt
  session.py                # Redis session store: create, get, revoke, revoke_all_for_user
  lockout.py                # Redis-backed login-failure rate limiter
  identity_factory.py       # build Identity dataclass from user+tenant+permissions
  dependencies.py           # FastAPI Depends() helpers: get_current_identity, require_authenticated

backend/app/gateway/identity/middlewares/
  __init__.py
  identity.py               # IdentityMiddleware (reads token/cookie, resolves Identity, sets ctx vars)

backend/app/gateway/identity/routers/
  __init__.py
  auth.py                   # /api/auth/oidc/{p}/login, /api/auth/oidc/{p}/callback, /api/auth/refresh, /api/auth/logout
  me.py                     # /api/me (current session/identity summary)

config/identity.yaml.example  # OIDC provider config template

backend/tests/identity/auth/
  __init__.py
  test_config.py            # load providers, env substitution
  test_oidc_flow.py         # mock IdP, full login → callback → session
  test_jwt.py               # sign/verify, RS256 key rotation scenario
  test_api_token.py         # create returns one-time plaintext, hash-only at rest, scopes enforced
  test_session.py           # Redis CRUD, revoke, revoke_all
  test_lockout.py           # 10 failures / 5min → 15min block; IP+email key
  test_identity_middleware.py
  test_dependencies.py
  test_auth_router.py       # route-level integration
  test_me_router.py
```

### Modified

```
backend/pyproject.toml             # add authlib, python-jose[cryptography], passlib[bcrypt]
backend/app/gateway/app.py         # register IdentityMiddleware (gated on flag); include auth/me routers
backend/app/gateway/identity/settings.py  # add jwt_private_key_path, jwt_public_key_path, session_ttl_access_sec, session_ttl_refresh_sec, login_lockout_max_attempts, login_lockout_window_sec, login_lockout_block_sec
backend/alembic/versions/20260421_0002_api_token_unique.py  # (new) add partial unique index on api_tokens (prefix, token_hash) WHERE revoked_at IS NULL
backend/app/gateway/identity/context.py  # add current_session_id ContextVar
backend/Makefile                   # add `make identity-keys` helper to generate RS256 keys
backend/CLAUDE.md                  # document auth routes + flag interaction
```

---

## Task 1: Deps + settings extension

- [ ] **Step 1.1: Add deps**

In `backend/pyproject.toml` `[project].dependencies` append:
```
"authlib>=1.3.0",
"python-jose[cryptography]>=3.3.0",
"passlib[bcrypt]>=1.7.4",
"itsdangerous>=2.2.0",  # for cookie signing
```
Run `uv sync`.

- [ ] **Step 1.2: Extend IdentitySettings**

Add fields (defaults chosen to not require manual config in M2 dev):

```python
jwt_private_key: str | None  # inline PEM or None to load from path
jwt_private_key_path: str    # default "/etc/deerflow/jwt_private.pem"
jwt_public_key_path: str
jwt_issuer: str              # "deerflow"
jwt_audience: str            # "deerflow-api"
access_token_ttl_sec: int    # 900 (15 min)
refresh_token_ttl_sec: int   # 604800 (7 days)
cookie_name: str             # "deerflow_session"
cookie_secure: bool          # True in prod, False when DEBUG
login_lockout_max_attempts: int  # 10
login_lockout_window_sec: int    # 300
login_lockout_block_sec: int     # 900
bcrypt_cost: int             # 12
internal_signing_key: str | None  # HMAC key for Gateway→LangGraph header (M5 uses); bootstrapped in M2
```

- [ ] **Step 1.3: Tests** — `test_settings.py` additions to verify each new env var / default.

- [ ] **Step 1.4: Commit** `chore(identity): extend settings for auth config`

---

## Task 2: OIDC provider config loader

**Signature:**

```python
# auth/config.py
from dataclasses import dataclass

@dataclass(frozen=True)
class OIDCProviderConfig:
    name: str
    issuer: str
    client_id: str
    client_secret: str
    scopes: list[str]            # default ["openid", "profile", "email"]
    authorize_url: str | None    # override; usually discovered
    token_url: str | None
    jwks_uri: str | None

def load_oidc_providers(path: str | None = None) -> dict[str, OIDCProviderConfig]:
    """Load providers from config/identity.yaml; resolve $ENV references."""
```

**Config template** (`config/identity.yaml.example`):

```yaml
oidc:
  providers:
    okta:
      issuer: https://YOUR_DOMAIN.okta.com
      client_id: $OKTA_CLIENT_ID
      client_secret: $OKTA_CLIENT_SECRET
      scopes: [openid, profile, email]
```

**Tests** (`test_config.py`):

- empty config → `{}`
- single provider → dict with one entry
- `$VAR` substitution
- missing required field (issuer/client_id/client_secret) → `ValueError`
- unknown keys under provider → ignored with warning

---

## Task 3: JWT signing

**Signatures:**

```python
# auth/jwt.py
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass(frozen=True)
class AccessTokenClaims:
    sub: str            # user_id (string)
    email: str
    tid: int | None     # active tenant id (None for platform_admin)
    wids: list[int]
    permissions: list[str]
    roles: dict         # {"platform": [...], "tenant": [...], "workspaces": {"1": "..."}}
    sid: str            # session id
    exp: int
    iat: int
    iss: str
    aud: str

def issue_access_token(claims: AccessTokenClaims, *, private_key_pem: str, algorithm: str = "RS256") -> str: ...
def verify_access_token(token: str, *, public_key_pem: str, issuer: str, audience: str) -> AccessTokenClaims: ...
def generate_refresh_token() -> str:  # 64 bytes random, url-safe base64
    ...
```

**Tests** (`test_jwt.py`):

- roundtrip signing + verifying
- expired token → raises specific `TokenExpiredError`
- wrong issuer → raises `InvalidIssuerError`
- wrong audience → raises `InvalidAudienceError`
- wrong signature → raises `InvalidSignatureError`
- tampered payload → raises `InvalidSignatureError`
- refresh token is 64 bytes base64url, each call different

**Key loading helper** (in `bootstrap` or first-run): if key files absent, generate RSA 2048 pair, write to `$DEERFLOW_HOME/_system/jwt_{private,public}.pem` with 0600/0644. `make identity-keys` invokes same helper for ops.

---

## Task 4: Redis session store

**Signatures:**

```python
# auth/session.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class SessionRecord:
    sid: str
    user_id: int
    tenant_id: int | None
    refresh_hash: str
    ip: str | None
    user_agent: str | None
    created_at: datetime
    revoked: bool

class SessionStore:
    def __init__(self, redis_client, *, refresh_ttl_sec: int): ...
    async def create(self, user_id: int, tenant_id: int | None, refresh_token: str, *, ip: str | None, ua: str | None) -> SessionRecord: ...
    async def get(self, sid: str) -> SessionRecord | None: ...
    async def revoke(self, sid: str) -> None: ...
    async def revoke_all_for_user(self, user_id: int) -> int:
        """Return count revoked."""
    async def list_for_user(self, user_id: int) -> list[SessionRecord]: ...
    async def verify_refresh(self, sid: str, refresh_token: str) -> bool: ...
```

**Redis layout:**
- `deerflow:session:{sid}` → hash { user_id, tenant_id, refresh_hash, created_at, ip, ua, revoked }, TTL = refresh_ttl_sec
- `deerflow:session:by_user:{user_id}` → SET of sids (for efficient revoke_all)

**Tests** (`test_session.py`): create → get round-trip; revoke makes get return None (or revoked=True); verify_refresh for wrong token returns False; revoke_all_for_user removes all sessions.

---

## Task 5: Login lockout

**Signature:**

```python
# auth/lockout.py
class LoginLockout:
    def __init__(self, redis_client, *, max_attempts: int, window_sec: int, block_sec: int): ...
    async def record_failure(self, *, ip: str, email: str) -> bool:
        """Return True if triggers block."""
    async def is_blocked(self, *, ip: str, email: str) -> bool: ...
    async def clear(self, *, ip: str, email: str) -> None: ...  # call on successful login
```

**Redis layout:**
- counter `deerflow:login_fail:{ip}:{email}` INCR, EXPIRE to window_sec on first
- block flag `deerflow:login_block:{ip}:{email}` SET with EXPIRE block_sec

**Tests** (`test_lockout.py`):
- single failure not blocked
- max_attempts failures within window → is_blocked True for block_sec
- window expires without reaching max → counter resets
- clear() removes both keys
- block key covers separate ip/email combinations independently

---

## Task 6: API token

**Signatures:**

```python
# auth/api_token.py
@dataclass
class CreatedToken:
    token_id: int
    plaintext: str   # returned ONCE to caller
    prefix: str      # stored for index lookup

async def create_api_token(
    session,
    *,
    user_id: int,
    tenant_id: int,
    workspace_id: int | None,
    name: str,
    scopes: list[str],
    expires_at: datetime | None,
    created_by: int,
) -> CreatedToken:
    """Generate 'dft_{prefix}_{secret}', bcrypt(plaintext), persist hash + scopes."""

async def verify_api_token(session, plaintext: str) -> Identity | None:
    """Look up by prefix; bcrypt compare; reject if expired/revoked; update last_used_at/ip."""

async def revoke_api_token(session, *, token_id: int, by_user_id: int) -> None: ...
```

**Token format:** `dft_` + 6 char prefix (base32, no padding) + `_` + 32 char secret (base32). Plaintext length = `4 + 6 + 1 + 32 = 43`. Only prefix is indexed; hash compared after lookup.

**Tests** (`test_api_token.py`):
- create returns plaintext, db stores only hash
- verify with correct plaintext → returns Identity with scopes
- verify with wrong secret but matching prefix → None
- verify expired → None + no last_used update
- verify revoked → None
- creating two tokens with colliding prefix → both work (prefix index returns list; verify picks the matching hash)
- last_used_at updated asynchronously (via background task or queued update; don't block the verify path); test tolerates eventual consistency up to 2s

---

## Task 7: OIDC client

**Signatures:**

```python
# auth/oidc.py
class OIDCClient:
    def __init__(self, config: OIDCProviderConfig, *, redis_client, state_ttl_sec: int = 300): ...
    async def login_redirect(self, *, redirect_uri: str, next_url: str | None) -> str:
        """Generate state+PKCE, store in Redis, return authorize URL."""
    async def handle_callback(self, *, code: str, state: str, redirect_uri: str) -> OIDCUserInfo:
        """Verify state+PKCE, exchange code, verify id_token (aud/iss/nonce), return user info."""

@dataclass(frozen=True)
class OIDCUserInfo:
    subject: str
    provider: str
    email: str
    display_name: str | None
    id_token_claims: dict
```

**Tests** (`test_oidc_flow.py`):
- Use a local FastAPI-based mock IdP (fixture in `conftest.py` under `tests/identity/auth/`) serving `/.well-known/openid-configuration`, `/authorize`, `/token`, `/.well-known/jwks.json`
- `login_redirect` produces valid authorize URL with state and code_challenge
- state key in Redis has TTL=300s
- `handle_callback` with matching state+nonce succeeds
- `handle_callback` with mismatched state → `StateMismatchError`
- `handle_callback` with mismatched nonce → `NonceMismatchError`
- `handle_callback` after state TTL → `StateExpiredError`

---

## Task 8: First-login policy + Identity factory

**Signature:**

```python
# auth/identity_factory.py
async def upsert_oidc_user(session, info: OIDCUserInfo) -> User:
    """Match by (provider, subject); fallback by email; create or bind."""

async def resolve_active_tenant(session, user: User, *, auto_provision: bool = False) -> tuple[Tenant | None, Workspace | None]:
    """
    - If user has membership → return first active tenant (alpha order) and default workspace
    - If no membership and auto_provision=True → create personal tenant + workspace
    - Else → return (None, None) (caller renders 'not invited' page)
    """

async def build_identity_for_user(session, user: User, tenant: Tenant, workspace: Workspace | None) -> Identity:
    """Flatten user_roles + workspace_members → permissions set."""
```

Note the spec §5.5 decisions: v1 default `auto_provision=False`. Return `(None, None)` triggers the /login page showing "not invited" error.

**Tests** (`test_identity_factory.py`): matching existing user, email fallback, create new user, no membership path, auto_provision path, permissions correctly flattened for each of the 5 seed roles.

---

## Task 9: Identity middleware

**Signature:**

```python
# middlewares/identity.py
class IdentityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, public_key_pem: str, session_store: SessionStore): ...
    async def dispatch(self, request, call_next):
        """
        1. Parse Authorization header and/or cookie
        2. If 'Bearer dft_...' → verify_api_token
        3. Else if 'Bearer eyJ...' → verify JWT, check session still valid
        4. Else if cookie present → same as JWT path
        5. Else → anonymous Identity (token_type="anonymous", user_id=None, tenant_id=None, permissions=frozenset())
        6. Set request.state.identity + ContextVars (current_identity, current_tenant_id, current_session_id)
        7. Call downstream; clear ContextVars in finally
        """
```

**Behavior matrix (test cases in `test_identity_middleware.py`):**
- No auth → `anonymous Identity (token_type="anonymous", user_id=None, tenant_id=None, permissions=frozenset())`, tenant_id=None
- Valid JWT + valid session → `Identity` with full permissions
- Valid JWT but session revoked → `anonymous Identity (token_type="anonymous", user_id=None, tenant_id=None, permissions=frozenset())`
- Expired JWT → `anonymous Identity (token_type="anonymous", user_id=None, tenant_id=None, permissions=frozenset())` (M2), not 401 directly (M3 decorator decides)
- Valid API token → `Identity` with token scopes as permissions
- Revoked API token → `anonymous Identity (token_type="anonymous", user_id=None, tenant_id=None, permissions=frozenset())`
- Malformed Authorization header → `anonymous Identity (token_type="anonymous", user_id=None, tenant_id=None, permissions=frozenset())` (don't crash)

Middleware registered only when `ENABLE_IDENTITY=true` (see Task 12).

---

## Task 10: Auth router

**Routes** (in `app/gateway/identity/routers/auth.py`):

```
GET  /api/auth/oidc/{provider}/login     → 302 to IdP authorize URL
GET  /api/auth/oidc/{provider}/callback  → 302 to next_url with Set-Cookie
POST /api/auth/refresh                   → 200 { access_token: "..." }
POST /api/auth/logout                    → 200 (revokes session + clears cookie)
```

**Signatures:**

```python
@router.get("/api/auth/oidc/{provider}/login")
async def oidc_login(provider: str, next: str | None = None, request: Request): ...

@router.get("/api/auth/oidc/{provider}/callback")
async def oidc_callback(provider: str, code: str, state: str, request: Request, response: Response): ...

@router.post("/api/auth/refresh")
async def refresh(request: Request, response: Response): ...

@router.post("/api/auth/logout")
async def logout(request: Request, response: Response): ...
```

**Cookie**: `Set-Cookie: deerflow_session={access_token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=900`. Refresh token is stored server-side in Redis only — the client never sees it. Refresh endpoint uses the session id inside the expired access token (which is still decodable for its claims) to check Redis session and issue a new access token.

**Tests** (`test_auth_router.py`):
- Full flow: login redirect → callback with mock IdP → cookie set → `GET /api/me` authenticated
- Callback with no membership → 302 to /login?error=no_membership
- Refresh with valid session → new access
- Refresh with revoked session → 401
- Logout clears cookie + revokes session; subsequent refresh → 401
- Login lockout after 10 failed oidc attempts from same IP → 429

---

## Task 11: Me router

**Routes** (in `app/gateway/identity/routers/me.py`):

```
GET    /api/me                   → user + active tenant + tenants list + workspaces + permissions
POST   /api/me/switch-tenant     → body { tenant_id }, returns new access token
GET    /api/me/tokens            → list own API tokens (prefix only)
POST   /api/me/tokens            → create token, returns plaintext ONCE
DELETE /api/me/tokens/{id}       → revoke own token
GET    /api/me/sessions          → list active sessions
DELETE /api/me/sessions/{sid}    → revoke one
PATCH  /api/me                   → update display_name / avatar
```

Each route uses `Depends(require_authenticated)` dependency.

**Tests** (`test_me_router.py`): all routes require auth (401 without), happy-path success, own-resource-only constraints (cannot revoke another user's token/session).

---

## Task 12: Wire middleware + routers into app

**Modify `app/gateway/app.py`:**

Inside `_init_identity_subsystem` (landed in M1), after bootstrap, add:

```python
from app.gateway.identity.session import SessionStore
from app.gateway.identity.middlewares.identity import IdentityMiddleware
from app.gateway.identity.routers import auth as auth_router_module
from app.gateway.identity.routers import me as me_router_module

# Create redis client, session store; register middleware and routers
```

Pattern: only register the middleware/routers if `settings.enabled`. When flag is off, behavior stays exactly as before (regression guard from M1 still green).

**Tests** (`test_gateway_identity_lifespan.py` extension): with flag on, `/api/auth/oidc/okta/login` returns 302; with flag off, `/api/auth/oidc/okta/login` returns 404 (route not registered).

---

## Task 13: Docs + release notes

- Update `backend/CLAUDE.md` with auth section.
- Update root `README.md` → "Optional: Enterprise Identity" section: add OIDC provider config instructions + `make identity-keys` helper.
- Add `config/identity.yaml.example` to repo.

---

## Verification + PR

1. `make identity-test` → all green.
2. Manual: spin mock IdP via fixture, curl through full flow.
3. Flag-off regression (M1 test) still green.
4. `uvx ruff check . && uvx ruff format --check .` clean.
5. Push branch, open PR HE1780/deer-flow:main ← feat/m2-authentication.

**Acceptance:**
- Logging in with Okta mock IdP yields a valid cookie, `GET /api/me` returns user info.
- Creating an API token returns plaintext once; subsequent list shows only prefix.
- Logout invalidates the session; further requests look anonymous.
- Lockout engages after 10 failures.
- Flag-off regression test still passes.

## Self-review vs spec §5

- §5.1 OIDC flow diagram: Task 7 + Task 10 covers all 8 steps.
- §5.2 Access/Refresh/API token formats: Task 3 + Task 6 match.
- §5.3 middleware stack placement: Task 9 registers IdentityMiddleware.
- §5.4 Gateway→LangGraph headers: deferred to M5 (correct).
- §5.5 first-login落库 with `auto_provision` flag: Task 8 implemented.
- §5.6 session management: Task 4 + Task 10 + Task 11 (list/revoke).
- §5.7 security: Task 5 (lockout), Task 6 (bcrypt), Task 10 (HttpOnly cookie).
- §5.8 multi-provider config: Task 2.
