from fastapi import APIRouter

from app.api.v1.endpoints import boards

api_router = APIRouter()

api_router.include_router(
    boards.router,
    prefix="/boards",
    tags=["boards"]
)