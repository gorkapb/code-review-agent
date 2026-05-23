from src.agent.pr_diff import PullRequestDiffError
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
        "observations": [],
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
