# HEARTH backend

## Setup

See [Running locally](../README.md#running-locally) for dependencies, environment
configuration, MongoDB, and HTTPS hosting with Caddy or nginx. The root uv project
requires Python 3.13+; MongoDB must be a **replica set** for transactions.

After setup, from the repository root:

```sh
cd backend
docker compose up -d --wait  # Local MongoDB only; skip for a configured remote DB.
../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Run from `backend/` to load its `.env`. Set `AUTH_SIGNING_SECRET` to at least
32 securely random bytes and `AUTH_ALLOWED_ORIGINS` to exact frontend origins
(e.g. `["https://localhost:5173"]`, no trailing slash). There is no fallback secret.
Refresh cookies require HTTPS; do not disable `Secure`. Same-site hosting is
preferred; unrelated sites require `AUTH_COOKIE_SAMESITE=none` and may still face
browser third-party-cookie restrictions. Compose is for local development, not
production; production MongoDB needs authentication, access controls, and TLS.

## API

Paths start with `/api/v1`. Interactive documentation is available at `/docs`.

| Method | Path | Requirements |
| --- | --- | --- |
| POST | `/users` | Public; JSON `email`, `password` |
| POST | `/auth/login` | Allowed Origin; JSON `email`, `password` |
| POST | `/auth/refresh` | Allowed Origin and refresh cookie |
| POST | `/auth/logout` | Allowed Origin; clears refresh cookie |
| GET | `/auth/sessions` | Bearer JWT; lists own sessions |
| DELETE | `/auth/sessions/{session_id}` | Bearer JWT; closes own session |
| DELETE | `/auth/sessions` | Bearer JWT; closes all own sessions |
| GET | `/users/me` | Bearer JWT |
| PATCH | `/users/me` | Bearer JWT; `current_password` plus `name`, `email`, and/or `new_password` |
| POST | `/users/me/disable` | Bearer JWT; disables account and closes all sessions |
| DELETE | `/users/me` | Bearer JWT; JSON `current_password`; deletes account and related data |

- Creation returns **201** with `id`, `name`, `email`, `email_verified`; GET/PATCH
  return the same public fields with **200**. Creation does not log in or verify
  email. The initial name is the normalized email local part; duplicates return **409**.
- Passwords require **15–128 characters**, an ASCII digit, and Unicode punctuation
  or a symbol. Spaces are preserved. Names are trimmed, nonunique, 1–128 characters.
- PATCH rejects null/unknown fields and empty updates. Actual email changes reset
  verification; email/password changes revoke all sessions and clear the cookie.
  Name-only changes and unchanged normalized email preserve sessions.
- DELETE returns **204**. Owned boards and descendants are deleted; other owners'
  boards survive with membership removed, departing-owned lists made ownerless,
  and departing-authored messages anonymized. Other users' tasks/replies remain.
  Reusing a deleted email creates a new identity without inherited relationships.
- Board/list/task APIs require bearer authentication and membership; list/task
  management requires list or board ownership. Some board/list/message operations
  exist only as internal services. `/auth/register` and `/auth/password` are retired.

## Authentication and errors

- **Tokens:** login/refresh return `access_token` and `token_type: "bearer"`; keep tokens in memory and send `Authorization: Bearer <token>`.
- **Expiry:** access tokens last up to 15 minutes; sessions expire after 30 days.
- **Cookies:** refresh uses an HttpOnly, Secure cookie scoped to `/api/v1/auth`; send `credentials: "include"`.
- **Origins:** login, refresh, and logout require an explicitly allowed Origin.
- **Refresh:** restore on startup, coordinate across tabs, and never blindly retry one-time rotation.
- **Sign-in required:** clear local auth on `reauthentication_required`, logout, password changes, or closing all sessions.
- **Frontend limits:** no logout controls or automatic access-token renewal yet.
- **Errors:** `{ "error": { "code": "...", "message": "..." } }`; auth/account responses use `Cache-Control: no-store`.
- **422:** invalid fields; inputs are not echoed. **401:** invalid credentials.
- **503 `database_busy`:** transaction retries exhausted.
- **503 `operation_outcome_unknown`:** outcome unconfirmed, not necessarily rolled back; check state before retrying.
- **Retries:** at most three transaction attempts or commit confirmations; ambiguous commits never replay writes.
- **Signing secrets:** keep stable across restarts and shared across instances of the same service. During rotation, distribute verification keys first; retain the old key for 15 minutes + 30 seconds after its last issuance.
- **Logging:** never log credentials, hashes, tokens, or signing secrets; keep PyMongo payload logging disabled.

## Tests

See the [backend test guide](tests/README.md) for setup, equivalence classes,
coverage, and commands, or the [frontend test guide](../frontend/tests/README.md)
for browser tests.

Password recovery, email verification, account re-enablement, and rate limiting
are not implemented; public login is not hardened against automated guessing.
