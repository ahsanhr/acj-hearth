"""Authentication/session contracts: concurrency."""

import asyncio

import pytest
from app.schemas.user import AccountPatch
from app.services.auth import AuthError

from tests.auth_support import (
    EMAIL,
    PASSWORD,
    authorize,
    call,
    login,
    register,
)


def test_concurrent_logins_and_refresh(api):
    http, db = api
    register(http)
    service = http.app.state.auth_service

    async def simultaneous_logins():
        return await asyncio.gather(
            *(service.login(EMAIL, PASSWORD) for _ in range(8)),
            return_exceptions=True,
        )

    results = call(http, simultaneous_logins)
    successes = [result for result in results if isinstance(result, tuple)]
    assert successes  # At least one transaction must commit.
    # Bounded retries do not promise every competing request will succeed.
    for result in results:
        if not isinstance(result, tuple):
            assert isinstance(result, AuthError)
            assert (result.status, result.code) == (503, "database_busy")
    assert len({result[0]["session_id"] for result in successes}) == len(successes)
    assert call(http, db.sessions.count_documents, {}) == min(5, len(successes))
    _, raw = call(http, service.login, EMAIL, PASSWORD)

    async def simultaneous_refreshes():
        return await asyncio.gather(
            service.refresh(raw), service.refresh(raw), return_exceptions=True
        )

    results = call(http, simultaneous_refreshes)
    assert sum(isinstance(r, tuple) for r in results) == 1
    assert sum(isinstance(r, AuthError) and r.status == 401 for r in results) == 1


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
            if asyncio.current_task().get_name() == "login":  # old credentials verified
                waiting.set()
                await proceed.wait()
            return await original_touch(user_id, tx, **conditions)

        monkeypatch.setattr(service, "touch_user", gated_touch)
        pending_login = asyncio.create_task(
            service.login(EMAIL, PASSWORD), name="login"
        )
        await asyncio.wait_for(waiting.wait(), timeout=10)
        try:
            if action == "password":
                await http.app.state.account_service.update(
                    user,
                    session["session_id"],
                    AccountPatch(
                        current_password=PASSWORD,
                        new_password="another password!2",
                    ),
                )
            elif action == "delete":
                await http.app.state.account_service.delete(
                    user, session["session_id"], PASSWORD
                )
            else:
                await service.revoke_account(user["_id"])
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
