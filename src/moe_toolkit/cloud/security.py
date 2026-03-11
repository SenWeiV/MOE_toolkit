"""Authentication helpers for the cloud API."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from moe_toolkit.cloud.settings import CloudSettings


def extract_bearer_token(authorization: str | None) -> str | None:
    """Extracts a bearer token from an Authorization header."""

    if authorization is None:
        return None
    prefix = "bearer "
    lowered = authorization.lower()
    if not lowered.startswith(prefix):
        return None
    return authorization[len(prefix) :].strip()


def is_authorized(
    settings: CloudSettings,
    authorization: str | None = Header(default=None),
) -> bool:
    """Returns whether the provided bearer token is currently accepted."""

    token = extract_bearer_token(authorization)
    if token is None:
        return False
    return token in settings.api_keys


def require_authorization(
    settings: CloudSettings,
    authorization: str | None = Header(default=None),
) -> str:
    """Validates a bearer token and returns it if accepted."""

    token = extract_bearer_token(authorization)
    if token is None or token not in settings.api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )
    return token
