import json

import httpx
import pytest

from src.agent.schemas import Finding, ReviewAnalysis
from src.agent.services import pull_request_review as pull_request_review_module


@pytest.mark.asyncio
async def test_review_pull_request_diff_calls_anthropic_with_structured_output(
    monkeypatch,
):
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)

        return httpx.Response(
            200,
            json={
                "id": "msg_123",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5-20251001",
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "text",
                        "text": ReviewAnalysis(
                            findings=[
                                Finding(
                                    severity="high",
                                    category="bug",
                                    line_ref="src/app.py:12",
                                    message="The new branch skips authentication.",
                                    suggestion="Require authentication before returning the response.",
                                    confidence="high",
                                )
                            ]
                        ).model_dump_json(),
                    }
                ],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )

    transport = httpx.MockTransport(handler)

    def create_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            transport=transport,
        )

    monkeypatch.setattr(
        pull_request_review_module, "_create_anthropic_client", create_client
    )

    result = await pull_request_review_module.review_pull_request_diff(
        diff="diff --git a/src/app.py b/src/app.py\n@@ -10,0 +11,2 @@\n+return data",
        metadata={"repository": "acme/widget", "pull_number": 42},
    )

    assert len(result.findings) == 1
    assert result.findings[0].line_ref == "src/app.py:12"
    assert requests[0]["model"] == "claude-haiku-4-5-20251001"
    assert requests[0]["output_config"]["format"]["type"] == "json_schema"
    assert requests[0]["output_config"]["format"]["schema"]["title"] == "ReviewAnalysis"


@pytest.mark.asyncio
async def test_review_pull_request_diff_skips_empty_diff():
    result = await pull_request_review_module.review_pull_request_diff(diff="  ")

    assert result == ReviewAnalysis(findings=[])


def test_create_anthropic_client_requires_api_key(monkeypatch):
    monkeypatch.setattr(pull_request_review_module.settings, "anthropic_api_key", "")

    with pytest.raises(
        pull_request_review_module.PullRequestReviewError,
        match="ANTHROPIC_API_KEY is required",
    ) as exc_info:
        pull_request_review_module._create_anthropic_client()

    assert exc_info.value.code == "missing_anthropic_api_key"


def test_parse_review_analysis_rejects_incomplete_response():
    with pytest.raises(pull_request_review_module.PullRequestReviewError) as exc_info:
        pull_request_review_module._parse_review_analysis(
            {"stop_reason": "max_tokens", "content": []}
        )

    assert exc_info.value.code == "incomplete_anthropic_response"
