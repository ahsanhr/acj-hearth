
"""Secure invitation creation for HEARTH boards."""

import hashlib
import secrets
from datetime import timedelta

from app.core.database import db
from app.core.security import utcnow
from app.services.auth import AuthError
from app.services.resources import ResourceAccess, parse_id


INVITATION_LIFETIME = timedelta(days=7)


async def create_board_invitation(board_id, *, identity, database=None):
    database = db if database is None else database
    access = ResourceAccess(database)
    board_id = parse_id(board_id)

    async def create(tx):
        actor = await access.actor(identity, tx)
        board = await access.board(board_id, actor, tx)

        if actor != board["createdBy"]:
            raise AuthError(
                403,
                "forbidden",
                "Only the board creator can generate invitations.",
            )

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = utcnow() + INVITATION_LIFETIME

        await database.board_invitations.insert_one(
            {
                "boardID": board_id,
                "token_hash": token_hash,
                "createdBy": actor,
                "expiresAt": expires_at,
                "revoked": False,
                "createdAt": utcnow(),
            },
            session=tx,
        )

        return {
            "token": token,
            "boardID": str(board_id),
            "expiresAt": expires_at.isoformat(),
        }

    return await access.auth.transaction(create)


async def accept_board_invitation(token, *, identity, database=None):
    database = db if database is None else database
    access = ResourceAccess(database)

    if not isinstance(token, str) or not token:
        raise AuthError(400, "invalid_invitation", "Invalid invitation link.")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def accept(tx):
        actor = await access.actor(identity, tx)

        invitation = await database.board_invitations.find_one(
            {
                "token_hash": token_hash,
                "revoked": False,
                "expiresAt": {"$gt": utcnow()},
            },
            session=tx,
        )

        if invitation is None:
            raise AuthError(
                404,
                "invitation_not_found",
                "Invitation is invalid or expired.",
            )

        board = await database.boards.find_one_and_update(
            {"_id": invitation["boardID"]},
            {
                "$addToSet": {"members": actor},
                "$inc": {"mutation_serial": 1},
            },
            session=tx,
        )

        if board is None:
            raise AuthError(
                404,
                "board_not_found",
                "This board no longer exists.",
            )

        return {
            "boardID": str(invitation["boardID"]),
            "message": "Successfully joined the board.",
        }

    return await access.auth.transaction(accept)

