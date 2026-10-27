"""Authenticated task CRUD regressions against real parent/account state."""

import pytest
from bson import ObjectId

from tests.account_support import create_account, snapshot
from tests.auth_support import call


def test_create_and_read_task_preserves_date_and_relationship(api, account_graph):
    http, db = api
    account, _, graph = account_graph
    path = f"/api/v1/lists/{graph['orphan_list']}/tasks/"
    payload = {"title": "New task", "description": "Details", "dueDate": "2026-10-25"}
    response = http.post(path, json=payload, headers=account["headers"])
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["listID"] == str(graph["orphan_list"])
    assert task["completed"] is False
    assert all(task[field] == value for field, value in payload.items())
    listing = http.get(path, headers=account["headers"])
    assert listing.status_code == 200
    assert {row["_id"] for row in listing.json()} == {
        task["_id"],
        str(graph["surviving_task"]),
    }
    assert (
        call(http, db.tasks.find_one, {"_id": ObjectId(task["_id"])})["listID"]
        == graph["orphan_list"]
    )


@pytest.mark.parametrize(
    "changes", [{"title": "Changed"}, {"completed": True}, {"dueDate": None}]
)
def test_partial_task_updates_preserve_untouched_fields(api, account_graph, changes):
    http, db = api
    account, _, graph = account_graph
    tid = graph["surviving_task"]
    before = call(http, db.tasks.find_one, {"_id": tid})
    counter = call(http, db.boards.find_one, {"_id": graph["surviving"]})[
        "mutation_serial"
    ]
    response = http.patch(
        f"/api/v1/tasks/{tid}", json=changes, headers=account["headers"]
    )
    assert response.status_code == 200, response.text
    after = call(http, db.tasks.find_one, {"_id": tid})
    assert after == {**before, **changes}
    assert response.json()["_id"] == str(tid)
    assert (
        call(http, db.boards.find_one, {"_id": graph["surviving"]})["mutation_serial"]
        == counter + 1
    )


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
@pytest.mark.parametrize(
    "task_id,status", [("invalid-id", 400), (str(ObjectId()), 404)]
)
def test_task_mutations_reject_invalid_or_missing_targets(
    api, account, method, task_id, status
):
    http, db = api
    before = snapshot(http, db)
    response = http.request(
        method,
        f"/api/v1/tasks/{task_id}",
        headers=account["headers"],
        **({"json": {"title": "No upsert"}} if method == "PATCH" else {}),
    )
    assert response.status_code == status, response.text
    assert snapshot(http, db) == before


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
@pytest.mark.parametrize("actor", ["missing", "outsider"])
def test_task_mutations_require_live_membership(api, account_graph, method, actor):
    http, db = api
    _, _, graph = account_graph
    headers = (
        create_account(http, db, "outsider@example.com")["headers"]
        if actor == "outsider"
        else {}
    )
    before = snapshot(http, db)
    response = http.request(
        method,
        f"/api/v1/tasks/{graph['surviving_task']}",
        headers=headers,
        **({"json": {"title": "Forbidden"}} if method == "PATCH" else {}),
    )
    assert response.status_code == (403 if actor == "outsider" else 401), response.text
    assert snapshot(http, db) == before


def test_task_deletion_cleans_cached_reference_in_same_transaction(api, account_graph):
    http, db = api
    account, _, graph = account_graph
    tid = graph["surviving_task"]
    call(
        http,
        db.todo_lists.update_one,
        {"_id": graph["orphan_list"]},
        {"$set": {"tasks": [tid]}},
    )
    counter = call(http, db.boards.find_one, {"_id": graph["surviving"]})[
        "mutation_serial"
    ]
    response = http.delete(f"/api/v1/tasks/{tid}", headers=account["headers"])
    assert response.status_code == 200, response.text
    assert call(http, db.tasks.find_one, {"_id": tid}) is None
    assert (
        call(http, db.todo_lists.find_one, {"_id": graph["orphan_list"]})["tasks"] == []
    )
    assert (
        call(http, db.boards.find_one, {"_id": graph["surviving"]})["mutation_serial"]
        == counter + 1
    )


def test_task_update_cannot_reassign_parent_or_accept_invalid_fields(
    api, account_graph
):
    http, db = api
    account, _, graph = account_graph
    before = snapshot(http, db)
    for changes in [
        {"listID": str(graph["owned_list"])},
        {"title": None},
        {"completed": None},
    ]:
        response = http.patch(
            f"/api/v1/tasks/{graph['surviving_task']}",
            json=changes,
            headers=account["headers"],
        )
        assert response.status_code == 422, response.text
    assert snapshot(http, db) == before
