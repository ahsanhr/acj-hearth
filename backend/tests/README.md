# Test layout

Tests are grouped by feature, with behavior categories inside the account and
authentication suites:

```text
tests/
├── conftest.py           # Shared settings, isolated MongoDB, account fixtures
├── accounts/             # 123 account cases across six behavior categories
├── auth/                 # 25 auth/session/security cases across five categories
├── boards/               # Board creation, membership, scoped access
├── tasks/                # Authenticated task CRUD and permissions
├── todo_lists/           # List ownership and retained ownerless containers
├── frontend/             # Three Playwright browser cases
└── support/              # Shared helpers; not collected as tests
    ├── accounts.py       # Account fixtures, instrumentation, race gates
    └── auth.py           # Login/registration, credentials, JWT session fixtures
```

Each directory is a Python package so repeated category filenames such as
`accounts/test_authorization.py` and `auth/test_authorization.py` collect without
module-name collisions. The root `conftest.py` applies to every feature; the
MongoDB test URI is still loaded from the environment or `backend/.env`.

See [account coverage](accounts/README.md) and
[auth/session coverage](auth/README.md) for category details. Rollback and
concurrency assertions and parameter sets are unchanged by the directory move.

## Commands

From the repository root:

```sh
# All 172 backend cases; no browser tests.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q \
  --ignore=backend/tests/frontend

# A feature or category.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/accounts -q
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/auth -q
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/accounts/test_rollback.py -q

# Browser tests separately (requires installed Playwright Chromium).
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/frontend -q

# All 175 cases, including browsers.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
```

Integration tests require `TEST_MONGODB_URI` pointing to a disposable development
MongoDB replica set. They create and drop isolated `hearth_test_*` databases;
never use production. Without a test URI, those tests skip. Unit checks alone do
not prove ACID behavior. Browser tests mock API responses and serve the root
`frontend/` directory over a local HTTP server.
