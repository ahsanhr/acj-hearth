from fastapi import APIRouter, Depends, status

from app.api.deps import current_identity
from app.schemas.board import BoardCreate
from app.services.board import create_board, get_all_boards

router = APIRouter()


@router.get("/")
async def get_boards(identity=Depends(current_identity)):
    return await get_all_boards(identity=identity)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_board(board: BoardCreate, identity=Depends(current_identity)):
    return await create_board(board, identity=identity)
