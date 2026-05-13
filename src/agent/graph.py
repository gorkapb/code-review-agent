from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class ReviewState(TypedDict):
    pr_url: str
    diff: str
    observations: list[str]
    metadata: dict[str, Any]


def parse_diff(state: ReviewState) -> dict:
    return {
        "diff": "--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,4 @@\n+import os\n def main():\n     pass",
        "metadata": {"files_changed": 1, "additions": 1, "deletions": 0},
    }


def analyze_with_llm(state: ReviewState) -> dict:
    return {
        "observations": [
            "Import added at module level — looks good.",
            "No tests updated for the new import.",
        ],
    }


def format_output(state: ReviewState) -> dict:
    return {
        "metadata": {
            **state["metadata"],
            "summary": f"Found {len(state['observations'])} observation(s) for {state['pr_url']}.",
        },
    }


builder = StateGraph(ReviewState)
builder.add_node(parse_diff)
builder.add_node(analyze_with_llm)
builder.add_node(format_output)
builder.add_edge(START, "parse_diff")
builder.add_edge("parse_diff", "analyze_with_llm")
builder.add_edge("analyze_with_llm", "format_output")
builder.add_edge("format_output", END)

graph = builder.compile()
