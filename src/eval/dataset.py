"""
Dataset loading utilities for the eval runner.

Supports JSON files (list of dicts) and CSV files.
Each record maps directly to an LLMTestCase — see field names below.
"""

import csv
import json
from pathlib import Path

from deepeval.test_case import LLMTestCase

# Maps JSON/CSV column names to LLMTestCase constructor kwargs.
# Only include fields you actually use; the rest stay None.
_FIELD_MAP = {
    "input": "input",
    "actual_output": "actual_output",
    "expected_output": "expected_output",
    "context": "context",
    "retrieval_context": "retrieval_context",
}


def _record_to_test_case(record: dict) -> LLMTestCase:
    kwargs = {}
    for src, dst in _FIELD_MAP.items():
        value = record.get(src)
        if value is not None:
            # context and retrieval_context must be lists
            if dst in ("context", "retrieval_context") and isinstance(value, str):
                value = [value]
            kwargs[dst] = value

    if "input" not in kwargs or "actual_output" not in kwargs:
        raise ValueError(
            f"Record missing required fields 'input' or 'actual_output': {record}"
        )

    return LLMTestCase(**kwargs)


def load_from_json(path: str | Path) -> list[LLMTestCase]:
    """Load test cases from a JSON file (list of objects)."""
    path = Path(path)
    records = json.loads(path.read_text())
    if not isinstance(records, list):
        raise ValueError(f"{path} must contain a JSON array at the top level")
    return [_record_to_test_case(r) for r in records]


def load_from_csv(
    path: str | Path,
    input_col: str = "input",
    actual_output_col: str = "actual_output",
) -> list[LLMTestCase]:
    """Load test cases from a CSV file."""
    path = Path(path)
    test_cases = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalise column names to the standard field names
            normalised = {**row}
            if input_col != "input":
                normalised["input"] = normalised.pop(input_col, None)
            if actual_output_col != "actual_output":
                normalised["actual_output"] = normalised.pop(actual_output_col, None)
            test_cases.append(_record_to_test_case(normalised))
    return test_cases


def load_dataset(path: str | Path, **csv_kwargs) -> list[LLMTestCase]:
    """Auto-detect format from file extension and load test cases."""
    path = Path(path)
    if path.suffix == ".json":
        return load_from_json(path)
    if path.suffix == ".csv":
        return load_from_csv(path, **csv_kwargs)
    raise ValueError(f"Unsupported file format: {path.suffix}. Use .json or .csv")
