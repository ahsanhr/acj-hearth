"""Board regressions using canonical IDs and authenticated, real transactions."""

import asyncio

import pytest
from app.services.auth import AuthError
from app.services.board import update_board

from tests.account_support import (
    REQUEST_TIMEOUT,
    create_account,
    request,
    service_identity,
    snapshot,
)
from tests.auth_support import PASSWORD, call


@pytest.mark.parametrize("include_owner", [False, True])
def test_board_creation_deduplicates_members_and_scopes_reads(
    api, account, include_owner
):
    http, db = api
    other = create_account(http, db, "bob@example.com")
    uid, oid = account["user"]["_id"], other["user"]["_id"]
    members = [str(oid)] + ([str(uid), str(uid)] if include_owner else [])
    response = http.post(
        "/api/v1/boards/",
        json={
            "boardName": "Group",
            "createdBy": str(uid),
            "members": members,
        },
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text
    assert set(response.json()["members"]) == {str(uid), str(oid)}
    for actor in [account, other]:
        boards = http.get("/api/v1/boards/", headers=actor["headers"])
        assert boards.status_code == 200
        assert [board["_id"] for board in boards.json()] == [response.json()["_id"]]
    outsider = create_account(http, db, "outsider@example.com")
    assert http.get("/api/v1/boards/", headers=outsider["headers"]).json() == []


def test_board_creator_cannot_select_another_owner(api, account):
    http, db = api
    other = create_account(http, db, "bob@example.com")
    before = snapshot(http, db)
    response = http.post(
        "/api/v1/boards/",
        json={
            "boardName": "Not mine",
            "createdBy": str(other["user"]["_id"]),
        },
        headers=account["headers"],
    )
    assert response.status_code == 403
    assert snapshot(http, db) == before


def test_board_updates_require_owner_and_preserve_canonical_relationships(
    api, account_graph
):
    http, db = api
    member, owner, graph = account_graph
    bid = graph["surviving"]
    before = call(http, db.boards.find_one, {"_id": bid})
    identity = service_identity(http, db, owner)
    updated = call(
        http,
        update_board,
        str(bid),
        {"boardName": "Renamed"},
        identity=identity,
        database=db,
    )
    assert updated["boardName"] == "Renamed"
    assert (
        call(http, db.boards.find_one, {"_id": bid})["mutation_serial"]
        == before["mutation_serial"] + 1
    )
    for changes, actor, status in [
        ({"createdBy": str(member["user"]["_id"])}, owner, 422),
        ({"boardName": "unauthorized"}, member, 403),
    ]:
        before = snapshot(http, db)
        with pytest.raises(AuthError) as error:
            call(
                http,
                update_board,
                str(bid),
                changes,
                identity=service_identity(http, db, actor),
                database=db,
            )
        assert error.value.status == status
        assert snapshot(http, db) == before


def test_membership_update_racing_cleanup_cannot_restore_deleted_member(
    api, account_graph
):
    http, db = api
    account, owner, graph = account_graph
    identity = service_identity(http, db, owner)

    async def race():
        return await asyncio.wait_for(
            asyncio.gather(
                update_board(
                    str(graph["surviving"]),
                    {
                        "members": [
                            str(owner["user"]["_id"]),
                            str(account["user"]["_id"]),
                        ],
                    },
                    identity=identity,
                    database=db,
                ),
                request(
                    http.app,
                    "DELETE",
                    "/api/v1/users/me",
                    payload={"current_password": PASSWORD},
                    headers=account["headers"],
                ),
                return_exceptions=True,
            ),
            timeout=REQUEST_TIMEOUT,
        )

    changed, deleted = call(http, race)
    assert not isinstance(deleted, BaseException), repr(deleted)
    assert deleted.status_code == 204, deleted.text
    if isinstance(changed, BaseException):
        assert isinstance(changed, AuthError), repr(changed)
        assert changed.status in (401, 422, 503)
    board = call(http, db.boards.find_one, {"_id": graph["surviving"]})
    assert board["members"] == [owner["user"]["_id"]]
