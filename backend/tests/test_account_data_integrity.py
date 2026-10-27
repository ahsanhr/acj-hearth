"""Account contracts: data integrity."""

from copy import deepcopy

import pytest
from app.api.v1.endpoints.auth import COOKIE_NAME
from app.core.setup_db import setup_database
from app.schemas.board import BoardCreate
from app.schemas.message import MessageUpdate
from app.schemas.user import (
    AccountPatch,
    PasswordConfirmation,
    Registration,
    UserPublic,
)
from app.services.auth import AuthError
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from tests.account_support import (
    ME,
    NEW_PASSWORD,
    PUBLIC_FIELDS,
    USERS,
    assert_one_transaction,
    cleared_cookie,
    create_account,
    mutate,
    public_response,
    service_identity,
    snapshot,
    transaction_writes,
)
from tests.auth_support import PASSWORD, call


def test_request_and_public_schemas_allow_only_agreed_fields():
    assert set(UserPublic.model_fields) == PUBLIC_FIELDS
    expected_inputs = {
        Registration: {"email", "password"},
        AccountPatch: {"name", "email", "new_password", "current_password"},
        PasswordConfirmation: {"current_password"},
        MessageUpdate: {"message"},
        BoardCreate: {"boardName", "createdBy", "members"},
    }
    for schema, fields in expected_inputs.items():
        assert set(schema.model_fields) == fields, schema.__name__
        assert schema.model_config["extra"] == "forbid", schema.__name__


