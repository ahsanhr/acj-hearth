"""Saved corkboard positions: strict input validation and list-manager access."""

import pytest
from app.api.deps import current_identity
from app.api.v1.api import api_router
from app.api.v1.endpoints import todo_lists
from app.schemas.todo_list import TodoListUpdate
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.support.accounts import create_account, snapshot


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"position": None},
        {"title": None},
        {"position": {"x": -1, "y": 0}},
        {"position": {"x": 5001, "y": 0}},
        {"position": {"x": 0, "y": 5001}},
        {"position": {"x": True, "y": 0}},
        {"position": {"x": 1.5, "y": 0}},
        {"position": {"x": "12", "y": 0}},
        {"position": {"x": 0}},
        {"position": {"x": 0, "y": 0, "z": 1}},
        {"ownerID": str(ObjectId())},
    ],
)
def test_position_schema_rejects_invalid_changes(changes):
    with pytest.raises(ValidationError):
        TodoListUpdate.model_validate(changes)


def test_position_schema_allows_partial_updates_without_erasing_title():
    position = {"x": 0, "y": 5000}
    assert TodoListUpdate(position=position).model_dump(exclude_unset=True) == {
        "position": position
    }
    assert TodoListUpdate(title="Renamed").model_dump(exclude_unset=True) == {
        "title": "Renamed"
    }


def test_position_schema_is_applied_to_api_route(monkeypatch):
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    identity = ({"_id": "verified-user"}, {"session_id": "verified-session"})
    app.dependency_overrides[current_identity] = lambda: identity
    calls = []

    async def update(list_id, changes, *, identity):
        calls.append((list_id, changes.model_dump(exclude_unset=True), identity))
        return {"_id": list_id, "position": changes.position.model_dump()}

    monkeypatch.setattr(todo_lists, "update_todo_list", update)
    with TestClient(app) as http:
        result = http.patch(
            "/api/v1/lists/list-1", json={"position": {"x": 10, "y": 20}}
        )
        assert result.status_code == 200, result.text
        assert calls == [("list-1", {"position": {"x": 10, "y": 20}}, identity)]
        assert (
            http.patch(
                "/api/v1/lists/list-1", json={"position": {"x": -1, "y": 20}}
            ).status_code
            == 422
        )
        assert len(calls) == 1


@pytest.mark.regression
def test_list_position_api_persists_for_list_and_board_owner(api, account_graph):
    http, _ = api
    member, owner, graph = account_graph
    path = f"/api/v1/lists/{graph['orphan_list']}"
    parent = f"/api/v1/boards/{graph['surviving']}/lists/"
    before = http.get(parent, headers=member["headers"]).json()
    original = next(row for row in before if row["_id"] == str(graph["orphan_list"]))
    # The member owns this list, and the board owner may also arrange it.
    for actor, position in [
        (member, {"x": 125, "y": 240}),
        (owner, {"x": 5000, "y": 0}),
    ]:
        response = http.patch(
            path, json={"position": position}, headers=actor["headers"]
        )
        assert response.status_code == 200, response.text
        assert response.json()["position"] == position
        assert response.json()["title"] == original["title"]
        listing = http.get(parent, headers=actor["headers"]).json()
        saved = next(row for row in listing if row["_id"] == original["_id"])
        assert saved["position"] == position


@pytest.mark.unhappy_path
def test_list_position_api_rejects_other_members_and_invalid_payload(
    api, account_graph
):
    http, db = api
    member, _, graph = account_graph
    # A member cannot arrange another member's list unless they own the board.
    # An outsider cannot arrange any list.
    outsider = create_account(http, db, "outsider@example.com")
    path = f"/api/v1/lists/{graph['orphan_list']}"
    before = snapshot(http, db)
    assert http.patch(path, json={"position": {"x": 1, "y": 2}}).status_code == 401
    response = http.patch(
        path, json={"position": {"x": 1, "y": 2}}, headers=outsider["headers"]
    )
    assert response.status_code == 403
    other_path = f"/api/v1/lists/{graph['other_list']}"
    assert (
        http.patch(
            other_path, json={"position": {"x": 1, "y": 2}}, headers=member["headers"]
        ).status_code
        == 403
    )
    assert (
        http.patch(
            path, json={"position": {"x": -1, "y": 2}}, headers=member["headers"]
        ).status_code
        == 422
    )
    assert snapshot(http, db) == before
