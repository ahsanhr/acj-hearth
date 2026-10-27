"""Replica-set cleanup, isolation, tombstones, and email-reuse acceptance tests."""

from copy import deepcopy

import pytest
from app.api.v1.endpoints.auth import COOKIE_NAME
from app.core.setup_db import setup_database
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from tests.account_support import (
    ME,
    USERS,
    cleared_cookie,
    create_account,
    mutate,
    public_response,
)
from tests.test_auth_api import PASSWORD, call


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
