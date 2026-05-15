"""
Core eval runner.

Ties together dataset loading and metric evaluation.
Use run_eval() directly in scripts, or call via run_evals.py CLI.
"""

from pathlib import Path

from deepeval import evaluate
from deepeval.evaluate.configs import DisplayConfig
from deepeval.test_case import LLMTestCase

from src.eval.dataset import load_dataset
from src.eval.metrics import load_metrics


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
    metrics = load_metrics(metric_names)

    if verbose:
        print(f"\nRunning {len(metrics)} metric(s) on {len(test_cases)} test case(s)")
        print(f"Dataset : {dataset_path}")
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
