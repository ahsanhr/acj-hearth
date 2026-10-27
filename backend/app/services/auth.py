"""MongoDB-backed authentication. All session mutations serialize on the owner."""

import asyncio
from datetime import timedelta
from uuid import uuid4

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
from starlette.concurrency import run_in_threadpool

from app.core.security import (
    new_refresh_token,
    refresh_hash,
    utcnow,
    verify_password,
)


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def unauthorized():
    return AuthError(401, "unauthorized", "Authentication required.")


def operation_outcome_unknown():
    return AuthError(
        503,
        "operation_outcome_unknown",
        "Unable to confirm whether account creation, update, or deletion completed. "
        "Reauthenticate and check account state before retrying.",
    )


def renewal_failed():
    return AuthError(
        401,
        "reauthentication_required",
        "Your session could not be renewed. Please sign in again.",
    )


class AuthService:
    def __init__(self, db):
        self.db = db
        self.users = db.users
        self.sessions = db.sessions

    async def transaction(self, operation):
        """Retry conflicts, but never replay writes on an ambiguous commit."""
        for attempt in range(3):
            async with self.db.client.start_session() as tx:
                try:
                    async with await tx.start_transaction(
                        read_concern=ReadConcern("snapshot"),
                        write_concern=WriteConcern("majority"),
                        max_commit_time_ms=5000,
                    ):
                        result = await operation(tx)
                        for commit_attempt in range(3):
                            try:
                                await tx.commit_transaction()
                                return result
                            except PyMongoError as exc:
                                if exc.has_error_label(
                                    "UnknownTransactionCommitResult"
                                ):
                                    if commit_attempt < 2:
                                        continue
                                    raise operation_outcome_unknown() from exc
                                raise
                except PyMongoError as exc:
                    if exc.has_error_label("TransientTransactionError"):
                        if attempt < 2:
                            await asyncio.sleep(0.01 * (attempt + 1))
                            continue
                        raise AuthError(
                            503, "database_busy", "Please try again."
                        ) from exc
                    raise

    async def touch_user(self, user_id, tx, **conditions):
        return await self.users.find_one_and_update(
            {"_id": user_id, "disabled": False, **conditions},
            {"$inc": {"auth_serial": 1}},
            session=tx,
            return_document=ReturnDocument.AFTER,
        )

    async def require_session(self, user_id, sid, tx):
        session = await self.sessions.find_one(
            {"user_id": user_id, "session_id": sid, "expires_at": {"$gt": utcnow()}},
            session=tx,
        )
        if not session:
            raise unauthorized()
        return session

    async def login(self, email: str, password: str):
        user = await self.users.find_one(
            {"email": email.strip().casefold(), "disabled": False}
        )
        if not user or not await run_in_threadpool(
            verify_password, password, user.get("password_hash", "")
        ):
            raise AuthError(401, "invalid_credentials", "Invalid email or password.")

        # A duplicate ID/hash aborts its transaction; regenerate rather than overwrite.
        for _ in range(5):
            raw = new_refresh_token()
            session = {
                "session_id": str(uuid4()),
                "user_id": user["_id"],
                "created_at": utcnow(),
                "refresh_token_hash": refresh_hash(raw),
            }
            session["expires_at"] = session["created_at"] + timedelta(days=30)
            session["refresh_expires_at"] = session["expires_at"]

            async def create(tx, session=session):
                owner = await self.touch_user(
                    user["_id"],
                    tx,
                    auth_version=user["auth_version"],
                    password_hash=user["password_hash"],
                )
                if not owner:
                    raise AuthError(
                        401, "invalid_credentials", "Invalid email or password."
                    )
                await self.sessions.delete_many(
                    {"user_id": user["_id"], "expires_at": {"$lte": utcnow()}},
                    session=tx,
                )
                await self.sessions.insert_one(dict(session), session=tx)
                ordered = (
                    await self.sessions.find(
                        {"user_id": user["_id"]},
                        session=tx,
                    )
                    .sort([("created_at", 1), ("session_id", 1)])
                    .to_list(length=None)
                )
                if len(ordered) > 5:
                    await self.sessions.delete_many(
                        {
                            "_id": {
                                "$in": [s["_id"] for s in ordered[: len(ordered) - 5]]
                            }
                        },
                        session=tx,
                    )
                return session

            try:
                return await self.transaction(create), raw
            except DuplicateKeyError:
                continue
        raise AuthError(
            503, "token_collision", "Could not create a session. Please try again."
        )

    async def authenticate(self, claims):
        user_id = ObjectId(claims["sub"])
        session = await self.sessions.find_one(
            {
                "session_id": claims["sid"],
                "user_id": user_id,
                "expires_at": {"$gt": utcnow()},
            }
        )
        user = await self.users.find_one({"_id": user_id, "disabled": False})
        if not session or not user:
            raise unauthorized()
        return user, session

    async def refresh(self, raw: str):
        if not raw or len(raw) > 512:
            raise renewal_failed()
        old_hash = refresh_hash(raw)
        found = await self.sessions.find_one({"refresh_token_hash": old_hash})
        if not found:
            raise renewal_failed()
        for _ in range(5):
            replacement = new_refresh_token()
            if replacement == raw:
                continue

            async def rotate(tx, replacement=replacement):
                if not await self.touch_user(found["user_id"], tx):
                    raise renewal_failed()
                now = utcnow()
                updated = await self.sessions.find_one_and_update(
                    {
                        "session_id": found["session_id"],
                        "user_id": found["user_id"],
                        "refresh_token_hash": old_hash,
                        "expires_at": {"$gt": now},
                        "refresh_expires_at": {"$gt": now},
                    },
                    {
                        "$set": {
                            "refresh_token_hash": refresh_hash(replacement),
                            "refresh_expires_at": min(
                                now + timedelta(days=30), found["expires_at"]
                            ),
                        }
                    },
                    return_document=ReturnDocument.AFTER,
                    session=tx,
                )
                if not updated:
                    raise renewal_failed()
                return updated

            try:
                return await self.transaction(rotate), replacement
            except DuplicateKeyError:
                continue
        raise AuthError(
            503, "token_collision", "Could not renew session. Please try again."
        )

    async def logout(self, raw: str | None):
        if not raw or len(raw) > 512:
            return
        hashed = refresh_hash(raw)
        found = await self.sessions.find_one({"refresh_token_hash": hashed})
        if not found:
            return

        async def remove(tx):
            await self.touch_user(found["user_id"], tx)
            # The cookie identified this session before serialization. Delete by
            # ID so a concurrent rotation cannot make an authorized logout a no-op.
            await self.sessions.delete_one(
                {"session_id": found["session_id"], "user_id": found["user_id"]},
                session=tx,
            )

        await self.transaction(remove)

    async def list_sessions(self, user_id, sid):
        sessions = (
            await self.sessions.find(
                {"user_id": user_id, "expires_at": {"$gt": utcnow()}},
                {"_id": 0, "session_id": 1, "created_at": 1, "expires_at": 1},
            )
            .sort([("created_at", 1), ("session_id", 1)])
            .to_list(length=None)
        )
        return [
            {**session, "current": session["session_id"] == sid} for session in sessions
        ]

    async def close_sessions(self, user_id, current_sid, target_sid=None):
        async def remove(tx):
            if not await self.touch_user(user_id, tx):
                raise unauthorized()
            await self.require_session(user_id, current_sid, tx)
            query = {"user_id": user_id}
            if target_sid is not None:
                query["session_id"] = target_sid
            result = await self.sessions.delete_many(query, session=tx)
            if target_sid and not result.deleted_count:
                raise AuthError(404, "session_not_found", "Session not found.")

        await self.transaction(remove)

    async def confirm_password(self, user, current_password):
        if not await run_in_threadpool(
            verify_password, current_password, user["password_hash"]
        ):
            raise AuthError(400, "incorrect_password", "Current password is incorrect.")

    async def confirmed_user(self, user, sid, tx):
        confirmed = await self.touch_user(
            user["_id"],
            tx,
            password_hash=user["password_hash"],
            auth_version=user["auth_version"],
        )
        if not confirmed:
            raise unauthorized()
        await self.require_session(user["_id"], sid, tx)
        return confirmed

    async def revoke_account(self, user_id, *, current_sid=None):
        """Disable an account; permanent deletion belongs to AccountService."""

        async def revoke(tx):
            user = await self.users.find_one_and_update(
                {"_id": user_id},
                {"$inc": {"auth_serial": 1}},
                session=tx,
            )
            if not user:
                raise unauthorized()
            if current_sid:
                await self.require_session(user_id, current_sid, tx)
            await self.users.update_one(
                {"_id": user_id},
                {"$set": {"disabled": True}, "$inc": {"auth_version": 1}},
                session=tx,
            )
            await self.sessions.delete_many({"user_id": user_id}, session=tx)

        await self.transaction(revoke)
