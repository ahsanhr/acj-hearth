from fastapi import APIRouter

from app.api.v1.endpoints import boards
from app.api.v1.endpoints import users
from app.api.v1.endpoints import todo_lists

api_router = APIRouter()

api_router.include_router(
    boards.router,
    prefix="/boards",
    tags=["boards"]
)

api_router.include_router(
    users.router,
    prefix="/users",
    tags=["users"]
)

api_router.include_router(
    todo_lists.router,
    prefix="/boards/{board_id}/lists",
    tags=["todo-lists"]
)