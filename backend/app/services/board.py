from app.core.database import db
from app.schemas.board import BoardCreate


async def get_all_boards():
    boards = []

    async for board in db["boards"].find():
        board["_id"] = str(board["_id"])
        boards.append(board)

    return boards


async def create_board(board: BoardCreate):
    board_data = board.model_dump()

    if board_data["createdBy"] not in board_data["members"]:
        board_data["members"].append(board_data["createdBy"])

    result = await db["boards"].insert_one(board_data)

    board_data["_id"] = str(result.inserted_id)

    return board_data