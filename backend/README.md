# HEARTH backend

## Setup

The backend supports Python 3.12+; the root uv project requires Python 3.13+. A MongoDB replica set is required (including locally). A standalone MongoDB server cannot run the authentication transactions.

Alternatively, use `uv sync` from the repository root to install the backend and browser-test dependencies.

```sh
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
# Put the generated value in AUTH_SIGNING_SECRET in .env.
docker compose up -d --wait
uvicorn app.main:app --reload
```

Set `AUTH_ALLOWED_ORIGINS` to a JSON array of exact frontend origins (scheme, host, port; no trailing slash). Missing, `null`, and unlisted Origins are rejected on login, refresh, and logout. CLI clients must supply an allowed Origin for those endpoints too. Empty allowed origins is fail-closed.

Refresh cookies always use `Secure`, so browser development requires HTTPS, e.g. a local HTTPS proxy or uvicorn with `--ssl-keyfile` and `--ssl-certfile`. Do not disable cookie security to work around development hosting. Avoid broad cookie domains. Cookies are host-only and scoped to `/api/v1/auth`.

The default `SameSite=Lax` works only for same-site frontend/API hosting. Unrelated domains require `AUTH_COOKIE_SAMESITE=none`, HTTPS, explicitly allowed credentialed CORS origins, and Origin validation. Browser third-party-cookie restrictions can still prevent such deployments; same-site hosting is preferable.

Startup validates JWT configuration, requires a replica set, and creates indexes. There is no fallback signing secret. Production MongoDB must use access controls, authenticated connections, and TLS. The Compose service is local-only and intentionally does not provide production security.

## API

All paths below start with `/api/v1`. JSON request bodies are required where shown.

| Method | Path | Authorization / body |
| --- | --- | --- |
| POST | `/auth/register` | `{ "email": "user@example.com", "password": "a long password!1" }` |
| POST | `/auth/login` | Allowed Origin; same email/password body |
| POST | `/auth/refresh` | Allowed Origin and refresh cookie; access JWT not required |
| POST | `/auth/logout` | Allowed Origin; clears refresh cookie even if no session exists |
| GET | `/auth/sessions` | Bearer JWT; own sessions only |
| DELETE | `/auth/sessions/{session_id}` | Bearer JWT; own session only |
| DELETE | `/auth/sessions` | Bearer JWT; delete all own sessions |
| POST | `/auth/password` | Bearer JWT; `{ "current_password": "...", "new_password": "..." }` |
| GET | `/users/me` | Bearer JWT |
| POST | `/users/me/disable` | Bearer JWT; disables own account and deletes all sessions |
| DELETE | `/users/me` | Bearer JWT; deletes own account and all sessions |

Registration returns HTTP 201 with `{ "id": "...", "email": "...", "email_verified": false }`. Email ownership is not verified. Duplicate normalized email returns HTTP 409. Registration does not automatically log in.

Login/refresh return `{ "access_token": "...", "token_type": "bearer" }` and set an HttpOnly refresh cookie. Refresh tokens never appear in JSON. Access JWTs last up to 15 minutes, capped at the session's fixed 30-day expiry. All session mutations serialize through a per-user MongoDB write inside a transaction. Conflict and ambiguous-commit retries are bounded; database errors fail closed with HTTP 503.

Passwords must have 15–128 characters, one ASCII digit, and one Unicode punctuation/symbol character. Spaces are preserved but do not meet the special-character rule. Password change verifies the current password and revokes all sessions, including the caller's. Account re-enablement has no public endpoint; trusted administrative application code can use `AuthService.revoke_account` for disabling/deleting other accounts after enforcing authorization.

Service errors have `{ "error": { "code": "...", "message": "..." } }`. Invalid credentials return HTTP 401 with `Invalid email or password.` Refresh failure returns HTTP 401:

```json
{
  "error": {
    "code": "reauthentication_required",
    "message": "Your session could not be renewed. Please sign in again."
  }
}
```

Request validation errors return HTTP 422 without echoing input values, including passwords. Authentication responses use `Cache-Control: no-store`.

## Frontend contract

The included frontend is an API preview, not an authentication UI. A browser authentication UI must:

1. Keep access JWTs only in memory and send `Authorization: Bearer <token>` for protected requests.
2. Use `credentials: "include"` for login, refresh, and logout requests.
3. Refresh on app startup/tab reopening to restore authentication from the persistent cookie.
4. Coordinate refresh across tabs (for example, Web Locks plus BroadcastChannel) so the same cookie is not consumed concurrently.
5. On `reauthentication_required`, discard the in-memory access JWT, display the server message, and navigate to login. Do not silently retry an invalid token.
6. Treat logout, password change, and clearing all sessions as clearing local authentication state.

Rotation is strictly one-time. A lost successful refresh response can require a new login. Failed refreshes do not automatically revoke a still-active session, and an old-token failure does not clear the cookie (which could otherwise erase a concurrent successful rotation).

## Signing-key rotation

Use HS256 with at least 32 securely random secret bytes. All instances must share the same issuer/audience and key configuration. To rotate without downtime, first distribute the new key to every verifier (as the configured previous key while the old key remains current), then switch all instances to sign with the new key while retaining the old key as previous. Keep the old verification key for at least 15 minutes plus 30 seconds after the last old-key issuance, then remove it. `kid` selects configured keys only, never external keys.

Never log passwords, bearer tokens, refresh cookies, or signing secrets; configure reverse proxies and observability systems accordingly.

## Existing data

The new authentication service uses `users.email` (normalized), `password_hash` (Argon2id), `disabled`, `email_verified`, `auth_version`, and `auth_serial`. It does not use the old scaffold's `password`, `userID`, or username for authentication. Existing accounts must be explicitly migrated before use: resolve case-insensitive email collisions, normalize emails, convert known passwords to Argon2id safely or provision fresh credentials, and initialize the authentication fields. Never copy plaintext passwords into `password_hash`; remove legacy raw passwords after migration. Do not run this service against unmigrated user data.

Index setup changes username uniqueness to apply only to string usernames, allowing email-only registration. It does not delete user documents. TTL cleanup is asynchronous; authorization always checks expiration independently.

## Tests

```sh
cd backend
.venv/bin/python -m pytest -q --ignore=tests/test_frontend.py
# Include real transaction/concurrency/API tests:
TEST_MONGODB_URI='mongodb://localhost:27017/?replicaSet=rs0' .venv/bin/python -m pytest -q --ignore=tests/test_frontend.py
```

The separate upstream frontend tests require Playwright and Chromium. From the repository root, install the browser with `uv run playwright install chromium`, then run `uv run pytest backend/tests/test_frontend.py`. These tests currently expect user-card rendering and element IDs that do not match `frontend/app.js`; that pre-existing frontend mismatch is separate from authentication.

Integration tests create uniquely named `hearth_test_*` databases and drop them afterward. Use a disposable replica set. Without `TEST_MONGODB_URI`, database tests are skipped; cryptography and validation tests still run.

Out of scope: password recovery, email verification, rate limiting, and Redis. Public login is therefore still susceptible to automated credential guessing; this is an accepted limitation, not a production hardening claim.
