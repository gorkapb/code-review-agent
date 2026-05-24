"""
Metric definitions for the code review agent eval suite.

Add or remove metrics here to change what gets measured across all eval runs.
Each metric function returns a configured deepeval metric instance.
"""

import os

from deepeval.metrics import AnswerRelevancyMetric, GEval
from deepeval.test_case import LLMTestCaseParams

from src.config import settings

DEFAULT_JUDGE_MODEL = "gpt-4o-mini"
JUDGE_MODEL = settings.eval_judge_model.strip() or DEFAULT_JUDGE_MODEL

if settings.openai_api_key.strip() and not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key.strip()

# Threshold below which a test case is considered failed
DEFAULT_THRESHOLD = 0.7


def answer_relevancy() -> AnswerRelevancyMetric:
    """Is the review output relevant to the input diff/question?"""
    return AnswerRelevancyMetric(
        threshold=DEFAULT_THRESHOLD,
        model=JUDGE_MODEL,
        include_reason=True,
    )


def code_review_quality() -> GEval:
    """Custom G-Eval metric: is the review actionable and accurate for a code review agent?"""
    return GEval(
        name="CodeReviewQuality",
        criteria=(
            "Evaluate whether the code review is accurate, actionable, and specific. "
            "A good review: (1) correctly identifies the intent of the change, "
            "(2) raises any real concerns without inventing problems, "
            "(3) suggests concrete next steps when relevant."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
        ],
        threshold=DEFAULT_THRESHOLD,
        model=JUDGE_MODEL,
    )


# Registry: maps a short name to its factory function.
# The runner loads metrics by name from this dict so you can select subsets via CLI.
METRICS_REGISTRY: dict[str, callable] = {
    "answer_relevancy": answer_relevancy,
    "code_review_quality": code_review_quality,
    # faithfulness (FaithfulnessMetric) requires retrieval_context — add it back
    # if the agent is extended with RAG retrieval.
}


def load_metrics(names: list[str] | None = None):
    """Return instantiated metric objects. Pass None to load all metrics."""
    registry = METRICS_REGISTRY
    if names is not None:
        unknown = set(names) - set(registry)
        if unknown:
            raise ValueError(f"Unknown metrics: {unknown}. Available: {list(registry)}")
        registry = {k: v for k, v in registry.items() if k in names}
    return [factory() for factory in registry.values()]
