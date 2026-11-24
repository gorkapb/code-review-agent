"""
Core eval runner.

Ties together dataset loading and metric evaluation.
Use run_eval() directly in scripts, or call via run_evals.py CLI.

Two entry points:
- run_eval(): score a dataset that already contains actual_output.
- run_review_eval(): call the real review agent on each diff in a review-case
  dataset (eval_dataset/review_cases.json), score it deterministically, then
  run judge metrics on the same outputs.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from deepeval import evaluate
from deepeval.evaluate.configs import DisplayConfig
from deepeval.test_case import LLMTestCase

from src.agent.schemas import Finding, ReviewAnalysis
from src.agent.services.pull_request_review import (
    _review_model,
    review_pull_request_diff,
)
from src.eval.dataset import load_dataset
from src.eval.metrics import JUDGE_MODEL, load_metrics

# Severities that count as a false alarm on a clean diff.
_ABOVE_LOW = {"critical", "high", "medium"}


def run_eval(
    dataset_path: str | Path,
    metric_names: list[str] | None = None,
    verbose: bool = True,
) -> dict:
    """
    Run an eval suite against a dataset file.

    Args:
        dataset_path: Path to a .json or .csv file of test cases.
        metric_names: Subset of metric names to run (None = all metrics).
        verbose: Print per-case results to stdout.

    Returns:
        Dict with keys 'passed', 'failed', 'total', and 'results'.
    """
    test_cases: list[LLMTestCase] = load_dataset(dataset_path)
    return _run_judge(test_cases, metric_names, verbose, label=str(dataset_path))


def _run_judge(
    test_cases: list[LLMTestCase],
    metric_names: list[str] | None,
    verbose: bool,
    label: str,
) -> dict:
    metrics = load_metrics(metric_names)

    if verbose:
        print(f"\nRunning {len(metrics)} metric(s) on {len(test_cases)} test case(s)")
        print(f"Dataset : {label}")
        print(f"Metrics : {[m.__class__.__name__ for m in metrics]}\n")

    results = evaluate(
        test_cases=test_cases,
        metrics=metrics,
        display_config=DisplayConfig(
            print_results=verbose,
            inspect_after_run=False,
        ),
    )

    passed = sum(1 for r in results.test_results if r.success)
    total = len(results.test_results)

    summary = {
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "results": results,
    }

    if verbose:
        print("\n--- Summary ---")
        print(f"Passed : {passed}/{total}")
        print(f"Failed : {total - passed}/{total}")

    return summary


# --- Review-case eval: real agent + deterministic scoring + judge -----------


@dataclass
class ReviewCaseResult:
    case: dict
    analysis: ReviewAnalysis
    passed: bool

    @property
    def output_text(self) -> str:
        return findings_to_text(self.analysis.findings)


def findings_to_text(findings: list[Finding]) -> str:
    """Render findings as plain text for the judge (actual_output)."""
    if not findings:
        return "No issues found."
    lines = []
    for i, f in enumerate(findings, 1):
        lines.append(
            f"{i}. [{f.severity}/{f.category}, confidence {f.confidence}] {f.line_ref}\n"
            f"   {f.message}\n"
            f"   Suggestion: {f.suggestion}"
        )
    return "\n".join(lines)


def _expected_text(case: dict) -> str:
    """Render the case's expectation as text for the judge (expected_output)."""
    if case["clean"]:
        return (
            "This diff is clean. A correct review reports no findings above low "
            "severity."
        )
    exp = case["expected"]
    return (
        f"A correct review flags a {exp['category']} issue related to "
        f"'{exp['keyword']}' in the changed code."
    )


def score_case(case: dict, findings: list[Finding]) -> bool:
    """Deterministic pass/fail for one case (no judge)."""
    if case["clean"]:
        return not any(f.severity in _ABOVE_LOW for f in findings)
    exp = case["expected"]
    keyword = exp["keyword"].lower()
    return any(
        f.category == exp["category"]
        and keyword in f"{f.message} {f.suggestion}".lower()
        for f in findings
    )


async def _review_all(cases: list[dict]) -> list[ReviewAnalysis]:
    # Sequential to keep rate limits and logs simple.
    return [
        await review_pull_request_diff(diff=case["diff"], metadata={}) for case in cases
    ]


