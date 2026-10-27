from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.database import db
from app.schemas.todo_list import TodoListCreate, TodoListUpdate
from app.services.auth import AuthError
from app.services.resources import (
    ResourceAccess,
    parse_changes,
    parse_id,
    public_document,
    require_list_manager,
)


async def create_todo_list(
    board_id: str, todo_list: TodoListCreate, *, identity, database=None
):
    board_id = parse_id(board_id)
    database = db if database is None else database
    access = ResourceAccess(database)
    data = {
        "_id": ObjectId(),
        "boardID": board_id,
        **todo_list.model_dump(),
        "tasks": [],
        "messages": [],
    }

    async def create(tx):
        actor = await access.actor(identity, tx)
        board = await access.board(board_id, actor, tx)
        if data["ownerID"] != actor:
            raise AuthError(403, "forbidden", "Create lists only for your own account.")
        if actor not in board["members"]:
            raise AuthError(403, "forbidden", "Board membership is required.")
        await database.todo_lists.insert_one(dict(data), session=tx)
        return public_document(data)

    try:
        return await access.auth.transaction(create)
    except DuplicateKeyError as exc:
        raise AuthError(
            409, "list_exists", "User already has a to-do list in this board."
        ) from exc


async def get_board_todo_lists(board_id: str, *, identity, database=None):
    board_id = parse_id(board_id)
    database = db if database is None else database
    access = ResourceAccess(database)
    actor = await access.actor(identity, write=False)
    await access.board(board_id, actor, write=False)
    return [
        public_document(row)
        async for row in database.todo_lists.find({"boardID": board_id})
    ]


async def update_todo_list(list_id, changes, *, identity, database=None):
    list_id = parse_id(list_id)
    database = db if database is None else database
    access = ResourceAccess(database)
    payload = parse_changes(TodoListUpdate, changes)
    fields = payload.model_dump()

    async def update(tx):
        actor = await access.actor(identity, tx)
        todo_list, board = await access.todo_list(list_id, actor, tx)
        require_list_manager(board, todo_list, actor)
        await database.todo_lists.update_one(
            {"_id": list_id}, {"$set": fields}, session=tx
        )
        return public_document({**todo_list, **fields})

    return await access.auth.transaction(update)
