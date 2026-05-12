from __future__ import annotations

import os
from fastapi import Header, HTTPException
from jose import jwt


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        raise HTTPException(status_code=401, detail="Authorization must be Bearer token")
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty Bearer token")
    return token


def get_user_id_from_jwt_unverified(token: str) -> str:
    try:
        claims = jwt.get_unverified_claims(token)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"Invalid JWT: {e}") from e
    sub = claims.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(status_code=401, detail="JWT missing subject (sub)")
    return sub


def auth_context(authorization: str | None = Header(default=None)) -> tuple[str, str | None]:
    """
    Returns (user_id, jwt_token).

    For local development, we decode claims without signature verification and rely on
    Supabase RLS enforcement by forwarding the JWT to PostgREST.
    """
    if not authorization:
        if (os.getenv("ALLOW_ANON_AI") or "").lower() in ("1", "true", "yes", "on"):
            return "anon", None
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = extract_bearer_token(authorization)
    user_id = get_user_id_from_jwt_unverified(token)
    return user_id, token

