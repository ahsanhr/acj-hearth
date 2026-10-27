from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import expect, sync_playwright

FRONTEND_PATH = Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture
def frontend_page():
    # Serve ES modules over HTTP, as browsers block file:// module imports.
    handler = partial(SimpleHTTPRequestHandler, directory=str(FRONTEND_PATH))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # A function-scoped Playwright lifecycle releases its event loop before
        # pytest-asyncio runs the backend tests in the same pytest invocation.
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                yield page
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_frontend_initial_layout(frontend_page):
    expect(frontend_page.locator("h1")).to_have_text("Users Dashboard")
    expect(frontend_page.locator("#load-users-btn")).to_be_visible()
    expect(frontend_page.locator("#content-output")).to_contain_text(
        "Click the button to load users..."
    )


def test_button_click_renders_preview_markup(frontend_page):
    frontend_page.route(
        "**/api/v1/users/preview",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<h3>API Connection Verified!</h3><p>Status: 200 OK</p>",
        ),
    )
    frontend_page.locator("#load-users-btn").click()
    output = frontend_page.locator("#content-output")
    expect(output.locator("h3")).to_have_text("API Connection Verified!")
    expect(output).to_contain_text("Status: 200 OK")


def test_button_click_reports_api_failure(frontend_page):
    frontend_page.route(
        "**/api/v1/users/preview",
        lambda route: route.fulfill(status=503, body="Service unavailable"),
    )
    frontend_page.locator("#load-users-btn").click()
    expect(frontend_page.locator("#content-output")).to_have_text(
        "Connection failed: HTTP error! status: 503"
    )
