"""Operator authentication and step-up authorization.

This is intentionally simple for the current single-operator paper deployment:
- Bearer token authenticates the operator.
- A separate step-up token is required for destructive/high-risk mutations.

Tokens are loaded from environment-backed settings and compared in constant
time. No credentials are written to logs.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from app.config import settings


@dataclass(frozen=True)
class AuthContext:
    actor: str
    authenticated: bool
    step_up: bool = False


def _match(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


async def require_operator(
    authorization: str | None = Header(default=None),
) -> AuthContext:
    token = _bearer_token(authorization)
    if not _match(token, settings.operator_auth_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="operator_auth_required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthContext(actor="operator", authenticated=True)


async def require_step_up(
    authorization: str | None = Header(default=None),
    x_aether_step_up: str | None = Header(default=None),
) -> AuthContext:
    token = _bearer_token(authorization)
    if not _match(token, settings.operator_auth_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="operator_auth_required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not _match(x_aether_step_up, settings.operator_step_up_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="step_up_required",
        )
    return AuthContext(actor="operator", authenticated=True, step_up=True)
