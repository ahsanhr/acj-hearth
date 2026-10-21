from fastapi import APIRouter, Depends, status

from app.api.deps import current_identity
from app.schemas.board import BoardCreate
from app.services.board import create_board, get_all_boards

router = APIRouter(dependencies=[Depends(current_identity)])


@router.get("/")
async def get_boards():
    return await get_all_boards()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_board(board: BoardCreate):
    return await create_board(board)