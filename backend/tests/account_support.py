"""Shared account contract fixtures; all persisted state uses the real replica set."""

import asyncio
from contextvars import ContextVar
from copy import deepcopy

import httpx
from app.api.v1.endpoints.auth import COOKIE_NAME
from app.core.security import utcnow
from bson import ObjectId
from pymongo.asynchronous.collection import AsyncCollection

from tests.auth_support import PASSWORD, call

USERS = "/api/v1/users"
ME = f"{USERS}/me"
NEW_PASSWORD = "another long password!2"
PUBLIC_FIELDS = {"id", "name", "email", "email_verified"}
VALIDATION_ERROR = {
    "error": {"code": "validation_error", "message": "Invalid request fields."}
}
COLLECTIONS = ("users", "sessions", "boards", "todo_lists", "tasks", "messages")


def create_account(http, db, email="alice@example.com", password=PASSWORD):
    response = http.post(USERS, json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    login = http.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    user = call(http, db.users.find_one, {"_id": ObjectId(response.json()["id"])})
    return {
        "user": user,
        "public": response.json(),
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
        "refresh": http.cookies.get(COOKIE_NAME),
        "password": password,
    }


def mutate(http, method="PATCH", payload=None, account=None):
    return http.request(
        method,
        ME,
        json=payload,
        headers=account["headers"] if account else {},
    )


def service_identity(http, db, account):
    session = call(http, db.sessions.find_one, {"user_id": account["user"]["_id"]})
    return account["user"], session


def snapshot(http, db):
    async def read_all():
        return {
            name: await db[name].find({}).sort("_id", 1).to_list(length=None)
            for name in COLLECTIONS
        }

    return deepcopy(call(http, read_all))


def public_response(response, status=200):
    assert response.status_code == status, response.text
    assert response.headers.get("cache-control") == "no-store"
    data = response.json()
    assert set(data) == PUBLIC_FIELDS
    assert ObjectId.is_valid(data["id"])
    assert isinstance(data["name"], str)
    assert isinstance(data["email"], str)
    assert type(data["email_verified"]) is bool
    return data


def cleared_cookie(response):
    cookie = response.headers.get("set-cookie", "")
    assert f"{COOKIE_NAME}=" in cookie
    assert "Max-Age=0" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie


def seed_graph(http, db, owner, other):
    """Owned cascade plus surviving conversation authored by both accounts.

    Real IDs and canonical BSON references deliberately bypass resource creation
    so cleanup tests isolate deletion, not yet-unimplemented resource validators.
    """
    uid, oid = owner["user"]["_id"], other["user"]["_id"]
    owned, surviving = ObjectId(), ObjectId()
    owned_list, orphan_list, other_list = ObjectId(), ObjectId(), ObjectId()
    owned_task, surviving_task = ObjectId(), ObjectId()
    cascade_message, deleted_message, reply = ObjectId(), ObjectId(), ObjectId()
    now = utcnow()
    # BSON datetimes have millisecond precision; compare persisted metadata
    # against fixtures at the same precision rather than Python microseconds.
    now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    documents = {
        "boards": [
            {
                "_id": owned,
                "boardName": "owned",
                "createdBy": uid,
                "members": [uid, oid],
                "mutation_serial": 0,
            },
            {
                "_id": surviving,
                "boardName": "surviving",
                "createdBy": oid,
                "members": [oid, uid],
                "mutation_serial": 0,
            },
        ],
        "todo_lists": [
            {"_id": owned_list, "boardID": owned, "ownerID": oid, "title": "cascade"},
            {
                "_id": orphan_list,
                "boardID": surviving,
                "ownerID": uid,
                "title": "retain",
            },
            {"_id": other_list, "boardID": surviving, "ownerID": oid, "title": "other"},
        ],
        "tasks": [
            {
                "_id": owned_task,
                "listID": owned_list,
                "title": "cascade",
                "completed": False,
            },
            {
                "_id": surviving_task,
                "listID": orphan_list,
                "title": "keep",
                "completed": False,
            },
        ],
        "messages": [
            {
                "_id": cascade_message,
                "listID": owned_list,
                "userID": oid,
                "message": "other user on deleted board",
                "createdAt": now,
            },
            {
                "_id": deleted_message,
                "listID": orphan_list,
                "userID": uid,
                "message": "private original content",
                "createdAt": now,
            },
            {
                "_id": reply,
                "listID": orphan_list,
                "userID": oid,
                "message": "visible reply",
                "createdAt": now,
                "replyTo": deleted_message,
            },
        ],
    }

    async def insert():
        for collection, rows in documents.items():
            await db[collection].insert_many(deepcopy(rows))

    call(http, insert)
    return {
        "owned": owned,
        "surviving": surviving,
        "owned_list": owned_list,
        "orphan_list": orphan_list,
        "other_list": other_list,
        "owned_task": owned_task,
        "surviving_task": surviving_task,
        "cascade_message": cascade_message,
        "deleted_message": deleted_message,
        "reply": reply,
        "documents": documents,
    }


WRITE_METHODS = (
    "insert_one",
    "insert_many",
    "update_one",
    "update_many",
    "replace_one",
    "find_one_and_update",
    "find_one_and_delete",
    "delete_one",
    "delete_many",
    "bulk_write",
)


def intercept_writes(monkeypatch, database_name, hook):
    """Run hook after the actual write, while its transaction is still open."""
    for name in WRITE_METHODS:
        original = getattr(AsyncCollection, name)

        async def wrapped(collection, *args, _name=name, _original=original, **kwargs):
            result = await _original(collection, *args, **kwargs)
            if collection.database.name == database_name:
                await hook(collection.name, _name, args, kwargs)
            return result

        monkeypatch.setattr(AsyncCollection, name, wrapped)


def transaction_writes(monkeypatch, database_name):
    """Record actual writes and require a live MongoDB transaction for each."""
    writes = []

    async def record(collection, method, args, kwargs):
        session = kwargs.get("session")
        assert session is not None and session.in_transaction, (collection, method)
        writes.append((collection, repr(session.session_id), session._transaction_id))

    intercept_writes(monkeypatch, database_name, record)
    return writes


def assert_one_transaction(writes, collections):
    assert {collection for collection, _, _ in writes} >= set(collections)
    assert len({(sid, tid) for _, sid, tid in writes}) == 1


REQUEST_TIMEOUT = 20


race_request = ContextVar("account_race_request", default=False)


async def request(app, method, path, *, payload=None, headers=None, gated=False):
    token = race_request.set(gated)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.example.com",
            timeout=REQUEST_TIMEOUT,
        ) as client:
            return await client.request(
                method,
                path,
                json=payload,
                headers={"Origin": "https://app.example.com", **(headers or {})},
            )
    finally:
        race_request.reset(token)


def gate_first_user_read(monkeypatch, db_name):
    """Pause after an old account snapshot is read, before mutation checks.

    ContextVar survives Starlette middleware task boundaries. No sleeps are used
    to guess when a request is authenticated.
    """
    original = AsyncCollection.find_one
    waiting, proceed = asyncio.Event(), asyncio.Event()
    hit = False

    async def gated(collection, *args, **kwargs):
        nonlocal hit
        result = await original(collection, *args, **kwargs)
        if (
            race_request.get()
            and not hit
            and collection.database.name == db_name
            and collection.name == "users"
            and result
            and kwargs.get("session") is None
        ):
            hit = True
            waiting.set()
            await asyncio.wait_for(proceed.wait(), timeout=REQUEST_TIMEOUT)
        return result

    monkeypatch.setattr(AsyncCollection, "find_one", gated)
    return waiting, proceed
