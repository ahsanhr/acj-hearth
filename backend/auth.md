# Authentication plan

Account creation, profile/password changes, and permanent deletion are implemented
under the [account API contract](README.md#api): public
`POST /api/v1/users` and authenticated `GET`, `PATCH`, `DELETE /api/v1/users/me`.
The former `/auth/register` and `/auth/password` routes are retired. Transaction
and commit-confirmation retries are capped at three total attempts; exhausted
contention may return `database_busy`, and an unconfirmed commit returns
`operation_outcome_unknown` without replaying its writes.

## Purpose

Support public registration, authenticate users at login, and validate their access to protected API requests. Manage password changes, account revocation, sessions, JWT access tokens, and refresh tokens.

Target a small project with one backend application, potentially running multiple instances. Use MongoDB only; do not add Redis. Password recovery, email verification, and rate limiting are out of scope for this version. Without rate limiting, login remains exposed to automated password guessing.

## Requirements

### Registration and password changes

- Allow public registration with email and password; users can log in immediately without email verification. Do not treat email ownership as verified.
- Trim surrounding email whitespace and normalize emails consistently for case-insensitive registration and login. Enforce uniqueness with a MongoDB unique index on the normalized email.
- Return HTTP 409 for duplicate registration with the message `An account with this email already exists.` This intentionally reveals account existence.
- Require passwords of 15–128 characters, including at least one ASCII digit (`0–9`) and one punctuation or symbol character. Whitespace does not count as a special character. Allow Unicode and spaces; never trim or silently truncate passwords.
- Apply the same password policy to registration and password changes, not to verification of existing passwords during login.
- Password changes require an authenticated user, the current password, and a valid new password. Verify the current password, store a new Argon2id hash, and delete all of the user's sessions, requiring a fresh login.
- Password recovery without the current password is out of scope.

### Login and token issuance

- Accept email and password for login; username login is not supported.
- Verify the user's password before creating a session.
- Use the user's MongoDB `_id` as the canonical user identifier, serialized as a string in JWT `sub`.
- Hash passwords and refresh tokens; never store their raw values.
- Use Argon2id through a maintained library to hash and verify passwords.
- Generate a new, unique `session_id` for each successful login.
- Issue a JWT access token and a refresh token tied to that session.
- Include the user ID (`sub`), session ID (`sid`), expiration (`exp`), and a unique token ID (`jti`) in each access JWT. A unique `jti` prevents separate token issuances from producing identical JWTs, even within the same second.
- Access JWTs have a 15-minute lifetime, capped at the session's expiration.
- Refreshed JWTs reuse the existing session ID but receive a new token ID.
- Return HTTP 401 with `Invalid email or password.` for unknown emails and incorrect passwords; do not distinguish those cases in responses.

### JWT signing and validation policy

- Use HS256 and explicitly allow only that algorithm during validation.
- Generate a signing secret containing at least 32 random bytes, store it outside source control, and share it securely across backend instances.
- Require `sub`, `sid`, `exp`, `iat`, `jti`, `iss`, and `aud`, validating their types and formats. Configure the expected issuer and audience consistently across instances.
- Use a `kid` header to select from configured keys only. Sign with the current key; temporarily accept the previous key during rotation. Never load keys from token-supplied URLs or paths.
- Keep the previous key available until its issued access tokens have expired, including clock-skew allowance; reject unknown key IDs.
- Allow up to 30 seconds of clock skew for JWT time validation. Session and refresh-token expiration checks have no grace period.

### Request validation

- Verify the JWT signature and expiration before trusting its claims.
- Extract the session ID from the verified JWT.
- Check that the session exists, has not expired, and belongs to the user identified by the JWT.
- Confirm that the user still exists and is not disabled. Deleted or disabled users cannot log in, refresh, or access protected endpoints.
- Reject requests when any validation fails.

### Session management

- Allow a maximum of five sessions per user.
- When a sixth session is created, delete the oldest session based on `created_at`.
- Enforce the limit even when logins occur concurrently.
- Require a MongoDB replica set in development and production. Use a transaction with a shared per-user write to serialize competing logins, create the session, and remove excess oldest sessions. Retry transaction conflicts using bounded retries.
- Password changes and account disabling/deletion must delete all owned sessions. Coordinate these operations with session creation through the same per-user write and transaction, so a racing login cannot escape revocation. Recheck account state and credential version before committing a login.
- Allow users to list their own sessions, close a session, and clear all their sessions.
- Restrict every session operation to the authenticated user's sessions.
- Normal logout deletes only the current session. Provide separate operations to close another owned session or all owned sessions.
- Deleting a session invalidates its access and refresh tokens, even if their expiration times have not passed.
- Sessions expire 30 days after creation. This fixed expiration is never extended by refresh.
- Do not expose refresh-token hashes when listing sessions.

### Token refresh

- Allow an expired access token to be replaced using a valid refresh token tied to an active session.
- Do not accept an expired access JWT alone as authorization to refresh.
- Reject refresh tokens associated with deleted or expired sessions.
- Refresh tokens have a maximum lifetime of 30 days, capped at the session's fixed expiration.
- Rotate the refresh token on every successful refresh and invalidate the previous token atomically, so concurrent requests cannot reuse it.
- Refreshing must not extend session expiration.
- Generate refresh tokens using Python `secrets.token_urlsafe(32)`. Store only the SHA-256 hash and locate sessions using a unique index on that hash; never accept the hash itself as a credential.
- Use strict rotation with no reuse/grace window. Match the old hash and unexpired session/token in an atomic conditional update; only one concurrent refresh can succeed. Ensure the user is still active before authorizing refresh.
- Invalid, expired, or reused refresh tokens return HTTP 401 with `{"error":{"code":"reauthentication_required","message":"Your session could not be renewed. Please sign in again."}}`.
- A failed refresh does not automatically revoke an otherwise active session.
- The frontend must display the renewal failure and return the user to login. Coordinate refreshes across tabs to avoid competing requests.
- If rotation succeeds but the response is lost, the old token cannot recover the session; reauthentication may be required. This is an accepted limitation.

### Browser token handling

- Return the access JWT in the response body; the browser keeps it in memory and sends it using the `Authorization: Bearer` header.
- Deliver refresh tokens only through an `HttpOnly`, `Secure` cookie, not in response bodies or browser local storage. Make SameSite configurable, defaulting to `Lax`.
- Hosting is not yet decided. Cross-site frontend/API deployments require `SameSite=None; Secure`, explicit credentialed CORS configuration, and strict Origin validation; `Lax` does not support cross-site fetch-based refresh.
- Replace the cookie on refresh and clear it on current-session logout or when clearing all sessions.
- Set cookie expiration to match `refresh_expires_at` and avoid setting a broad cookie domain.
- Protect cookie-authenticated endpoints against CSRF with server-side Origin validation against configured allowed origins, in addition to SameSite restrictions.
- Current-session logout may authenticate directly with the refresh cookie, without a valid access JWT. Validate Origin, delete the matching session, and clear the cookie. If the cookie/session is missing or already invalid, still clear the cookie and return success. The refresh cookie must not authorize listing sessions or deleting other sessions.

### Implementation preferences

- Prefer in-house application logic and Python standard-library functionality over unnecessary external dependencies.
- Do not implement custom cryptographic algorithms or password hashing. Use established cryptographic implementations and a maintained JWT library for signing and validation.
- Use a password-specific hash for passwords and standard-library SHA-256 for high-entropy refresh tokens.
- Select a maintained Argon2id implementation and update dependencies: the existing `passlib[bcrypt]` requirement does not implement the chosen password-hashing policy.
- Never log passwords, raw refresh tokens, access JWTs, or signing secrets. Use HTTPS for browser authentication.

## Data model

The users collection must contain a normalized unique email, Argon2id password hash, disabled status, and a per-user authentication version/serialization field. Use the latter to coordinate login with password changes and account revocation.

Create a `sessions` collection with these fields:

| Field | Purpose |
| --- | --- |
| `session_id` | Unique, randomly generated session identifier |
| `user_id` | Reference to the owner's MongoDB `_id` |
| `created_at` | Creation time, used to identify the oldest session |
| `expires_at` | Fixed session expiration: `created_at` plus 30 days |
| `refresh_expires_at` | Current refresh-token expiration, no later than `expires_at` |
| `refresh_token_hash` | Hash used to verify the current refresh token |

Enforce unique database indexes on `session_id` and `refresh_token_hash`, plus an index on `(user_id, created_at, session_id)` for session listing and deterministic oldest-session eviction. A collision must never overwrite or reuse an existing session; retry with a new identifier/token. JWTs do not need to be stored in the collection.

Store timestamps in UTC. Reject sessions and refresh tokens when `now >= expires_at` or `now >= refresh_expires_at`, respectively. A TTL index on `expires_at` may clean up documents, but MongoDB TTL deletion is asynchronous and must never replace expiration validation.

## Flows

### Registration

1. Normalize the email and validate the password policy.
2. Hash the password with Argon2id and create an enabled user under the unique normalized-email index.
3. Return HTTP 409 with the agreed message on a duplicate email, including concurrent registrations.
4. Allow the user to log in immediately; email ownership is not verified.

### Login

1. Normalize the email, verify the password, and reject disabled or missing users.
2. Generate a unique session ID and refresh token.
3. In a transaction, serialize through the per-user write, recheck account/credential state, create the session, and enforce the five-session limit.
4. Issue a JWT with all required claims, capped at session expiration.
5. Return the access JWT in the response body and set the secure refresh-token cookie.

### Protected request

1. Verify the JWT signature and expiration.
2. Read the user ID and session ID from the verified claims.
3. Confirm the session exists, has not expired, and belongs to that user; confirm the user exists and is enabled.
4. Allow the request only if all checks pass.

### Refresh

1. Validate the request origin and read the refresh token from its cookie.
2. Hash the refresh token with SHA-256 and locate the session by its indexed hash; check `refresh_expires_at`.
3. Confirm the session is active, has not reached its fixed expiration, and belongs to an existing enabled user.
4. Atomically replace the refresh-token hash and expiration, rejecting reuse of the old token. Cap the new expiration at the session expiration.
5. Issue a new access JWT for the same session with a new token ID and expiration capped at the session expiration, and replace the refresh-token cookie.
6. On an invalid, expired, or reused token, return the agreed HTTP 401 reauthentication error without automatically revoking the session.

### Logout or clear sessions

1. For current-session logout, validate Origin and use the refresh cookie to locate the session; a valid access JWT is not required. For other-session deletion or clearing all sessions, require an authenticated user.
2. Delete only the current cookie's session or the requested sessions owned by the authenticated user.
3. Clear the refresh-token cookie for current-session logout or when clearing all sessions. Current-session logout succeeds even when its session is already gone.
4. Reject subsequent access and refresh attempts associated with the deleted sessions.

### Password change and account revocation

1. For password change, authenticate the user, verify the current password, and validate/hash the new password.
2. Serialize through the same per-user transaction mechanism as login. Update the password or disable/delete the account, and delete all owned sessions atomically.
3. Clear the caller's refresh cookie when applicable. Require a new login after password change; disabled or deleted accounts cannot log in.

## Tests

### Login and uniqueness

- Correct email/password credentials succeed; incorrect credentials and username-based login fail.
- JWT `sub` and the session's `user_id` identify the same MongoDB user `_id`.
- Creating a session assigns a session ID.
- Separate successful logins produce distinct session IDs and distinct JWTs, including logins within the same second. Verify that existing sessions are not overwritten.
- Simulate a session-ID collision and verify that creation retries with a new ID without modifying the existing session.
- Refreshing issues a distinct JWT with a new token ID while retaining the same session ID.
- Passwords are stored as Argon2id hashes and verify correctly; refresh tokens are stored as hashes, not raw values.

### Request validation

- A valid JWT tied to an active session grants authentication.
- Missing, malformed, expired, tampered, or incorrectly signed JWTs are rejected.
- JWTs referencing missing, expired, or mismatched sessions are rejected.
- After a session is closed, its JWT is rejected even if the JWT has not expired.
- Access JWTs expire after 15 minutes or at session expiration, whichever is earlier.
- Reject unexpected algorithms, wrong issuer/audience, unknown key IDs, and missing or wrongly typed required claims.
- Test current/previous signing keys during rotation and rejection after the old key is retired.
- Deleted and disabled users cannot log in, refresh, or access protected endpoints, even if a stale session document exists.

### Session management

- Users can retrieve their own session list without exposing refresh-token hashes.
- A sixth login removes the oldest session, and that session's access and refresh tokens stop working.
- Concurrent logins do not exceed the five-session limit.
- Clearing sessions invalidates all access and refresh tokens tied to that user without affecting other users.
- Users cannot list, close, or modify another user's sessions.
- Normal logout closes only the current session; closing another owned session leaves the current session active.
- Sessions expire exactly 30 days after creation; refreshing does not move that expiration.
- Password changes and account disabling/deletion remove every owned session without affecting other users.
- Race login against password change and account disabling/deletion; no session may escape the revocation policy.
- Test concurrent login enforcement using a real replica-set MongoDB deployment and transaction retries.
- Expiration checks reject at the exact boundary even if TTL cleanup has not removed the document.

### Token refresh

- A valid refresh token issues a new access JWT, including when the previous access JWT has expired.
- Invalid or expired refresh tokens are rejected.
- Refresh tokens belonging to deleted or expired sessions are rejected.
- Every successful refresh rotates the refresh token; the previous token cannot be reused, including through concurrent requests.
- Refresh tokens expire within 30 days and never outlive their session.
- Refresh updates `refresh_expires_at` without extending the fixed session expiration.
- Only one concurrent request with the same refresh token succeeds.
- Invalid, expired, and reused refresh tokens produce the agreed HTTP 401 code/message without automatically revoking active sessions.
- Simulate a lost successful refresh response: retrying the old token fails and the frontend prompts for login.
- Confirm stored hashes cannot be submitted in place of raw refresh tokens.

### Browser security

- Refresh-token cookies have `HttpOnly`, `Secure`, configured SameSite (default `Lax`), and the correct expiration.
- Refresh tokens are not included in response bodies or session listings.
- Current-session logout and clearing all sessions remove the refresh-token cookie.
- Cookie-authenticated requests from disallowed origins are rejected.
- Logout succeeds using only the refresh cookie after access-token expiration or tab reopening, and clears the cookie even if the session is missing.
- The frontend displays the reauthentication message on refresh failure.

### Registration and password changes

- Registration normalizes email and rejects case-insensitive duplicates with HTTP 409 and the agreed message, including simultaneous registrations.
- New users can log in without email verification; their email is not treated as verified.
- Passwords must have 15–128 characters, at least one ASCII digit, and at least one punctuation/symbol character. Whitespace alone does not satisfy the special-character rule.
- Unicode and spaces are preserved; passwords are never trimmed or truncated.
- Password changes reject the wrong current password and invalid new passwords; successful changes store a new Argon2id hash and invalidate every existing session.
- Unknown email and incorrect password login failures share the same HTTP 401 message.
