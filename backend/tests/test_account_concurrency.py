"""Account contracts: concurrency."""

import asyncio

import pytest
from app.services.auth import AuthError

from tests.account_support import (
    ME,
    NEW_PASSWORD,
    REQUEST_TIMEOUT,
    USERS,
    create_account,
    gate_first_user_read,
    request,
    service_identity,
)
from tests.auth_support import PASSWORD, call


def test_concurrent_normalized_creations_have_one_winner(api):
    http, db = api

    async def race():
        return await asyncio.wait_for(
            asyncio.gather(
                *[
                    request(
                        http.app,
                        "POST",
                        USERS,
                        payload={"email": email, "password": PASSWORD},
                    )
                    for email in [" Race@EXAMPLE.com ", "race@example.com"]
                ]
            ),
            timeout=REQUEST_TIMEOUT,
        )

    responses = call(http, race)
    assert sorted(r.status_code for r in responses) == [201, 409], [
        r.text for r in responses
    ]
    duplicate = next(response for response in responses if response.status_code == 409)
    assert duplicate.json()["error"] == {
        "code": "email_exists",
        "message": "An account with this email already exists.",
    }
    assert call(http, db.users.count_documents, {"email": "race@example.com"}) == 1
    assert call(http, db.sessions.count_documents, {}) == 0


def test_concurrent_email_updates_have_one_winner_and_no_partial_loser(api, account):
    http, db = api
    other = create_account(http, db, "bob@example.com")

    async def race():
        return await asyncio.wait_for(
            asyncio.gather(
                *[
                    request(
                        http.app,
                        "PATCH",
                        ME,
                        payload={
                            "email": "same@example.com",
                            "name": f"winner-{i}",
                            "new_password": NEW_PASSWORD,
                            "current_password": PASSWORD,
                        },
                        headers=identity["headers"],
                    )
                    for i, identity in enumerate([account, other])
                ]
            ),
            timeout=REQUEST_TIMEOUT,
        )

    responses = call(http, race)
    assert sorted(r.status_code for r in responses) == [200, 409], [
        r.text for r in responses
    ]
    for index, identity in enumerate([account, other]):
        user = call(http, db.users.find_one, {"_id": identity["user"]["_id"]})
        count = call(http, db.sessions.count_documents, {"user_id": user["_id"]})
        if responses[index].status_code == 200:
            assert user["email"] == "same@example.com"
            assert user["name"] == f"winner-{index}"
            assert count == 0
        else:
            assert user == identity["user"]
            assert count == 1


@pytest.mark.parametrize(
    "pending,winner",
    [
        ("login", "password"),
        ("login", "email"),
        ("login", "delete"),
        ("patch", "password"),
        ("delete", "password"),
        ("patch", "delete"),
        ("delete", "delete"),
        ("patch", "revoke_session"),
        ("delete", "revoke_session"),
    ],
)
def test_stale_identity_or_confirmation_cannot_authorize_after_mutation(
    api, account, monkeypatch, pending, winner
):
    http, db = api

    async def race():
        waiting, proceed = gate_first_user_read(monkeypatch, db.name)
        if pending == "login":
            method, path = "POST", "/api/v1/auth/login"
            payload = {"email": "alice@example.com", "password": PASSWORD}
        else:
            method, path = ("PATCH" if pending == "patch" else "DELETE"), ME
            payload = {"current_password": PASSWORD}
            if pending == "patch":
                payload["name"] = "Must not persist"
        task = asyncio.create_task(
            request(
                http.app,
                method,
                path,
                payload=payload,
                headers=account["headers"],
                gated=True,
            )
        )
        try:
            await asyncio.wait_for(waiting.wait(), timeout=REQUEST_TIMEOUT)
            if winner != "revoke_session":
                changes = {
                    "password": {"new_password": NEW_PASSWORD},
                    "email": {"email": "changed@example.com"},
                    "delete": {},
                }[winner]
                deleting = winner == "delete"
                result = await request(
                    http.app,
                    "DELETE" if deleting else "PATCH",
                    ME,
                    payload={"current_password": PASSWORD, **changes},
                    headers=account["headers"],
                )
                assert result.status_code == (204 if deleting else 200), result.text
            else:
                service = http.app.state.auth_service
                session = await db.sessions.find_one(
                    {"user_id": account["user"]["_id"]}
                )
                await service.close_sessions(
                    account["user"]["_id"], session["session_id"]
                )
        finally:
            proceed.set()
            if not waiting.is_set():
                task.cancel()
        return await asyncio.wait_for(task, timeout=REQUEST_TIMEOUT)

    response = call(http, race)
    assert response.status_code == 401, response.text
    user = call(http, db.users.find_one, {"_id": account["user"]["_id"]})
    if winner == "delete":
        assert user is None
    elif pending != "login":
        assert user["name"] != "Must not persist"
    assert (
        call(http, db.sessions.count_documents, {"user_id": account["user"]["_id"]})
        == 0
    )


