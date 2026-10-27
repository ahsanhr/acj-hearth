"""Account contracts: rollback."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from app.services.auth import AuthError, AuthService
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import AutoReconnect, OperationFailure

from tests.support.accounts import (
    NEW_PASSWORD,
    USERS,
    intercept_writes,
    mutate,
    snapshot,
)
from tests.support.auth import PASSWORD, call

UNKNOWN_MESSAGE = (
    "Unable to confirm whether account creation, update, or deletion completed. "
    "Reauthenticate and check account state before retrying."
)


def labelled(label):
    return OperationFailure(
        "injected transaction error", code=251, details={"errorLabels": [label]}
    )


class RetrySession:
    def __init__(self, failures=()):
        self.failures = list(failures)
        self.commits = 0

    async def start_transaction(self, **kwargs):
        @asynccontextmanager
        async def transaction():
            yield self

        return transaction()

    async def commit_transaction(self):
        self.commits += 1
        if self.failures:
            failure = self.failures.pop(0)
            if failure:
                raise failure


class RetryDatabase:
    users = sessions = None

    def __init__(self, commit_failures=()):
        self.commit_failures = commit_failures
        self.opened = []
        self.client = self

    @asynccontextmanager
    async def start_session(self):
        session = RetrySession(self.commit_failures)
        self.opened.append(session)
        yield session


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


@pytest.mark.asyncio
async def test_confirmed_transient_aborts_stop_after_three_total_attempts():
    db = RetryDatabase()
    operation = AsyncMock(side_effect=labelled("TransientTransactionError"))
    with pytest.raises(AuthError) as error:
        await AuthService(db).transaction(operation)
    assert error.value.status == 503
    assert error.value.code == "database_busy"
    assert operation.await_count == len(db.opened) == 3


@pytest.mark.asyncio
async def test_transient_abort_then_success_retries_entire_operation():
    db = RetryDatabase()
    operation = AsyncMock(
        side_effect=[labelled("TransientTransactionError"), "committed"]
    )
    assert await AuthService(db).transaction(operation) == "committed"
    assert operation.await_count == len(db.opened) == 2


@pytest.mark.asyncio
async def test_unknown_commit_retries_confirmation_without_replaying_writes():
    db = RetryDatabase([labelled("UnknownTransactionCommitResult"), None])
    operation = AsyncMock(return_value="committed")
    assert await AuthService(db).transaction(operation) == "committed"
    assert operation.await_count == len(db.opened) == 1
    assert db.opened[0].commits == 2


@pytest.mark.asyncio
async def test_unknown_commit_exhaustion_is_three_confirmations_not_write_replays():
    db = RetryDatabase([labelled("UnknownTransactionCommitResult") for _ in range(10)])
    operation = AsyncMock(return_value="possibly committed")
    with pytest.raises(AuthError) as error:
        await AuthService(db).transaction(operation)
    assert operation.await_count == len(db.opened) == 1
    assert db.opened[0].commits == 3
    assert error.value.status == 503
    assert error.value.code == "operation_outcome_unknown"
    assert error.value.message == UNKNOWN_MESSAGE


@pytest.mark.asyncio
async def test_nontransient_database_error_is_not_retried():
    db = RetryDatabase()
    failure = OperationFailure("nontransient failure", code=12345)
    operation = AsyncMock(side_effect=failure)
    with pytest.raises(OperationFailure) as error:
        await AuthService(db).transaction(operation)
    assert error.value is failure
    assert operation.await_count == len(db.opened) == 1


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
@pytest.mark.parametrize("confirm_on_retry", [True, False])
def test_lost_commit_confirmation_does_not_replay_committed_mutation(
    api, account, monkeypatch, method, confirm_on_retry
):
    http, db = api
    original_commit = AsyncClientSession.commit_transaction
    commits = []
    original_sid = None

    async def uncertain_commit(tx):
        nonlocal original_sid
        if original_sid is None:
            original_sid = tx.session_id
        assert tx.session_id == original_sid
        commits.append(tx._transaction_id)
        await original_commit(tx)
        if not confirm_on_retry or len(commits) == 1:
            raise labelled("UnknownTransactionCommitResult")

    monkeypatch.setattr(AsyncClientSession, "commit_transaction", uncertain_commit)
    payload = {"current_password": PASSWORD}
    if method == "PATCH":
        payload["name"] = "Committed exactly once"
    response = mutate(http, method=method, payload=payload, account=account)
    assert len(commits) == (2 if confirm_on_retry else 3)
    assert len(set(commits)) == 1
    assert response.status_code == (
        (200 if method == "PATCH" else 204) if confirm_on_retry else 503
    ), response.text
    if not confirm_on_retry:
        assert response.json() == {
            "error": {"code": "operation_outcome_unknown", "message": UNKNOWN_MESSAGE}
        }
    user = call(http, db.users.find_one, {"_id": account["user"]["_id"]})
    if method == "PATCH":
        assert user["name"] == "Committed exactly once"
        assert user["auth_serial"] == account["user"]["auth_serial"] + 1
    else:
        assert user is None
        assert (
            call(http, db.sessions.count_documents, {"user_id": account["user"]["_id"]})
            == 0
        )


def test_creation_insert_with_lost_acknowledgement_is_not_blindly_replayed(
    api, monkeypatch
):
    http, db = api
    original_insert = AsyncCollection.insert_one
    inserted = []

    async def lost_ack(collection, document, *args, **kwargs):
        result = await original_insert(collection, document, *args, **kwargs)
        if collection.database.name == db.name and collection.name == "users":
            inserted.append(document["_id"])
            raise AutoReconnect("simulated lost insert acknowledgement")
        return result

    monkeypatch.setattr(AsyncCollection, "insert_one", lost_ack)
    response = http.post(
        USERS, json={"email": "alice@example.com", "password": PASSWORD}
    )
    assert len(inserted) == 1
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "operation_outcome_unknown"
    assert call(http, db.users.count_documents, {}) in (0, 1)
    assert call(http, db.sessions.count_documents, {}) == 0
