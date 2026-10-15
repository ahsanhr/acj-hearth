from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def get_boards():
    return {"message": "Boards endpoint working"}