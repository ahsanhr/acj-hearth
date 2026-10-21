import asyncio

import pytest

from app.services.auth import AuthError
from tests.test_auth_api import EMAIL, PASSWORD, authorize, call, login, register


@pytest.mark.parametrize("action", ["password", "disable", "delete"])
def test_login_cannot_escape_concurrent_revocation(api, monkeypatch, action):
    http, db = api
    register(http)
    authorize(http, login(http))
    service = http.app.state.auth_service
    user = call(http, db.users.find_one, {"email": EMAIL})
    session = call(http, db.sessions.find_one, {})
    original_touch = service.touch_user

    async def race():
        waiting = asyncio.Event()
        proceed = asyncio.Event()

        async def gated_touch(user_id, tx, **conditions):
            if "auth_version" in conditions:  # login has already verified old credentials
                waiting.set()
                await proceed.wait()
            return await original_touch(user_id, tx, **conditions)

        monkeypatch.setattr(service, "touch_user", gated_touch)
        pending_login = asyncio.create_task(service.login(EMAIL, PASSWORD))
        await asyncio.wait_for(waiting.wait(), timeout=10)
        try:
            if action == "password":
                await service.change_password(user, session["session_id"], PASSWORD, "another password!2")
            else:
                await service.revoke_account(user["_id"], delete=action == "delete")
        finally:
            proceed.set()
        return (await asyncio.gather(pending_login, return_exceptions=True))[0]

    result = call(http, race)
    assert isinstance(result, AuthError)
    assert result.status == 401
    assert call(http, db.sessions.count_documents, {}) == 0


def test_logout_identified_before_rotation_still_revokes(api, monkeypatch):
    http, db = api
    register(http)
    service = http.app.state.auth_service
    _, raw = call(http, service.login, EMAIL, PASSWORD)
    original_touch = service.touch_user

    async def race():
        waiting = asyncio.Event()
        proceed = asyncio.Event()

        async def gated_touch(user_id, tx, **conditions):
            if asyncio.current_task().get_name() == "logout":
                waiting.set()
                await proceed.wait()
            return await original_touch(user_id, tx, **conditions)

        monkeypatch.setattr(service, "touch_user", gated_touch)
        pending_logout = asyncio.create_task(service.logout(raw), name="logout")
        await asyncio.wait_for(waiting.wait(), timeout=10)
        try:
            rotated = await service.refresh(raw)
        finally:
            proceed.set()
        await pending_logout
        return rotated[1]

    rotated_raw = call(http, race)
    assert call(http, db.sessions.count_documents, {}) == 0
    with pytest.raises(AuthError):
        call(http, service.refresh, rotated_raw)

