
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.schemas.task import TaskCreate, TaskUpdate
from app.services.task import (
    create_task,
    get_list_tasks,
    update_task,
    delete_task
)


LIST_ID = "6ad77b999edd8378557c4c03"
TASK_ID = "6ada1cf5fcf3ff740da91127"


def make_list():
    return {
        "_id": ObjectId(LIST_ID),
        "boardID": "6ad7764f2e8b163e1532bfc5",
        "ownerID": "test-user-123",
        "title": "My Study Tasks"
    }


def make_task():
    return {
        "_id": ObjectId(TASK_ID),
        "listID": LIST_ID,
        "title": "Finish HEARTH backend",
        "description": "Implement and test the Task API",
        "completed": False,
        "dueDate": "2026-10-25"
    }


@pytest.mark.asyncio
async def test_create_task():
    mock_lists = MagicMock()
    mock_lists.find_one = AsyncMock(return_value=make_list())

    mock_tasks = MagicMock()
    mock_tasks.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id=ObjectId(TASK_ID))
    )

    task = TaskCreate(
        title="Finish HEARTH backend",
        description="Implement and test the Task API",
        dueDate=date(2026, 10, 25)
    )

    with patch("app.services.task.db") as mock_db:
        mock_db.__getitem__.side_effect = {
            "todo_lists": mock_lists,
            "tasks": mock_tasks
        }.__getitem__

        result = await create_task(LIST_ID, task)

    assert result["_id"] == TASK_ID
    assert result["listID"] == LIST_ID
    assert result["title"] == "Finish HEARTH backend"
    assert result["completed"] is False
    assert result["dueDate"] == "2026-10-25"
    mock_tasks.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_task_invalid_list_id():
    task = TaskCreate(title="Test task")

    with pytest.raises(HTTPException) as exc:
        await create_task("invalid-id", task)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_task_list_not_found():
    mock_lists = MagicMock()
    mock_lists.find_one = AsyncMock(return_value=None)

    task = TaskCreate(title="Test task")

    with patch("app.services.task.db") as mock_db:
        mock_db.__getitem__.return_value = mock_lists

        with pytest.raises(HTTPException) as exc:
            await create_task(LIST_ID, task)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_list_tasks():
    mock_lists = MagicMock()
    mock_lists.find_one = AsyncMock(return_value=make_list())

    async def mock_find(query):
        yield make_task()

    mock_tasks = MagicMock()
    mock_tasks.find.side_effect = mock_find

    with patch("app.services.task.db") as mock_db:
        mock_db.__getitem__.side_effect = {
            "todo_lists": mock_lists,
            "tasks": mock_tasks
        }.__getitem__

        result = await get_list_tasks(LIST_ID)

    assert len(result) == 1
    assert result[0]["_id"] == TASK_ID
    assert result[0]["title"] == "Finish HEARTH backend"


@pytest.mark.asyncio
async def test_get_list_tasks_empty():
    mock_lists = MagicMock()
    mock_lists.find_one = AsyncMock(return_value=make_list())

    async def mock_find(query):
        for item in []:
            yield item

    mock_tasks = MagicMock()
    mock_tasks.find.side_effect = mock_find

    with patch("app.services.task.db") as mock_db:
        mock_db.__getitem__.side_effect = {
            "todo_lists": mock_lists,
            "tasks": mock_tasks
        }.__getitem__

        result = await get_list_tasks(LIST_ID)

    assert result == []


@pytest.mark.asyncio
async def test_get_list_tasks_invalid_id():
    with pytest.raises(HTTPException) as exc:
        await get_list_tasks("invalid-id")

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_get_list_tasks_list_not_found():
    mock_lists = MagicMock()
    mock_lists.find_one = AsyncMock(return_value=None)

    with patch("app.services.task.db") as mock_db:
        mock_db.__getitem__.return_value = mock_lists

        with pytest.raises(HTTPException) as exc:
            await get_list_tasks(LIST_ID)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_task():
    original = make_task()
    updated = make_task()
    updated["title"] = "Updated task title"

    mock_tasks = MagicMock()
    mock_tasks.find_one = AsyncMock(side_effect=[original, updated])
    mock_tasks.update_one = AsyncMock()

    task_update = TaskUpdate(title="Updated task title")

    with patch("app.services.task.db") as mock_db:
        mock_db.__getitem__.return_value = mock_tasks

        result = await update_task(TASK_ID, task_update)

    assert result["title"] == "Updated task title"
    assert result["_id"] == TASK_ID
    mock_tasks.update_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_task():
    original = make_task()
    updated = make_task()
    updated["completed"] = True

    mock_tasks = MagicMock()
    mock_tasks.find_one = AsyncMock(side_effect=[original, updated])
    mock_tasks.update_one = AsyncMock()

    with patch("app.services.task.db") as mock_db:
        mock_db.__getitem__.return_value = mock_tasks

        result = await update_task(
            TASK_ID,
            TaskUpdate(completed=True)
        )

    assert result["completed"] is True
    mock_tasks.update_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_task_invalid_id():
    with pytest.raises(HTTPException) as exc:
        await update_task("invalid-id", TaskUpdate(completed=True))

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_task_not_found():
    mock_tasks = MagicMock()
    mock_tasks.find_one = AsyncMock(return_value=None)

    with patch("app.services.task.db") as mock_db:
        mock_db.__getitem__.return_value = mock_tasks

        with pytest.raises(HTTPException) as exc:
            await update_task(TASK_ID, TaskUpdate(completed=True))

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_task():
    mock_tasks = MagicMock()
    mock_tasks.delete_one = AsyncMock(
        return_value=MagicMock(deleted_count=1)
    )

    with patch("app.services.task.db") as mock_db:
        mock_db.__getitem__.return_value = mock_tasks

        result = await delete_task(TASK_ID)

    assert result["message"] == "Task deleted successfully"
    mock_tasks.delete_one.assert_awaited_once_with(
        {"_id": ObjectId(TASK_ID)}
    )


@pytest.mark.asyncio
async def test_delete_task_invalid_id():
    with pytest.raises(HTTPException) as exc:
        await delete_task("invalid-id")

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_task_not_found():
    mock_tasks = MagicMock()
    mock_tasks.delete_one = AsyncMock(
        return_value=MagicMock(deleted_count=0)
    )

    with patch("app.services.task.db") as mock_db:
        mock_db.__getitem__.return_value = mock_tasks

        with pytest.raises(HTTPException) as exc:
            await delete_task(TASK_ID)

    assert exc.value.status_code == 404
