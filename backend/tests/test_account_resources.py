"""Canonical relationship storage and transaction coordination on resource APIs."""

import asyncio

import pytest
from app.services.auth import AuthError
from bson import ObjectId

from tests.account_support import create_account, mutate, service_identity
from tests.test_account_failures import intercept_writes
from tests.test_auth_api import call


@pytest.mark.parametrize("field", ["mutation_serial", "auth_serial"])
def test_board_coordination_fields_are_server_managed(api, account, field):
    http, db = api
    response = http.post(
        "/api/v1/boards/",
        headers=account["headers"],
        json={
            "boardName": "protected",
            "createdBy": str(account["user"]["_id"]),
            "members": [],
            field: 900,
        },
    )
    assert response.status_code == 422, response.text
    assert call(http, db.boards.count_documents, {}) == 0


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
    writes = []

    async def record(name, method, args, kwargs):
        session = kwargs.get("session")
        assert session is not None and session.in_transaction
        writes.append((name, method, repr(session.session_id), session._transaction_id))

    intercept_writes(monkeypatch, db.name, record)
    response = http.post(path, json=payload, headers=account["headers"])
    assert response.status_code == 201, response.text
    assert any(name == "boards" for name, *_ in writes)
    assert any(name == "users" for name, *_ in writes)
    assert any(name == collection for name, *_ in writes)
    assert len({(sid, tid) for _, _, sid, tid in writes}) == 1
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


@pytest.mark.parametrize("resource", ["list", "task"])
@pytest.mark.parametrize("identity", ["missing", "nonmember"])
def test_resource_creation_requires_live_membership(
    api, account_graph, resource, identity
):
    http, db = api
    account, _, graph = account_graph
    if identity == "nonmember":
        outsider = create_account(http, db, "outsider@example.com")
        headers = outsider["headers"]
        uid = outsider["user"]["_id"]
    else:
        headers, uid = {}, account["user"]["_id"]
    if resource == "list":
        path = f"/api/v1/boards/{graph['surviving']}/lists/"
        payload = {"ownerID": str(uid), "title": "forbidden"}
    else:
        path = f"/api/v1/lists/{graph['orphan_list']}/tasks/"
        payload = {"title": "forbidden"}
    response = http.post(path, json=payload, headers=headers)
    assert response.status_code == (401 if identity == "missing" else 403), (
        response.text
    )
    assert call(http, db.todo_lists.count_documents, {"title": "forbidden"}) == 0
    assert call(http, db.tasks.count_documents, {"title": "forbidden"}) == 0


def test_malformed_relationship_id_is_rejected_without_creating_data(api, account):
    http, db = api
    response = http.post(
        "/api/v1/boards/",
        headers=account["headers"],
        json={
            "boardName": "invalid reference",
            "createdBy": str(account["user"]["_id"]),
            "members": ["not-an-objectid"],
        },
    )
    assert response.status_code == 422, response.text
    assert call(http, db.boards.count_documents, {}) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"message": "restore content"},
        {"userID": str(ObjectId())},
        {"deleted": False},
    ],
)
def test_tombstones_are_anonymous_and_cannot_be_restored(api, account_graph, changes):
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
        payload={"current_password": owner["password"]},
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
            changes,
            identity=identity,
            database=db,
        )
    assert error.value.status in (409, 422)
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


@pytest.mark.parametrize("operation", ["create_message", "update_message"])
def test_message_writes_coordinate_with_account_deletion(api, account_graph, operation):
    from app.services import message

    from tests.test_account_races import REQUEST_TIMEOUT, request
    from tests.test_auth_api import PASSWORD

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
    writes = []

    async def record(name, method, args, kwargs):
        session = kwargs.get("session")
        assert session is not None and session.in_transaction
        writes.append((name, repr(session.session_id), session._transaction_id))

    intercept_writes(monkeypatch, db.name, record)
    args = (str(graph[target]),) if changes is None else (str(graph[target]), changes)
    call(http, handler, *args, identity=identity, database=db)
    assert {name for name, *_ in writes} >= {"users", "boards", collection}
    assert len({(sid, tid) for _, sid, tid in writes}) == 1
    assert (
        call(http, db.boards.find_one, {"_id": graph["surviving"]})["mutation_serial"]
        > 0
    )


@pytest.mark.parametrize("resource", ["task", "list"])
def test_other_member_edits_racing_board_deletion_cannot_recreate_data(
    api, account_graph, resource
):
    from app.services.task import update_task
    from app.services.todo_list import update_todo_list

    from tests.test_account_races import REQUEST_TIMEOUT, request
    from tests.test_auth_api import PASSWORD

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


def test_message_edits_cannot_upsert_or_modify_other_authors(api, account_graph):
    from app.services.message import update_message

    http, db = api
    _, owner, graph = account_graph
    identity = service_identity(http, db, owner)
    for target, status in [(ObjectId(), 404), (graph["deleted_message"], 403)]:
        with pytest.raises(AuthError) as error:
            call(
                http,
                update_message,
                str(target),
                {"message": "forbidden"},
                identity=identity,
                database=db,
            )
        assert error.value.status == status
    assert call(http, db.messages.count_documents, {"message": "forbidden"}) == 0
