"""
CLI entry point for the eval runner.

Usage:
    uv run python run_evals.py
    uv run python run_evals.py --dataset eval_dataset/code_review_cases.json
    uv run python run_evals.py --metrics answer_relevancy faithfulness
    uv run python run_evals.py --list-metrics
"""

import argparse
import sys

from src.eval.metrics import METRICS_REGISTRY
from src.eval.runner import run_eval

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
    args = parser.parse_args()

    if args.list_metrics:
        print("Available metrics:")
        for name in METRICS_REGISTRY:
            print(f"  {name}")
        sys.exit(0)

    summary = run_eval(
        dataset_path=args.dataset,
        metric_names=args.metrics,
    )

    sys.exit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
