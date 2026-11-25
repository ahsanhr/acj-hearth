import json
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

FRONTEND_PATH = Path(__file__).resolve().parents[1]


@pytest.fixture
def api_state():
    return {
        "user": {"id": "user-1", "name": "Alex", "email": "alex@example.com"},
        "boards": [{"_id": "board-1", "boardName": "Family", "createdBy": "user-1"}],
        "lists": [
            {
                "_id": "list-1",
                "boardID": "board-1",
                "ownerID": "user-1",
                "title": "My chores",
            }
        ],
        "tasks": [
            {
                "_id": "task-1",
                "listID": "list-1",
                "title": "Wash dishes",
                "description": "After dinner",
                "dueDate": "2026-12-01",
                "completed": False,
            }
        ],
        "requests": [],
        "restored": False,
        "refreshes": 0,
        "fail_login": False,
        "expire_tasks": False,
        "fail_refresh": False,
        "fail_task_write": False,
        "fail_position_write": False,
    }


def mock_api(route, state):
    request = route.request
    path = urlparse(request.url).path.removeprefix("/api/v1")
    method = request.method
    body = request.post_data_json if request.post_data else None
    state["requests"].append((method, path, body, request.headers))

    def respond(data=None, status=200):
        route.fulfill(
            status=status,
            content_type="application/json",
            body="" if status == 204 else json.dumps(data),
        )

    def fail(message, status=401):
        respond({"error": {"message": message}}, status)

    if path == "/auth/refresh":
        state["refreshes"] += 1
        if not state["restored"] or state["fail_refresh"]:
            fail("Your session could not be renewed. Please sign in again.")
        else:
            respond({"access_token": "renewed-token"})
    elif path == "/auth/login":
        if state["fail_login"]:
            fail("Invalid email or password.")
        else:
            state["restored"] = True
            respond({"access_token": "login-token"})
    elif path == "/auth/logout":
        state["restored"] = False
        respond(status=204)
    elif path == "/users" and method == "POST":
        respond(state["user"], 201)
    elif path == "/users/me":
        if method == "PATCH":
            state["user"]["name"] = body["name"]
        respond(state["user"])
    elif not request.headers.get("authorization"):
        fail("Authentication required.")
    elif path == "/boards/":
        if method == "POST":
            board = {"_id": "board-2", **body}
            state["boards"].append(board)
            respond(board, 201)
        else:
            respond(state["boards"])
    elif path.endswith("/lists/"):
        board_id = path.split("/")[2]
        if method == "POST":
            todo_list = {"_id": "list-2", "boardID": board_id, **body}
            state["lists"].append(todo_list)
            respond(todo_list, 201)
        else:
            respond([row for row in state["lists"] if row["boardID"] == board_id])
    elif path.startswith("/lists/") and path.endswith("/tasks/"):
        list_id = path.split("/")[2]
        if state["expire_tasks"] and request.headers["authorization"] != (
            "Bearer renewed-token"
        ):
            fail("Authentication required.")
        elif method == "POST":
            task = {"_id": "task-2", "listID": list_id, "completed": False, **body}
            state["tasks"].append(task)
            respond(task, 201)
        else:
            respond([row for row in state["tasks"] if row["listID"] == list_id])
    elif path.startswith("/lists/") and method == "PATCH":
        if state["fail_position_write"]:
            fail("Cannot save note position.", 503)
            return
        todo_list = next(
            row for row in state["lists"] if row["_id"] == path.split("/")[2]
        )
        todo_list.update(body)
        respond(todo_list)
    elif path.startswith("/tasks/"):
        task_id = path.split("/")[2]
        if state["fail_task_write"]:
            fail("Cannot save task.", 503)
            return
        task = next(row for row in state["tasks"] if row["_id"] == task_id)
        if method == "DELETE":
            state["tasks"].remove(task)
            respond({"message": "Deleted"})
        else:
            task.update(body)
            respond(task)
    elif path.endswith("/invitations"):
        respond({"token": "share-token", "expiresAt": "2026-12-01"}, 201)
    elif path == "/boards/invitations/share-token/accept":
        respond({"boardID": "board-1"})
    else:
        fail(f"Unexpected API request: {method} {path}", 404)


