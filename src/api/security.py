"""API key authentication.

Third parties authenticate with a bearer token: ``Authorization: Bearer <key>``
(RFC 6750), the de-facto standard for protected HTTP APIs.

API keys are high-entropy random tokens (not human passwords), so we store and
look them up by a deterministic HMAC-SHA256 keyed hash. That keeps the hash
column UNIQUE + indexed and makes auth a single O(1) equality lookup — something
a salted password hash (bcrypt/argon2) cannot do, since it would force a full
table scan. The raw key is shown to the caller once at creation and never stored.
"""

import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.storage.database import get_db
from src.storage.models import ApiKey, Tenant

# auto_error=False so we own the 401 response. HTTPBearer's default raises 403
# on a missing token, but RFC 6750 wants 401 + a `WWW-Authenticate: Bearer`
# challenge — which is also what third-party clients and SDKs expect.
_bearer_scheme = HTTPBearer(auto_error=False, description="API key as a bearer token")


def hash_api_key(raw_key: str) -> str:
    """Return the HMAC-SHA256 hex digest used to store and look up a key."""
    return hmac.new(
        settings.api_key_pepper.encode(),
        raw_key.encode(),
        hashlib.sha256,
    ).hexdigest()


def generate_api_key() -> str:
    """Generate a new raw API key. Returned once; only its hash is persisted."""
    return f"cra_{secrets.token_urlsafe(32)}"


def _unauthorized(detail: str, *, invalid_token: bool = False) -> HTTPException:
    # RFC 6750: signal a bad token with `error="invalid_token"`; a plain
    # `Bearer` challenge means "credentials required".
    challenge = 'Bearer error="invalid_token"' if invalid_token else "Bearer"
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": challenge},
    )


async def get_current_tenant(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(_bearer_scheme)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Tenant:
    """Resolve the tenant for a request's bearer token, or raise 401.

    Matches only active tenants holding a non-revoked key.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing bearer token.")

    stmt = (
        select(Tenant)
        .join(ApiKey, ApiKey.tenant_id == Tenant.id)
        .where(
            ApiKey.key_hash == hash_api_key(credentials.credentials),
            ApiKey.revoked_at.is_(None),
            Tenant.is_active.is_(True),
        )
    )
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if tenant is None:
        raise _unauthorized("Invalid bearer token.", invalid_token=True)
    return tenant


CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
