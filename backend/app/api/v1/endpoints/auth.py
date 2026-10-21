from datetime import timezone

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import current_identity, get_auth_service, require_origin
from app.core.security import issue_access_token
from app.schemas.token import AccessToken, SessionPublic
from app.schemas.user import Credentials, PasswordChange, Registration, UserPublic

router = APIRouter()
COOKIE_NAME = "__Secure-hearth_refresh"
COOKIE_PATH = "/api/v1/auth"


def clear_refresh_cookie(response: Response, request: Request):
    response.delete_cookie(
        COOKIE_NAME, path=COOKIE_PATH, secure=True, httponly=True,
        samesite=request.app.state.settings.AUTH_COOKIE_SAMESITE,
    )


def token_response(request: Request, response: Response, session, raw):
    settings = request.app.state.settings
    token = issue_access_token(session, settings)
    response.set_cookie(
        COOKIE_NAME, raw, path=COOKIE_PATH,
        expires=session["refresh_expires_at"].astimezone(timezone.utc),
        httponly=True, secure=True, samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    response.headers["Cache-Control"] = "no-store"
    return AccessToken(access_token=token)


def public_user(user):
    return UserPublic(id=str(user["_id"]), email=user["email"], email_verified=False)


@router.post("/register", response_model=UserPublic, status_code=201)
async def register(payload: Registration, service=Depends(get_auth_service)):
    return public_user(await service.register(str(payload.email), payload.password.get_secret_value()))


@router.post("/login", response_model=AccessToken, dependencies=[Depends(require_origin)])
async def login(payload: Credentials, request: Request, response: Response,
                service=Depends(get_auth_service)):
    session, raw = await service.login(str(payload.email), payload.password.get_secret_value())
    return token_response(request, response, session, raw)


@router.post("/refresh", response_model=AccessToken, dependencies=[Depends(require_origin)])
async def refresh(request: Request, response: Response, service=Depends(get_auth_service)):
    session, raw = await service.refresh(request.cookies.get(COOKIE_NAME, ""))
    return token_response(request, response, session, raw)


@router.post("/logout", status_code=204, dependencies=[Depends(require_origin)])
async def logout(request: Request, response: Response, service=Depends(get_auth_service)):
    await service.logout(request.cookies.get(COOKIE_NAME))
    clear_refresh_cookie(response, request)


@router.get("/sessions", response_model=list[SessionPublic])
async def list_sessions(identity=Depends(current_identity), service=Depends(get_auth_service)):
    user, session = identity
    return await service.list_sessions(user["_id"], session["session_id"])


@router.delete("/sessions", status_code=204)
async def clear_sessions(request: Request, response: Response,
                         identity=Depends(current_identity), service=Depends(get_auth_service)):
    user, session = identity
    await service.close_sessions(user["_id"], session["session_id"])
    clear_refresh_cookie(response, request)


@router.delete("/sessions/{session_id}", status_code=204)
async def close_session(session_id: str, request: Request, response: Response,
                        identity=Depends(current_identity), service=Depends(get_auth_service)):
    user, current = identity
    await service.close_sessions(user["_id"], current["session_id"], session_id)
    if session_id == current["session_id"]:
        clear_refresh_cookie(response, request)


@router.post("/password", status_code=204)
async def change_password(payload: PasswordChange, request: Request, response: Response,
                          identity=Depends(current_identity), service=Depends(get_auth_service)):
    user, session = identity
    await service.change_password(
        user, session["session_id"], payload.current_password.get_secret_value(),
        payload.new_password.get_secret_value(),
    )
    clear_refresh_cookie(response, request)
