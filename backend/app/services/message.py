"""Authenticated message writes; no invitation or UI workflow is implemented."""

from bson import ObjectId
from pymongo import ReturnDocument

from app.core.database import db
from app.core.security import utcnow
from app.schemas.message import MessageCreate, MessageUpdate
from app.services.auth import AuthError
from app.services.resources import ResourceAccess, parse_changes, parse_id


def public_message(message, author=None):
    # Never trust cached text/author fields once a message has been deleted.
    deleted = bool(message.get("deleted")) or author is None
    return {
        "id": str(message["_id"]),
        "listID": str(message["listID"]),
        "userID": None if deleted else str(message["userID"]),
        "author": "DELETED-USER" if deleted else author,
        "message": "message deleted" if deleted else message["message"],
        "createdAt": message["createdAt"],
        "deleted": deleted,
        "replyTo": str(message["replyTo"]) if message.get("replyTo") else None,
    }


async def create_message(list_id, changes, *, identity, database=None):
    database = db if database is None else database
    list_id = parse_id(list_id)
    payload = parse_changes(MessageCreate, changes)
    access = ResourceAccess(database)

    async def create(tx):
        actor = await access.actor(identity, tx)
        await access.todo_list(list_id, actor, tx)
        if payload.replyTo is not None and not await database.messages.find_one(
            {"_id": payload.replyTo, "listID": list_id},
            session=tx,
        ):
            raise AuthError(
                404, "message_not_found", "Reply target not found in this conversation."
            )
        data = {
            "_id": ObjectId(),
            "listID": list_id,
            "userID": actor,
            "createdAt": utcnow(),
            "deleted": False,
            **payload.model_dump(),
        }
        await database.messages.insert_one(data, session=tx)
        author = await database.users.find_one({"_id": actor}, {"name": 1}, session=tx)
        return public_message(data, author["name"])

    return await access.auth.transaction(create)


async def update_message(message_id, changes, *, identity, database=None):
    database = db if database is None else database
    message_id = parse_id(message_id)
    payload = parse_changes(MessageUpdate, changes)
    access = ResourceAccess(database)

    async def update(tx):
        actor = await access.actor(identity, tx)
        message = await database.messages.find_one({"_id": message_id}, session=tx)
        if message is None:
            raise AuthError(404, "message_not_found", "Message not found.")
        await access.todo_list(message["listID"], actor, tx)
        if message.get("deleted"):
            raise AuthError(
                409, "message_deleted", "Deleted messages cannot be restored."
            )
        if message["userID"] != actor:
            raise AuthError(403, "forbidden", "Only the author can edit a message.")
        updated = await database.messages.find_one_and_update(
            {"_id": message_id, "userID": actor, "deleted": {"$ne": True}},
            {"$set": {"message": payload.message}},
            return_document=ReturnDocument.AFTER,
            session=tx,
        )
        if updated is None:
            raise AuthError(
                409, "message_deleted", "Deleted messages cannot be restored."
            )
        author = await database.users.find_one({"_id": actor}, {"name": 1}, session=tx)
        return public_message(updated, author["name"])

    return await access.auth.transaction(update)


async def get_list_messages(list_id, *, identity, database=None):
    database = db if database is None else database
    list_id = parse_id(list_id)
    access = ResourceAccess(database)
    actor = await access.actor(identity, write=False)
    await access.todo_list(list_id, actor, write=False)
    messages = (
        await database.messages.find({"listID": list_id})
        .sort(
            [("createdAt", 1), ("_id", 1)],
        )
        .to_list(length=None)
    )
    authors = {
        row["userID"]
        for row in messages
        if not row.get("deleted") and row.get("userID")
    }
    names = {
        user["_id"]: user["name"]
        async for user in database.users.find(
            {"_id": {"$in": list(authors)}},
            {"name": 1},
        )
    }
    return [public_message(row, names.get(row.get("userID"))) for row in messages]
