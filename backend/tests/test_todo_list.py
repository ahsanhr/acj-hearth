"""List ownership, canonical references, permissions, and retained containers."""

import pytest
from app.services.auth import AuthError
from app.services.board import update_board
from app.services.todo_list import update_todo_list
from bson import ObjectId

from tests.account_support import create_account, mutate, service_identity, snapshot
from tests.auth_support import PASSWORD, call


def test_create_read_and_duplicate_list_are_atomic(api, account_graph):
    http, db = api
    account, _, graph = account_graph
    path = f"/api/v1/boards/{graph['owned']}/lists/"
    payload = {"ownerID": str(account["user"]["_id"]), "title": "My tasks"}
    response = http.post(path, json=payload, headers=account["headers"])
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["boardID"] == str(graph["owned"])
    assert row["ownerID"] == payload["ownerID"]
    assert row["tasks"] == row["messages"] == []
    listing = http.get(path, headers=account["headers"])
    assert listing.status_code == 200
    assert {item["_id"] for item in listing.json()} == {
        row["_id"],
        str(graph["owned_list"]),
    }
    before = snapshot(http, db)
    assert http.post(path, json=payload, headers=account["headers"]).status_code == 409
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "board_id,status", [("invalid-id", 400), (str(ObjectId()), 404)]
)
def test_invalid_or_missing_list_parent_is_rejected(api, account, board_id, status):
    http, db = api
    before = snapshot(http, db)
    path = f"/api/v1/boards/{board_id}/lists/"
    response = http.post(
        path,
        json={"ownerID": str(account["user"]["_id"]), "title": "Fail"},
        headers=account["headers"],
    )
    assert response.status_code == status, response.text
    assert http.get(path, headers=account["headers"]).status_code == status
    assert snapshot(http, db) == before


def test_cannot_assign_list_to_another_member_or_read_unrelated_board(
    api, account_graph
):
    http, db = api
    account, other, graph = account_graph
    path = f"/api/v1/boards/{graph['owned']}/lists/"
    before = snapshot(http, db)
    response = http.post(
        path,
        json={"ownerID": str(other["user"]["_id"]), "title": "Not mine"},
        headers=account["headers"],
    )
    assert response.status_code == 403
    assert snapshot(http, db) == before
    outsider = create_account(http, db, "outsider@example.com")
    assert http.get(path, headers=outsider["headers"]).status_code == 403


def test_only_board_owner_manages_retained_ownerless_lists(api, account_graph):
    http, db = api
    account, owner, graph = account_graph
    response = mutate(
        http, method="DELETE", payload={"current_password": PASSWORD}, account=account
    )
    assert response.status_code == 204, response.text
    owner_identity = service_identity(http, db, owner)
    counter = call(http, db.boards.find_one, {"_id": graph["surviving"]})[
        "mutation_serial"
    ]
    result = call(
        http,
        update_todo_list,
        str(graph["orphan_list"]),
        {"title": "Managed by board owner"},
        identity=owner_identity,
        database=db,
    )
    assert result["title"] == "Managed by board owner" and result["ownerID"] is None
    assert (
        call(http, db.boards.find_one, {"_id": graph["surviving"]})["mutation_serial"]
        == counter + 1
    )
    member = create_account(http, db, "member@example.com")
    call(
        http,
        update_board,
        str(graph["surviving"]),
        {"members": [str(member["user"]["_id"])]},
        identity=owner_identity,
        database=db,
    )
    before = snapshot(http, db)
    with pytest.raises(AuthError) as error:
        call(
            http,
            update_todo_list,
            str(graph["orphan_list"]),
            {"title": "Forbidden"},
            identity=service_identity(http, db, member),
            database=db,
        )
    assert error.value.status == 403
    assert snapshot(http, db) == before
