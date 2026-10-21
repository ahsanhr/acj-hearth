import certifi
from pymongo import AsyncMongoClient

from app.core.config import settings


# Do not enable TLS implicitly for a local, non-TLS replica set.
_tls = (
    {"tlsCAFile": certifi.where()}
    if settings.MONGODB_URI.startswith("mongodb+srv://")
    or "tls=true" in settings.MONGODB_URI.lower()
    else {}
)
client = AsyncMongoClient(
    settings.MONGODB_URI, tz_aware=True, serverSelectionTimeoutMS=5000, **_tls
)

db = client[settings.MONGODB_DB_NAME]


async def check_database_connection():
    await client.admin.command("ping")
    return True


async def close_database_connection():
    await client.close()