from typing import Any, TypedDict

from src.agent.schemas import Finding


class ReviewState(TypedDict):
    pr_url: str
    diff: str
    findings: list[Finding]
    metadata: dict[str, Any]
