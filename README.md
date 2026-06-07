# Code Review Agent

> AI agent that reviews GitHub Pull Requests, with evals and observability built in.

## What it does

Give it a GitHub PR URL and it produces a structured review — potential bugs,
security concerns, maintainability suggestions, and style notes — each tied to a
specific file and line with a severity, explanation, and suggested fix.

Every review runs as a background job: the API enqueues it, an ARQ worker runs the
LangGraph agent, and the result is persisted in Postgres. Each run is traced
(Langfuse for the agent, OpenTelemetry for the infrastructure) and model calls are
cost-tracked.

## Quick start

**Prerequisites:** Docker, an Anthropic API key.

```bash
cp .env.example .env          # then set ANTHROPIC_API_KEY (and optional tokens)
docker compose up --build
```

This starts four services: `migrate` (applies Alembic migrations, then exits),
`app` (the API on http://localhost:8000), `worker` (the ARQ job runner), plus
`postgres` and `redis`. Data persists in named volumes across restarts.

Tear everything down, including volumes:

```bash
docker compose down -v
```

## API

```bash
# Enqueue a review — returns a job id
curl -X POST http://localhost:8000/reviews \
  -H 'content-type: application/json' \
  -d '{"pr_url": "https://github.com/owner/repo/pull/123"}'
# => {"job_id": "..."}

# Poll for status / result
curl http://localhost:8000/reviews/<job_id>
```

`GET /reviews/{job_id}` returns `queued` / `in_progress` while running and the
full review once `complete` (or `failed`). Health check at `GET /health`.

## Configuration

All configuration lives in `.env` (see `.env.example` for the full list). Notable
values:

- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` — the review model.
- `GITHUB_TOKEN` — optional; raises GitHub rate limits and allows private repos.
- `LANGFUSE_*` — Langfuse tracing; leave keys blank to run without it. Self-hosted
  Langfuse on the host is reached from containers via `host.docker.internal`.
- `OTEL_*` — OpenTelemetry export; without an OTLP endpoint, spans are created but
  not exported.

## Evals

The eval suite uses [deepeval](https://deepeval.com) with LLM-as-judge metrics
(`gpt-4o-mini` by default). Set `OPENAI_API_KEY` in `.env`, then:

```bash
uv run python run_evals.py                         # all metrics, default dataset
uv run python run_evals.py --metrics answer_relevancy code_review_quality
uv run python run_evals.py --dataset eval_dataset/my_cases.json
uv run python run_evals.py --list-metrics
```

Exit code is `0` if all cases pass, `1` otherwise. Metrics live in
`src/eval/metrics.py` (register one in `METRICS_REGISTRY`); datasets are JSON or
CSV files in `eval_dataset/`.

## Observability

- **OpenTelemetry** — operational telemetry. FastAPI, HTTPX, and SQLAlchemy are
  auto-instrumented; the ARQ enqueue and worker handoff use manual spans so the
  worker continues the API trace. Job lifecycle and queue-latency metrics are
  emitted under `code_review.*`. Export via OTLP by setting `OTEL_EXPORTER_OTLP_ENDPOINT`.
- **Langfuse** — agent telemetry. Each review job is one trace (deterministic id
  from the job id) with nested observations for diff fetch, review generation, and
  output formatting, plus token usage for cost tracking. `LANGFUSE_CAPTURE_CONTENT`
  is `false` by default so diffs and outputs are not sent.

## Development

```bash
uv sync --all-groups
uv run pre-commit install   # runs ruff lint + format on every commit
uv run pytest
```

CI (GitHub Actions) runs ruff, builds the Docker Compose stack, and runs the test
suite on every push and PR.

## Stack

- **API:** FastAPI (async Python 3.13)
- **Queue / worker:** Redis + ARQ
- **Database:** PostgreSQL (async SQLAlchemy + Alembic)
- **Agent:** LangGraph + Anthropic Claude
- **Evals:** deepeval (LLM-as-judge)
- **Observability:** structlog + OpenTelemetry + Langfuse
- **Infra:** Docker Compose (local), Railway (production)

## Author

Gorka Pineda. AI Engineer at Kyndryl, PhD candidate in Computer Science (UAB
Barcelona). [LinkedIn](https://www.linkedin.com/in/gorka-pineda/)
