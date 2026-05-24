import json
from typing import Any

import httpx

from src.agent.schemas import ReviewAnalysis
from src.config import settings
from src.observability.langfuse import (
    start_langfuse_observation,
    summarize_diff,
    summarize_pull_request_metadata,
    trace_content_enabled,
)

ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_TIMEOUT_SECONDS = 60.0
DEFAULT_REVIEW_MODEL = "claude-haiku-4-5-20251001"
REVIEW_MAX_TOKENS = 2048


class PullRequestReviewError(Exception):
    def __init__(self, message: str, *, code: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        error = {
            "type": "pull_request_review_failed",
            "code": self.code,
            "message": self.message,
        }
        if self.status_code is not None:
            error["status_code"] = self.status_code
        return error


async def review_pull_request_diff(
    *,
    diff: str,
    metadata: dict[str, Any] | None = None,
) -> ReviewAnalysis:
    if not diff.strip():
        return ReviewAnalysis(findings=[])

    request_payload = _build_review_request(diff, metadata or {})
    async with _create_anthropic_client() as client:
        with start_langfuse_observation(
            name="anthropic-pr-review",
            as_type="generation",
            input=_trace_generation_input(request_payload, diff, metadata or {}),
            metadata=_trace_generation_metadata(diff, metadata or {}),
            model=str(request_payload["model"]),
            model_parameters=_trace_model_parameters(request_payload),
        ) as generation:
            response = await _post_message(client, request_payload)
            if generation is not None:
                generation.update(
                    output=_trace_generation_output(response),
                    usage_details=_anthropic_usage_details(response),
                )

    return _parse_review_analysis(response)


def _create_anthropic_client() -> httpx.AsyncClient:
    api_key = settings.anthropic_api_key.strip()
    if not api_key:
        raise PullRequestReviewError(
            "ANTHROPIC_API_KEY is required to analyze pull request diffs.",
            code="missing_anthropic_api_key",
        )

    return httpx.AsyncClient(
        base_url=settings.anthropic_api_base_url.rstrip("/"),
        headers={
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
            "x-api-key": api_key,
        },
        timeout=ANTHROPIC_TIMEOUT_SECONDS,
    )


async def _post_message(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        response = await client.post("/v1/messages", json=payload)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise PullRequestReviewError(
            _anthropic_error_message(exc.response),
            code=_anthropic_error_code(exc.response),
            status_code=exc.response.status_code,
        ) from exc
    except httpx.RequestError as exc:
        raise PullRequestReviewError(
            f"Could not reach Anthropic API: {exc}",
            code="anthropic_unreachable",
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise PullRequestReviewError(
            "Anthropic API returned invalid JSON.",
            code="invalid_anthropic_response",
        ) from exc

    if not isinstance(payload, dict):
        raise PullRequestReviewError(
            "Anthropic API returned an unexpected response.",
            code="unexpected_anthropic_response",
        )
    return payload


def _build_review_request(diff: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": _review_model(),
        "max_tokens": REVIEW_MAX_TOKENS,
        "temperature": 0,
        "system": _review_system_prompt(),
        "messages": [
            {
                "role": "user",
                "content": _review_user_prompt(diff, metadata),
            }
        ],
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": ReviewAnalysis.model_json_schema(),
            }
        },
    }


def _review_model() -> str:
    return settings.anthropic_model.strip() or DEFAULT_REVIEW_MODEL


def _review_system_prompt() -> str:
    return (
        "You are a senior software engineer reviewing a GitHub pull request diff. "
        "Report only actionable issues that are directly supported by the diff. "
        "Prioritize correctness, security, data loss, performance regressions, "
        "missing tests for risky changes, and maintainability. Avoid praise, style "
        "nitpicks, speculation, and comments about unchanged code. If there are no "
        "actionable issues, return an empty findings list."
    )


def _review_user_prompt(diff: str, metadata: dict[str, Any]) -> str:
    metadata_json = json.dumps(metadata, default=str, indent=2, sort_keys=True)
    return (
        "Review this parsed pull request diff and return structured findings.\n\n"
        f"Pull request metadata:\n{metadata_json}\n\n"
        f"Parsed diff:\n{diff}"
    )


def _parse_review_analysis(response: dict[str, Any]) -> ReviewAnalysis:
    stop_reason = response.get("stop_reason")
    if stop_reason in {"max_tokens", "refusal"}:
        raise PullRequestReviewError(
            f"Anthropic response stopped before a complete review: {stop_reason}.",
            code="incomplete_anthropic_response",
        )

    content = response.get("content")
    if not isinstance(content, list) or not content:
        raise PullRequestReviewError(
            "Anthropic API returned an empty review.",
            code="unexpected_anthropic_response",
        )

    text_blocks = [
        block.get("text")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    review_text = "\n".join(text for text in text_blocks if isinstance(text, str))
    if not review_text.strip():
        raise PullRequestReviewError(
            "Anthropic API did not return structured review content.",
            code="unexpected_anthropic_response",
        )

    try:
        return ReviewAnalysis.model_validate_json(review_text)
    except ValueError as exc:
        raise PullRequestReviewError(
            "Anthropic API returned review content that does not match the schema.",
            code="invalid_review_schema",
        ) from exc


def _anthropic_error_message(response: httpx.Response) -> str:
    detail = response.reason_phrase
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            detail = str(error["message"])
        elif payload.get("message"):
            detail = str(payload["message"])

    return f"Anthropic API request failed ({response.status_code}): {detail}"


def _anthropic_error_code(response: httpx.Response) -> str:
    if response.status_code == 401:
        return "anthropic_auth_failed"
    if response.status_code == 403:
        return "anthropic_forbidden"
    if response.status_code == 404:
        return "anthropic_model_not_found"
    if response.status_code == 413:
        return "anthropic_request_too_large"
    if response.status_code == 429:
        return "anthropic_rate_limit_exceeded"
    return "anthropic_api_error"


def _trace_generation_input(
    payload: dict[str, Any], diff: str, metadata: dict[str, Any]
) -> dict[str, Any]:
    if trace_content_enabled():
        return {
            "system": payload.get("system"),
            "messages": payload.get("messages"),
        }

    return {
        "content_redacted": True,
        "diff": summarize_diff(diff),
        "metadata": summarize_pull_request_metadata(metadata),
    }


def _trace_generation_metadata(diff: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "anthropic_api_version": ANTHROPIC_API_VERSION,
        "diff": summarize_diff(diff),
        **summarize_pull_request_metadata(metadata),
    }


def _trace_model_parameters(
    payload: dict[str, Any],
) -> dict[str, str | int | float | bool | list[str] | None]:
    output_format = payload.get("output_config", {}).get("format", {})
    return {
        "temperature": payload.get("temperature"),
        "max_tokens": payload.get("max_tokens"),
        "output_format": output_format.get("type"),
    }


def _trace_generation_output(response: dict[str, Any]) -> dict[str, Any]:
    text = _response_text(response)
    if trace_content_enabled():
        return {
            "id": response.get("id"),
            "model": response.get("model"),
            "stop_reason": response.get("stop_reason"),
            "content": response.get("content"),
        }

    return {
        "id": response.get("id"),
        "model": response.get("model"),
        "stop_reason": response.get("stop_reason"),
        "content_redacted": True,
        "content_blocks": len(response.get("content", []))
        if isinstance(response.get("content"), list)
        else None,
        "text_characters": len(text),
    }


def _response_text(response: dict[str, Any]) -> str:
    content = response.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    )


def _anthropic_usage_details(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return {}

    details: dict[str, int] = {}
    mapping = {
        "input_tokens": "input",
        "output_tokens": "output",
        "cache_creation_input_tokens": "cache_creation_input_tokens",
        "cache_read_input_tokens": "cache_read_input_tokens",
    }
    for source_key, langfuse_key in mapping.items():
        value = usage.get(source_key)
        if isinstance(value, int):
            details[langfuse_key] = value
    return details
