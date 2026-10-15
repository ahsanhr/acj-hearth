import certifi
from pymongo import AsyncMongoClient

from app.core.config import settings


client = AsyncMongoClient(
    settings.MONGODB_URI,
    tlsCAFile=certifi.where()
)

db = client[settings.MONGODB_DB_NAME]


async def check_database_connection():
    await client.admin.command("ping")
    return True


async def close_database_connection():
    await client.close()