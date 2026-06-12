"""End-to-end auth wiring tests.

These drive the real ASGI app through httpx so they prove the dependency is
actually attached to the routes — the unit tests in test_reviews_route.py call
the handlers directly and can't catch a route accidentally losing its guard.
The DB and queue are faked so the test stays hermetic (no Postgres/Redis).
"""

from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import create_app
from src.storage.database import get_db

PR_URL = "https://github.com/acme/widget/pull/42"


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeDb:
    """Backs both the auth lookup (execute) and the route handlers (add/get)."""

    def __init__(self, *, tenant: Any = None, review: Any = None) -> None:
        self._tenant = tenant
        self._review = review
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None: ...

    async def commit(self) -> None: ...

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self._tenant)

    async def get(self, _model: Any, _key: str) -> Any:
        return self._review


class FakePool:
    async def enqueue_job(self, *_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(job_id="job-1")


def _make_client(db: FakeDb) -> AsyncClient:
    app = create_app()
    app.state.arq_pool = FakePool()

    async def _override_db():
        yield db

    # get_db is cached per-request, so auth and the handler share this instance.
    app.dependency_overrides[get_db] = _override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_health_is_public():
    async with _make_client(FakeDb()) as client:
        response = await client.get("/health")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_post_reviews_rejects_missing_token():
    async with _make_client(FakeDb()) as client:
        response = await client.post("/reviews", json={"pr_url": PR_URL})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_get_review_rejects_missing_token():
    async with _make_client(FakeDb()) as client:
        response = await client.get("/reviews/some-job-id")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_reviews_rejects_invalid_token():
    # No tenant matches the token's hash -> 401 with the RFC 6750 challenge.
    async with _make_client(FakeDb(tenant=None)) as client:
        response = await client.post(
            "/reviews",
            json={"pr_url": PR_URL},
            headers={"Authorization": "Bearer cra_nope"},
        )

    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]


@pytest.mark.asyncio
async def test_post_reviews_accepts_valid_token():
    tenant = SimpleNamespace(id="tenant-1")
    async with _make_client(FakeDb(tenant=tenant)) as client:
        response = await client.post(
            "/reviews",
            json={"pr_url": PR_URL},
            headers={"Authorization": "Bearer cra_valid"},
        )

    assert response.status_code == 202
    assert response.json()["job_id"]
