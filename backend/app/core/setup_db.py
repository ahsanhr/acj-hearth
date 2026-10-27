import asyncio

from app.core.database import db, close_database_connection


async def setup_database(database=None):
    database = db if database is None else database
    # Never silently expose unmigrated accounts with case-sensitive identities or
    # the old scaffold's password fields. See README.md before migrating data.
    async for user in database.users.find({}, {
        "email": 1, "password_hash": 1, "disabled": 1, "email_verified": 1,
        "auth_version": 1, "auth_serial": 1,
    }):
        email = user.get("email")
        if (
            not isinstance(email, str) or email != email.strip().casefold()
            or not isinstance(user.get("password_hash"), str)
            or not user["password_hash"].startswith("$argon2id$")
            or type(user.get("disabled")) is not bool
            or type(user.get("email_verified")) is not bool
            or type(user.get("auth_version")) is not int
            or type(user.get("auth_serial")) is not int
        ):
            raise RuntimeError("Existing users require authentication migration; see README.md")
    if await database.users.find_one({"password": {"$exists": True}}, {"_id": 1}):
        raise RuntimeError("Remove legacy password fields after migration; see README.md")
    await database.users.create_index("email", unique=True)
    # Registration no longer requires usernames; retain uniqueness only when present.
    indexes = await database.users.index_information()
    if "username_1" in indexes and not indexes["username_1"].get("partialFilterExpression"):
        await database.users.drop_index("username_1")
    await database.users.create_index(
        "username", unique=True, partialFilterExpression={"username": {"$type": "string"}}
    )
    await database.sessions.create_index("session_id", unique=True)
    await database.sessions.create_index("refresh_token_hash", unique=True)
    await database.sessions.create_index([("user_id", 1), ("created_at", 1), ("session_id", 1)])
    await database.sessions.create_index("expires_at", expireAfterSeconds=0)

    await database["todo_lists"].create_index(
        [("boardID", 1), ("ownerID", 1)],
        unique=True
    )

    print("Database indexes created successfully!")


async def main():
    try:
        await setup_database()
    finally:
        await close_database_connection()


if __name__ == "__main__":
    asyncio.run(main())