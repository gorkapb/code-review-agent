from datetime import UTC, datetime

import pytest

from src.agent import nodes as nodes_module
from src.agent.schemas import (
    Finding,
    PullRequestDiff,
    PullRequestMetadata,
    ReviewAnalysis,
)


@pytest.mark.asyncio
async def test_fetch_diff_node_delegates_to_github_pull_request_diff_service(
    monkeypatch,
):
    async def fetch_pull_request_diff(pr_url: str) -> PullRequestDiff:
        assert pr_url == "https://github.com/acme/widget/pull/42"
        return PullRequestDiff(
            diff="diff --git a/app.py b/app.py",
            metadata=PullRequestMetadata(
                pr_url=pr_url,
                repository="acme/widget",
                owner="acme",
                repo="widget",
                pull_number=42,
                draft=False,
                files_changed=1,
                changed_files=1,
                additions=1,
                deletions=0,
                files_without_patch=0,
                files=[],
                fetched_at=datetime(2026, 5, 23, tzinfo=UTC),
            ),
        )

    monkeypatch.setattr(
        nodes_module, "fetch_pull_request_diff", fetch_pull_request_diff
    )

    result = await nodes_module.fetch_diff(
        {
            "pr_url": "https://github.com/acme/widget/pull/42",
            "diff": "",
            "findings": [],
            "metadata": {},
        }
    )

    assert result["diff"] == "diff --git a/app.py b/app.py"
    assert result["metadata"]["repository"] == "acme/widget"
    assert result["metadata"]["files_changed"] == 1
    assert result["metadata"]["fetched_at"] == "2026-05-23T00:00:00Z"


@pytest.mark.asyncio
async def test_analyze_diff_node_delegates_to_review_service(monkeypatch):
    async def review_pull_request_diff(
        *,
        diff: str,
        metadata: dict,
    ) -> ReviewAnalysis:
        assert diff == "diff --git a/app.py b/app.py"
        assert metadata == {"files_changed": 1}
        return ReviewAnalysis(
            findings=[
                Finding(
                    severity="high",
                    category="bug",
                    line_ref="app.py:12",
                    message="The branch skips authorization.",
                    suggestion="Check authorization before returning data.",
                    confidence="high",
                )
            ]
        )

    monkeypatch.setattr(
        nodes_module, "review_pull_request_diff", review_pull_request_diff
    )

    result = await nodes_module.analyze_diff(
        {
            "pr_url": "https://github.com/acme/widget/pull/42",
            "diff": "diff --git a/app.py b/app.py",
            "findings": [],
            "metadata": {"files_changed": 1},
        }
    )

    assert result["findings"][0].line_ref == "app.py:12"


def test_format_output_node_delegates_to_review_output_service(monkeypatch):
    finding = Finding(
        severity="medium",
        category="testing",
        line_ref="app.py:20",
        message="The behavior changed without coverage.",
        suggestion="Add a regression test for this path.",
        confidence="medium",
    )

    def build_review_output(
        *,
        pr_url: str,
        findings: list[Finding],
        metadata: dict,
    ) -> dict:
        assert pr_url == "https://github.com/acme/widget/pull/42"
        assert findings == [finding]
        assert metadata == {"repository": "acme/widget"}
        return {"findings": [{"line_ref": "app.py:20"}], "metadata": metadata}

    monkeypatch.setattr(nodes_module, "build_review_output", build_review_output)

    result = nodes_module.format_output(
        {
            "pr_url": "https://github.com/acme/widget/pull/42",
            "diff": "diff --git a/app.py b/app.py",
            "findings": [finding],
            "metadata": {"repository": "acme/widget"},
        }
    )

    assert result == {
        "findings": [{"line_ref": "app.py:20"}],
        "metadata": {"repository": "acme/widget"},
    }
