from fastapi import APIRouter, status

from app.schemas.board import BoardCreate
from app.services.board import get_all_boards, create_board

router = APIRouter()


@router.get("/")
async def get_boards():
    return await get_all_boards()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_board(board: BoardCreate):
    return await create_board(board)