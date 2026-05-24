from datetime import UTC, datetime
from typing import Any
from urllib.parse import ParseResult, urlparse

import httpx

from src.agent.schemas import (
    PullRequestDiff,
    PullRequestFileMetadata,
    PullRequestMetadata,
    PullRequestRef,
)
from src.config import settings

GITHUB_API_VERSION = "2022-11-28"
GITHUB_TIMEOUT_SECONDS = 15.0
GITHUB_PER_PAGE = 100


class PullRequestDiffError(Exception):
    def __init__(self, message: str, *, code: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        error = {
            "type": "pull_request_fetch_failed",
            "code": self.code,
            "message": self.message,
        }
        if self.status_code is not None:
            error["status_code"] = self.status_code
        return error


async def fetch_pull_request_diff(pr_url: str) -> PullRequestDiff:
    pr_ref = _parse_github_pr_url(pr_url)

    async with _create_github_client(pr_ref.api_base_url) as client:
        pull_request = await _get_json(
            client, f"/repos/{pr_ref.full_name}/pulls/{pr_ref.number}"
        )
        files = await _get_paginated_json(
            client, f"/repos/{pr_ref.full_name}/pulls/{pr_ref.number}/files"
        )

    return PullRequestDiff(
        diff=_format_pull_request_diff(pull_request, files),
        metadata=_build_metadata(pr_url, pr_ref, pull_request, files),
    )


def _parse_github_pr_url(pr_url: str) -> PullRequestRef:
    parsed = urlparse(pr_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise PullRequestDiffError(
            "Expected a GitHub pull request URL.",
            code="invalid_pr_url",
        )

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 4 or path_parts[2] != "pull":
        raise PullRequestDiffError(
            "Expected a GitHub pull request URL like /owner/repo/pull/123.",
            code="invalid_pr_url",
        )

    try:
        pull_number = int(path_parts[3])
    except ValueError as exc:
        raise PullRequestDiffError(
            "GitHub pull request URL contains an invalid PR number.",
            code="invalid_pr_url",
        ) from exc

    owner, repo = path_parts[0], path_parts[1]
    api_base_url = _github_api_base_url(parsed)
    return PullRequestRef(
        owner=owner, repo=repo, number=pull_number, api_base_url=api_base_url
    )


def _github_api_base_url(parsed_url: ParseResult) -> str:
    configured_url = settings.github_api_base_url.strip()
    if configured_url:
        return configured_url.rstrip("/")

    host = parsed_url.hostname or ""
    port = f":{parsed_url.port}" if parsed_url.port else ""
    netloc = f"{host}{port}"
    if host.lower() == "github.com":
        return "https://api.github.com"
    return f"{parsed_url.scheme}://{netloc}/api/v3"


def _create_github_client(api_base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=api_base_url,
        headers=_github_headers(),
        timeout=GITHUB_TIMEOUT_SECONDS,
    )


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "code-review-agent",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    token = (settings.github_token or settings.gh_token).strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _get_json(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await _get(client, path, params=params)
    payload = _response_json(response)
    if not isinstance(payload, dict):
        raise PullRequestDiffError(
            "GitHub API returned an unexpected response.",
            code="unexpected_github_response",
        )
    return payload


async def _get_paginated_json(
    client: httpx.AsyncClient,
    path: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1

    while True:
        response = await _get(
            client,
            path,
            params={"per_page": GITHUB_PER_PAGE, "page": page},
        )
        payload = _response_json(response)
        if not isinstance(payload, list):
            raise PullRequestDiffError(
                "GitHub API returned an unexpected paginated response.",
                code="unexpected_github_response",
            )

        items.extend(payload)
        if len(payload) < GITHUB_PER_PAGE:
            return items
        page += 1


async def _get(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as exc:
        raise PullRequestDiffError(
            _github_error_message(exc.response),
            code=_github_error_code(exc.response),
            status_code=exc.response.status_code,
        ) from exc
    except httpx.RequestError as exc:
        raise PullRequestDiffError(
            f"Could not reach GitHub API: {exc}",
            code="github_unreachable",
        ) from exc


def _response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise PullRequestDiffError(
            "GitHub API returned invalid JSON.",
            code="invalid_github_response",
        ) from exc


def _github_error_message(response: httpx.Response) -> str:
    detail = response.reason_phrase
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict) and payload.get("message"):
        detail = str(payload["message"])

    if (
        response.status_code == 403
        and response.headers.get("x-ratelimit-remaining") == "0"
    ):
        reset_at = _format_rate_limit_reset(response.headers.get("x-ratelimit-reset"))
        if reset_at:
            detail = f"{detail} Rate limit resets at {reset_at}."

    return f"GitHub API request failed ({response.status_code}): {detail}"


def _github_error_code(response: httpx.Response) -> str:
    if response.status_code == 404:
        return "pull_request_not_found"
    if response.status_code in {401, 403}:
        if response.headers.get("x-ratelimit-remaining") == "0":
            return "github_rate_limit_exceeded"
        return "github_auth_failed"
    return "github_api_error"


def _format_rate_limit_reset(reset_header: str | None) -> str | None:
    if reset_header is None:
        return None
    try:
        reset_timestamp = int(reset_header)
    except ValueError:
        return None
    return datetime.fromtimestamp(reset_timestamp, UTC).isoformat()


def _format_pull_request_diff(
    pull_request: dict[str, Any],
    files: list[dict[str, Any]],
) -> str:
    lines = [
        f"Pull Request: {_repo_full_name(pull_request)}#{pull_request.get('number', '')}",
        f"URL: {pull_request.get('html_url', '')}",
        f"Title: {pull_request.get('title', '')}",
        (
            "Base: "
            f"{_nested_get(pull_request, 'base', 'ref')} "
            f"({_short_sha(_nested_get(pull_request, 'base', 'sha'))})"
        ),
        (
            "Head: "
            f"{_nested_get(pull_request, 'head', 'ref')} "
            f"({_short_sha(_nested_get(pull_request, 'head', 'sha'))})"
        ),
        (
            "Stats: "
            f"{pull_request.get('changed_files', len(files))} file(s), "
            f"+{pull_request.get('additions', 0)} "
            f"-{pull_request.get('deletions', 0)}"
        ),
        "",
    ]

    for index, file in enumerate(files, start=1):
        lines.extend(_format_file_diff(index, file))
        lines.append("")

    return "\n".join(lines).strip()


def _format_file_diff(index: int, file: dict[str, Any]) -> list[str]:
    filename = str(file.get("filename", ""))
    previous_filename = file.get("previous_filename")
    additions = file.get("additions", 0)
    deletions = file.get("deletions", 0)
    status = file.get("status", "unknown")
    patch = file.get("patch")

    lines = [
        f"File {index}: {filename}",
        f"Status: {status} (+{additions} -{deletions})",
        _diff_git_header(filename, previous_filename),
    ]

    if previous_filename:
        lines.extend([f"rename from {previous_filename}", f"rename to {filename}"])

    lines.extend(_file_header_lines(filename, str(status), previous_filename))
    if patch:
        lines.append(str(patch))
    else:
        lines.append(
            "[No textual patch returned by GitHub. The file may be binary or too large.]"
        )
    return lines


def _diff_git_header(filename: str, previous_filename: Any) -> str:
    old_filename = previous_filename or filename
    return f"diff --git a/{old_filename} b/{filename}"


def _file_header_lines(
    filename: str,
    status: str,
    previous_filename: Any,
) -> list[str]:
    old_filename = previous_filename or filename
    if status == "added":
        return ["--- /dev/null", f"+++ b/{filename}"]
    if status == "removed":
        return [f"--- a/{old_filename}", "+++ /dev/null"]
    return [f"--- a/{old_filename}", f"+++ b/{filename}"]


def _build_metadata(
    pr_url: str,
    pr_ref: PullRequestRef,
    pull_request: dict[str, Any],
    files: list[dict[str, Any]],
) -> PullRequestMetadata:
    changed_files = int(pull_request.get("changed_files") or len(files))
    additions = int(pull_request.get("additions") or 0)
    deletions = int(pull_request.get("deletions") or 0)

    return PullRequestMetadata(
        pr_url=pr_url,
        repository=pr_ref.full_name,
        owner=pr_ref.owner,
        repo=pr_ref.repo,
        pull_number=pr_ref.number,
        title=pull_request.get("title"),
        author=_nested_get(pull_request, "user", "login"),
        state=pull_request.get("state"),
        draft=bool(pull_request.get("draft", False)),
        html_url=pull_request.get("html_url"),
        api_url=pull_request.get("url"),
        base_ref=_nested_get(pull_request, "base", "ref"),
        base_sha=_nested_get(pull_request, "base", "sha"),
        head_ref=_nested_get(pull_request, "head", "ref"),
        head_sha=_nested_get(pull_request, "head", "sha"),
        merge_commit_sha=pull_request.get("merge_commit_sha"),
        commits=pull_request.get("commits"),
        files_changed=changed_files,
        changed_files=changed_files,
        additions=additions,
        deletions=deletions,
        files_without_patch=sum(1 for file in files if not file.get("patch")),
        files=[_file_metadata(file) for file in files],
        fetched_at=datetime.now(UTC),
    )


def _file_metadata(file: dict[str, Any]) -> PullRequestFileMetadata:
    return PullRequestFileMetadata(
        filename=file.get("filename"),
        status=file.get("status"),
        additions=file.get("additions", 0),
        deletions=file.get("deletions", 0),
        changes=file.get("changes", 0),
        patch_available=bool(file.get("patch")),
        blob_url=file.get("blob_url"),
        raw_url=file.get("raw_url"),
        previous_filename=file.get("previous_filename"),
    )


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _repo_full_name(pull_request: dict[str, Any]) -> str:
    return _nested_get(pull_request, "base", "repo", "full_name") or ""


def _short_sha(value: Any) -> str:
    return str(value or "")[:7]
