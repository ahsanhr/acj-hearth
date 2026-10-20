from fastapi import APIRouter, status

from app.schemas.todo_list import TodoListCreate
from app.services.todo_list import create_todo_list, get_board_todo_lists

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_todo_list(board_id: str, todo_list: TodoListCreate):
    return await create_todo_list(board_id, todo_list)


@router.get("/")
async def get_todo_lists(board_id: str):
    return await get_board_todo_lists(board_id)