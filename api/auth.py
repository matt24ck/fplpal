"""Clerk-backed request auth for the paid-surface endpoints.

The web app attaches the user's Clerk session JWT as a Bearer token; we verify
it locally (RS256 against Clerk's JWKS — no network call per request, the key
set is fetched once and cached) and hand the route the stable user id (``sub``).

Config (env):
  CLERK_ISSUER              required — the Clerk Frontend API URL, e.g.
                            ``https://xxx.clerk.accounts.dev`` (dev) or
                            ``https://clerk.fplpal.com`` (prod). Found in the
                            Clerk dashboard under API keys.
  CLERK_AUTHORIZED_PARTIES  optional comma-separated origins checked against
                            the token's ``azp`` claim (defense against tokens
                            minted for another Clerk app of the same instance).
  AUTH_DISABLED             set to ``1`` to skip verification entirely (local
                            tinkering without a Clerk app; never in prod).
"""

from __future__ import annotations

import os
from pathlib import Path

import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, Request

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_jwks_client: jwt.PyJWKClient | None = None


def _issuer() -> str | None:
    iss = os.environ.get("CLERK_ISSUER", "").strip().rstrip("/")
    return iss or None


def _jwks() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(f"{_issuer()}/.well-known/jwks.json", cache_keys=True)
    return _jwks_client


def require_user(request: Request) -> str:
    """FastAPI dependency: verify the Bearer token, return the Clerk user id.

    401 on missing/invalid/expired tokens; 503 if the server has no issuer
    configured (fail closed — a misconfigured deploy must not serve paid
    surfaces unauthenticated).
    """
    if os.environ.get("AUTH_DISABLED") == "1":
        return "dev-user"

    issuer = _issuer()
    if issuer is None:
        raise HTTPException(
            status_code=503,
            detail="auth not configured — set CLERK_ISSUER (or AUTH_DISABLED=1 for local dev)",
        )

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="sign in to use this feature")
    token = header[7:].strip()

    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False},  # Clerk session tokens carry no aud
            leeway=10,
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="session expired or invalid — sign in again")

    parties = [
        p.strip().rstrip("/")
        for p in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",")
        if p.strip()
    ]
    azp = str(claims.get("azp", "")).rstrip("/")
    if parties and azp and azp not in parties:
        raise HTTPException(status_code=401, detail="token issued for another origin")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="session expired or invalid — sign in again")
    return str(sub)
