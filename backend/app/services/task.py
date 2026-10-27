from bson import ObjectId

from app.core.database import db
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.auth import AuthError
from app.services.resources import (
    ResourceAccess,
    parse_changes,
    parse_id,
    public_document,
    require_list_manager,
)


async def create_task(list_id: str, task: TaskCreate, *, identity, database=None):
    list_id = parse_id(list_id)
    database = db if database is None else database
    access = ResourceAccess(database)
    data = {
        "_id": ObjectId(),
        "listID": list_id,
        **task.model_dump(mode="json"),
        "completed": False,
    }

    async def create(tx):
        actor = await access.actor(identity, tx)
        todo_list, board = await access.todo_list(list_id, actor, tx)
        require_list_manager(board, todo_list, actor)
        await database.tasks.insert_one(dict(data), session=tx)
        return public_document(data)

    return await access.auth.transaction(create)


async def get_list_tasks(list_id: str, *, identity, database=None):
    list_id = parse_id(list_id)
    database = db if database is None else database
    access = ResourceAccess(database)
    actor = await access.actor(identity, write=False)
    await access.todo_list(list_id, actor, write=False)
    return [
        public_document(row) async for row in database.tasks.find({"listID": list_id})
    ]


async def mutate_task(task_id, *, identity, database, fields=None, delete=False):
    """One coordination path for both task editing and deletion."""
    task_id = parse_id(task_id)
    access = ResourceAccess(database)

    async def mutate(tx):
        actor = await access.actor(identity, tx)
        task = await database.tasks.find_one({"_id": task_id}, session=tx)
        if task is None:
            raise AuthError(404, "task_not_found", "Task not found.")
        todo_list, board = await access.todo_list(task["listID"], actor, tx)
        require_list_manager(board, todo_list, actor)
        if delete:
            await database.tasks.delete_one({"_id": task_id}, session=tx)
            # Lists normally query tasks by parent; remove any cached IDs too.
            await database.todo_lists.update_one(
                {"_id": todo_list["_id"]},
                {"$pull": {"tasks": task_id}},
                session=tx,
            )
            return {"message": "Task deleted successfully"}
        if fields:
            await database.tasks.update_one(
                {"_id": task_id}, {"$set": fields}, session=tx
            )
        return public_document({**task, **(fields or {})})

    return await access.auth.transaction(mutate)


async def update_task(task_id: str, task: TaskUpdate, *, identity, database=None):
    payload = parse_changes(TaskUpdate, task)
    return await mutate_task(
        task_id,
        identity=identity,
        database=db if database is None else database,
        fields=payload.model_dump(exclude_unset=True, mode="json"),
    )


async def delete_task(task_id: str, *, identity, database=None):
    return await mutate_task(
        task_id,
        identity=identity,
        database=db if database is None else database,
        delete=True,
    )
