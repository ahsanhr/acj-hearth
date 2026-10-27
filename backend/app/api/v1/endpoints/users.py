from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse

from app.api.deps import current_identity, get_account_service, get_auth_service
from app.api.v1.endpoints.auth import clear_refresh_cookie, public_user
from app.schemas.user import (
    AccountPatch,
    PasswordConfirmation,
    Registration,
    UserPublic,
)

router = APIRouter()


@router.get("/preview", response_class=HTMLResponse)
def get_user_preview():
    return """
    <div style="background-color: #21262d; border: 1px solid #30363d; border-radius: 6px; padding: 12px; margin-top: 10px;">
        <h3 style="margin: 0 0 6px 0; color: #58a6ff;">API Connection Verified!</h3>
        <p style="margin: 0; color: #8b949e; font-size: 14px;">
            This raw HTML was generated directly by the FastAPI backend endpoint.
        </p>
        <span style="display: inline-block; margin-top: 8px; font-size: 12px; color: #3fb950; font-weight: bold;">
            ✓ Status: 200 OK
        </span>
    </div>
    """


@router.post("", response_model=UserPublic, status_code=201)
async def create_account(payload: Registration, service=Depends(get_account_service)):
    user = await service.create(str(payload.email), payload.password.get_secret_value())
    return public_user(user)


@router.get("/me", response_model=UserPublic)
async def me(identity=Depends(current_identity)):
    return public_user(identity[0])


@router.patch("/me", response_model=UserPublic)
async def update_me(
    payload: AccountPatch,
    request: Request,
    response: Response,
    identity=Depends(current_identity),
    service=Depends(get_account_service),
):
    user, session = identity
    updated, revoked = await service.update(user, session["session_id"], payload)
    if revoked:
        clear_refresh_cookie(response, request)
    return public_user(updated)


@router.delete("/me", status_code=204)
async def delete_me(
    payload: PasswordConfirmation,
    request: Request,
    response: Response,
    identity=Depends(current_identity),
    service=Depends(get_account_service),
):
    user, session = identity
    await service.delete(
        user, session["session_id"], payload.current_password.get_secret_value()
    )
    clear_refresh_cookie(response, request)


@router.post("/me/disable", status_code=204)
async def disable_me(
    request: Request,
    response: Response,
    identity=Depends(current_identity),
    service=Depends(get_auth_service),
):
    user, session = identity
    await service.revoke_account(user["_id"], current_sid=session["session_id"])
    clear_refresh_cookie(response, request)
