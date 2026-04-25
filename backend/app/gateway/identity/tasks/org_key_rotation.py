"""Background task: silently rotate permanent org API keys that have reached auto_rotate_at."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.gateway.identity.audit.events import AuditEvent
from app.gateway.identity.audit.writer import AuditBatchWriter

logger = logging.getLogger(__name__)

# How far ahead to set the next auto_rotate_at after a successful rotation.
# 90 days is a reasonable default; callers can override by passing a session_maker
# wired to a different rotation window config.
_DEFAULT_ROTATE_INTERVAL_DAYS = 90


def generate_org_key() -> tuple[str, str, str]:
    """Return (plaintext, sha256_hex_hash, prefix)."""
    raw = secrets.token_urlsafe(32)
    plaintext = f"sk_org_{raw}"
    prefix = plaintext[:12]  # e.g. "sk_org_xxxxx"
    token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    return plaintext, token_hash, prefix


async def rotate_expired_permanent_keys(
    session_maker: async_sessionmaker,
    *,
    writer: AuditBatchWriter | None = None,
    rotate_interval_days: int = _DEFAULT_ROTATE_INTERVAL_DAYS,
) -> int:
    """Find org_api_keys with no_expiry=true and auto_rotate_at <= now().

    Generate a new key for each, atomically replace token_hash/prefix/
    last_rotated_at/auto_rotate_at in the same session, and emit an
    ``org_key.auto_rotated`` audit event.

    Safe to call frequently (e.g. every hour): when no keys need rotation
    the SELECT returns zero rows and no writes are performed.

    Args:
        session_maker: Async SQLAlchemy session factory bound to the
            identity engine (same one used by the audit batch writer).
        writer: Optional AuditBatchWriter.  When provided, a non-critical
            audit event is emitted for each rotated key.  When None the
            rotation still proceeds — audit is best-effort.
        rotate_interval_days: How many days ahead to schedule the *next*
            auto_rotate_at after a successful rotation.  Defaults to 90.

    Returns:
        The number of keys that were rotated this run (0 if nothing to do).
    """
    now = datetime.now(UTC)

    async with session_maker() as session:
        # Raw SQL avoids any ORM model dependency (ORM model for org_api_keys
        # may not exist yet in this milestone) and keeps the import surface
        # minimal.  The query selects only rows that:
        #   - are not revoked (revoked_at IS NULL)
        #   - are permanent (no_expiry = true)
        #   - have reached their rotation deadline (auto_rotate_at <= now)
        stmt = text(
            """
            SELECT id, tenant_id, name
            FROM identity.org_api_keys
            WHERE no_expiry = true
              AND auto_rotate_at IS NOT NULL
              AND auto_rotate_at <= :now
              AND revoked_at IS NULL
            ORDER BY auto_rotate_at ASC
            """
        )
        result = await session.execute(stmt, {"now": now})
        rows = result.fetchall()

        if not rows:
            return 0

        count = 0
        next_rotate_at = now + timedelta(days=rotate_interval_days)

        for row in rows:
            key_id: int = row[0]
            tenant_id: int = row[1]
            key_name: str = row[2]

            try:
                _plaintext, new_hash, new_prefix = generate_org_key()
                await session.execute(
                    text(
                        """
                        UPDATE identity.org_api_keys
                        SET token_hash      = :token_hash,
                            prefix          = :prefix,
                            last_rotated_at = :now,
                            auto_rotate_at  = :next_rotate_at
                        WHERE id = :id
                          AND revoked_at IS NULL
                        """
                    ),
                    {
                        "token_hash": new_hash,
                        "prefix": new_prefix,
                        "now": now,
                        "next_rotate_at": next_rotate_at,
                        "id": key_id,
                    },
                )
                count += 1
                logger.info(
                    "org_key.auto_rotated: key_id=%d tenant_id=%d name=%r",
                    key_id,
                    tenant_id,
                    key_name,
                )

                if writer is not None:
                    event = AuditEvent(
                        action="org_key.auto_rotated",
                        result="success",
                        tenant_id=tenant_id,
                        resource_type="org_api_key",
                        resource_id=str(key_id),
                        metadata={
                            "key_name": key_name,
                            "next_rotate_at": next_rotate_at.isoformat(),
                        },
                    )
                    try:
                        await writer.enqueue(event, critical=False)
                    except Exception:
                        logger.debug(
                            "audit enqueue failed for org_key.auto_rotated key_id=%d",
                            key_id,
                            exc_info=True,
                        )

            except Exception:
                logger.exception(
                    "Failed to rotate org key id=%d tenant_id=%d; skipping",
                    key_id,
                    tenant_id,
                )
                # Continue to next key rather than aborting the entire batch.
                continue

        if count:
            await session.commit()

    return count
