from fastapi import APIRouter

from app.api.v1.endpoints import auth, boards, tasks, todo_lists, users

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])

api_router.include_router(
    boards.router,
    prefix="/boards",
    tags=["boards"]
)

api_router.include_router(
    todo_lists.router,
    prefix="/boards/{board_id}/lists",
    tags=["todo-lists"]
)

api_router.include_router(
    tasks.router,
    prefix="/lists/{list_id}/tasks",
    tags=["tasks"]
)

api_router.add_api_route(
    "/tasks/{task_id}",
    tasks.edit_task,
    methods=["PATCH"],
    tags=["tasks"]
)

api_router.add_api_route(
    "/tasks/{task_id}",
    tasks.remove_task,
    methods=["DELETE"],
    tags=["tasks"]
)
