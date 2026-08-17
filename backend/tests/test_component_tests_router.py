"""Regression tests for the component-tests router.

The component-tests routes resolve the caller via
``get_optional_user_from_request(request)``, which is ``async``. Calling it
without ``await`` left ``user`` as a coroutine (never ``None``), so the first
``str(user.id)`` raised ``AttributeError: 'coroutine' object has no attribute
'id'`` and every route 500'd. These tests stamp a real user (with an
``auth_source``) on each request and assert the routes return 200 rather than
crashing — they fail loudly on the un-``await``ed regression.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED
from app.gateway.authz import AuthContext, Permissions
from app.gateway.routers import component_tests

_STUB_PERMISSIONS: list[str] = [
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
    Permissions.THREADS_DELETE,
    Permissions.RUNS_CREATE,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
]


class _AuthedUserMiddleware(BaseHTTPMiddleware):
    """Stamp a user + auth_source so ``get_optional_user_from_request`` resolves.

    Mirrors the auth-disabled path: ``request.state.user`` plus an accepted
    ``auth_source``, so the async resolver returns the user instead of falling
    through to the JWT-cookie branch.
    """

    def __init__(self, app: ASGIApp, user_factory: Callable[[], User]) -> None:
        super().__init__(app)
        self._user_factory = user_factory

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        user = self._user_factory()
        request.state.user = user
        request.state.auth_source = AUTH_SOURCE_AUTH_DISABLED
        request.state.auth = AuthContext(user=user, permissions=list(_STUB_PERMISSIONS))
        return await call_next(request)


def _make_test_user() -> User:
    return User(
        email="component-test@example.com",
        password_hash="x",
        system_role="user",
        id=uuid4(),
    )


def _make_app(user_factory: Callable[[], User] | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(_AuthedUserMiddleware, user_factory=user_factory or _make_test_user)
    app.include_router(component_tests.router)
    return app


def test_list_components_awaits_user_resolution():
    repo = MagicMock()
    repo.list_by_user = AsyncMock(return_value=[{"id": "comp-1"}])
    app = _make_app()
    app.state.component_repo = repo

    with TestClient(app) as client:
        response = client.get("/api/component-tests/components")

    assert response.status_code == 200
    assert response.json() == {"components": [{"id": "comp-1"}]}
    repo.list_by_user.assert_awaited_once()


def test_create_component_awaits_user_resolution():
    created = {
        "id": "comp-1",
        "user_id": "default",
        "name": "Echo",
        "transport": "http_post",
        "enabled": True,
    }
    repo = MagicMock()
    repo.create = AsyncMock(return_value=created)
    app = _make_app()
    app.state.component_repo = repo

    with TestClient(app) as client:
        response = client.post(
            "/api/component-tests/components",
            json={
                "name": "Echo",
                "transport": "http_post",
                "api_url": "https://postman-echo.com/post",
            },
        )

    assert response.status_code == 200
    assert response.json() == created
    # user_id came from the resolved (awaited) user, not a coroutine.
    assert repo.create.await_args.kwargs["user_id"] is not None
