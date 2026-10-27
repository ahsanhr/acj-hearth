
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.core.database import db
from app.schemas.task import TaskCreate, TaskUpdate

async def create_task(list_id: str, task: TaskCreate):
    try:
        list_object_id = ObjectId(list_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid list ID")

    todo_list = await db["todo_lists"].find_one({"_id": list_object_id})

    if todo_list is None:
        raise HTTPException(status_code=404, detail="To-do list not found")

    task_data = {
        "listID": list_id,
        "title": task.title,
        "description": task.description,
        "completed": False,
        "dueDate": task.dueDate.isoformat() if task.dueDate else None
    }

    result = await db["tasks"].insert_one(task_data)
    task_data["_id"] = str(result.inserted_id)

    return task_data


async def get_list_tasks(list_id: str):
    try:
        list_object_id = ObjectId(list_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid list ID")

    todo_list = await db["todo_lists"].find_one({"_id": list_object_id})

    if todo_list is None:
        raise HTTPException(status_code=404, detail="To-do list not found")

    tasks = []

    async for task in db["tasks"].find({"listID": list_id}):
        task["_id"] = str(task["_id"])
        tasks.append(task)

    return tasks


async def update_task(task_id: str, task: TaskUpdate):
    try:
        task_object_id = ObjectId(task_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid task ID")

    existing_task = await db["tasks"].find_one({"_id": task_object_id})

    if existing_task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    update_data = task.model_dump(exclude_unset=True)

    if "dueDate" in update_data and update_data["dueDate"] is not None:
        update_data["dueDate"] = update_data["dueDate"].isoformat()

    if update_data:
        await db["tasks"].update_one(
            {"_id": task_object_id},
            {"$set": update_data}
        )

    updated_task = await db["tasks"].find_one({"_id": task_object_id})
    updated_task["_id"] = str(updated_task["_id"])

    return updated_task


async def delete_task(task_id: str):
    try:
        task_object_id = ObjectId(task_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid task ID")

    result = await db["tasks"].delete_one({"_id": task_object_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"message": "Task deleted successfully"}
