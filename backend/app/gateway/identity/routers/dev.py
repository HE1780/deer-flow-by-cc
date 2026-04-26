"""DEV-ONLY endpoint: mint a bootstrap JWT + register a Redis session.

Registered only when ENABLE_IDENTITY=true AND DEERFLOW_DEV_LOGIN=true.
Never exposed in production.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.gateway.identity.auth.identity_factory import build_identity_for_user
from app.gateway.identity.auth.jwt import AccessTokenClaims, issue_access_token
from app.gateway.identity.auth.session import SessionStore
from app.gateway.identity.auth.runtime import get_runtime
from app.gateway.identity.db import create_engine_and_sessionmaker
from app.gateway.identity.models.tenant import Tenant, Workspace
from app.gateway.identity.models.user import Membership, User
from app.gateway.identity.settings import get_identity_settings

router = APIRouter(prefix="/api/dev", tags=["dev"])

_TTL = 3600


@router.post("/bootstrap-token")
async def dev_bootstrap_token():
    settings = get_identity_settings()
    email = settings.bootstrap_admin_email
    if not email:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DEERFLOW_BOOTSTRAP_ADMIN_EMAIL not set",
        )

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
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    f"bootstrap admin {email!r} not found — run `make identity-bootstrap`",
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
                    await session.execute(
                        select(Tenant).order_by(Tenant.id).limit(1)
                    )
                ).scalar_one_or_none()
            if tenant is None:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE, "no tenant rows exist"
                )

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

    rt = get_runtime()
    store = SessionStore(
        rt.redis_client,
        refresh_ttl_sec=_TTL,
        key_prefix="deerflow",
    )
    record = await store.create(
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        refresh_token=uuid.uuid4().hex,
        ip=None,
        ua="dev-bootstrap",
    )

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
        exp=now + _TTL,
        iss=settings.jwt_issuer,
        aud=settings.jwt_audience,
    )
    token = issue_access_token(claims, private_key_pem=private_pem)
    return {"token": token, "cookie_name": settings.cookie_name}
