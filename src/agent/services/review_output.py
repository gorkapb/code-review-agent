from typing import Any

from src.agent.schemas import Finding
from src.observability.langfuse import (
    start_langfuse_observation,
    summarize_pull_request_metadata,
)


def build_review_output(
    *,
    pr_url: str,
    findings: list[Finding],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    with start_langfuse_observation(
        name="format-review-output",
        input={
            "pr_url": pr_url,
            "finding_count": len(findings),
            "metadata": summarize_pull_request_metadata(metadata),
        },
    ) as observation:
        serialized_findings = [finding.model_dump(mode="json") for finding in findings]
        result = {
            "findings": serialized_findings,
            "metadata": {
                **metadata,
                "summary": f"Found {len(serialized_findings)} finding(s) for {pr_url}.",
            },
        }

        if observation is not None:
            observation.update(
                output={
                    "finding_count": len(serialized_findings),
                    "metadata": summarize_pull_request_metadata(result["metadata"]),
                }
            )

        return result
