from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.api import api_router

app = FastAPI(title="HEARTH API")

app.include_router(api_router, prefix="/api/v1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Adjust
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)