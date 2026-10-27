"""Authorization: caller identity, password confirmation, membership, and origins."""

import pytest
from app.services.auth import AuthError

from tests.account_support import (
    ME,
    NEW_PASSWORD,
    USERS,
    create_account,
    mutate,
    service_identity,
    snapshot,
)
from tests.auth_support import PASSWORD, call, login


# GET denial states are covered by test_auth_authorization.py. Each mutation
# route still checks every live-identity state, including a JWT with no session.
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
@pytest.mark.parametrize("state", ["missing", "revoked", "disabled", "deleted"])
def test_account_mutations_require_active_identity(api, account, method, state):
    http, db = api
    uid = account["user"]["_id"]
    headers = account["headers"] if state != "missing" else {}
    if state == "revoked":
        call(http, db.sessions.delete_many, {"user_id": uid})
    elif state == "disabled":
        call(http, db.users.update_one, {"_id": uid}, {"$set": {"disabled": True}})
    elif state == "deleted":
        call(http, db.users.delete_one, {"_id": uid})
    before = snapshot(http, db)
    payload = {
        "current_password": PASSWORD,
        **({"name": "Not allowed"} if method == "PATCH" else {}),
    }
    response = http.request(method, ME, headers=headers, json=payload)
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers.get("cache-control") == "no-store"
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "fields,confirmation",
    [
        ({"name": "New"}, None),
        ({"name": "New"}, "wrong"),
        ({"email": "new@example.com"}, "wrong"),
        ({"new_password": NEW_PASSWORD}, "wrong"),
    ],
    ids=["missing-confirmation", "name", "email", "password"],
)
def test_every_patch_requires_password_confirmation(api, account, fields, confirmation):
    http, db = api
    # Preserve the multi-session failure guarantee formerly duplicated in the
    # auth API regression: no current or other owned session may be revoked.
    assert login(http, email=account["user"]["email"]).status_code == 200
    before = snapshot(http, db)
    payload = dict(fields)
    if confirmation is not None:
        payload["current_password"] = confirmation
    response = mutate(http, payload=payload, account=account)
    assert response.status_code == (422 if confirmation is None else 400), response.text
    assert response.json()["error"]["code"] == (
        "validation_error" if confirmation is None else "incorrect_password"
    )
    assert snapshot(http, db) == before


def test_delete_requires_correct_password_before_any_cleanup(api, account_graph):
    http, db = api
    account, _, _ = account_graph
    before = snapshot(http, db)
    response = mutate(
        http, method="DELETE", payload={"current_password": "wrong"}, account=account
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "incorrect_password"
    assert snapshot(http, db) == before


def test_client_cannot_select_another_account(api, account):
    http, db = api
    other = create_account(http, db, "bob@example.com")
    before = snapshot(http, db)
    for method in ["PATCH", "DELETE"]:
        response = mutate(
            http,
            method=method,
            payload={
                "id": str(other["user"]["_id"]),
                "current_password": PASSWORD,
                **({"name": "attack"} if method == "PATCH" else {}),
            },
            account=account,
        )
        assert response.status_code == 422, response.text
    for method in ["GET", "PATCH", "DELETE"]:
        assert http.request(
            method, f"{USERS}/{other['user']['_id']}", headers=account["headers"]
        ).status_code in (404, 405)
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "origin,allowed",
    [("https://app.example.com", True), ("https://evil.example", False)],
)
def test_patch_cors_preflight_preserves_origin_and_credentials_policy(
    api, origin, allowed
):
    http, _ = api
    response = http.options(
        ME,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == (200 if allowed else 400)
    if allowed:
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"
        assert "PATCH" in response.headers["access-control-allow-methods"]
    else:
        assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("resource", ["list", "task"])
@pytest.mark.parametrize("identity", ["missing", "nonmember"])
def test_resource_creation_requires_live_membership(
    api, account_graph, resource, identity
):
    http, db = api
    account, _, graph = account_graph
    if identity == "nonmember":
        outsider = create_account(http, db, "outsider@example.com")
        headers, uid = outsider["headers"], outsider["user"]["_id"]
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


def test_board_owner_cannot_edit_another_authors_active_message(api, account_graph):
    from app.services.message import update_message

    http, db = api
    _, owner, graph = account_graph
    before = snapshot(http, db)
    with pytest.raises(AuthError) as error:
        call(
            http,
            update_message,
            str(graph["deleted_message"]),
            {"message": "forbidden"},
            identity=service_identity(http, db, owner),
            database=db,
        )
    assert error.value.status == 403
    assert snapshot(http, db) == before
