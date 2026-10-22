
from fastapi import APIRouter, status

from app.schemas.task import TaskCreate, TaskUpdate
from app.services.task import create_task, get_list_tasks, update_task

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_task(list_id: str, task: TaskCreate):
    return await create_task(list_id, task)


@router.get("/")
async def get_tasks(list_id: str):
    return await get_list_tasks(list_id)


async def edit_task(task_id: str, task: TaskUpdate):
    return await update_task(task_id, task)
