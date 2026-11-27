from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import current_identity
from app.schemas.todo_list import TodoListCreate, TodoListUpdate
from app.services.todo_list import (
    create_todo_list,
    get_board_todo_lists,
    update_todo_list,
)

router = APIRouter()
CurrentIdentity = Annotated[tuple, Depends(current_identity)]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_todo_list(
    board_id: str, todo_list: TodoListCreate, identity: CurrentIdentity
):
    return await create_todo_list(board_id, todo_list, identity=identity)


@router.get("/")
async def get_todo_lists(board_id: str, identity: CurrentIdentity):
    return await get_board_todo_lists(board_id, identity=identity)


async def edit_todo_list(
    list_id: str, changes: TodoListUpdate, identity: CurrentIdentity
):
    return await update_todo_list(list_id, changes, identity=identity)
