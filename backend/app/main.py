from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from app.api.v1.api import api_router
from app.core.config import settings as default_settings
from app.core.database import db
from app.core.setup_db import setup_database
from app.services.auth import AuthError, AuthService
from app.services.user import AccountService


def create_app(settings=None, database=None, *, initialize_database=True):
    config = default_settings if settings is None else settings
    database = db if database is None else database

    @asynccontextmanager
    async def lifespan(app):
        config.validate_auth()
        if initialize_database:
            hello = await database.client.admin.command("hello")
            if not hello.get("setName"):
                raise RuntimeError("Authentication requires a MongoDB replica set")
            await setup_database(database)
        try:
            yield
        finally:
            if initialize_database:
                await database.client.close()

    app = FastAPI(title="HEARTH API", lifespan=lifespan)
    app.state.settings = config
    app.state.auth_service = AuthService(database)
    app.state.account_service = AccountService(database, app.state.auth_service)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.AUTH_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def prevent_auth_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/api/v1/auth", "/api/v1/users")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, exc: AuthError):
        headers = {"Cache-Control": "no-store"}
        if exc.status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status,
            headers=headers,
        )

    @app.exception_handler(PyMongoError)
    async def database_error(request: Request, exc: PyMongoError):
        return JSONResponse(
            {
                "error": {
                    "code": "database_unavailable",
                    "message": "Service temporarily unavailable.",
                }
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Neither raw inputs nor validator details belong in public errors.
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Invalid request fields.",
                }
            },
            status_code=422,
            headers={"Cache-Control": "no-store"},
        )

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
