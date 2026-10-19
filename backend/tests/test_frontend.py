from pathlib import Path
import pytest
from playwright.sync_api import Page, expect

FRONTEND_HTML_PATH = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"
)

# Test 1: HTML structure and initial element presence
def test_frontend_initial_layout(page: Page):
    page.goto(FRONTEND_HTML_PATH.as_uri())

    heading = page.locator("h1")
    button = page.locator("#load-users-btn")
    output = page.locator("#content-output")

    expect(heading).to_have_text("Users Dashboard")
    expect(button).to_be_visible()
    expect(output).to_contain_text("Click the button to load users...")

# Test 2: Button click triggers API mock and renders raw HTML cards
def test_button_click_renders_user_markup(page: Page):
    # Intercept the FastAPI route call
    page.route(
        "**/api/v1/users/",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id": 10, "email": "clara@uf.edu", "is_active": true}]',
        ),
    )

    page.goto(FRONTEND_HTML_PATH.as_uri())
    page.locator("#load-users-btn").click()

    user_card = page.locator('.user-card[data-user-id="10"]')
    expect(user_card).to_be_visible()
    expect(user_card).to_contain_text("clara@uf.edu")
    expect(user_card).to_contain_text("Status: Active")