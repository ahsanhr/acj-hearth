
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.schemas.todo_list import TodoListCreate
from app.services.todo_list import create_todo_list, get_board_todo_lists


BOARD_ID = "6ad7764f2e8b163e1532bfc5"
USER_ID = "test-user-123"


def make_board():
    return {
        "_id": ObjectId(BOARD_ID),
        "boardName": "HEARTH Test Board",
        "createdBy": USER_ID,
        "members": [USER_ID]
    }


def make_todo_list():
    return TodoListCreate(
        ownerID=USER_ID,
        title="My Study Tasks"
    )


@pytest.mark.asyncio
async def test_create_todo_list():
    mock_boards = MagicMock()
    mock_boards.find_one = AsyncMock(return_value=make_board())

    mock_lists = MagicMock()
    mock_lists.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id=ObjectId())
    )

    with patch("app.services.todo_list.db") as mock_db:
        mock_db.__getitem__.side_effect = {
            "boards": mock_boards,
            "todo_lists": mock_lists
        }.__getitem__

        result = await create_todo_list(BOARD_ID, make_todo_list())

    assert result["boardID"] == BOARD_ID
    assert result["ownerID"] == USER_ID
    assert result["title"] == "My Study Tasks"
    assert result["tasks"] == []
    assert result["messages"] == []
    assert "_id" in result
    mock_lists.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_todo_list_invalid_board_id():
    with pytest.raises(HTTPException) as exc:
        await create_todo_list("invalid-id", make_todo_list())

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_todo_list_board_not_found():
    mock_boards = MagicMock()
    mock_boards.find_one = AsyncMock(return_value=None)

    with patch("app.services.todo_list.db") as mock_db:
        mock_db.__getitem__.return_value = mock_boards

        with pytest.raises(HTTPException) as exc:
            await create_todo_list(BOARD_ID, make_todo_list())

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_todo_list_non_member():
    mock_boards = MagicMock()
    mock_boards.find_one = AsyncMock(return_value=make_board())

    todo_list = TodoListCreate(
        ownerID="another-user",
        title="My Tasks"
    )

    with patch("app.services.todo_list.db") as mock_db:
        mock_db.__getitem__.return_value = mock_boards

        with pytest.raises(HTTPException) as exc:
            await create_todo_list(BOARD_ID, todo_list)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_todo_list_duplicate():
    mock_boards = MagicMock()
    mock_boards.find_one = AsyncMock(return_value=make_board())

    mock_lists = MagicMock()
    mock_lists.insert_one = AsyncMock(
        side_effect=DuplicateKeyError("Duplicate list")
    )

    with patch("app.services.todo_list.db") as mock_db:
        mock_db.__getitem__.side_effect = {
            "boards": mock_boards,
            "todo_lists": mock_lists
        }.__getitem__

        with pytest.raises(HTTPException) as exc:
            await create_todo_list(BOARD_ID, make_todo_list())

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_get_board_todo_lists():
    list_id = ObjectId()

    mock_boards = MagicMock()
    mock_boards.find_one = AsyncMock(return_value=make_board())

    async def mock_find(query):
        yield {
            "_id": list_id,
            "boardID": BOARD_ID,
            "ownerID": USER_ID,
            "title": "My Study Tasks",
            "tasks": [],
            "messages": []
        }

    mock_lists = MagicMock()
    mock_lists.find.side_effect = mock_find

    with patch("app.services.todo_list.db") as mock_db:
        mock_db.__getitem__.side_effect = {
            "boards": mock_boards,
            "todo_lists": mock_lists
        }.__getitem__

        result = await get_board_todo_lists(BOARD_ID)

    assert len(result) == 1
    assert result[0]["_id"] == str(list_id)
    assert result[0]["title"] == "My Study Tasks"


@pytest.mark.asyncio
async def test_get_board_todo_lists_empty():
    mock_boards = MagicMock()
    mock_boards.find_one = AsyncMock(return_value=make_board())

    async def mock_find(query):
        for item in []:
            yield item

    mock_lists = MagicMock()
    mock_lists.find.side_effect = mock_find

    with patch("app.services.todo_list.db") as mock_db:
        mock_db.__getitem__.side_effect = {
            "boards": mock_boards,
            "todo_lists": mock_lists
        }.__getitem__

        result = await get_board_todo_lists(BOARD_ID)

    assert result == []


@pytest.mark.asyncio
async def test_get_board_todo_lists_invalid_board():
    with pytest.raises(HTTPException) as exc:
        await get_board_todo_lists("invalid-id")

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_get_board_todo_lists_board_not_found():
    mock_boards = MagicMock()
    mock_boards.find_one = AsyncMock(return_value=None)

    with patch("app.services.todo_list.db") as mock_db:
        mock_db.__getitem__.return_value = mock_boards

        with pytest.raises(HTTPException) as exc:
            await get_board_todo_lists(BOARD_ID)

    assert exc.value.status_code == 404
