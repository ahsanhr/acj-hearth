import asyncio

from pydantic import ValidationError

from app.core.database import close_database_connection, db
from app.models.user import UserModel


async def setup_database(database=None):
    database = db if database is None else database
    # Development has no legacy-account migration path. Fail closed on invalid
    # stored accounts rather than silently accepting obsolete credentials.
    async for user in database.users.find({}):
        try:
            UserModel.model_validate(user)
        except ValidationError:
            raise RuntimeError(
                "Stored account does not match the canonical user model"
            ) from None
    obsolete_fields = {"firstName", "lastName", "userID", "username", "password"}
    for name, index in (await database.users.index_information()).items():
        if any(field in obsolete_fields for field, _ in index["key"]):
            await database.users.drop_index(name)
    await database.users.create_index("email", unique=True)
    await database.sessions.create_index("session_id", unique=True)
    await database.sessions.create_index("refresh_token_hash", unique=True)
    await database.sessions.create_index(
        [("user_id", 1), ("created_at", 1), ("session_id", 1)]
    )
    await database.sessions.create_index("expires_at", expireAfterSeconds=0)

    owner_keys = [("boardID", 1), ("ownerID", 1)]
    owner_filter = {"ownerID": {"$type": "objectId"}}
    for name, index in (await database.todo_lists.index_information()).items():
        if index["key"] == owner_keys and (
            not index.get("unique")
            or index.get("partialFilterExpression") != owner_filter
        ):
            await database.todo_lists.drop_index(name)
    await database.todo_lists.create_index(
        owner_keys,
        unique=True,
        partialFilterExpression=owner_filter,
    )
    await database.boards.create_index("createdBy")
    await database.boards.create_index("members")
    await database.todo_lists.create_index("boardID")
    await database.todo_lists.create_index("ownerID")
    await database.tasks.create_index("listID")
    await database.messages.create_index([("listID", 1), ("createdAt", 1)])
    await database.messages.create_index("userID")

    print("Database indexes created successfully!")


async def main():
    try:
        await setup_database()
    finally:
        await close_database_connection()


if __name__ == "__main__":
    asyncio.run(main())
