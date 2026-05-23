from typing import Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

from src.agent.pr_diff import fetch_pull_request_diff

logger = structlog.get_logger(__name__)


class ReviewState(TypedDict):
    pr_url: str
    diff: str
    observations: list[str]
    metadata: dict[str, Any]


async def parse_diff(state: ReviewState) -> dict[str, Any]:
    logger.debug("node entered", node="parse_diff", pr_url=state["pr_url"])
    pull_request_diff = await fetch_pull_request_diff(state["pr_url"])
    result = {"diff": pull_request_diff.diff, "metadata": pull_request_diff.metadata}
    logger.debug(
        "node completed",
        node="parse_diff",
        files_changed=result["metadata"]["files_changed"],
    )
    return result


def analyze_with_llm(state: ReviewState) -> dict:
    logger.debug("node entered", node="analyze_with_llm")
    observations = [
        "Import added at module level — looks good.",
        "No tests updated for the new import.",
    ]
    logger.info(
        "analysis completed",
        node="analyze_with_llm",
        observation_count=len(observations),
    )
    return {"observations": observations}


def format_output(state: ReviewState) -> dict:
    logger.debug("node entered", node="format_output")
    result = {
        "metadata": {
            **state["metadata"],
            "summary": f"Found {len(state['observations'])} observation(s) for {state['pr_url']}.",
        },
    }
    logger.debug("node completed", node="format_output")
    return result


builder = StateGraph(ReviewState)
builder.add_node(parse_diff)
builder.add_node(analyze_with_llm)
builder.add_node(format_output)
builder.add_edge(START, "parse_diff")
builder.add_edge("parse_diff", "analyze_with_llm")
builder.add_edge("analyze_with_llm", "format_output")
builder.add_edge("format_output", END)

graph = builder.compile()
