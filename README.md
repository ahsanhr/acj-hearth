# ACJ Hearth

## Backend Structure

The backend is scaffolded as a monolithic FastAPI application using a layered architecture. All backend code lives under the `backend/` directory.

```text
backend/
├── app/
│   ├── api/
│   │   ├── deps.py
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── auth.py
│   │       │   └── users.py
│   │       └── api.py
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   └── security.py
│   ├── models/
│   │   ├── base.py
│   │   └── user.py
│   ├── schemas/
│   │   ├── token.py
│   │   └── user.py
│   ├── services/
│   │   └── user.py
│   └── main.py
├── alembic/
├── tests/
├── .env
├── README.md
└── requirements.txt
```

### `backend/app/main.py`

Application entrypoint. This is where the FastAPI app is initialized, routers are included, and application-level middleware will be registered.

### `backend/app/api/`

Routing and controller layer for REST endpoints.

- `deps.py`: Shared FastAPI dependencies such as database sessions, authentication dependencies, or current-user resolution.
- `v1/api.py`: Aggregates all version 1 route modules and applies shared prefixes.
- `v1/endpoints/`: Contains path operation functions, grouped by resource or feature. These files act as the controllers for the API.

### `backend/app/core/`

Global application configuration and infrastructure setup.

- `config.py`: Environment-driven settings using Pydantic settings.
- `database.py`: Database engine, connection, and session setup.
- `security.py`: Security-related helpers such as password hashing and JWT handling.

### `backend/app/models/`

Database models, typically SQLAlchemy ORM models.

- `base.py`: Shared declarative base for ORM models.
- `user.py`: User table/model definition.

### `backend/app/schemas/`

Pydantic schemas used for request validation and response serialization.

- `token.py`: Authentication token schemas.
- `user.py`: User-related DTOs such as create, update, and response schemas.

### `backend/app/services/`

Business logic layer. Services coordinate application behavior and keep business rules separate from API route handlers.

Example flow:

```text
HTTP Request -> API Endpoint -> Service -> Model/Database -> Response Schema -> HTTP Response
```

### `backend/alembic/`

Database migration directory. Alembic migration files and configuration will live here once database migrations are initialized.

### `backend/tests/`

Backend test suite. Tests should be organized around API behavior, services, and database logic as the backend grows.

### `backend/requirements.txt`

Python dependencies for the backend application.
