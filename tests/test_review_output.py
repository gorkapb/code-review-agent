from src.agent.schemas import Finding
from src.agent.services.review_output import build_review_output


def test_build_review_output_serializes_findings_and_summary():
    finding = Finding(
        severity="medium",
        category="testing",
        line_ref="app.py:20",
        message="The behavior changed without coverage.",
        suggestion="Add a regression test for this path.",
        confidence="medium",
    )

    result = build_review_output(
        pr_url="https://github.com/acme/widget/pull/42",
        findings=[finding],
        metadata={"repository": "acme/widget"},
    )

    assert result["findings"] == [finding.model_dump(mode="json")]
    assert result["metadata"]["repository"] == "acme/widget"
    assert result["metadata"]["summary"] == (
        "Found 1 finding(s) for https://github.com/acme/widget/pull/42."
    )
