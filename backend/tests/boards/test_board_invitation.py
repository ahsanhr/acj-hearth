"""Tests for HEARTH board invitations."""

import hashlib

from datetime import timedelta
from app.core.security import utcnow

import pytest
from bson import ObjectId

from tests.support.accounts import create_account
from tests.support.auth import call


@pytest.mark.happy_path
def test_board_creator_invites_user_who_joins(api, account):
    http, db = api

    # Create another user who is not yet a board member.
    invited_user = create_account(http, db, "invited@example.com")

    # Create a board owned by the original account.
    owner_id = str(account["user"]["_id"])
    response = http.post(
        "/api/v1/boards/",
        json={
            "boardName": "Invitation Test Board",
            "createdBy": owner_id,
            "members": [],
        },
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text
    board_id = response.json()["_id"]

    # The board creator generates an invitation.
    invitation = http.post(
        f"/api/v1/boards/{board_id}/invitations",
        headers=account["headers"],
    )
    assert invitation.status_code == 201, invitation.text

    token = invitation.json()["token"]
    assert token
    assert invitation.json()["boardID"] == board_id

    # Verify the database stores a hash, not the raw token.
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    stored = call(
        http,
        db.board_invitations.find_one,
        {"token_hash": token_hash},
    )
    assert stored is not None
    assert stored["boardID"] == ObjectId(board_id)
    assert stored["revoked"] is False

    # The invited user accepts the invitation.
    accepted = http.post(
        f"/api/v1/boards/invitations/{token}/accept",
        headers=invited_user["headers"],
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["boardID"] == board_id

    # Verify the invited user is now a board member.
    board = call(
        http,
        db.boards.find_one,
        {"_id": ObjectId(board_id)},
    )
    assert invited_user["user"]["_id"] in board["members"]

    # The invited user can now see the board.
    boards = http.get(
        "/api/v1/boards/",
        headers=invited_user["headers"],
    )
    assert boards.status_code == 200
    assert board_id in [item["_id"] for item in boards.json()]


@pytest.mark.unhappy_path
def test_non_owner_cannot_generate_invitation(api, account):
    http, db = api

    other = create_account(http, db, "other@example.com")
    owner_id = str(account["user"]["_id"])

    response = http.post(
        "/api/v1/boards/",
        json={
            "boardName": "Private Board",
            "createdBy": owner_id,
            "members": [str(other["user"]["_id"])],
        },
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text
    board_id = response.json()["_id"]

    # A board member who isn't the creator tries to invite someone.
    invitation = http.post(
        f"/api/v1/boards/{board_id}/invitations",
        headers=other["headers"],
    )

    assert invitation.status_code == 403
    assert invitation.json()["error"]["code"] == "forbidden"

    # No invitation should have been created.
    invitations = call(
        http,
        db.board_invitations.count_documents,
        {"boardID": ObjectId(board_id)},
    )
    assert invitations == 0


@pytest.mark.unhappy_path
def test_invalid_and_expired_invitations_are_rejected(api, account):
    http, db = api

    owner_id = str(account["user"]["_id"])

    response = http.post(
        "/api/v1/boards/",
        json={
            "boardName": "Expiration Test Board",
            "createdBy": owner_id,
            "members": [],
        },
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text
    board_id = response.json()["_id"]

    invited_user = create_account(http, db, "expired@example.com")

    # An invented token must not allow someone to join.
    invalid = http.post(
        "/api/v1/boards/invitations/not-a-real-token/accept",
        headers=invited_user["headers"],
    )
    assert invalid.status_code == 404
    assert invalid.json()["error"]["code"] == "invitation_not_found"

    # Generate a legitimate invitation.
    invitation = http.post(
        f"/api/v1/boards/{board_id}/invitations",
        headers=account["headers"],
    )
    assert invitation.status_code == 201, invitation.text
    token = invitation.json()["token"]

    # Simulate an invitation that has passed its expiration date.
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    call(
        http,
        db.board_invitations.update_one,
        {"token_hash": token_hash},
        {"$set": {"expiresAt": utcnow() - timedelta(days=1)}},
    )

    expired = http.post(
        f"/api/v1/boards/invitations/{token}/accept",
        headers=invited_user["headers"],
    )
    assert expired.status_code == 404
    assert expired.json()["error"]["code"] == "invitation_not_found"

    # Neither attempt should have added the user to the board.
    board = call(
        http,
        db.boards.find_one,
        {"_id": ObjectId(board_id)},
    )
    assert invited_user["user"]["_id"] not in board["members"]


@pytest.mark.regression
def test_accepting_invitation_twice_does_not_duplicate_member(api, account):
    http, db = api

    owner_id = str(account["user"]["_id"])
    invited_user = create_account(http, db, "duplicate@example.com")

    response = http.post(
        "/api/v1/boards/",
        json={
            "boardName": "Duplicate Invitation Test",
            "createdBy": owner_id,
            "members": [],
        },
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text
    board_id = response.json()["_id"]

    invitation = http.post(
        f"/api/v1/boards/{board_id}/invitations",
        headers=account["headers"],
    )
    assert invitation.status_code == 201, invitation.text
    token = invitation.json()["token"]

    # Accept the same invitation twice.
    for _ in range(2):
        accepted = http.post(
            f"/api/v1/boards/invitations/{token}/accept",
            headers=invited_user["headers"],
        )
        assert accepted.status_code == 200, accepted.text

    # The user should appear only once in the members array.
    board = call(
        http,
        db.boards.find_one,
        {"_id": ObjectId(board_id)},
    )
    assert board["members"].count(invited_user["user"]["_id"]) == 1


@pytest.mark.unhappy_path
def test_board_invitations_require_authentication(api, account):
    http, db = api

    owner_id = str(account["user"]["_id"])

    response = http.post(
        "/api/v1/boards/",
        json={
            "boardName": "Authentication Test Board",
            "createdBy": owner_id,
            "members": [],
        },
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text
    board_id = response.json()["_id"]

    # Create a valid invitation as the board owner.
    invitation = http.post(
        f"/api/v1/boards/{board_id}/invitations",
        headers=account["headers"],
    )
    assert invitation.status_code == 201, invitation.text
    token = invitation.json()["token"]

    # Requests without authentication must be rejected.
    create_without_auth = http.post(
        f"/api/v1/boards/{board_id}/invitations",
    )
    assert create_without_auth.status_code == 401

    accept_without_auth = http.post(
        f"/api/v1/boards/invitations/{token}/accept",
    )
    assert accept_without_auth.status_code == 401
