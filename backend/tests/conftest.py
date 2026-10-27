import os
from pathlib import Path
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.main import create_app
from app.services import board, task, todo_list
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pymongo import AsyncMongoClient


@pytest.fixture
def auth_settings():
    return Settings(
        _env_file=None,
        AUTH_SIGNING_SECRET=SecretStr("a" * 48),
        AUTH_ALLOWED_ORIGINS=["https://app.example.com"],
    )


@pytest.fixture
def account(api):
    from tests.support.accounts import create_account

    return create_account(*api)


@pytest.fixture
def account_graph(api, account):
    from tests.support.accounts import create_account, seed_graph

    http, db = api
    other = create_account(http, db, "bob@example.com")
    return account, other, seed_graph(http, db, account, other)


@pytest.fixture
def api(auth_settings, monkeypatch):
    uri = os.environ.get("TEST_MONGODB_URI") or dotenv_values(
        Path(__file__).resolve().parents[1] / ".env"
    ).get("TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set TEST_MONGODB_URI to a disposable MongoDB replica set")
    mongo = AsyncMongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    # Atlas limits database names to 38 bytes; retain 96 bits of randomness.
    database = mongo[f"hearth_test_{uuid4().hex[:24]}"]
    # Upstream resource services use module-level database references. Keep API
    # tests isolated from the configured development/production database.
    monkeypatch.setattr(board, "db", database)
    monkeypatch.setattr(todo_list, "db", database)
    monkeypatch.setattr(task, "db", database)
    application = create_app(auth_settings, database)
    with TestClient(application, base_url="https://api.example.com") as http:
        http.headers["Origin"] = "https://app.example.com"
        try:
            yield http, database
        finally:
            http.portal.call(mongo.drop_database, database.name)