def test_duplicate_email_rejects_entire_combined_patch(api, account):
    http, db = api
    create_account(http, db, "bob@example.com")
    before = snapshot(http, db)
    # Creation duplicates are covered by the account concurrency test. Protect
    # this distinct mutation path from persisting any part of a rejected update.
    response = mutate(
        http,
        payload={
            "email": " BOB@EXAMPLE.COM ",
            "name": "Must not persist",
            "new_password": NEW_PASSWORD,
            "current_password": PASSWORD,
        },
        account=account,
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == {
        "code": "email_exists",
        "message": "An account with this email already exists.",
    }
    assert snapshot(http, db) == before


def test_responses_and_logs_never_expose_secrets(api, account, caplog):
    http, _ = api
    caplog.set_level("DEBUG")
    secrets = [
        PASSWORD,
        NEW_PASSWORD,
        account["user"]["password_hash"],
        account["refresh"],
        account["headers"]["Authorization"].split()[1],
    ]
    responses = [
        http.get(ME, headers=account["headers"]),
        mutate(
            http,
            payload={"name": "Safe", "current_password": PASSWORD},
            account=account,
        ),
        mutate(
            http, payload={"name": "Safe", "current_password": "wrong"}, account=account
        ),
        mutate(
            http,
            payload={
                "name": None,
                "new_password": NEW_PASSWORD,
                "current_password": PASSWORD,
            },
            account=account,
        ),
    ]
    for response in responses:
        assert response.headers.get("cache-control") == "no-store"
        for secret in secrets:
            assert secret not in response.text
    for secret in secrets:
        assert secret not in caplog.text


def test_retired_routes_are_not_registered(api):
    http, db = api
    before = snapshot(http, db)
    for path in ["/api/v1/auth/register", "/api/v1/auth/password"]:
        response = http.post(
            path,
            json={
                "email": "alice@example.com",
                "password": PASSWORD,
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
            },
        )
        assert response.status_code in (404, 405), response.text
        assert path not in http.get("/openapi.json").json()["paths"]
    assert snapshot(http, db) == before


def test_delete_cascades_owned_boards_but_preserves_other_users_conversations(
    api, account_graph
):
    http, db = api
    account, other, graph = account_graph
    uid, oid = account["user"]["_id"], other["user"]["_id"]
    extra_login = http.post(
        "/api/v1/auth/login",
        json={"email": account["user"]["email"], "password": PASSWORD},
    )
    assert extra_login.status_code == 200
    extra_headers = {"Authorization": f"Bearer {extra_login.json()['access_token']}"}
    extra_refresh = http.cookies.get(COOKIE_NAME)
    other_sessions = call(http, db.sessions.find_one, {"user_id": oid})
    response = mutate(
        http, method="DELETE", payload={"current_password": PASSWORD}, account=account
    )
    assert response.status_code == 204, response.text
    assert response.content == b""
    assert response.headers.get("cache-control") == "no-store"
    cleared_cookie(response)
    assert call(http, db.users.find_one, {"_id": uid}) is None
    assert call(http, db.sessions.count_documents, {"user_id": uid}) == 0
    assert call(http, db.users.find_one, {"_id": oid}) == other["user"]
    assert (
        call(http, db.sessions.find_one, {"_id": other_sessions["_id"]})
        == other_sessions
    )
    for collection, identifier in [
        ("boards", graph["owned"]),
        ("todo_lists", graph["owned_list"]),
        ("tasks", graph["owned_task"]),
        ("messages", graph["cascade_message"]),
    ]:
        assert call(http, db[collection].find_one, {"_id": identifier}) is None
    board = call(http, db.boards.find_one, {"_id": graph["surviving"]})
    assert board["createdBy"] == oid
    assert board["members"] == [oid]
    assert board["mutation_serial"] > 0
    orphan = call(http, db.todo_lists.find_one, {"_id": graph["orphan_list"]})
    assert orphan["ownerID"] is None
    assert orphan["boardID"] == graph["surviving"]
    assert orphan["title"] == "retain"
    assert (
        call(http, db.tasks.find_one, {"_id": graph["surviving_task"]})
        == graph["documents"]["tasks"][1]
    )
    assert (
        call(http, db.todo_lists.find_one, {"_id": graph["other_list"]})
        == graph["documents"]["todo_lists"][2]
    )
    assert (
        call(http, db.messages.find_one, {"_id": graph["reply"]})
        == graph["documents"]["messages"][2]
    )
    tombstone = call(http, db.messages.find_one, {"_id": graph["deleted_message"]})
    original = graph["documents"]["messages"][1]
    assert tombstone["_id"] == original["_id"]
    assert tombstone["createdAt"] == original["createdAt"]
    assert tombstone["listID"] == original["listID"]
    assert tombstone.get("userID") is None
    assert tombstone["deleted"] is True
    assert tombstone.get("message") in (None, "", "message deleted")
    for secret in [
        str(uid),
        account["user"]["email"],
        account["user"]["name"],
        original["message"],
    ]:
        assert secret not in repr(tombstone)
    for headers in [account["headers"], extra_headers]:
        assert http.get(ME, headers=headers).status_code == 401
        assert (
            mutate(
                http,
                payload={"name": "resurrect", "current_password": PASSWORD},
                account={"headers": headers},
            ).status_code
            == 401
        )
    for refresh in [account["refresh"], extra_refresh]:
        assert (
            http.post(
                "/api/v1/auth/refresh", headers={"Cookie": f"{COOKIE_NAME}={refresh}"}
            ).status_code
            == 401
        )
    assert (
        http.post(
            "/api/v1/auth/login",
            json={"email": account["user"]["email"], "password": PASSWORD},
        ).status_code
        == 401
    )
    # A recreated email is a new identity, not a recovery of the deleted one.
    response = http.post(
        USERS, json={"email": " ALICE@EXAMPLE.COM ", "password": PASSWORD}
    )
    replacement = public_response(response, 201)
    assert ObjectId(replacement["id"]) != uid
    assert (
        call(http, db.messages.find_one, {"_id": graph["deleted_message"]}) == tombstone
    )
    assert (
        call(http, db.boards.count_documents, {"members": ObjectId(replacement["id"])})
        == 0
    )


def test_multiple_deleted_list_owners_can_leave_anonymous_lists_on_same_board(
    api, account_graph
):
    http, db = api
    account, other, graph = account_graph
    third = create_account(http, db, "carol@example.com")
    uid = third["user"]["_id"]
    call(
        http,
        db.boards.update_one,
        {"_id": graph["surviving"]},
        {"$addToSet": {"members": uid}},
    )
    list_id = ObjectId()
    call(
        http,
        db.todo_lists.insert_one,
        {
            "_id": list_id,
            "boardID": graph["surviving"],
            "ownerID": uid,
            "title": "third",
        },
    )
    for departing in [account, third]:
        response = mutate(
            http,
            method="DELETE",
            payload={"current_password": PASSWORD},
            account=departing,
        )
        assert response.status_code == 204, response.text
    assert (
        call(
            http,
            db.todo_lists.count_documents,
            {"boardID": graph["surviving"], "ownerID": None},
        )
        == 2
    )
    assert http.get(ME, headers=other["headers"]).status_code == 200


def test_deleting_a_user_without_related_data_does_not_touch_unrelated_board(
    api, account
):
    http, db = api
    other = create_account(http, db, "bob@example.com")
    board = {
        "_id": ObjectId(),
        "boardName": "unrelated",
        "createdBy": other["user"]["_id"],
        "members": [other["user"]["_id"]],
        "mutation_serial": 0,
    }
    call(http, db.boards.insert_one, deepcopy(board))
    response = mutate(
        http, method="DELETE", payload={"current_password": PASSWORD}, account=account
    )
    assert response.status_code == 204, response.text
    assert call(http, db.boards.find_one, {"_id": board["_id"]}) == board
    assert http.get(ME, headers=other["headers"]).status_code == 200


def test_email_unique_index_rejects_direct_duplicate_insert(api, account):
    http, db = api
    duplicate = {**account["user"], "_id": ObjectId()}
    with pytest.raises(DuplicateKeyError):
        call(http, db.users.insert_one, duplicate)
    assert (
        call(http, db.users.count_documents, {"email": account["user"]["email"]}) == 1
    )


def test_startup_removes_obsolete_username_index(api):
    http, db = api
    call(
        http,
        db.users.create_index,
        "username",
        unique=True,
        partialFilterExpression={"username": {"$type": "string"}},
    )
    call(http, setup_database, db)
    indexes = call(http, db.users.index_information)
    assert not any(
        any(field == "username" for field, _ in index["key"])
        for index in indexes.values()
    )
    assert any(
        index.get("unique") and index["key"] == [("email", 1)]
        for index in indexes.values()
    )


def test_list_owner_index_allows_null_but_not_duplicate_live_owner(api, account):
    http, db = api
    board_id, owner = ObjectId(), account["user"]["_id"]
    row = {"boardID": board_id, "ownerID": owner, "title": "first"}
    call(http, db.todo_lists.insert_one, deepcopy(row))
    with pytest.raises(DuplicateKeyError):
        call(http, db.todo_lists.insert_one, deepcopy(row))
    for title in ["anonymous one", "anonymous two"]:
        call(http, db.todo_lists.insert_one, {**row, "ownerID": None, "title": title})
    assert (
        call(
            http, db.todo_lists.count_documents, {"boardID": board_id, "ownerID": None}
        )
        == 2
    )


def test_board_creation_stores_objectid_relationships_and_initializes_counter(
    api, account
):
    http, db = api
    other = create_account(http, db, "bob@example.com")
    response = http.post(
        "/api/v1/boards/",
        headers=account["headers"],
        json={
            "boardName": "canonical",
            "createdBy": str(account["user"]["_id"]),
            "members": [str(other["user"]["_id"])],
        },
    )
    assert response.status_code == 201, response.text
    board = call(http, db.boards.find_one, {"boardName": "canonical"})
    assert isinstance(board["_id"], ObjectId)
    assert board["createdBy"] == account["user"]["_id"]
    assert set(board["members"]) == {account["user"]["_id"], other["user"]["_id"]}
    assert all(isinstance(member, ObjectId) for member in board["members"])
    assert type(board["mutation_serial"]) is int and board["mutation_serial"] == 0
    assert response.json()["createdBy"] == str(account["user"]["_id"])


@pytest.mark.parametrize("resource", ["list", "task"])
def test_descendant_creation_touches_board_in_same_transaction(
    api, account_graph, monkeypatch, resource
):
    http, db = api
    account, other, graph = account_graph
    uid = account["user"]["_id"]
    if resource == "list":
        # No list on owned board currently belongs to the board owner.
        path = f"/api/v1/boards/{graph['owned']}/lists/"
        payload = {"ownerID": str(uid), "title": "new list"}
        collection = "todo_lists"
    else:
        path = f"/api/v1/lists/{graph['orphan_list']}/tasks/"
        payload = {"title": "new task"}
        collection = "tasks"
    writes = transaction_writes(monkeypatch, db.name)
    response = http.post(path, json=payload, headers=account["headers"])
    assert response.status_code == 201, response.text
    assert_one_transaction(writes, {"users", "boards", collection})
    identifier = graph["owned"] if resource == "list" else graph["surviving"]
    assert call(http, db.boards.find_one, {"_id": identifier})["mutation_serial"] > 0
    if resource == "list":
        record = call(http, db.todo_lists.find_one, {"title": "new list"})
        assert record["ownerID"] == uid
        assert isinstance(record["boardID"], ObjectId)
    else:
        assert isinstance(
            call(http, db.tasks.find_one, {"title": "new task"})["listID"], ObjectId
        )


def test_tombstones_are_anonymous_and_cannot_be_restored(api, account_graph):
    from app.services.message import get_list_messages, public_message, update_message

    http, db = api
    account, owner, graph = account_graph
    identity = service_identity(http, db, owner)
    # Cached content and author fields must be physically removed, not just hidden.
    call(
        http,
        db.messages.update_one,
        {"_id": graph["deleted_message"]},
        {
            "$set": {
                "authorName": "Alice",
                "authorEmail": account["user"]["email"],
                "attachment": "private",
            },
        },
    )
    response = mutate(
        http,
        method="DELETE",
        payload={"current_password": account["password"]},
        account=account,
    )
    assert response.status_code == 204, response.text
    tombstone = call(http, db.messages.find_one, {"_id": graph["deleted_message"]})
    assert not {"authorName", "authorEmail", "attachment"} & tombstone.keys()
    with pytest.raises(AuthError) as error:
        call(
            http,
            update_message,
            str(graph["deleted_message"]),
            {"message": "restore content"},
            identity=identity,
            database=db,
        )
    assert error.value.status == 409
    assert (
        call(http, db.messages.find_one, {"_id": graph["deleted_message"]}) == tombstone
    )
    messages = call(
        http,
        get_list_messages,
        str(graph["orphan_list"]),
        identity=identity,
        database=db,
    )
    deleted = next(
        row for row in messages if row["id"] == str(graph["deleted_message"])
    )
    assert (
        deleted["author"] == "DELETED-USER" and deleted["message"] == "message deleted"
    )
    assert deleted["userID"] is None
    assert (
        next(row for row in messages if row["id"] == str(graph["reply"]))["message"]
        == "visible reply"
    )
    # Even a stale/corrupt cache cannot override the deleted-state serializer.
    assert (
        public_message({**tombstone, "message": "cached secret"}, "Alice")["message"]
        == "message deleted"
    )


@pytest.mark.parametrize(
    "operation",
    [
        "message_create",
        "message_edit",
        "task_edit",
        "task_delete",
        "list_edit",
        "board_edit",
    ],
)
def test_content_mutations_share_account_and_board_transaction(
    api, account_graph, monkeypatch, operation
):
    from app.services import board, message, task, todo_list

    http, db = api
    account, owner, graph = account_graph
    cases = {
        "message_create": (
            message.create_message,
            "orphan_list",
            {"message": "new"},
            "messages",
        ),
        "message_edit": (
            message.update_message,
            "deleted_message",
            {"message": "edited"},
            "messages",
        ),
        "task_edit": (task.update_task, "surviving_task", {"title": "edited"}, "tasks"),
        "task_delete": (task.delete_task, "surviving_task", None, "tasks"),
        "list_edit": (
            todo_list.update_todo_list,
            "orphan_list",
            {"title": "edited"},
            "todo_lists",
        ),
        "board_edit": (
            board.update_board,
            "surviving",
            {"boardName": "edited"},
            "boards",
        ),
    }
    handler, target, changes, collection = cases[operation]
    identity = service_identity(
        http, db, owner if operation == "board_edit" else account
    )
    writes = transaction_writes(monkeypatch, db.name)
    args = (str(graph[target]),) if changes is None else (str(graph[target]), changes)
    call(http, handler, *args, identity=identity, database=db)
    assert_one_transaction(writes, {"users", "boards", collection})
    assert (
        call(http, db.boards.find_one, {"_id": graph["surviving"]})["mutation_serial"]
        > 0
    )


def test_every_cleanup_write_uses_the_same_transaction(api, account_graph, monkeypatch):
    http, db = api
    account, _, _ = account_graph
    writes = transaction_writes(monkeypatch, db.name)
    response = mutate(
        http, method="DELETE", payload={"current_password": PASSWORD}, account=account
    )
    assert response.status_code == 204, response.text
    assert_one_transaction(
        writes, {"users", "sessions", "boards", "todo_lists", "tasks", "messages"}
    )


def test_message_edits_never_upsert_missing_targets(api, account_graph):
    from app.services.message import update_message

    http, db = api
    _, owner, _ = account_graph
    missing = ObjectId()
    before = snapshot(http, db)
    with pytest.raises(AuthError) as error:
        call(
            http,
            update_message,
            str(missing),
            {"message": "not created"},
            identity=service_identity(http, db, owner),
            database=db,
        )
    assert error.value.status == 404
    assert call(http, db.messages.find_one, {"_id": missing}) is None
    assert snapshot(http, db) == before
