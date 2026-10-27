"""Failure injection around REAL MongoDB writes, not a mocked transaction."""

import pytest
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import OperationFailure

from tests.account_support import NEW_PASSWORD, mutate, snapshot
from tests.test_auth_api import PASSWORD

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


@pytest.mark.parametrize("stage", ["user_update", "session_revocation"])
def test_combined_patch_rolls_back_user_and_sessions_after_write_failure(
    api, account, monkeypatch, stage
):
    http, db = api
    before = snapshot(http, db)
    injected = []

    async def fail(collection, method, args, kwargs):
        submitted_update = repr(args[1:])
        target = (
            stage == "user_update"
            and collection == "users"
            and "password_hash" in submitted_update
            or stage == "session_revocation"
            and collection == "sessions"
            and method.startswith("delete")
        )
        if target:
            assert kwargs.get("session") is not None, (
                "Account writes must participate in a transaction"
            )
            injected.append(collection)
            raise OperationFailure("injected after account write", code=12345)

    intercept_writes(monkeypatch, db.name, fail)
    response = mutate(
        http,
        payload={
            "name": "Rollback",
            "email": "rollback@example.com",
            "new_password": NEW_PASSWORD,
            "current_password": PASSWORD,
        },
        account=account,
    )
    assert injected, f"The {stage} failure injection was not reached"
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "database_unavailable"
    assert snapshot(http, db) == before
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "stage", ["boards", "todo_lists", "tasks", "messages", "sessions", "users"]
)
def test_each_deletion_cleanup_stage_rolls_back_all_collections(
    api, account_graph, monkeypatch, stage
):
    http, db = api
    account, _, _ = account_graph
    before = snapshot(http, db)
    injected = []

    async def fail(collection, method, args, kwargs):
        if collection == stage and not (
            method == "find_one_and_update" and collection == "users"
        ):
            # Skip account/board coordination writes: inject at actual cleanup.
            if collection == "boards" and not method.startswith("delete"):
                return
            if collection == "users" and not method.startswith("delete"):
                return
            assert kwargs.get("session") is not None
            injected.append((collection, method))
            raise OperationFailure("injected cleanup failure", code=12345)

    intercept_writes(monkeypatch, db.name, fail)
    response = mutate(
        http, method="DELETE", payload={"current_password": PASSWORD}, account=account
    )
    assert injected, f"No cleanup write reached for {stage}"
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "database_unavailable"
    assert snapshot(http, db) == before
    assert "set-cookie" not in response.headers


def test_every_cleanup_write_uses_the_same_transaction(api, account_graph, monkeypatch):
    http, db = api
    account, _, _ = account_graph
    writes = []

    async def record(collection, method, args, kwargs):
        tx = kwargs.get("session")
        assert tx is not None and tx.in_transaction, (collection, method)
        writes.append((collection, tx.session_id, tx._transaction_id))

    intercept_writes(monkeypatch, db.name, record)
    response = mutate(
        http, method="DELETE", payload={"current_password": PASSWORD}, account=account
    )
    assert response.status_code == 204, response.text
    assert {name for name, _, _ in writes} >= {
        "users",
        "sessions",
        "boards",
        "todo_lists",
        "tasks",
        "messages",
    }
    assert len({(repr(sid), tid) for _, sid, tid in writes}) == 1
