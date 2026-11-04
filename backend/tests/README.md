# Backend tests

## Test types and organization

- **Unit:** validation, JWT handling, and retry logic without MongoDB.
- **Integration:** API/service behavior against real MongoDB, including rollback
  and competing operations. Retry fakes test control flow, not database guarantees.
- `accounts/`: account creation, updates, deletion, and permissions.
- `auth/`: login, tokens, cookies, and sessions.
- `boards/`, `todo_lists/`, `tasks/`: resource operations and access rules.
- `support/` and `conftest.py`: shared helpers and setup.

## Path groups

| Marker | Cases | Purpose |
| --- | ---: | --- |
| `happy_path` | 21 | Valid inputs and successful operations |
| `unhappy_path` | 59 | Validation, authentication, and authorization failures |
| `regression` | 67 | Stateful lifecycle, integrity, rollback, and concurrency checks |

Regression scenarios may include accepted and denied operations. All three
markers are needed for full coverage.

## Equivalence classes

Test representative inputs that share a validator or guard, rather than every
permutation. Keep distinct outcomes and minimum/maximum boundary cases separate.

| Area | Happy / valid classes | Unhappy / invalid classes |
| --- | --- | --- |
| Registration | Normalized email; preserved Unicode/whitespace password; length boundaries | Missing/wrong-type credentials; malformed email; short/long password; no ASCII digit or punctuation/symbol; unknown field |
| Profile | Partial/combined updates; unchanged email; name boundaries | Empty update; null/invalid fields; missing/incorrect confirmation; duplicate email |
| Identity | Live user/session | Missing token; revoked session; disabled/deleted user; expired, malformed, tampered, or mismatched JWT |
| Origins | Exact allowed origin | Missing/unlisted origin; denied preflight |
| Resources | Owner/member access; canonical relationships; task updates/deletion | Malformed/missing targets; unauthenticated/nonmember access; forbidden ownership changes |
| Sessions | Secure cookies; rotation; logout; owned-session management | Replay; expired/revoked/evicted session; foreign-session access |

- Shared guards use representative method/state pairings, not full cross-products.
- Wrong-password and unknown-email errors must match; JWT claims, algorithms,
  signatures, and retired keys remain distinct checks.
- Access-token expiration permits refresh; session expiration does not.
- Rollback checks intercept real writes; event gates control race ordering.

## Module guide

Both `accounts/` and `auth/` use these modules:

| Module | Purpose |
| --- | --- |
| `test_happy_paths.py` | Successful operations |
| `test_invalid_inputs.py` | Request and configuration validation |
| `test_authorization.py` | Identity and permission enforcement |
| `test_data_integrity.py` | Stored-state and lifecycle guarantees |
| `test_concurrency.py` | Competing operations |

`accounts/test_rollback.py` owns shared transaction failure/retry checks.
See the [backend API guide](../README.md#api) for application behavior.

## Test setup

- Set `TEST_MONGODB_URI` in the environment or `backend/.env` (environment wins).
- Use a **disposable development replica set**, never production. Fixtures create
  and drop isolated `hearth_test_*` databases; they never fall back to `MONGODB_URI`.
- Without a test URI, integration tests skip; unit results do not prove database safety.
- FastAPI runs in-process. No separate backend server or Caddy is required.

## Run

From the repository root, after `uv sync`:

```sh
# All backend tests.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q

# Select a path group; substitute unhappy_path or regression as needed.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -m happy_path -q

# Select a feature; substitute auth, boards, tasks, or todo_lists as needed.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/accounts -q

# Inspect parameterized cases without executing them.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests --collect-only -q
```

[Frontend browser tests](../../frontend/tests/README.md) are separate.
