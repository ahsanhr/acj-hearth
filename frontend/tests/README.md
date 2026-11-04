# Frontend browser tests

`test_frontend.py` contains three existing Playwright tests for the frontend
preview:

- Initial page layout and default content.
- Clicking the load button renders the fetched preview HTML.
- A failed API request displays an error message.

The fixture serves the parent `frontend/` directory over a temporary local HTTP
server and opens it in Chromium. Playwright exercises browser JavaScript, clicks,
and DOM updates. API responses for `/api/v1/users/preview` are mocked, so these
are browser UI tests rather than full-stack tests. No MongoDB, backend process,
or backend test fixtures are required.

Playwright and pytest are already provided by the root project's development
dependencies. From the repository root:

```sh
# Install Chromium if it is not already available.
uv run playwright install chromium

# Only the three frontend cases.
uv run pytest frontend/tests -q

# Both suites (backend integration tests need TEST_MONGODB_URI).
PYTHONPATH=backend uv run pytest backend/tests frontend/tests -q
```

When using the existing virtual environment directly, replace `uv run pytest`
with `.venv/bin/python -m pytest`.
