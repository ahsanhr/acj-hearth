"""Shared account contract fixtures; all persisted state uses the real replica set."""

from copy import deepcopy

from app.api.v1.endpoints.auth import COOKIE_NAME
from app.core.security import utcnow
from bson import ObjectId

from tests.test_auth_api import PASSWORD, call

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