@pytest.fixture
def frontend_page(api_state):
    handler = partial(SimpleHTTPRequestHandler, directory=str(FRONTEND_PATH))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.route("**/api/v1/**", lambda route: mock_api(route, api_state))
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                yield page
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def sign_in(page, open_board=True):
    page.locator("#btn-goto-login").click()
    page.locator("#login-email").fill("alex@example.com")
    page.locator("#login-password").fill("existing-password")
    page.locator("#form-login").get_by_role("button", name="enter", exact=True).click()
    expect(page.locator("#home-page")).to_be_visible()
    expect(page.locator("#board-cards")).to_contain_text("Family")
    if open_board:
        page.locator('[data-board-id="board-1"]').click()
        expect(page.locator("#lists")).to_contain_text("My chores")


def test_login_loads_board_and_logout(frontend_page, api_state):
    page = frontend_page
    expect(page.locator("#view-welcome")).to_be_visible()
    sign_in(page)
    expect(page.locator("#modal-view")).not_to_be_visible()
    expect(page.locator("#board-heading")).to_have_text("Family")
    expect(page.get_by_role("checkbox", name="Wash dishes")).not_to_be_checked()
    assert any(
        headers.get("authorization") == "Bearer login-token"
        for _, path, _, headers in api_state["requests"]
        if path == "/boards/"
    )
    page.locator("#btn-logout").click()
    expect(page.locator("#view-login")).to_be_visible()
    expect(page.locator("#workspace")).not_to_be_visible()
    assert page.evaluate("localStorage.length") == 0


def test_signup_registers_then_saves_name(frontend_page, api_state):
    page = frontend_page
    page.locator("#btn-goto-signup").click()
    page.locator("#signup-name").fill("Taylor")
    page.locator("#signup-email").fill("taylor@example.com")
    page.locator("#signup-password").fill("a-long-password1!")
    page.locator("#form-signup").get_by_role("button", name="enter").click()
    expect(page.locator("#user-display-name")).to_have_text("Taylor")
    registration = next(
        body
        for method, path, body, _ in api_state["requests"]
        if method == "POST" and path == "/users"
    )
    assert registration == {
        "email": "taylor@example.com",
        "password": "a-long-password1!",
    }
    assert any(
        method == "PATCH"
        and path == "/users/me"
        and body == {"name": "Taylor", "current_password": "a-long-password1!"}
        for method, path, body, _ in api_state["requests"]
    )


def test_login_error_keeps_form_visible(frontend_page, api_state):
    api_state["fail_login"] = True
    page = frontend_page
    page.locator("#btn-goto-login").click()
    page.locator("#login-email").fill("alex@example.com")
    page.locator("#login-password").fill("wrong")
    page.locator("#form-login").get_by_role("button", name="enter", exact=True).click()
    expect(page.locator("#auth-error")).to_have_text("Invalid email or password.")
    expect(page.locator("#view-login")).to_be_visible()
    expect(page.locator("#form-login button[type=submit]")).to_be_enabled()


def test_create_board_and_list(frontend_page, api_state):
    page = frontend_page
    sign_in(page, open_board=False)
    page.locator("#board-name").fill("Study group")
    page.get_by_role("button", name="Create board", exact=True).click()
    expect(page.locator("#board-heading")).to_have_text("Study group")
    page.locator("#list-title").fill("Homework")
    page.get_by_role("button", name="Create my list").click()
    expect(page.locator("#lists")).to_contain_text("Homework")
    expect(page.locator("#form-list")).not_to_be_visible()
    assert api_state["lists"][-1]["boardID"] == "board-2"
    assert api_state["lists"][-1]["ownerID"] == "user-1"


