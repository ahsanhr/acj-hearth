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
| POST | `/users` | Public; `{ "email": "user@example.com", "password": "a long password!1" }` |
| POST | `/auth/login` | Allowed Origin; same email/password body |
| POST | `/auth/refresh` | Allowed Origin and refresh cookie; access JWT not required |
| POST | `/auth/logout` | Allowed Origin; clears refresh cookie even if no session exists |
| GET | `/auth/sessions` | Bearer JWT; own sessions only |
| DELETE | `/auth/sessions/{session_id}` | Bearer JWT; own session only |
| DELETE | `/auth/sessions` | Bearer JWT; delete all own sessions |
| PATCH | `/users/me` | Bearer JWT; `current_password` plus any of `name`, `email`, `new_password` |
| GET | `/users/me` | Bearer JWT |
| POST | `/users/me/disable` | Bearer JWT; disables own account and deletes all sessions |
| DELETE | `/users/me` | Bearer JWT; `{ "current_password": "..." }`; atomically removes own account, sessions, and related data |

Account creation returns HTTP 201 with `{ "id": "...", "name": "user", "email": "user@example.com", "email_verified": false }`. The display name starts as the normalized email local part. Email ownership is not verified. Duplicate normalized email returns HTTP 409. Creation does not automatically log in. `/auth/register` has been removed.

Account retrieval and successful PATCH return HTTP 200 with only `id`, `name`, `email`, and `email_verified`. PATCH requires the current password for every mutable field, including name-only changes. Omitted fields remain untouched; nulls, unknown/protected fields, and updates without mutable fields are rejected. Names are trimmed, nonempty aliases of 1–128 characters and need not be unique. Changing email does not rename the account; an actual normalized-email change resets verification. `/auth/password` is removed, with no compatibility wrapper.

Password changes and actual email changes revoke every session atomically and clear the refresh cookie, requiring fresh login. Name-only updates and an unchanged normalized email preserve sessions. DELETE independently verifies the current password and returns HTTP 204 after committing cleanup, then clears the refresh cookie.

Deleting an owner deletes their boards and all dependent lists, tasks, and messages, even when other members contributed. Boards owned by others survive: remove the departing membership, retain their lists with a null owner, preserve other users' replies/tasks, and replace only the departing author's messages with anonymous `DELETED-USER` / `message deleted` tombstones. The surviving board owner manages retained ownerless lists. The deleted email may be registered again under a fresh account ID, with no inherited relationships.

All related mutations use shared account/board transaction coordination; descendant writes cannot escape a concurrent parent/account deletion. Existing board/list/task APIs require bearer authentication and board membership. Task and list management is restricted to their list owner or board owner. Board/list edit and message create/edit/read **service functions** implement safe internal boundaries; no additional HTTP endpoints, invitation workflow, or frontend UI have been added for them.

Login/refresh return `{ "access_token": "...", "token_type": "bearer" }` and set an HttpOnly refresh cookie. Refresh tokens never appear in JSON. Access JWTs last up to 15 minutes, capped at the session's fixed 30-day expiry. All session mutations serialize through a per-user MongoDB write inside a transaction. Confirmed transient transaction failures get at most three total attempts; ambiguous commits get at most three confirmations of the same transaction, never a replay of writes. Exhausted contention returns HTTP 503 `database_busy`; concurrent callers are not all guaranteed to succeed. An unconfirmed commit returns HTTP 503 `operation_outcome_unknown`, which does not imply rollback.

Passwords must have 15–128 characters, one ASCII digit, and one Unicode punctuation/symbol character. Spaces are preserved but do not meet the special-character rule. Password change verifies the current password and revokes all sessions, including the caller's. Account re-enablement has no public endpoint. The existing `AuthService.revoke_account` operation disables accounts; permanent deletion belongs to the account service so related-data cleanup cannot be bypassed.

Service errors have `{ "error": { "code": "...", "message": "..." } }`. Invalid credentials return HTTP 401 with `Invalid email or password.` Refresh failure returns HTTP 401:

```json
{
  "error": {
    "code": "reauthentication_required",
    "message": "Your session could not be renewed. Please sign in again."
  }
}
```

Request validation errors return HTTP 422 with `{ "error": { "code": "validation_error", "message": "Invalid request fields." } }`, without echoing inputs or validator details. Authentication and account responses use `Cache-Control: no-store`. An unconfirmed account insert returns HTTP 503 with `operation_outcome_unknown`; do not blindly replay an ambiguously delivered request.

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

Never log passwords, password hashes, bearer tokens, refresh cookies, or signing secrets; configure reverse proxies and observability systems accordingly. PyMongo command/reply payload logging is disabled because its DEBUG output includes stored credentials and session data; do not re-enable it.

## Existing data

There are no existing accounts to migrate. The canonical `users` model contains an immutable BSON `_id`, `name`, normalized `email`, server-generated Argon2id `password_hash`, `disabled`, `email_verified`, `auth_version`, and `auth_serial`. Startup rejects documents outside that model rather than converting legacy data.

Index setup enforces unique normalized email, removes obsolete legacy-field indexes (including username uniqueness), and restricts per-board list-owner uniqueness to non-null BSON ObjectIds so multiple anonymous containers can coexist. It does not delete user documents. TTL cleanup is asynchronous; authorization always checks expiration independently.

## Tests

Account and auth/session tests are organized by happy paths, invalid inputs,
authorization, and data integrity, with separate concurrency and shared rollback
coverage. Tests are grouped by feature under `tests/`, with helpers in
`tests/support/`. See the [test layout](tests/README.md),
[account tests](tests/accounts/README.md), and
[auth/session tests](tests/auth/README.md) for coverage and focused commands.

```sh
cd backend
.venv/bin/python -m pytest -q
# Include real transaction/concurrency/API tests:
TEST_MONGODB_URI='mongodb://localhost:27017/?replicaSet=rs0' .venv/bin/python -m pytest -q
```

Frontend browser tests live separately in [`frontend/tests/`](../frontend/tests/README.md) and require Playwright and Chromium. From the repository root, install the browser with `uv run playwright install chromium`, then run `uv run pytest frontend/tests`. They serve the frontend over HTTP and mock `/api/v1/users/preview`, covering initial layout, HTML rendering, and API errors. They do not require MongoDB or a running backend. The development dependencies include `pytest-asyncio` for async retry-control tests.

Run the complete suite, including authentication transaction/concurrency tests and browser tests, from the repository root:

```sh
TEST_MONGODB_URI='mongodb://localhost:27017/?replicaSet=rs0' PYTHONPATH=backend uv run pytest backend/tests frontend/tests -q
```

Integration tests create uniquely named `hearth_test_*` databases and drop them afterward. Use a disposable replica set. Set `TEST_MONGODB_URI` in the process environment or `backend/.env`; the environment takes precedence. Tests do not fall back to the application's `MONGODB_URI`. Without a test URI, database tests are skipped; cryptography and validation tests still run. Database names fit Atlas's 38-byte limit. Resource tests use real authenticated transactions rather than legacy unauthenticated string-ID mocks.

Out of scope: password recovery, email verification, rate limiting, and Redis. Public login is therefore still susceptible to automated credential guessing; this is an accepted limitation, not a production hardening claim.
