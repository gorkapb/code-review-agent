import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import structlog
from langfuse import Langfuse, propagate_attributes

from src.config import settings

logger = structlog.get_logger(__name__)

_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|bearer|credential|password|secret|token)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[-. ]?)?(?:\d{3}[-. ]?){2}\d{4}\b")
_NON_ENV_CHAR_RE = re.compile(r"[^a-z0-9_-]+")

_client: Langfuse | None = None


def langfuse_configured() -> bool:
    return (
        settings.langfuse_tracing_enabled
        and bool(settings.langfuse_public_key.strip())
        and bool(settings.langfuse_secret_key.strip())
    )


def get_langfuse_client() -> Langfuse | None:
    global _client

    if not langfuse_configured():
        return None

    if _client is None:
        _client = Langfuse(
            public_key=settings.langfuse_public_key.strip(),
            secret_key=settings.langfuse_secret_key.strip(),
            base_url=settings.langfuse_url,
            environment=_langfuse_environment(settings.env),
            release=settings.service_version,
            debug=settings.langfuse_debug,
            sample_rate=settings.langfuse_sample_rate,
            mask=_mask_sensitive_data,
        )
        logger.info(
            "langfuse tracing configured",
            base_url=settings.langfuse_url,
            sample_rate=settings.langfuse_sample_rate,
        )

    return _client


def create_trace_id(seed: str) -> str | None:
    client = get_langfuse_client()
    if client is None:
        return None

    return client.create_trace_id(seed=seed)


@contextmanager
def start_langfuse_observation(
    *,
    name: str,
    as_type: str = "span",
    input: Any | None = None,
    output: Any | None = None,
    metadata: Any | None = None,
    model: str | None = None,
    model_parameters: dict[str, str | int | float | bool | list[str] | None]
    | None = None,
    trace_id: str | None = None,
) -> Iterator[Any | None]:
    client = get_langfuse_client()
    if client is None:
        yield None
        return

    trace_context = {"trace_id": trace_id} if trace_id else None
    with client.start_as_current_observation(
        name=name,
        as_type=as_type,
        input=input,
        output=output,
        metadata=metadata,
        model=model,
        model_parameters=model_parameters,
        trace_context=trace_context,
    ) as observation:
        yield observation


@contextmanager
def propagate_langfuse_attributes(
    *,
    trace_name: str,
    metadata: Mapping[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Iterator[None]:
    if not langfuse_configured():
        yield
        return

    with propagate_attributes(
        trace_name=trace_name,
        version=settings.service_version,
        metadata=_string_metadata(metadata or {}),
        tags=tags,
    ):
        yield


def flush_langfuse() -> None:
    if _client is not None:
        _client.flush()


def shutdown_langfuse() -> None:
    if _client is not None:
        _client.shutdown()


def trace_content_enabled() -> bool:
    return settings.langfuse_capture_content


def summarize_pull_request_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: metadata.get(key)
        for key in (
            "pr_url",
            "repository",
            "pull_number",
            "title",
            "author",
            "state",
            "draft",
            "base_ref",
            "head_ref",
            "commits",
            "files_changed",
            "additions",
            "deletions",
            "files_without_patch",
        )
        if key in metadata
    }


def summarize_diff(diff: str) -> dict[str, Any]:
    return {
        "redacted": not trace_content_enabled(),
        "characters": len(diff),
        "lines": len(diff.splitlines()),
    }


def _string_metadata(metadata: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        text = str(value)
        result[str(key)] = text[:200]
    return result


def _mask_sensitive_data(*, data: Any, **_: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: "[REDACTED]"
            if _SENSITIVE_KEY_RE.search(str(key))
            else _mask_sensitive_data(data=value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_mask_sensitive_data(data=item) for item in data]
    if isinstance(data, tuple):
        return [_mask_sensitive_data(data=item) for item in data]
    if isinstance(data, str):
        data = _EMAIL_RE.sub("[REDACTED_EMAIL]", data)
        data = _CREDIT_CARD_RE.sub("[REDACTED_CARD]", data)
        return _PHONE_RE.sub("[REDACTED_PHONE]", data)
    return data


def _langfuse_environment(value: str) -> str:
    environment = _NON_ENV_CHAR_RE.sub("-", value.lower()).strip("-_")
    if not environment or environment.startswith("langfuse"):
        return "default"
    return environment
