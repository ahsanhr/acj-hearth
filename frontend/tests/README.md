# Frontend browser tests

The tests serve `frontend/` over a temporary local HTTP server and exercise the
real JavaScript in Chromium. API responses are mocked before navigation, so no
MongoDB, backend process, or HTTPS setup is required for these UI tests.

Coverage includes:

- Login, registration followed by login/name update, and logout.
- Authentication errors and session restoration.
- Home-page board cards, navigation history, direct board links, and empty states.
- Creating boards and lists.
- Dragging notes, keyboard movement, persisted positions, and failed-save rollback.
- Creating, completing, editing, and deleting tasks.
- Failed task writes and checkbox rollback.
- Invitation generation, link prefilling, and acceptance.
- Coordinating concurrent requests during token renewal and failed renewal.
- Read-only permissions and rendering user content as text, not HTML.

From the repository root:

```sh
uv run playwright install chromium  # One-time browser installation.
uv run pytest frontend/tests -q
```

With an existing virtual environment, use `.venv/bin/python -m pytest` instead
of `uv run pytest`.

These tests verify browser behavior and request payloads, not real database or
cookie security behavior. For a manual integration check, run the app following
the [root README](../../README.md), use two accounts to share a board through an
invitation, move a note with its handle, and verify tasks and positions persist
for both accounts after refresh. HTTPS is required for the
real backend's secure refresh cookie.

For backend tests, see the [backend test guide](../../backend/tests/README.md).