def test_task_create_complete_edit_delete(frontend_page, api_state):
    page = frontend_page
    sign_in(page)
    note = page.locator('[data-list-id="list-1"]')
    note.get_by_label("New task", exact=True).fill("Buy milk")
    note.get_by_role("button", name="Add task", exact=True).click()
    row = note.locator('[data-task-id="task-2"]')
    checkbox = row.get_by_role("checkbox", name="Buy milk")
    checkbox.check()
    expect(row.locator(".completed")).to_have_text("Buy milk")
    row.get_by_role("button", name="Edit", exact=True).click()
    row.get_by_label("Title", exact=True).fill("Buy oat milk")
    row.get_by_label("Description", exact=True).fill("Two cartons")
    row.get_by_label("Due date", exact=True).fill("2026-12-15")
    row.get_by_role("button", name="Save", exact=True).click()
    expect(row).to_contain_text("Buy oat milk")
    expect(row).to_contain_text("Two cartons")
    expect(row).to_contain_text("2026-12-15")
    page.once("dialog", lambda dialog: dialog.accept())
    row.get_by_role("button", name="Delete", exact=True).click()
    expect(row).to_have_count(0)
    assert len(api_state["tasks"]) == 1


def test_task_failure_rolls_back_checkbox(frontend_page, api_state):
    page = frontend_page
    sign_in(page)
    api_state["fail_task_write"] = True
    checkbox = page.get_by_role("checkbox", name="Wash dishes")
    checkbox.check()
    expect(page.locator("#app-error")).to_have_text("Cannot save task.")
    expect(checkbox).not_to_be_checked()
    expect(checkbox).to_be_enabled()


def test_invitations_and_link_prefill(frontend_page):
    page = frontend_page
    page.goto(f"{page.url}?invite=share-token")
    sign_in(page, open_board=False)
    expect(page.locator("#invitation-token")).to_have_value("share-token")
    page.get_by_role("button", name="Join board", exact=True).click()
    expect(page.locator("#invitation-token")).to_have_value("")
    expect(page).not_to_have_url(re.compile(r"invite="))
    page.get_by_role("button", name="Invite members").click()
    expect(page.locator("#invitation-link")).to_have_value(
        re.compile(r"\?invite=share-token#home$")
    )
    link = page.locator("#invitation-link").input_value()
    page.get_by_role("link", name="Home", exact=True).click()
    page.locator("#invitation-token").fill(link)
    page.get_by_role("button", name="Join board", exact=True).click()
    expect(page.locator("#invitation-token")).to_have_value("")


def test_restore_and_parallel_request_refresh(frontend_page, api_state):
    page = frontend_page
    api_state["restored"] = True
    api_state["lists"].append(
        {"_id": "list-2", "boardID": "board-1", "ownerID": "user-2", "title": "Other"}
    )
    page.reload()
    expect(page.locator("#home-page")).to_be_visible()
    page.locator('[data-board-id="board-1"]').click()
    expect(page.locator("#lists")).to_contain_text("My chores")
    before = api_state["refreshes"]
    # Login issues a different token, so both task fetches will return 401.
    page.locator("#btn-logout").click()
    page.locator("#login-email").fill("alex@example.com")
    page.locator("#login-password").fill("password")
    api_state["expire_tasks"] = True
    page.locator("#form-login").get_by_role("button", name="enter", exact=True).click()
    page.locator('[data-board-id="board-1"]').click()
    expect(page.locator("#lists")).to_contain_text("Other")
    assert api_state["refreshes"] == before + 1


def test_failed_renewal_returns_to_login(frontend_page, api_state):
    page = frontend_page
    sign_in(page)
    api_state["expire_tasks"] = True
    api_state["fail_refresh"] = True
    page.locator("#btn-refresh").click()
    expect(page.locator("#view-login")).to_be_visible()
    expect(page.locator("#auth-error")).to_contain_text("could not be renewed")
    expect(page.locator("#workspace")).not_to_be_visible()


