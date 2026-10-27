"""Account data operations; credential/session logic remains in auth/security."""

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import (
    ConnectionFailure,
    DuplicateKeyError,
    ServerSelectionTimeoutError,
    WriteConcernError,
)
from pymongo.write_concern import WriteConcern
from starlette.concurrency import run_in_threadpool

from app.core.security import hash_password
from app.models.message import tombstone_document
from app.models.user import UserModel
from app.services.auth import AuthError, AuthService, operation_outcome_unknown


class AccountService:
    def __init__(self, db, auth=None):
        self.db = db
        self.auth = auth if auth is not None else AuthService(db)
        self.users = db.users.with_options(write_concern=WriteConcern("majority"))

    async def create(self, email: str, password: str):
        email = email.strip().casefold()
        user = UserModel(
            _id=ObjectId(),
            name=email.split("@", 1)[0],
            email=email,
            password_hash=await run_in_threadpool(hash_password, password),
            email_verified=False,
            disabled=False,
            auth_version=0,
            auth_serial=0,
        ).model_dump(by_alias=True)
        try:
            await self.users.insert_one(user)
        except DuplicateKeyError as exc:
            raise AuthError(
                409, "email_exists", "An account with this email already exists."
            ) from exc
        except ServerSelectionTimeoutError:
            # No server was selected; preserve the normal availability error.
            raise
        except (ConnectionFailure, WriteConcernError) as exc:
            # The insert may have reached MongoDB. Never replay it blindly.
            raise operation_outcome_unknown() from exc
        return user

    async def update(self, user, sid, payload):
        await self.auth.confirm_password(
            user, payload.current_password.get_secret_value()
        )
        changes = payload.model_dump(
            exclude_unset=True,
            exclude={"current_password", "new_password"},
        )
        if payload.new_password is not None:
            changes["password_hash"] = await run_in_threadpool(
                hash_password,
                payload.new_password.get_secret_value(),
            )

        async def change(tx):
            current = await self.auth.confirmed_user(user, sid, tx)
            email_changed = "email" in changes and changes["email"] != current["email"]
            revoke = email_changed or "password_hash" in changes
            submitted = dict(changes)
            if email_changed:
                submitted["email_verified"] = False
            update = {"$set": submitted}
            if revoke:
                update["$inc"] = {"auth_version": 1}
            await self.users.update_one({"_id": user["_id"]}, update, session=tx)
            if revoke:
                await self.db.sessions.delete_many({"user_id": user["_id"]}, session=tx)
            # Serialize only after commit, with values from this transaction.
            result = {**current, **submitted}
            return result, revoke

        try:
            return await self.auth.transaction(change)
        except DuplicateKeyError as exc:
            raise AuthError(
                409, "email_exists", "An account with this email already exists."
            ) from exc

    async def delete(self, user, sid, current_password):
        await self.auth.confirm_password(user, current_password)

        async def remove(tx):
            await self.auth.confirmed_user(user, sid, tx)
            await self._cleanup(user["_id"], tx)
            await self.db.sessions.delete_many({"user_id": user["_id"]}, session=tx)
            await self.users.delete_one({"_id": user["_id"]}, session=tx)

        await self.auth.transaction(remove)

    async def _cleanup(self, uid, tx):
        # Inventory: boards(createdBy/members), todo_lists(boardID/ownerID),
        # tasks(listID), messages(listID/userID/replyTo), sessions(user_id).
        # Include historical lists/messages even after a user left a board.
        boards = await self.db.boards.find(
            {"$or": [{"createdBy": uid}, {"members": uid}]},
            session=tx,
        ).to_list(length=None)
        own_lists = await self.db.todo_lists.find({"ownerID": uid}, session=tx).to_list(
            length=None
        )
        authored = await self.db.messages.find({"userID": uid}, session=tx).to_list(
            length=None
        )
        message_lists = await self.db.todo_lists.find(
            {"_id": {"$in": list({message["listID"] for message in authored})}},
            session=tx,
        ).to_list(length=None)
        affected = {board["_id"] for board in boards}
        affected.update(row["boardID"] for row in [*own_lists, *message_lists])
        owned = []
        for board_id in sorted(affected):
            board = await self.db.boards.find_one_and_update(
                {"_id": board_id},
                {"$inc": {"mutation_serial": 1}},
                return_document=ReturnDocument.AFTER,
                session=tx,
            )
            if board and board["createdBy"] == uid:
                owned.append(board_id)

        dependent_lists = await self.db.todo_lists.find(
            {"boardID": {"$in": owned}},
            session=tx,
        ).to_list(length=None)
        list_ids = [row["_id"] for row in dependent_lists]
        await self.db.tasks.delete_many({"listID": {"$in": list_ids}}, session=tx)
        await self.db.messages.delete_many({"listID": {"$in": list_ids}}, session=tx)
        await self.db.todo_lists.delete_many({"_id": {"$in": list_ids}}, session=tx)
        await self.db.boards.delete_many({"_id": {"$in": owned}}, session=tx)

        await self.db.boards.update_many(
            {"members": uid},
            {"$pull": {"members": uid}},
            session=tx,
        )
        await self.db.todo_lists.update_many(
            {"ownerID": uid},
            {"$set": {"ownerID": None}},
            session=tx,
        )
        async for message in self.db.messages.find({"userID": uid}, session=tx):
            await self.db.messages.replace_one(
                {"_id": message["_id"], "userID": uid},
                tombstone_document(message),
                session=tx,
            )
