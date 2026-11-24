"""
CLI entry point for the eval runner.

Usage:
    uv run python run_evals.py
    uv run python run_evals.py --dataset eval_dataset/code_review_cases.json
    uv run python run_evals.py --metrics answer_relevancy faithfulness
    uv run python run_evals.py --list-metrics
    uv run python run_evals.py --review-cases eval_dataset/review_cases.json \
        --metrics code_review_quality
"""

import argparse
import sys

from src.eval.metrics import METRICS_REGISTRY
from src.eval.runner import run_eval, run_review_eval

DEFAULT_DATASET = "eval_dataset/code_review_cases.json"


def main():
    parser = argparse.ArgumentParser(description="Run deepeval metrics on a dataset")
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"Path to eval dataset (.json or .csv). Default: {DEFAULT_DATASET}",
    )
    parser.add_argument(
        "--metrics",
        nargs="+",
        default=None,
        help="Metric names to run. Runs all metrics if omitted.",
    )
    parser.add_argument(
        "--list-metrics",
        action="store_true",
        help="Print available metric names and exit",
    )
    parser.add_argument(
        "--review-cases",
        default=None,
        help="Review-case dataset: run the real agent on each diff, score it, then judge.",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="With --review-cases, skip the LLM judge and only score deterministically.",
    )
    parser.add_argument(
        "--output-dir",
        default="eval_results",
        help="With --review-cases, where to write the JSON report. Default: eval_results",
    )
    args = parser.parse_args()

    if args.list_metrics:
        print("Available metrics:")
        for name in METRICS_REGISTRY:
            print(f"  {name}")
        sys.exit(0)

    if args.review_cases:
        report = run_review_eval(
            dataset_path=args.review_cases,
            metric_names=args.metrics,
            judge=not args.no_judge,
            output_dir=args.output_dir,
        )
        t = report["totals"]
        ok = (
            t["bugs_caught"] == t["bug_total"]
            and t["false_alarms"] == 0
            and t.get("judge_passed", 0) == t.get("judge_total", 0)
        )
        sys.exit(0 if ok else 1)

    summary = run_eval(
        dataset_path=args.dataset,
        metric_names=args.metrics,
    )

    sys.exit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