def test_non_owner_has_read_only_tasks_and_safe_text(frontend_page, api_state):
    api_state["boards"][0]["createdBy"] = "user-2"
    api_state["lists"][0]["ownerID"] = "user-2"
    api_state["tasks"][0]["title"] = '<img src=x onerror="alert(1)">'
    page = frontend_page
    sign_in(page)
    note = page.locator('[data-list-id="list-1"]')
    expect(note.get_by_role("checkbox")).to_be_disabled()
    expect(note.get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    expect(note.get_by_role("button", name="Add task", exact=True)).to_have_count(0)
    expect(page.locator("#btn-invite")).not_to_be_visible()
    expect(note).to_contain_text('<img src=x onerror="alert(1)">')
    expect(note.locator("img")).to_have_count(0)
    expect(note.locator(".note-handle")).to_have_count(0)


def test_home_lists_boards_and_navigation_history(frontend_page, api_state):
    api_state["boards"].append(
        {"_id": "board-2", "boardName": "Friends", "createdBy": "user-2"}
    )
    page = frontend_page
    sign_in(page, open_board=False)
    expect(page.get_by_role("navigation", name="Main navigation")).to_be_visible()
    expect(page.locator("#board-cards .board-card")).to_have_count(2)
    expect(page.locator('[data-board-id="board-2"]')).to_contain_text("Shared with you")
    page.locator('[data-board-id="board-2"]').click()
    expect(page.locator("#board-heading")).to_have_text("Friends")
    expect(page.locator("#home-page")).not_to_be_visible()
    page.get_by_role("link", name="Home", exact=True).click()
    expect(page.locator("#home-page")).to_be_visible()
    page.go_back()
    expect(page.locator("#board-heading")).to_have_text("Friends")
    page.reload()
    expect(page.locator("#board-heading")).to_have_text("Friends")
    expect(page.locator("#board-content")).to_be_visible()


def drag_note(page, dx, dy):
    handle = page.locator('[data-list-id="list-1"] .note-handle')
    box = handle.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=8)
    page.mouse.up()


def test_note_drag_is_saved_and_restored(frontend_page, api_state):
    page = frontend_page
    sign_in(page)
    note = page.locator('[data-list-id="list-1"]')
    original = note.evaluate("node => ({ x: node.offsetLeft, y: node.offsetTop })")
    drag_note(page, 150, 80)
    expect(page.locator("#app-status")).to_have_text("Note position saved.")
    expected = {"x": original["x"] + 150, "y": original["y"] + 80}
    assert api_state["lists"][0]["position"] == expected
    page.reload()
    expect(page.locator("#lists")).to_contain_text("My chores")
    expect(note).to_have_css("left", f"{expected['x']}px")
    expect(note).to_have_css("top", f"{expected['y']}px")
    # Task controls remain usable after moving the note.
    note.get_by_role("checkbox", name="Wash dishes").check()
    expect(note.locator(".completed")).to_have_text("Wash dishes")


def test_failed_note_save_rolls_back(frontend_page, api_state):
    page = frontend_page
    sign_in(page)
    api_state["fail_position_write"] = True
    note = page.locator('[data-list-id="list-1"]')
    original = note.evaluate("node => node.style.left")
    drag_note(page, 120, 50)
    expect(page.locator("#app-error")).to_have_text("Cannot save note position.")
    expect(note).to_have_css("left", original)
    expect(note.locator(".note-handle")).to_be_enabled()
    assert "position" not in api_state["lists"][0]


def test_note_keyboard_movement_is_bounded(frontend_page, api_state):
    page = frontend_page
    sign_in(page)
    handle = page.get_by_role("button", name="Move My chores", exact=True)
    handle.focus()
    handle.press("Shift+ArrowRight")
    expect(page.locator("#app-status")).to_have_text("Note position saved.")
    assert api_state["lists"][0]["position"] == {"x": 74, "y": 24}
    handle.press("Shift+ArrowLeft")
    expect(page.locator('[data-list-id="list-1"]')).to_have_css("left", "24px")
    expect(handle).to_be_enabled()
    handle.press("Shift+ArrowLeft")
    expect(page.locator('[data-list-id="list-1"]')).to_have_css("left", "0px")
    expect(handle).to_be_enabled()
    assert api_state["lists"][0]["position"]["x"] == 0


def test_home_empty_state(frontend_page, api_state):
    api_state["boards"].clear()
    page = frontend_page
    page.locator("#btn-goto-login").click()
    page.locator("#login-email").fill("alex@example.com")
    page.locator("#login-password").fill("password")
    page.locator("#form-login").get_by_role("button", name="enter", exact=True).click()
    expect(page.locator("#home-empty")).to_be_visible()
    expect(page.locator("#board-cards .board-card")).to_have_count(0)
    expect(page.locator("#form-board")).to_be_visible()
