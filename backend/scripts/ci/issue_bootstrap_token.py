"""Mint a short-lived RS256 JWT for the bootstrap admin user.

Used by the CI identity smoke workflow to avoid the OIDC dance. The JWT is
signed with the same RS256 key the Gateway uses for internal auth, so
``IdentityMiddleware`` resolves it exactly like a post-OIDC access token.

Usage::

    DEERFLOW_BOOTSTRAP_ADMIN_EMAIL=admin@smoke.test \\
        python scripts/ci/issue_bootstrap_token.py

Exit 0 with the JWT printed on stdout; exit 2 on config / DB errors.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid

from sqlalchemy import select

from app.gateway.identity.auth.identity_factory import build_identity_for_user
from app.gateway.identity.auth.jwt import AccessTokenClaims, issue_access_token
from app.gateway.identity.db import create_engine_and_sessionmaker
from app.gateway.identity.models.tenant import Tenant, Workspace
from app.gateway.identity.models.user import Membership, User
from app.gateway.identity.settings import get_identity_settings


async def _mint() -> str:
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
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None:
                raise SystemExit(
                    f"bootstrap admin {email!r} not found (run `make identity-bootstrap` first)"
                )

            tenant = (
                await session.execute(
                    select(Tenant)
                    .join(Membership, Membership.tenant_id == Tenant.id)
                    .where(Membership.user_id == user.id, Membership.status == 1)
                    .order_by(Tenant.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if tenant is None:
                tenant = (
                    await session.execute(select(Tenant).order_by(Tenant.id).limit(1))
                ).scalar_one_or_none()
                if tenant is None:
                    raise SystemExit("no tenant rows exist — bootstrap did not run")

            workspace = (
                await session.execute(
                    select(Workspace)
                    .where(Workspace.tenant_id == tenant.id)
                    .order_by(Workspace.id)
                    .limit(1)
                )
            ).scalar_one_or_none()

            identity = await build_identity_for_user(session, user, tenant, workspace)
    finally:
        await engine.dispose()

    now = int(time.time())
    claims = AccessTokenClaims(
        sub=str(identity.user_id),
        email=identity.email or email,
        tid=identity.tenant_id,
        wids=list(identity.workspace_ids),
        permissions=sorted(identity.permissions),
        roles=identity.roles,
        sid=uuid.uuid4().hex,
        iat=now,
        exp=now + 60,
        iss=settings.jwt_issuer,
        aud=settings.jwt_audience,
    )
    return issue_access_token(claims, private_key_pem=private_pem)


def main() -> None:
    try:
        token = asyncio.run(_mint())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(token)


if __name__ == "__main__":
    main()
