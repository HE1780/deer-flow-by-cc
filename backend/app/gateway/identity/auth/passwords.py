"""Password hashing helpers backed by the ``bcrypt`` package.

Centralizes how user passwords and registration codes are hashed and verified
so every call site picks up the configured ``DEERFLOW_BCRYPT_COST`` instead of
silently falling back to the bcrypt library default.

Note on the two bcrypt providers in this codebase:

- This module wraps the native ``bcrypt`` library. Use it for user passwords
  and registration code plaintext (anything that runs through
  ``settings.bcrypt_cost``).
- ``app.gateway.identity.auth.api_token`` keeps using ``passlib.hash.bcrypt``
  for API token hashes — that surface is unrelated and intentionally left
  alone.
"""

from __future__ import annotations

import bcrypt

from app.gateway.identity.settings import get_identity_settings


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash for ``plaintext`` using the configured cost."""
    cost = get_identity_settings().bcrypt_cost
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=cost)).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True iff ``plaintext`` matches the previously stored ``hashed``."""
    if not hashed:
        return False
    return bcrypt.checkpw(plaintext.encode(), hashed.encode())
