from typing import Any

import structlog

from src.agent.services.github_pull_request_diff import fetch_pull_request_diff
from src.agent.services.pull_request_review import review_pull_request_diff
from src.agent.services.review_output import build_review_output
from src.agent.state import ReviewState

logger = structlog.get_logger(__name__)


async def fetch_diff(state: ReviewState) -> dict[str, Any]:
    logger.debug("node entered", node="fetch_diff", pr_url=state["pr_url"])
    pull_request_diff = await fetch_pull_request_diff(state["pr_url"])
    result = {
        "diff": pull_request_diff.diff,
        "metadata": pull_request_diff.metadata.model_dump(mode="json"),
    }
    logger.debug(
        "node completed",
        node="fetch_diff",
        files_changed=result["metadata"]["files_changed"],
    )
    return result


async def analyze_diff(state: ReviewState) -> dict[str, Any]:
    logger.debug("node entered", node="analyze_diff")
    review = await review_pull_request_diff(
        diff=state["diff"],
        metadata=state.get("metadata", {}),
    )
    logger.info(
        "review completed",
        node="analyze_diff",
        finding_count=len(review.findings),
    )
    return {"findings": review.findings}


def format_output(state: ReviewState) -> dict[str, Any]:
    logger.debug("node entered", node="format_output")
    result = build_review_output(
        pr_url=state["pr_url"],
        findings=state["findings"],
        metadata=state["metadata"],
    )
    logger.debug("node completed", node="format_output")
    return result
