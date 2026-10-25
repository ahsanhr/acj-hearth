
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from app.services.board import create_board, get_all_boards
from app.schemas.board import BoardCreate


@pytest.mark.asyncio
async def test_get_all_boards():
    board_id = ObjectId()

    async def mock_find():
        yield {
            "_id": board_id,
            "boardName": "HEARTH Test Board",
            "createdBy": "test-user-123",
            "members": ["test-user-123"]
        }

    mock_collection = MagicMock()
    mock_collection.find.side_effect = mock_find

    with patch("app.services.board.db") as mock_db:
        mock_db.__getitem__.return_value = mock_collection

        boards = await get_all_boards()

    assert len(boards) == 1
    assert boards[0]["_id"] == str(board_id)
    assert boards[0]["boardName"] == "HEARTH Test Board"


@pytest.mark.asyncio
async def test_get_all_boards_empty():
    async def mock_find():
        for board in []:
            yield board

    mock_collection = MagicMock()
    mock_collection.find.side_effect = mock_find

    with patch("app.services.board.db") as mock_db:
        mock_db.__getitem__.return_value = mock_collection

        boards = await get_all_boards()

    assert boards == []


@pytest.mark.asyncio
async def test_create_board():
    board = BoardCreate(
        boardName="HEARTH Test Board",
        createdBy="test-user-123",
        members=[]
    )

    mock_collection = MagicMock()
    mock_collection.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id=ObjectId())
    )

    with patch("app.services.board.db") as mock_db:
        mock_db.__getitem__.return_value = mock_collection

        result = await create_board(board)

    assert result["boardName"] == "HEARTH Test Board"
    assert result["createdBy"] == "test-user-123"
    assert "test-user-123" in result["members"]
    assert "_id" in result
    mock_collection.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_board_existing_member():
    board = BoardCreate(
        boardName="HEARTH Test Board",
        createdBy="test-user-123",
        members=["test-user-123"]
    )

    mock_collection = MagicMock()
    mock_collection.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id=ObjectId())
    )

    with patch("app.services.board.db") as mock_db:
        mock_db.__getitem__.return_value = mock_collection

        result = await create_board(board)

    assert result["members"].count("test-user-123") == 1
