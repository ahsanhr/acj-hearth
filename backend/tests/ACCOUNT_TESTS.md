# Account service TDD tests

The condensed suite verifies the [account API contract](../README.md#api) through
concrete resource service boundaries. It has **144 parameterized account cases
in seven modules**: the condensed 130 plus 14 checks connected as the previously
deferred content boundaries were implemented. Existing security/auth tests supply
shared token and password-policy coverage. Missing behavior must fail, not `xfail`.

## Run

From the repository root, with the existing dependencies:

```sh
# Unit checks; integration tests skip if no test URI exists in env or backend/.env.
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_account*.py -q

# Full backend acceptance suite against a DISPOSABLE MongoDB replica set.
TEST_MONGODB_URI='mongodb://localhost:27017/?replicaSet=rs0' \
  PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q \
  --ignore=backend/tests/test_frontend.py
```

`backend/compose.yaml` provides a local replica set. The `api` fixture creates
and drops an isolated `hearth_test_*` database, checks replica-set support at
startup, and redirects resource services away from the development database.
Never use production. Test database names fit Atlas's 38-byte limit. Set
`TEST_MONGODB_URI` in the environment or `backend/.env` (environment wins); tests
never use `MONGODB_URI` as a fallback. Unit-only success does **not** establish
ACID behavior.

## Coverage and organization

| Module | Distinct guarantees |
| --- | --- |
| `test_account_schemas.py` | Public allowlist/serializer, registration allowlist, password boundaries/Unicode, missing/null/wrong-type/extra input |
| `test_account_api.py` | Public canonical creation without login; strict request envelopes; active identity on every route; current-password confirmation; partial/combined updates; name boundaries; normalization; duplicate-email atomicity; caller-only targets; session/cookie revocation; secret/log protection; retired routes; CORS |
| `test_account_deletion.py` | Owned-board cascade, surviving replies/tasks/conversations, anonymous tombstones, multiple null list owners, unrelated-data isolation, fresh identity after email reuse, database uniqueness and startup indexes |
| `test_account_resources.py` | Canonical BSON references, protected/initialized board counter, shared transactions across resource mutations, tombstone serialization/irreversibility, cached-data removal, protected authors, missing-message upserts, content/deletion races |
| `test_account_races.py` | Concurrent duplicate registration/PATCH, stale identity/password/session rejection, other members' creation racing board deletion, stale writes after membership cleanup |
| `test_account_failures.py` | Real post-write failure rollback for combined PATCH and every cleanup collection; all cleanup writes in one transaction |
| `test_account_transactions.py` | Three-attempt limits; confirmed-abort retry; commit confirmation without replay; real committed-but-unconfirmed PATCH/DELETE; lost creation acknowledgement |

All account routes are tested for missing/revoked sessions and disabled/deleted
accounts. JWT syntax, tampering, expiry, expired sessions, issuer/audience, and
key rotation are tested once through the shared auth dependency in
`test_auth_api.py` and `test_security.py`, not repeated for every account route.
Likewise, exhaustive password permutations belong at the schema/security layer;
the API retains representative invalid-password checks and proves exact Unicode
and whitespace preservation through stored Argon2id hashes.

Concurrency cases cover each relevant mechanism and pending operation without
an exhaustive Cartesian product. Event gates establish stale-identity ordering;
concurrent requests exercise database write conflicts. Failure injection wraps
real PyMongo writes and raises **after** them. Retry-control fakes establish
counts/control flow only, not atomicity. Merely discarding a successful response
is no longer a separate test: lost acknowledgement/commit tests already prove
that a committed operation can have an uncertain result.

## Connected content boundaries and resource regressions

The speculative adapters were removed during condensation. Once concrete
message, board-edit, and list-edit services existed, their checks were connected
directly in `test_account_resources.py`; no speculative signatures or HTTP
endpoints are required. All the formerly deferred content acceptance categories
now have executable coverage:

- Anonymous tombstone reads, retained replies, removal of cached author/content
  fields, irreversible markers, protected authors, and non-upserting edits.
- Message creation/edits racing account/parent-board deletion, with all mutation
  writes sharing the same account/board transaction.
- Other members' descendant edits racing owned-board deletion without recreating
  deleted parents or data.

`test_board.py`, `test_todo_list.py`, and `test_task.py` now use real authenticated
transactions and canonical BSON references instead of unauthenticated legacy
string-ID mocks. They cover scoped reads, list uniqueness, partial task updates,
invalid/missing parents, owner-only management of retained ownerless lists, and
membership edits racing account cleanup.

The auth concurrency regression accepts only the documented `503 database_busy`
when three attempts exhaust under contention; it still requires a successful
transaction, unique session IDs, the exact session count implied by successful
logins (capped at five), and strict one-winner refresh rotation.

## Scope boundaries

- Boards have one creator/owner and may have multiple members. Friend invites,
  acceptance, and friend-list management are a separate feature.
- Client retry/unknown-outcome UX and browser cookie processing are not proven
  by backend tests. No safe replay of ambiguously delivered requests is promised.
- Idempotency, rate limiting, deletion load/capacity tests, and frontend work are
  deferred. No migrations or compatibility routes are included.
- Fixtures use BSON ObjectIds, a `deleted: true` tombstone marker, nullable
  author/list-owner references, and millisecond-precision BSON datetimes.
