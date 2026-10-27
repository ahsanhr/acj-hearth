"""Shared account/board transaction coordination for relationship writes.

Always touch accounts (sorted) before boards (sorted), then mutate descendants.
A board counter creates a write conflict with account deletion by any member.
"""

from bson import ObjectId
from pydantic import ValidationError
from pymongo import ReturnDocument

from app.models.base import object_id
from app.services.auth import AuthError, AuthService, unauthorized


def parse_id(value):
    try:
        return object_id(value)
    except ValueError as exc:
        raise AuthError(400, "invalid_id", "Invalid resource identifier.") from exc


def parse_changes(schema, value):
    try:
        return value if isinstance(value, schema) else schema.model_validate(value)
    except ValidationError:
        raise AuthError(422, "validation_error", "Invalid request fields.") from None


def public_document(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {
            key: public_document(item)
            for key, item in value.items()
            if key != "mutation_serial"
        }
    if isinstance(value, list):
        return [public_document(item) for item in value]
    return value


def require_list_manager(board, todo_list, actor):
    if actor not in {board["createdBy"], todo_list.get("ownerID")}:
        raise AuthError(
            403, "forbidden", "Only the list or board owner can manage this list."
        )


class ResourceAccess:
    def __init__(self, database):
        self.db = database
        self.auth = AuthService(database)

    async def actor(self, identity, tx=None, *, referenced_users=(), write=True):
        if not identity or not identity[1]:
            raise unauthorized()
        user, session = identity
        uid = user["_id"]
        # New account references must serialize with deletion of those accounts.
        for target in sorted({uid, *referenced_users}):
            conditions = {"auth_version": user["auth_version"]} if target == uid else {}
            if write:
                active = await self.auth.touch_user(target, tx, **conditions)
            else:
                active = await self.db.users.find_one(
                    {"_id": target, "disabled": False, **conditions},
                    session=tx,
                )
            if not active:
                if target == uid:
                    raise unauthorized()
                raise AuthError(
                    422, "invalid_member", "Referenced account is not active."
                )
        await self.auth.require_session(uid, session["session_id"], tx)
        return uid

    async def board(self, board_id, actor, tx=None, *, write=True):
        if write:
            board = await self.db.boards.find_one_and_update(
                {"_id": board_id},
                {"$inc": {"mutation_serial": 1}},
                return_document=ReturnDocument.AFTER,
                session=tx,
            )
        else:
            board = await self.db.boards.find_one({"_id": board_id}, session=tx)
        if board is None:
            raise AuthError(404, "board_not_found", "Board not found.")
        if actor != board["createdBy"] and actor not in board.get("members", []):
            raise AuthError(403, "forbidden", "Board membership is required.")
        return board

    async def todo_list(self, list_id, actor, tx=None, *, write=True):
        todo_list = await self.db.todo_lists.find_one({"_id": list_id}, session=tx)
        if todo_list is None:
            raise AuthError(404, "list_not_found", "To-do list not found.")
        board = await self.board(todo_list["boardID"], actor, tx, write=write)
        return todo_list, board
