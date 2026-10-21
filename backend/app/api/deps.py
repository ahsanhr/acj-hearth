from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from app.core.security import decode_access_token
from app.services.auth import AuthError, unauthorized

bearer = HTTPBearer(auto_error=False)


def get_auth_service(request: Request):
    return request.app.state.auth_service


def require_origin(request: Request):
    origin = request.headers.get("origin")
    if not origin or origin == "null" or origin not in request.app.state.settings.AUTH_ALLOWED_ORIGINS:
        raise AuthError(403, "invalid_origin", "Request origin is not allowed.")


async def current_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    service=Depends(get_auth_service),
):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    try:
        claims = decode_access_token(credentials.credentials, request.app.state.settings)
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise unauthorized() from exc
    return await service.authenticate(claims)
