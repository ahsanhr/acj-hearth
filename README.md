# ACJ Hearth

## Running locally

Use **either Caddy or nginx** to serve the frontend over HTTPS and forward API
requests to FastAPI. No frontend build or npm install is required. The commands
below target macOS with Homebrew; run them from the repository root unless noted.

### 1. Install dependencies and configure the backend

Install Python 3.13+ dependencies with uv, and have Docker Desktop (or another
Docker engine with Compose) running:

```sh
brew install uv
uv sync
```

If `backend/.env` does not exist, create it from the example:

```sh
cp backend/.env.example backend/.env
```

Generate a signing secret once:

```sh
.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Edit `backend/.env`, paste the generated value into `AUTH_SIGNING_SECRET`, and
confirm these settings (preserve any other existing configuration):

```env
MONGODB_URI=mongodb://localhost:27017/?replicaSet=rs0
MONGODB_DB_NAME=hearth
AUTH_SIGNING_SECRET=PASTE_GENERATED_VALUE_HERE
AUTH_ALLOWED_ORIGINS=["https://localhost:5173"]
AUTH_COOKIE_SAMESITE=lax
```

Keep the secret private; do not commit `.env` or regenerate the secret every
startup. A missing or short secret prevents the backend from starting.

### 2. Start MongoDB and FastAPI

```sh
cd backend
docker compose up -d --wait
../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Wait for `Application startup complete` and leave this terminal running.
Run FastAPI from `backend/` so it reads `backend/.env`. MongoDB must be a replica
set; the included Compose configuration initializes one automatically.

### 3. Choose one HTTPS server

Both options below serve `https://localhost:5173` and proxy `/api/` to the backend.
**Do not run both on port 5173.** Certificates are local-development certificates,
not public certificates; neither option registers a domain or publishes the app
online. The configurations bind the app to loopback interfaces only. Do not share
certificate-authority private keys.

#### Option A: Caddy

Install Caddy:

```sh
brew install caddy
```

Create `Caddyfile` in the repository root, replacing the frontend path with the
absolute path to your checkout's `frontend/` directory:

```caddyfile
{
    auto_https disable_redirects
}

https://localhost:5173 {
    bind 127.0.0.1 ::1
    tls internal
    root * /absolute/path/to/acj-hearth/frontend
    reverse_proxy /api/* 127.0.0.1:8000
    file_server
}
```

`disable_redirects` avoids opening privileged port 80; HTTPS on port 5173 remains
enabled. In a second terminal, from the repository root:

```sh
caddy fmt --overwrite ./Caddyfile
caddy run --config ./Caddyfile --adapter caddyfile
```

Allow Caddy to install its local certificate authority if prompted. If the
browser does not trust the certificate, leave Caddy running and run this in
another terminal, then restart the browser:

```sh
sudo caddy trust
```

#### Option B: nginx

Install nginx and mkcert, then create a trusted local certificate:

```sh
brew install nginx mkcert
mkcert -install
mkdir -p "$HOME/.config/hearth"
mkcert -cert-file "$HOME/.config/hearth/localhost.pem" \
  -key-file "$HOME/.config/hearth/localhost-key.pem" \
  localhost 127.0.0.1 ::1
```

Find your nginx configuration:

```sh
echo "$(brew --prefix)/etc/nginx/nginx.conf"
```

Add the following `server` block **inside its existing `http` block**. Replace
all paths with absolute paths for your machine; nginx does not expand `$HOME`
or `~` in these directives. `YOUR_USER` is your macOS account name.

```nginx
server {
    listen 127.0.0.1:5173 ssl;
    listen [::1]:5173 ssl;
    server_name localhost;

    ssl_certificate /Users/YOUR_USER/.config/hearth/localhost.pem;
    ssl_certificate_key /Users/YOUR_USER/.config/hearth/localhost-key.pem;

    root /absolute/path/to/acj-hearth/frontend;
    index index.html;

    location /api/ {
        # No trailing slash: preserve /api/ in forwarded requests.
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

Validate and start nginx:

```sh
nginx -t
brew services start nginx
```

If nginx is already running, apply configuration changes with `nginx -s reload`
instead. The block above is loopback-only; review or remove any other default
server blocks if you also want to prevent nginx from listening on other interfaces.

### 4. Open the app

Visit **https://localhost:5173** and sign up or log in. Use this exact origin,
not `http://localhost:5173` or `https://127.0.0.1:5173`.

Keep the backend and your chosen HTTPS server running. On subsequent runs, start
Docker, repeat step 2, and start your chosen server; dependency installation,
secret generation, and certificate setup are one-time tasks. Restart FastAPI
after changing `backend/.env`.

To stop: press Ctrl+C in the FastAPI and Caddy terminals, or use
`brew services stop nginx` for nginx. To stop MongoDB, run
`docker compose stop` from `backend/` (this preserves its data).

### Troubleshooting

- **`AUTH_SIGNING_SECRET must contain at least 32 bytes`:** generate and set the
  secret in `backend/.env`, then restart FastAPI from `backend/`.
- **Caddy cannot bind port 80:** include the `auto_https disable_redirects`
  global block shown above; do not run the whole server as root to work around it.
- **502 Bad Gateway:** verify FastAPI is running at `127.0.0.1:8000` and its
  startup completed successfully.
- **Origin rejected:** check the exact `AUTH_ALLOWED_ORIGINS` value and restart
  FastAPI. Origins must not contain a trailing slash.
- **Certificate warning:** run `sudo caddy trust` for Caddy, or `mkcert -install`
  for nginx, then restart your browser. Do not disable secure cookie settings.
- **Address already in use:** stop the other process using port 5173 or 8000.

## Frontend account setup

The existing signup and login forms call the backend API. Signup creates an
account, logs in, and saves the optional display name through the profile API.
Access tokens stay in memory; opening the page restores the session from the
HttpOnly refresh cookie. Refresh uses Web Locks to serialize requests across
same-origin tabs. Browsers without Web Locks require explicit login instead.

Refresh cookies are always `Secure`, so browser development requires HTTPS as
shown above. The backend may use HTTP on loopback behind the local HTTPS proxy.

The `api-base` meta tag in `frontend/index.html` defaults to `/api/v1` for
same-origin proxy hosting. For a separately hosted API, set it to the API's
HTTPS URL including `/api/v1` and allow the exact frontend origin in the
backend configuration. Same-site hosting is preferable for refresh cookies.

Account creation and refresh requests are not automatically retried. If account
creation cannot be confirmed, try signing in before creating the account again.
The current UI has no logout control or protected board operations yet; automatic
access-token renewal for those future operations is not implemented.

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
├── tests/
│   ├── accounts/
│   ├── auth/
│   ├── boards/
│   ├── tasks/
│   ├── todo_lists/
│   ├── support/
│   └── conftest.py
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

Pydantic models representing MongoDB documents. Database access uses PyMongo.

- `base.py`: Shared MongoDB document model and ObjectId handling.
- `user.py`: User document model definition.

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

### `backend/tests/`

Backend tests are grouped into feature directories (`accounts`, `auth`, `boards`, `tasks`, and `todo_lists`). Shared fixtures live in `conftest.py` and reusable helpers in `support/`. See [the backend test layout and commands](backend/tests/README.md).

Browser tests are separate in [`frontend/tests/`](frontend/tests/README.md). They use Playwright with mocked API responses. The existing cases still target the previous preview UI and have not been updated for the authentication forms.

### `backend/requirements.txt`

Python dependencies for the backend application.
