
from fastapi import APIRouter, Depends, status

from app.api.deps import current_identity
from app.schemas.board import BoardCreate
from app.services.board import create_board, get_all_boards
from app.services.board_invitation import (
    create_board_invitation,
    accept_board_invitation,
)
router = APIRouter()


@router.get("/")
async def get_boards(identity=Depends(current_identity)):
    return await get_all_boards(identity=identity)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_board(board: BoardCreate, identity=Depends(current_identity)):
    return await create_board(board, identity=identity)


@router.post(
    "/{board_id}/invitations",
    status_code=status.HTTP_201_CREATED,
)
async def generate_board_invitation(
    board_id: str,
    identity=Depends(current_identity),
):
    return await create_board_invitation(
        board_id,
        identity=identity,
    )

@router.post("/invitations/{token}/accept")
async def join_board_with_invitation(
    token: str,
    identity=Depends(current_identity),
):
    return await accept_board_invitation(
        token,
        identity=identity,
    )