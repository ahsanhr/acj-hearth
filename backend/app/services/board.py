from bson import ObjectId

from app.core.database import db
from app.core.security import utcnow
from app.schemas.board import BoardCreate, BoardUpdate
from app.services.auth import AuthError
from app.services.resources import (
    ResourceAccess,
    parse_changes,
    parse_id,
    public_document,
)


async def get_all_boards(*, identity, database=None):
    database = db if database is None else database
    access = ResourceAccess(database)
    actor = await access.actor(identity, write=False)
    return [
        public_document(board)
        async for board in database.boards.find(
            {"$or": [{"members": actor}, {"createdBy": actor}]},
        )
    ]


async def create_board(board: BoardCreate, *, identity, database=None):
    database = db if database is None else database
    access = ResourceAccess(database)
    data = board.model_dump()
    members = sorted({data["createdBy"], *data["members"]})
    data.update(_id=ObjectId(), members=members, mutation_serial=0, createdAt=utcnow())

    async def create(tx):
        actor = await access.actor(identity, tx, referenced_users=members)
        if actor != data["createdBy"]:
            raise AuthError(403, "forbidden", "A board must be owned by its creator.")
        await database.boards.insert_one(dict(data), session=tx)
        return public_document(data)

    return await access.auth.transaction(create)


async def update_board(board_id, changes, *, identity, database=None):
    database = db if database is None else database
    access = ResourceAccess(database)
    board_id = parse_id(board_id)
    payload = parse_changes(BoardUpdate, changes)
    submitted = payload.model_dump(exclude_unset=True)

    async def update(tx):
        actor = await access.actor(identity, tx, referenced_users=payload.members or [])
        board = await access.board(board_id, actor, tx)
        if actor != board["createdBy"]:
            raise AuthError(
                403, "forbidden", "Only the board owner can manage membership."
            )
        fields = dict(submitted)
        if "members" in fields:
            fields["members"] = sorted({actor, *fields["members"]})
        await database.boards.update_one(
            {"_id": board_id}, {"$set": fields}, session=tx
        )
        return public_document({**board, **fields})

    return await access.auth.transaction(update)
