from fastapi import APIRouter, Depends, status

from app.api.deps import current_identity
from app.schemas.todo_list import TodoListCreate
from app.services.todo_list import create_todo_list, get_board_todo_lists

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_todo_list(
    board_id: str, todo_list: TodoListCreate, identity=Depends(current_identity)
):
    return await create_todo_list(board_id, todo_list, identity=identity)


@router.get("/")
async def get_todo_lists(board_id: str, identity=Depends(current_identity)):
    return await get_board_todo_lists(board_id, identity=identity)
