import httpx
import pytest

from src.agent.schemas import PullRequestDiff
from src.agent.services import (
    github_pull_request_diff as github_pull_request_diff_module,
)


def _pull_request_payload() -> dict:
    return {
        "number": 42,
        "html_url": "https://github.com/acme/widget/pull/42",
        "url": "https://api.github.com/repos/acme/widget/pulls/42",
        "title": "Improve widget handling",
        "state": "open",
        "draft": False,
        "user": {"login": "octocat"},
        "base": {
            "ref": "main",
            "sha": "1234567890abcdef",
            "repo": {"full_name": "acme/widget"},
        },
        "head": {
            "ref": "feature/widgets",
            "sha": "abcdef1234567890",
            "repo": {"full_name": "acme/widget"},
        },
        "merge_commit_sha": "fedcba9876543210",
        "commits": 3,
        "changed_files": 1,
        "additions": 5,
        "deletions": 2,
    }


def _files_payload() -> list[dict]:
    return [
        {
            "filename": "src/new_widget.py",
            "previous_filename": "src/widget.py",
            "status": "renamed",
            "additions": 5,
            "deletions": 2,
            "changes": 7,
            "patch": "@@ -1,2 +1,5 @@\n-old\n+new",
            "blob_url": "https://github.com/acme/widget/blob/head/src/new_widget.py",
            "raw_url": "https://raw.githubusercontent.com/acme/widget/head/src/new_widget.py",
        }
    ]


@pytest.mark.asyncio
async def test_fetch_pull_request_diff_formats_diff_and_metadata(monkeypatch):
    requested_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append((request.url.path, dict(request.url.params)))
        if request.url.path == "/repos/acme/widget/pulls/42":
            return httpx.Response(200, json=_pull_request_payload())
        if request.url.path == "/repos/acme/widget/pulls/42/files":
            return httpx.Response(200, json=_files_payload())
        return httpx.Response(404, json={"message": "not found"})

    transport = httpx.MockTransport(handler)

    def create_client(api_base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=api_base_url,
            headers=github_pull_request_diff_module._github_headers(),
            transport=transport,
        )

    monkeypatch.setattr(
        github_pull_request_diff_module, "_create_github_client", create_client
    )

    result = await github_pull_request_diff_module.fetch_pull_request_diff(
        "https://github.com/acme/widget/pull/42"
    )

    assert requested_paths == [
        ("/repos/acme/widget/pulls/42", {}),
        ("/repos/acme/widget/pulls/42/files", {"page": "1", "per_page": "100"}),
    ]
    assert "Pull Request: acme/widget#42" in result.diff
    assert "diff --git a/src/widget.py b/src/new_widget.py" in result.diff
    assert "rename from src/widget.py" in result.diff
    assert "@@ -1,2 +1,5 @@" in result.diff

    assert isinstance(result, PullRequestDiff)
    assert result.metadata.repository == "acme/widget"
    assert result.metadata.pull_number == 42
    assert result.metadata.files_changed == 1
    assert result.metadata.additions == 5
    assert result.metadata.deletions == 2
    assert result.metadata.files_without_patch == 0
    assert result.metadata.files[0].previous_filename == "src/widget.py"


def test_parse_github_pr_url_accepts_files_tab_urls():
    pr_ref = github_pull_request_diff_module._parse_github_pr_url(
        "https://github.com/acme/widget/pull/42/files"
    )

    assert pr_ref.owner == "acme"
    assert pr_ref.repo == "widget"
    assert pr_ref.number == 42
    assert pr_ref.api_base_url == "https://api.github.com"


def test_parse_github_pr_url_rejects_non_pr_urls():
    with pytest.raises(
        github_pull_request_diff_module.PullRequestDiffError,
        match="Expected a GitHub pull request URL",
    ) as exc_info:
        github_pull_request_diff_module._parse_github_pr_url(
            "https://github.com/acme/widget/issues/42"
        )

    assert exc_info.value.code == "invalid_pr_url"


@pytest.mark.asyncio
async def test_get_paginated_json_fetches_all_pages():
    requested_pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_pages.append(request.url.params["page"])
        page = int(request.url.params["page"])
        page_size = int(request.url.params["per_page"])
        payload = [{"filename": f"file-{index}.py"} for index in range(page_size)]
        if page == 2:
            payload = [{"filename": "last.py"}]
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.github.com", transport=transport
    ) as client:
        files = await github_pull_request_diff_module._get_paginated_json(
            client, "/repos/a/b/pulls/1/files"
        )

    assert requested_pages == ["1", "2"]
    assert len(files) == github_pull_request_diff_module.GITHUB_PER_PAGE + 1


def test_github_headers_use_available_token(monkeypatch):
    monkeypatch.setattr(
        github_pull_request_diff_module.settings, "github_token", "secret-token"
    )

    headers = github_pull_request_diff_module._github_headers()

    assert headers["Authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_fetch_pull_request_diff_raises_clear_error_for_missing_pr(
    monkeypatch,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    transport = httpx.MockTransport(handler)

    def create_client(api_base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=api_base_url, transport=transport)

    monkeypatch.setattr(
        github_pull_request_diff_module, "_create_github_client", create_client
    )

    with pytest.raises(
        github_pull_request_diff_module.PullRequestDiffError
    ) as exc_info:
        await github_pull_request_diff_module.fetch_pull_request_diff(
            "https://github.com/acme/widget/pull/999"
        )

    assert exc_info.value.code == "pull_request_not_found"
    assert exc_info.value.status_code == 404
    assert exc_info.value.to_dict() == {
        "type": "pull_request_fetch_failed",
        "code": "pull_request_not_found",
        "message": "GitHub API request failed (404): Not Found",
        "status_code": 404,
    }
