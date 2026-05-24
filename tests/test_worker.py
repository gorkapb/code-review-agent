from src.agent.services.github_pull_request_diff import PullRequestDiffError
from src.agent.services.pull_request_review import PullRequestReviewError
from src.worker.worker import _failure_result


def test_failure_result_exposes_pull_request_diff_errors():
    result = _failure_result(
        "https://github.com/acme/widget/pull/999",
        PullRequestDiffError(
            "GitHub API request failed (404): Not Found",
            code="pull_request_not_found",
            status_code=404,
        ),
    )

    assert result == {
        "pr_url": "https://github.com/acme/widget/pull/999",
        "diff": "",
        "findings": [],
        "metadata": {},
        "error": {
            "type": "pull_request_fetch_failed",
            "code": "pull_request_not_found",
            "message": "GitHub API request failed (404): Not Found",
            "status_code": 404,
        },
    }


def test_failure_result_hides_unexpected_error_details():
    result = _failure_result(
        "https://github.com/acme/widget/pull/42",
        RuntimeError("database password leaked in stack detail"),
    )

    assert result["error"] == {
        "type": "review_failed",
        "code": "unexpected_error",
        "message": "Unexpected error while reviewing pull request.",
    }


def test_failure_result_exposes_pull_request_review_errors():
    result = _failure_result(
        "https://github.com/acme/widget/pull/42",
        PullRequestReviewError(
            "ANTHROPIC_API_KEY is required to analyze pull request diffs.",
            code="missing_anthropic_api_key",
        ),
    )

    assert result == {
        "pr_url": "https://github.com/acme/widget/pull/42",
        "diff": "",
        "findings": [],
        "metadata": {},
        "error": {
            "type": "pull_request_review_failed",
            "code": "missing_anthropic_api_key",
            "message": "ANTHROPIC_API_KEY is required to analyze pull request diffs.",
        },
    }
