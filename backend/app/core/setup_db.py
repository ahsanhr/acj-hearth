import asyncio

from app.core.database import db, close_database_connection


async def setup_database():
    await db["users"].create_index("email", unique=True)
    await db["users"].create_index("username", unique=True)

    await db["todo_lists"].create_index(
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