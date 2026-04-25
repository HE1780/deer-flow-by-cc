"""Mint a short-lived RS256 JWT for the bootstrap admin user.

Used by the CI identity smoke workflow and local dev to avoid the OIDC dance.
The JWT is signed with the same RS256 key the Gateway uses for internal auth,
and the session is registered in Redis so IdentityMiddleware accepts it.

Usage::

    DEERFLOW_BOOTSTRAP_ADMIN_EMAIL=admin@local.test \\
        python scripts/ci/issue_bootstrap_token.py

    # Longer TTL for manual browser testing (default 60s, pass --ttl <seconds>):
    DEERFLOW_BOOTSTRAP_ADMIN_EMAIL=admin@local.test \\
        python scripts/ci/issue_bootstrap_token.py --ttl 3600

Exit 0 with the JWT printed on stdout; exit 2 on config / DB errors.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid

import redis.asyncio as aioredis
from sqlalchemy import select

from app.gateway.identity.auth.identity_factory import build_identity_for_user
from app.gateway.identity.auth.jwt import AccessTokenClaims, issue_access_token
from app.gateway.identity.auth.session import SessionStore
from app.gateway.identity.db import create_engine_and_sessionmaker
from app.gateway.identity.models.tenant import Tenant, Workspace
from app.gateway.identity.models.user import Membership, User
from app.gateway.identity.settings import get_identity_settings


async def _mint(ttl_sec: int) -> str:
    settings = get_identity_settings()

    if not settings.enabled:
        raise SystemExit("ENABLE_IDENTITY must be true to mint a bootstrap JWT")

    email = settings.bootstrap_admin_email
    if not email:
        raise SystemExit("DEERFLOW_BOOTSTRAP_ADMIN_EMAIL must be set")

    if settings.jwt_private_key:
        private_pem = settings.jwt_private_key
    else:
        with open(settings.jwt_private_key_path, encoding="utf-8") as f:
            private_pem = f.read()

    engine, maker = create_engine_and_sessionmaker(settings.database_url)
    try:
        async with maker() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if user is None:
                raise SystemExit(f"bootstrap admin {email!r} not found (run `make identity-bootstrap` first)")

            tenant = (await session.execute(select(Tenant).join(Membership, Membership.tenant_id == Tenant.id).where(Membership.user_id == user.id, Membership.status == 1).order_by(Tenant.id).limit(1))).scalar_one_or_none()
            if tenant is None:
                tenant = (await session.execute(select(Tenant).order_by(Tenant.id).limit(1))).scalar_one_or_none()
                if tenant is None:
                    raise SystemExit("no tenant rows exist — bootstrap did not run")

            workspace = (await session.execute(select(Workspace).where(Workspace.tenant_id == tenant.id).order_by(Workspace.id).limit(1))).scalar_one_or_none()

            identity = await build_identity_for_user(session, user, tenant, workspace)
    finally:
        await engine.dispose()

    # Register session in Redis so IdentityMiddleware can validate the sid.
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        store = SessionStore(
            redis_client,
            refresh_ttl_sec=ttl_sec,
            key_prefix="deerflow",
        )
        refresh_token = uuid.uuid4().hex
        record = await store.create(
            user_id=identity.user_id,
            tenant_id=identity.tenant_id,
            refresh_token=refresh_token,
            ip=None,
            ua="bootstrap-script",
        )
    finally:
        await redis_client.aclose()

    now = int(time.time())
    claims = AccessTokenClaims(
        sub=str(identity.user_id),
        email=identity.email or email,
        tid=identity.tenant_id,
        wids=list(identity.workspace_ids),
        permissions=sorted(identity.permissions),
        roles=identity.roles,
        sid=record.sid,
        iat=now,
        exp=now + ttl_sec,
        iss=settings.jwt_issuer,
        aud=settings.jwt_audience,
    )
    return issue_access_token(claims, private_key_pem=private_pem)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint a bootstrap JWT for local dev / CI")
    parser.add_argument("--ttl", type=int, default=60, help="Token TTL in seconds (default: 60)")
    args = parser.parse_args()

    try:
        token = asyncio.run(_mint(args.ttl))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(token)


if __name__ == "__main__":
    main()