def _judge_review_cases(
    results: list[ReviewCaseResult], metric_names: list[str] | None
) -> dict[str, list[dict]]:
    """Run judge metrics quietly; return {case_id: [metric result dicts]}."""
    test_cases = [
        LLMTestCase(
            name=r.case["id"],
            input=r.case["diff"],
            actual_output=r.output_text,
            expected_output=_expected_text(r.case),
        )
        for r in results
    ]
    evaluation = evaluate(
        test_cases=test_cases,
        metrics=load_metrics(metric_names),
        display_config=DisplayConfig(
            print_results=False,
            show_indicator=False,
            inspect_after_run=False,
        ),
    )
    return {
        tr.name: [
            {
                "name": m.name,
                "score": m.score,
                "threshold": m.threshold,
                "success": m.success,
                "reason": m.reason,
                "evaluation_model": m.evaluation_model,
                "error": m.error,
            }
            for m in (tr.metrics_data or [])
        ]
        for tr in evaluation.test_results
    }


def _case_record(r: ReviewCaseResult, judge_metrics: list[dict] | None) -> dict:
    record = {
        "id": r.case["id"],
        "clean": r.case["clean"],
        "expected": r.case["expected"],
        "deterministic_pass": r.passed,
        "findings": [f.model_dump(mode="json") for f in r.analysis.findings],
    }
    if judge_metrics is not None:
        record["judge"] = judge_metrics
    return record


def _print_review_summary(report: dict) -> None:
    judged = report["judge_model"] is not None
    header = f"{'case':<34} {'det':<5} {'judge':<6} findings"
    print("\n" + header)
    print("-" * len(header))
    for c in report["cases"]:
        judge_col = ""
        if judged:
            scores = [m["score"] for m in c.get("judge", []) if m["score"] is not None]
            judge_col = " ".join(f"{s:.2f}" for s in scores) or "err"
        tags = ", ".join(f"{f['severity']}/{f['category']}" for f in c["findings"])
        det = "PASS" if c["deterministic_pass"] else "FAIL"
        print(f"{c['id']:<34} {det:<5} {judge_col:<6} {tags or '-'}")

    t = report["totals"]
    print(f"\nBugs caught             : {t['bugs_caught']}/{t['bug_total']}")
    print(f"Clean diffs, false alarm: {t['false_alarms']}/{t['clean_total']}")
    if judged:
        print(
            f"Judge passed            : {t['judge_passed']}/{t['judge_total']} "
            f"(mean score {t['judge_mean_score']:.2f})"
        )


def run_review_eval(
    dataset_path: str | Path,
    metric_names: list[str] | None = None,
    verbose: bool = True,
    judge: bool = True,
    output_dir: str | Path | None = "eval_results",
) -> dict:
    """
    Call the real review agent on every case, score deterministically, then
    (optionally) run judge metrics on the same outputs.

    Prints a compact summary and writes a JSON report (one record per case
    with findings, deterministic result and judge score/reason) to output_dir.
    """
    started_at = datetime.now(UTC)
    cases = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    analyses = asyncio.run(_review_all(cases))
    results = [
        ReviewCaseResult(case=c, analysis=a, passed=score_case(c, a.findings))
        for c, a in zip(cases, analyses, strict=True)
    ]

    judge_by_case = _judge_review_cases(results, metric_names) if judge else {}

    bug_results = [r for r in results if not r.case["clean"]]
    clean_results = [r for r in results if r.case["clean"]]
    totals = {
        "bugs_caught": sum(r.passed for r in bug_results),
        "bug_total": len(bug_results),
        "false_alarms": sum(not r.passed for r in clean_results),
        "clean_total": len(clean_results),
    }
    if judge:
        per_case = list(judge_by_case.values())
        scores = [m["score"] for ms in per_case for m in ms if m["score"] is not None]
        totals |= {
            "judge_passed": sum(all(m["success"] for m in ms) for ms in per_case),
            "judge_total": len(per_case),
            "judge_mean_score": sum(scores) / len(scores) if scores else 0.0,
        }

    report = {
        "started_at": started_at.isoformat(),
        "dataset": str(dataset_path),
        "review_model": _review_model(),
        "judge_model": JUDGE_MODEL if judge else None,
        "totals": totals,
        "cases": [
            _case_record(r, judge_by_case.get(r.case["id"]) if judge else None)
            for r in results
        ],
    }

    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"review_{started_at:%Y%m%dT%H%M%SZ}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["report_path"] = str(path)

    if verbose:
        _print_review_summary(report)
        if "report_path" in report:
            print(f"\nReport: {report['report_path']}")

    return report
