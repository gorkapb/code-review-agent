from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, status

from src.api.routes import reviews


class FakePool:
    def __init__(
        self, *, enqueue_result: Any | None = None, raises: Exception | None = None
    ) -> None:
        self.enqueue_result = enqueue_result
        self.raises = raises
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any | None:
        self.calls.append((function, args, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.enqueue_result


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.commits += 1


TENANT = SimpleNamespace(id="tenant-1")


@pytest.mark.asyncio
async def test_enqueue_review_passes_telemetry_context_to_arq(monkeypatch):
    job_id = "a" * 32
    telemetry_context = {
        "job_id": job_id,
        "queued_at": "2026-05-24T12:34:56+00:00",
        "request_id": "req-123",
    }
    request = SimpleNamespace(state=SimpleNamespace(request_id="req-123"), headers={})
    pool = FakePool(enqueue_result=SimpleNamespace(job_id=job_id))
    span_calls: list[tuple[str, dict[str, Any]]] = []

    def build_context(
        *,
        job_id: str,
        queued_at: Any,
        request_id: str,
    ) -> dict[str, Any]:
        assert job_id == "a" * 32
        assert queued_at is not None
        assert request_id == "req-123"
        return telemetry_context

    monkeypatch.setattr(reviews, "new_job_id", lambda: job_id)
    monkeypatch.setattr(reviews, "build_telemetry_context", build_context)

    @contextmanager
    def start_enqueue_span(
        *,
        pr_url: str,
        telemetry_context: dict[str, Any],
    ):
        span_calls.append((pr_url, telemetry_context))
        yield

    monkeypatch.setattr(reviews, "start_enqueue_span", start_enqueue_span)

    db = FakeSession()
    response = await reviews.enqueue_review(
        reviews.ReviewRequest(pr_url="https://github.com/acme/widget/pull/42"),
        request,
        TENANT,
        pool,
        db,
    )

    assert response == reviews.ReviewResponse(job_id=job_id)
    # The owning row is created (with tenant_id) and committed before enqueue.
    assert len(db.added) == 1
    assert db.added[0].tenant_id == TENANT.id
    assert db.added[0].id == job_id
    assert db.commits == 1
    assert span_calls == [
        (
            "https://github.com/acme/widget/pull/42",
            telemetry_context,
        )
    ]
    assert pool.calls == [
        (
            "analyze_pr_task",
            ("https://github.com/acme/widget/pull/42",),
            {
                "_job_id": job_id,
                "telemetry_context": telemetry_context,
            },
        )
    ]


@pytest.mark.asyncio
async def test_enqueue_review_rejects_duplicate_arq_job(monkeypatch):
    job_id = "a" * 32
    request = SimpleNamespace(state=SimpleNamespace(request_id="req-123"), headers={})
    pool = FakePool(enqueue_result=None)
    span_calls: list[tuple[str, dict[str, Any]]] = []

    def build_context(
        *,
        job_id: str,
        queued_at: Any,
        request_id: str,
    ) -> dict[str, Any]:
        assert job_id == "a" * 32
        assert queued_at is not None
        assert request_id == "req-123"
        return {
            "job_id": job_id,
            "queued_at": "2026-05-24T12:34:56+00:00",
            "request_id": request_id,
        }

    monkeypatch.setattr(reviews, "new_job_id", lambda: job_id)
    monkeypatch.setattr(reviews, "build_telemetry_context", build_context)

    @contextmanager
    def start_enqueue_span(
        *,
        pr_url: str,
        telemetry_context: dict[str, Any],
    ):
        span_calls.append((pr_url, telemetry_context))
        yield

    monkeypatch.setattr(reviews, "start_enqueue_span", start_enqueue_span)

    db = FakeSession()
    with pytest.raises(HTTPException) as exc_info:
        await reviews.enqueue_review(
            reviews.ReviewRequest(pr_url="https://github.com/acme/widget/pull/42"),
            request,
            TENANT,
            pool,
            db,
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    # The pending row must be discarded — no worker will pick this job up.
    assert db.deleted == db.added
    assert span_calls == [
        (
            "https://github.com/acme/widget/pull/42",
            pool.calls[0][2]["telemetry_context"],
        )
    ]
    assert pool.calls[0][2]["_job_id"] == job_id


@pytest.mark.asyncio
async def test_enqueue_review_discards_row_when_enqueue_fails(monkeypatch):
    job_id = "a" * 32
    request = SimpleNamespace(state=SimpleNamespace(request_id="req-123"), headers={})
    pool = FakePool(raises=RuntimeError("redis down"))

    monkeypatch.setattr(reviews, "new_job_id", lambda: job_id)
    monkeypatch.setattr(
        reviews,
        "build_telemetry_context",
        lambda **_: {"job_id": job_id, "queued_at": "", "request_id": "req-123"},
    )

    @contextmanager
    def start_enqueue_span(*, pr_url: str, telemetry_context: dict[str, Any]):
        yield

    monkeypatch.setattr(reviews, "start_enqueue_span", start_enqueue_span)

    db = FakeSession()
    with pytest.raises(HTTPException) as exc_info:
        await reviews.enqueue_review(
            reviews.ReviewRequest(pr_url="https://github.com/acme/widget/pull/42"),
            request,
            TENANT,
            pool,
            db,
        )

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    # The committed pending row is rolled back so it never orphans.
    assert db.deleted == db.added
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_get_review_hides_other_tenants_job():
    # A row owned by a different tenant must look like a 404, not a 403.
    other = SimpleNamespace(tenant_id="other-tenant")

    class Db:
        async def get(self, _model: Any, _key: str) -> Any:
            return other

    with pytest.raises(HTTPException) as exc_info:
        await reviews.get_review("job-1", TENANT, FakePool(), Db())

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