@pytest.mark.parametrize("resource", ["list", "task"])
def test_other_member_creation_racing_owned_board_deletion_leaves_no_orphans(
    api, account_graph, resource
):
    http, db = api
    account, other, graph = account_graph

    async def race():
        if resource == "list":
            # A new member needs a distinct list because ownership is unique.
            path = f"/api/v1/boards/{graph['owned']}/lists/"
            # Existing fixture's owned list belongs to other; delete it before
            # racing so uniqueness does not mask the parent-deletion race.
            await db.tasks.delete_many({"listID": graph["owned_list"]})
            await db.messages.delete_many({"listID": graph["owned_list"]})
            await db.todo_lists.delete_one({"_id": graph["owned_list"]})
            payload = {"ownerID": str(other["user"]["_id"]), "title": "racing list"}
        else:
            path = f"/api/v1/lists/{graph['owned_list']}/tasks/"
            payload = {"title": "racing task", "description": "concurrent"}
        return await asyncio.wait_for(
            asyncio.gather(
                request(
                    http.app, "POST", path, payload=payload, headers=other["headers"]
                ),
                request(
                    http.app,
                    "DELETE",
                    ME,
                    payload={"current_password": PASSWORD},
                    headers=account["headers"],
                ),
            ),
            timeout=REQUEST_TIMEOUT,
        )

    created, deleted = call(http, race)
    assert deleted.status_code == 204, deleted.text
    assert created.status_code in (201, 401, 403, 404, 503), created.text
    assert call(http, db.boards.find_one, {"_id": graph["owned"]}) is None
    # Check both representations to detect legacy string-ID orphans as well.
    assert (
        call(
            http,
            db.todo_lists.count_documents,
            {"boardID": {"$in": [graph["owned"], str(graph["owned"])]}},
        )
        == 0
    )
    assert call(http, db.tasks.count_documents, {"title": "racing task"}) == 0
    assert call(http, db.messages.count_documents, {"listID": graph["owned_list"]}) == 0


def test_stale_member_write_on_surviving_board_is_rejected_after_membership_cleanup(
    api, account_graph, monkeypatch
):
    http, db = api
    account, _, graph = account_graph

    async def race():
        waiting, proceed = gate_first_user_read(monkeypatch, db.name)
        pending = asyncio.create_task(
            request(
                http.app,
                "POST",
                f"/api/v1/lists/{graph['orphan_list']}/tasks/",
                payload={"title": "deleted member write"},
                headers=account["headers"],
                gated=True,
            )
        )
        try:
            await asyncio.wait_for(waiting.wait(), timeout=REQUEST_TIMEOUT)
            deleted = await request(
                http.app,
                "DELETE",
                ME,
                payload={"current_password": PASSWORD},
                headers=account["headers"],
            )
            assert deleted.status_code == 204, deleted.text
        finally:
            proceed.set()
            if not waiting.is_set():
                pending.cancel()
        return await asyncio.wait_for(pending, timeout=REQUEST_TIMEOUT)

    response = call(http, race)
    assert response.status_code == 401, response.text
    assert call(http, db.tasks.count_documents, {"title": "deleted member write"}) == 0


@pytest.mark.parametrize("operation", ["create_message", "update_message"])
def test_message_writes_coordinate_with_account_deletion(api, account_graph, operation):
    from app.services import message

    from tests.account_support import REQUEST_TIMEOUT, request
    from tests.auth_support import PASSWORD

    http, db = api
    account, other, graph = account_graph
    # Creation by another member races parent-board deletion. Editing by the
    # author races their own deletion on a surviving board.
    actor = other if operation == "create_message" else account
    target = (
        graph["owned_list"]
        if operation == "create_message"
        else graph["deleted_message"]
    )
    identity = service_identity(http, db, actor)
    handler = getattr(message, operation)

    async def race():
        return await asyncio.wait_for(
            asyncio.gather(
                handler(
                    str(target),
                    {"message": "racing content"},
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

    written, deleted = call(http, race)
    assert not isinstance(deleted, BaseException), repr(deleted)
    assert deleted.status_code == 204, deleted.text
    if isinstance(written, BaseException):
        assert isinstance(written, AuthError), repr(written)
        assert written.status in (401, 403, 404, 503)
    assert call(http, db.messages.count_documents, {"message": "racing content"}) == 0
    assert call(http, db.messages.count_documents, {"listID": graph["owned_list"]}) == 0


@pytest.mark.parametrize("resource", ["task", "list"])
def test_other_member_edits_racing_board_deletion_cannot_recreate_data(
    api, account_graph, resource
):
    from app.services.task import update_task
    from app.services.todo_list import update_todo_list

    from tests.account_support import REQUEST_TIMEOUT, request
    from tests.auth_support import PASSWORD

    http, db = api
    account, other, graph = account_graph
    identity = service_identity(http, db, other)
    handler = update_task if resource == "task" else update_todo_list
    target = graph["owned_task"] if resource == "task" else graph["owned_list"]

    async def race():
        return await asyncio.wait_for(
            asyncio.gather(
                handler(
                    str(target),
                    {"title": "not recreated"},
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

    edited, deleted = call(http, race)
    assert not isinstance(deleted, BaseException), repr(deleted)
    assert deleted.status_code == 204, deleted.text
    if isinstance(edited, BaseException):
        assert isinstance(edited, AuthError), repr(edited)
        assert edited.status in (401, 403, 404, 503)
    assert call(http, db.tasks.find_one, {"_id": graph["owned_task"]}) is None
    assert call(http, db.todo_lists.find_one, {"_id": graph["owned_list"]}) is None
