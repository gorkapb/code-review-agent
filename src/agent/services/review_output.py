from typing import Any

from src.agent.schemas import Finding


def build_review_output(
    *,
    pr_url: str,
    findings: list[Finding],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    serialized_findings = [finding.model_dump(mode="json") for finding in findings]
    return {
        "findings": serialized_findings,
        "metadata": {
            **metadata,
            "summary": f"Found {len(serialized_findings)} finding(s) for {pr_url}.",
        },
    }
