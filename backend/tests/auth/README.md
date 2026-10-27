# Authentication and session test organization

The auth/session/security suite uses the same categories as the
[account tests](../accounts/README.md). It contains **25 cases in five modules**,
down from 27 overlapping examples in the former flat auth/security modules.
Distinct security mechanisms were not collapsed into generic "negative" tests.

## Categories

| Category / module | Cases | Guarantees |
| --- | ---: | --- |
| Happy paths - `test_happy_paths.py` | 1 | Login without email verification, normalized credentials, secure refresh-cookie attributes, JWT/session/user linkage, hashed refresh storage, fixed lifetime, safe session listing, and accepted bearer authentication |
| Invalid inputs - `test_invalid_inputs.py` | 4 | Wrong-password/unknown-email failures are indistinguishable and create no session; username-based login fails safely; missing password-policy digit/symbol classes fail; missing signing secret fails closed |
| Authorization - `test_authorization.py` | 11 | Expired access vs. session expiration; disabled/deleted accounts including externally restored sessions; Origin enforcement; missing/malformed/tampered/mismatched JWTs; issuer, audience, required session claim, signing algorithms, keys, and key rotation |
| Data integrity - `test_data_integrity.py` | 4 | One-time refresh rotation and replay rejection without extending lifetime; current-session-only/idempotent logout; oldest-session eviction, foreign-session isolation, individual/all-owned-session closure; Argon2id verification; unique JWT IDs and session-capped expiration |
| Concurrency - `test_concurrency.py` | 5 | Concurrent login session cap with bounded-contention errors; one-winner refresh rotation; login racing password change/disable/deletion; logout racing refresh |

**Rollback is shared, not duplicated.** The existing 18 cases in
`../accounts/test_rollback.py` exercise the shared `AuthService.transaction` retry
and commit-confirmation mechanism, plus real account/session rollback during
PATCH and deletion. Those cases remain separate and unchanged. This refactor does
not claim new failure-injection coverage for session creation/refresh specifically.

## What was deduplicated

- Remove the short-password policy example already covered by account input and
  length-boundary tests. Keep missing-digit and missing-punctuation/symbol cases:
  they exercise different validation rules.
- Remove the standalone registration Unicode/whitespace normalization example:
  account creation already proves exact preservation through a real Argon2id
  hash, and the account schema cases exercise normalization.
- Login's happy path no longer repeats duplicate registration or makes a second
  login solely to inspect another cookie. The account registration race now
  asserts the exact duplicate-email code/message as well as one database winner.
- Invalid-login testing no longer repeats invalid account-creation requests.
- Account password-change success/failure and revocation are owned by the account
  categories. The old-password login rejection assertion is retained there, and
  password-confirmation failures now verify that **multiple** owned sessions stay
  untouched. The auth authorization case concentrates on disabling an account and
  rejects a valid old session even if it is externally reinserted.
- Session-cap testing reuses its last valid token after checking eviction instead
  of performing an unnecessary seventh login just to restore authentication.

The existing multi-step auth/session lifecycle scenarios retain their state and
isolation assertions; they are not loops added to hide independent examples.
All original auth concurrency assertions and parameter combinations are retained.
Issuer vs. audience and wrong algorithm vs. wrong signature stay separate cases.

## Shared helpers and running

`../support/auth.py` owns HTTP login/registration helpers, test credentials, portal
calls, and JWT session fixtures. Account and resource tests import those helpers
directly rather than importing a test module. No application logic changed.

From the repository root:

```sh
# Authentication/session/security categories.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/auth -q

# Shared rollback/retry checks.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/accounts/test_rollback.py -q

# Complete backend suite, excluding browser tests.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q \
  --ignore=backend/tests/frontend
```

Integration tests require `TEST_MONGODB_URI` in the environment or `backend/.env`.
Use a disposable development replica set; fixtures create and drop isolated
`hearth_test_*` databases. Missing configuration skips integration tests rather
than substituting mocks for transaction/concurrency behavior. Browser/frontend,
load/rate-limit, and client retry UX tests remain outside this backend run.
