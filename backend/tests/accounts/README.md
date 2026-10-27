# Account test organization

The account suite verifies the [account API contract](../../README.md#api) through
six categories: **123 parameterized cases**, reduced from 144 by removing
overlapping examples. Tests remain independent, with useful parameter IDs;
examples were not hidden inside loops just to reduce the displayed count.

## Categories

| Category / module | Cases | What it establishes |
| --- | ---: | --- |
| Happy paths - `test_happy_paths.py` | 13 | Canonical creation without login; read-only retrieval; name/email/password/combined updates; unchanged email; nonunique aliases; valid name/password boundaries and Unicode |
| Invalid inputs - `test_invalid_inputs.py` | 31 | Malformed/nonobject/null bodies; missing/null/wrong-type fields; empty updates; invalid names/emails/passwords; protected fields and server-managed state |
| Authorization - `test_authorization.py` | 21 | Live identity on mutations; current-password confirmation; caller-only account targets; membership; message authorship; allowed/disallowed origins |
| Data integrity - `test_data_integrity.py` | 22 | DTO/public allowlists; atomic duplicate-email rejection; no secrets in responses/logs; retired routes; deletion cascades and retained replies; fresh identity after email reuse; database constraints; shared transactions; irreversible tombstones and no upserts |
| Rollback - `test_rollback.py` | 18 | Post-write failures during PATCH and every cleanup stage; bounded retries; confirmed aborts; ambiguous commit confirmation without write replay; lost insert acknowledgement |
| Concurrency - `test_concurrency.py` | 18 | Duplicate registrations/updates; stale identities/passwords/sessions; parent deletion racing other members' creation/edits; message/deletion races and membership cleanup |

Related [auth/security tests](../auth/README.md) use the same categories.
Board/list/task regressions live in `../boards/`, `../todo_lists/`, and `../tasks/`.
This organization changes tests and test helpers only, not application behavior.

## Deduplication decisions

- **Public serialization:** creation checks the complete public response with
  verification false; retrieval checks the current verification state as true.
  Separate unit examples repeating both serializer outputs were removed.
- **Password acceptance:** keep minimum length, maximum Unicode length, and
  Unicode punctuation examples. Symbol/whitespace preservation is already proven
  by the creation/hash integration test and `../auth/test_data_integrity.py`.
- **Name boundaries:** test 1/128-character acceptance and invalid length/type
  at the schema layer. One name-only API path still verifies trimming, persistence,
  untouched fields, and session preservation.
- **Invalid requests:** keep representatives for malformed JSON, nonobject data,
  and a null body, rather than repeating the same parser errors on every route.
  Missing/null/wrong-type credential examples remain distinct.
- **Protected fields:** representative rejection tests plus exact request DTO
  allowlists and `extra=forbid` cover unknown/protected fields without enumerating
  every spelling. The caller-only API test exercises both mutation routes.
- **Authentication:** GET denial behavior is covered in
  `../auth/test_authorization.py`. PATCH and DELETE each retain all
  missing/revoked/disabled/deleted states as separate mutation entry points.
- **Password confirmation:** missing confirmation is checked once for the shared
  PATCH DTO; an incorrect password is still tested independently for name, email,
  and password changes, plus deletion.
- **Duplicate email:** the account concurrency test verifies creation duplicates,
  including the exact 409 envelope. The integrity category concentrates on atomic
  multi-field PATCH rejection and the database unique index.
- **Tombstones:** verify removal of cached author/content fields, anonymous reads,
  and irreversible edits once, with an exact 409 expectation. Schema rejection of
  client-supplied deletion state is separate from the tombstone invariant.
- **Transaction observations:** shared helpers replace repeated recording/assertion
  code, but each distinct resource mutation still has its own parameterized case.

All existing rollback/concurrency assertions and parameter combinations were
retained. The creation race additionally checks the duplicate-email error envelope
previously repeated in the auth happy path. Shared instrumentation, request/event
gates, and fixtures live in `../support/accounts.py`; common HTTP auth helpers
live in `../support/auth.py`. Tests never import helpers from test modules.

## Run

From the repository root with the existing dependencies:

```sh
# All account categories (integration tests need a configured test URI).
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/accounts -q

# One category, for example authorization.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/accounts/test_authorization.py -q

# Full backend regression suite; excludes Playwright browser tests.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
```

Set `TEST_MONGODB_URI` in the environment or `backend/.env` (environment wins).
Tests never fall back to `MONGODB_URI`. Use a **disposable development replica
set**, never production: each fixture creates and drops its own `hearth_test_*`
database. Names fit Atlas's 38-byte limit. Without a test URI, integration tests
skip; schema/security/retry-control checks can still run.

Real PyMongo writes are intercepted **after** they execute to prove transaction
rollback, not just avoidance of writes. Event gates establish stale-identity
ordering, and concurrent requests exercise database conflicts. Retry fakes prove
control flow/counts only; a unit-only run does not establish ACID guarantees.

## Scope boundaries

- Internal message/board-edit/list-edit services are tested without inventing
  additional HTTP endpoints or a friend-invitation workflow.
- The board, list, and task feature directories additionally cover scoped reads,
  resource permissions, partial task updates, owner-only management of retained
  ownerless lists, and membership edits racing account cleanup.
- The auth concurrency regression permits only documented `503 database_busy`
  failures when three attempts exhaust, while preserving unique sessions, the
  five-session cap, and strict one-winner refresh rotation.
- Client retry UX, browser cookie processing, rate limiting, idempotency, deletion
  capacity/load testing, and frontend work remain outside this backend suite.
