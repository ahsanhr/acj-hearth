import os
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
from pymongo import AsyncMongoClient
import pytest

from app.core.config import Settings
from app.main import create_app
from app.services import board, todo_list


@pytest.fixture
def auth_settings():
    return Settings(
        _env_file=None, AUTH_SIGNING_SECRET=SecretStr("a" * 48),
        AUTH_ALLOWED_ORIGINS=["https://app.example.com"],
    )


@pytest.fixture
def api(auth_settings, monkeypatch):
    uri = os.environ.get("TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set TEST_MONGODB_URI to a disposable MongoDB replica set")
    mongo = AsyncMongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    database = mongo[f"hearth_test_{uuid4().hex}"]
    # Upstream resource services use module-level database references. Keep API
    # tests isolated from the configured development/production database.
    monkeypatch.setattr(board, "db", database)
    monkeypatch.setattr(todo_list, "db", database)
    application = create_app(auth_settings, database)
    with TestClient(application, base_url="https://api.example.com") as http:
        http.headers["Origin"] = "https://app.example.com"
        try:
            yield http, database
        finally:
            http.portal.call(mongo.drop_database, database.name)
