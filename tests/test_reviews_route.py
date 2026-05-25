from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, status

from src.api.routes import reviews


class FakePool:
    def __init__(self, *, enqueue_result: Any | None = None) -> None:
        self.enqueue_result = enqueue_result
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any | None:
        self.calls.append((function, args, kwargs))
        return self.enqueue_result


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
    def start_span(
        name: str,
        *,
        pr_url: str,
        telemetry_context: dict[str, Any],
        inject_context: bool = False,
        continue_from_context: bool = False,
    ):
        span_calls.append(
            (name, pr_url, telemetry_context, inject_context, continue_from_context)
        )
        yield

    monkeypatch.setattr(reviews, "start_span", start_span)

    response = await reviews.enqueue_review(
        reviews.ReviewRequest(pr_url="https://github.com/acme/widget/pull/42"),
        request,
        pool,
    )

    assert response == reviews.ReviewResponse(job_id=job_id)
    assert span_calls == [
        (
            "enqueue-pr-review",
            "https://github.com/acme/widget/pull/42",
            telemetry_context,
            True,
            False,
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
    def start_span(
        name: str,
        *,
        pr_url: str,
        telemetry_context: dict[str, Any],
        inject_context: bool = False,
        continue_from_context: bool = False,
    ):
        span_calls.append(
            (name, pr_url, telemetry_context, inject_context, continue_from_context)
        )
        yield

    monkeypatch.setattr(reviews, "start_span", start_span)

    with pytest.raises(HTTPException) as exc_info:
        await reviews.enqueue_review(
            reviews.ReviewRequest(pr_url="https://github.com/acme/widget/pull/42"),
            request,
            pool,
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert span_calls == [
        (
            "enqueue-pr-review",
            "https://github.com/acme/widget/pull/42",
            pool.calls[0][2]["telemetry_context"],
            True,
            False,
        )
    ]
    assert pool.calls[0][2]["_job_id"] == job_id
