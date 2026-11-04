# ACJ Hearth

Hearth is a shared productivity app built around collaborative boards, task
lists, and messages. It uses a plain HTML/CSS/JavaScript frontend, a FastAPI
backend, and MongoDB.

## Project structure

```text
acj-hearth/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI entrypoint
│   │   ├── api/             # Routes and request dependencies
│   │   ├── core/            # Configuration, database, and security
│   │   ├── models/          # Stored document models
│   │   ├── schemas/         # Request/response validation
│   │   └── services/        # Business logic and transactions
│   ├── tests/              # Backend tests and testing guide
│   ├── compose.yaml        # Local MongoDB replica set
│   └── .env.example        # Backend configuration template
├── frontend/
│   ├── index.html          # Pages and forms
│   ├── css/                # Styles
│   ├── js/                 # UI logic and API calls
│   └── tests/              # Browser tests
├── docs/                   # Detailed setup and service documentation
├── Caddyfile               # Local HTTPS server and API proxy
└── pyproject.toml          # Python dependencies and tooling
```

## Running locally

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and **Caddy or nginx**.
For local MongoDB, also start Docker Desktop. Commands below assume macOS and
start in the repository root. No npm install or frontend build is needed.

### 1. One-time setup

```sh
brew install uv
uv sync
cp backend/.env.example backend/.env  # Only if .env does not already exist.
.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Paste the generated secret into `backend/.env` and confirm:

```env
MONGODB_URI=mongodb://localhost:27017/?replicaSet=rs0
MONGODB_DB_NAME=hearth
AUTH_SIGNING_SECRET=PASTE_GENERATED_VALUE_HERE
AUTH_ALLOWED_ORIGINS=["https://localhost:5173"]
AUTH_COOKIE_SAMESITE=lax
```

Use your development connection URI instead if MongoDB is remote. A replica set
is required. Keep `.env` private and reuse the signing secret between restarts.

### 2. Start the backend

```sh
cd backend
docker compose up -d --wait  # Skip when using remote MongoDB.
../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Wait for **Application startup complete** and leave the terminal running.

### 3. Start HTTPS hosting

Use **one** of the following; HTTPS is required for secure authentication cookies.

**Caddy:** install with `brew install caddy`, then update the `root` path in
`Caddyfile` to your checkout's absolute `frontend/` path. In a second terminal,
from the repository root:

```sh
caddy run --config ./Caddyfile --adapter caddyfile
```

If prompted, allow local certificate trust. For certificate warnings, run
`sudo caddy trust` with Caddy running, then restart the browser.

**nginx:** follow the [local HTTPS guide](docs/local-https.md#nginx) to configure
its certificate, frontend directory, and API proxy, then run:

```sh
nginx -t
brew services start nginx  # If already running: nginx -s reload
```

### 4. Open Hearth

Visit **https://localhost:5173**. Keep both the backend and HTTPS server running.
On subsequent runs, repeat steps 2–3 only; do not regenerate secrets/certificates.

Stop FastAPI/Caddy with Ctrl+C, or nginx with `brew services stop nginx`.
Stop local MongoDB with `docker compose stop` from `backend/`.

For details, see the [HTTPS setup guide](docs/local-https.md),
[backend API guide](backend/README.md), and [backend test guide](backend/tests/README.md).
