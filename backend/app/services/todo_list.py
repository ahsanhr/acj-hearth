from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.core.database import db
from app.schemas.todo_list import TodoListCreate


async def create_todo_list(board_id: str, todo_list: TodoListCreate):
    try:
        board_object_id = ObjectId(board_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid board ID")

    board = await db["boards"].find_one({"_id": board_object_id})

    if board is None:
        raise HTTPException(status_code=404, detail="Board not found")

    if todo_list.ownerID not in board.get("members", []):
        raise HTTPException(
            status_code=403,
            detail="User is not a member of this board"
        )

    list_data = {
        "boardID": board_id,
        "ownerID": todo_list.ownerID,
        "title": todo_list.title,
        "tasks": [],
        "messages": []
    }

    try:
        result = await db["todo_lists"].insert_one(list_data)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="User already has a to-do list in this board"
        )

    list_data["_id"] = str(result.inserted_id)

    return list_data


async def get_board_todo_lists(board_id: str):
    try:
        board_object_id = ObjectId(board_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid board ID")

    board = await db["boards"].find_one({"_id": board_object_id})

    if board is None:
        raise HTTPException(status_code=404, detail="Board not found")

    todo_lists = []

    async for todo_list in db["todo_lists"].find({"boardID": board_id}):
        todo_list["_id"] = str(todo_list["_id"])
        todo_lists.append(todo_list)

    return todo_lists