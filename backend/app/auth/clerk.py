"""Clerk session-token verification for the backend.

The frontend (gated by Clerk) sends the Clerk session JWT as a Bearer token.
We verify it against the Clerk instance's JWKS. A valid token means the request
comes from a signed-in (allowlisted) user, which we treat as the owner.

When require_clerk_auth is false (e.g. local dev with no Clerk), verification
is a no-op and routes fall back to the owner-PIN model.
"""

import logging
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def _jwks_client(issuer: str) -> PyJWKClient:
    # PyJWKClient caches keys in-process and refetches on unknown kid.
    return PyJWKClient(f"{issuer.rstrip('/')}/.well-known/jwks.json")


def verify_clerk_token(token: str) -> dict | None:
    """Return the verified claims, or None if the token is missing/invalid."""
    settings = get_settings()
    issuer = settings.clerk_jwt_issuer
    if not issuer or not token:
        return None
    try:
        signing_key = _jwks_client(issuer).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False},
            leeway=30,  # tolerate small clock skew
        )
    except Exception as exc:  # invalid signature / expired / wrong issuer / network
        logger.warning("Clerk token verification failed: %s", str(exc)[:160])
        return None

    # Optional: restrict to known frontends via the authorized-party claim.
    parties = settings.authorized_parties_list
    azp = claims.get("azp")
    if parties and azp and azp not in parties:
        logger.warning("Clerk token azp %r not in authorized parties", azp)
        return None
    return claims


def clerk_user_from_header(authorization: str | None) -> dict | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return verify_clerk_token(token.strip())


def require_clerk_user(authorization: str | None = Header(default=None)) -> dict | None:
    """FastAPI dependency: enforce a valid Clerk session when lockdown is on."""
    settings = get_settings()
    user = clerk_user_from_header(authorization)
    if settings.require_clerk_auth and user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
