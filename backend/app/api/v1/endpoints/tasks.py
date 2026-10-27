from fastapi import APIRouter, Depends, status

from app.api.deps import current_identity
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.task import create_task, delete_task, get_list_tasks, update_task

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_task(list_id: str, task: TaskCreate, identity=Depends(current_identity)):
    return await create_task(list_id, task, identity=identity)


@router.get("/")
async def get_tasks(list_id: str, identity=Depends(current_identity)):
    return await get_list_tasks(list_id, identity=identity)


async def edit_task(task_id: str, task: TaskUpdate, identity=Depends(current_identity)):
    return await update_task(task_id, task, identity=identity)


async def remove_task(task_id: str, identity=Depends(current_identity)):
    return await delete_task(task_id, identity=identity)
