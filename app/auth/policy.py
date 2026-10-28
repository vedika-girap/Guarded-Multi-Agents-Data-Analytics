from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.config import ROLE_LEVELS, Settings, get_settings


@dataclass(frozen=True)
class Identity:
    user_id: str
    tenant_id: str
    role: str


DEV_IDENTITY = Identity(user_id="local-dev-user", tenant_id="local-dev-tenant", role="viewer")


def _auth_error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": error_code, "message": message},
    )


def resolve_identity(
    authorization: str | None,
    settings: Settings,
    x_role: str | None = None,
) -> Identity:
    """Resolve identity from a fixed local principal or a verified JWT.

    x_role remains an ignored argument during migration; it can never grant privileges.
    """
    del x_role
    if settings.auth_mode == "dev":
        return DEV_IDENTITY

    if not authorization or not authorization.startswith("Bearer "):
        raise _auth_error(401, "AUTHENTICATION_REQUIRED", "Provide a valid Bearer token.")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise _auth_error(401, "AUTHENTICATION_REQUIRED", "Provide a valid Bearer token.")
    if settings.auth_jwt_secret is None or not settings.auth_jwt_issuer or not settings.auth_jwt_audience:
        # This should be caught at startup, but keep the boundary safe if called directly.
        raise _auth_error(503, "AUTH_CONFIGURATION_ERROR", "JWT authentication is not configured.")

    try:
        claims = jwt.decode(
            token,
            settings.auth_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            options={"require": ["exp", "iss", "aud", "sub", "tenant_id", "role"]},
        )
    except ExpiredSignatureError:
        raise _auth_error(401, "TOKEN_EXPIRED", "The access token has expired.") from None
    except InvalidTokenError:
        raise _auth_error(401, "INVALID_TOKEN", "The access token is invalid.") from None

    user_id = claims.get("sub")
    tenant_id = claims.get("tenant_id")
    role = claims.get("role")
    if not all(isinstance(value, str) and value.strip() for value in (user_id, tenant_id, role)):
        raise _auth_error(401, "INVALID_TOKEN_CLAIMS", "The access token is missing required identity claims.")
    if role not in ROLE_LEVELS:
        raise _auth_error(403, "ROLE_NOT_ALLOWED", "The access token contains an unsupported role.")
    return Identity(user_id=user_id, tenant_id=tenant_id, role=role)


def current_identity(
    authorization: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> Identity:
    return resolve_identity(authorization, get_settings(), x_role)


def can_view_rows(role: str) -> bool:
    return role in ROLE_LEVELS and ROLE_LEVELS[role] >= ROLE_LEVELS["analyst"]
