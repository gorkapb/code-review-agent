# Code Review Agent

> Production-grade AI agent that reviews GitHub Pull Requests with eval pipelines, observability, and cost tracking built in.

## What it does

Code Review Agent ingests a GitHub Pull Request and produces a structured review:
potential bugs, security concerns, maintainability suggestions, and style observations.
Each observation is tied to a specific file and line, with severity, explanation, and
a suggested fix.

Unlike most LLM-powered code review tools, this project treats production concerns
as first-class: every run is traced and persisted, every model call is cost-tracked,
and a regression eval suite runs on every commit against a curated dataset of real
PRs with human reviews as ground truth.

## Why this project

This is a portfolio project demonstrating how to ship AI systems that survive
production: not just "the agent works on a sunny day", but instrumented, evaluated,
multi-tenant, and cost-aware from day one. The goal is to make every architectural
decision visible and defensible.

## Getting started

**Prerequisites:** Python 3.13+, [uv](https://docs.astral.sh/uv/)

```bash
# Clone and install dependencies
git clone https://github.com/gorkapb/code-review-agent.git
cd code-review-agent
uv sync --all-groups

# Install pre-commit hooks (required before first commit)
uv run pre-commit install

# Apply database migrations
uv run alembic upgrade head

# Run the API server
uv run python main.py

# Run the ARQ worker
uv run arq src.worker.worker.WorkerSettings
```

The server starts at `http://localhost:8000`. Hot-reload is enabled by default.

Pre-commit runs `ruff` (lint + format) automatically on every `git commit`. To run it manually:

```bash
uv run pre-commit run --all-files
```

### Docker Compose (recommended for local development)

Starts the API server together with Postgres and Redis — no local installs required beyond Docker.

```bash
cp .env.example .env
docker compose up --build
```

The API is available at `http://localhost:8000`. Data is persisted in named volumes (`postgres_data`, `redis_data`) across restarts.

Postgres and Redis are exposed to the host on non-default ports to avoid conflicts with other local stacks such as Langfuse:

```bash
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/code_review
REDIS_URL=redis://127.0.0.1:16379
```

Inside Docker Compose, the app still connects to `postgres:5432` and `redis:6379`.

To tear everything down and remove volumes:

```bash
docker compose down -v
```

## Running evals

The eval suite uses [deepeval](https://deepeval.com) with LLM-as-judge metrics. Set an OpenAI key in `.env`; metrics use `gpt-4o-mini` as the judge by default.

```bash
OPENAI_API_KEY=sk-...
EVAL_JUDGE_MODEL=gpt-4o-mini
```

**Run all metrics against the default dataset:**

```bash
uv run python run_evals.py
```

**Run a subset of metrics:**

```bash
uv run python run_evals.py --metrics answer_relevancy code_review_quality
```

**Point at a different dataset:**

```bash
uv run python run_evals.py --dataset eval_dataset/my_cases.json
```

**List available metrics:**

```bash
uv run python run_evals.py --list-metrics
```

Exit code is `0` if all cases pass, `1` if any fail — CI-friendly by default.

### Adding a dataset

Create a `.json` file (array of objects) in `eval_dataset/`. Required fields: `input`, `actual_output`. Optional: `expected_output`, `context`, `retrieval_context`.

```json
[
  {
    "input": "the prompt or diff sent to the agent",
    "actual_output": "the agent's response",
    "expected_output": "what a good response looks like",
    "context": ["background facts the response should be faithful to"]
  }
]
```

CSV is also supported — pass `--dataset path/to/file.csv`.

### Adding a metric

Open `src/eval/metrics.py`, define a function that returns a configured deepeval metric, then register it in `METRICS_REGISTRY`:

```python
def my_metric() -> SomeMetric:
    return SomeMetric(threshold=0.7, model=JUDGE_MODEL, include_reason=True)

METRICS_REGISTRY["my_metric"] = my_metric
```

That's it — it shows up in `--list-metrics` and can be selected via `--metrics my_metric`.

### Changing the judge model

Set `EVAL_JUDGE_MODEL` in `.env`. Any model supported by deepeval works (for example, `gpt-4o`).

## Langfuse tracing

The worker emits Langfuse traces for each PR review job when Langfuse credentials are configured:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENABLED=true
```

Each job uses a deterministic trace ID derived from the ARQ job ID, adds job and PR metadata as trace attributes, and records nested observations for GitHub diff fetch, Anthropic review generation, and output formatting. The Anthropic generation includes model name, model parameters, and token usage for Langfuse cost tracking.

By default, `LANGFUSE_CAPTURE_CONTENT=false` avoids sending full PR diffs and model outputs to Langfuse. Set it to `true` only when the reviewed code can be stored in your Langfuse project; API keys, tokens, passwords, emails, phone numbers, and card-like numbers are still masked before export.

## OpenTelemetry telemetry

OpenTelemetry is configured in code for API, queue, worker, HTTP client, and database timing. FastAPI, HTTPX, and SQLAlchemy are instrumented automatically; the ARQ enqueue and worker handoff use manual spans so the worker continues the API trace through the serialized job context. Queue wait time is also recorded as a custom histogram metric, `code_review.queue.latency`, in seconds.

To export traces and metrics, point the OTLP HTTP exporter at a collector:

```bash
OTEL_TRACING_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
# or set signal-specific endpoints:
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://otel-collector:4318/v1/traces
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://otel-collector:4318/v1/metrics
OTEL_SAMPLE_RATE=1.0
OTEL_METRIC_EXPORT_INTERVAL_MILLIS=60000.0
```

`OTEL_EXPORTER_OTLP_HEADERS` is also supported for hosted backends that require auth headers. Without an OTLP endpoint, spans and metrics are still created for local propagation tests but no exporter is attached.

## Observability boundary

OpenTelemetry is used for operational telemetry: API latency, enqueue duration, queue latency, worker duration, database spans, HTTP client spans, failures, retries, and service-level metrics.

Use Langfuse is used for agent telemetry: graph/node observations, prompts, model inputs and outputs, generations, token usage, cost tracking, and review-quality debugging.

## Status

In active development. MVP target: **end of May 2026**. See [Roadmap](#roadmap) for
the current phase.

## Architecture

_Diagram coming in week 2 (ADR-002)._

## Stack

- **Backend:** FastAPI, async Python
- **Database:** PostgreSQL (SQLAlchemy async), pgvector for repo context retrieval
- **Cache / queue:** Redis + ARQ
- **Agent framework:** LangGraph
- **Eval:** LLM-as-Judge + heuristic metrics + regression dataset
- **Observability:** structlog + OpenTelemetry + Prometheus
- **Auth:** API keys + JWT, multi-tenant aware
- **Infra:** Docker Compose (local), Railway or Fly.io (production)

## Roadmap

- [x] Repo scaffolding, ADR-001 (domain & stack rationale)
- [x] FastAPI skeleton + Postgres + Redis via Docker Compose (week 1)
- [x] Async job queue with ARQ — enqueue, poll, and cancel PR review jobs (week 2)
- [x] Persistent review storage — PostgreSQL models, Alembic migrations, hybrid Postgres/Redis state (week 2)
- [ ] Architecture diagram + LLM-as-Judge study (week 2)
- [ ] Agent end-to-end: PR diff → structured review, instrumented from day one (week 3)
- [ ] Eval pipeline + regression dataset of 20-50 PRs (week 4)
- [ ] Multi-tenant auth, retry logic, public deployment (June)
- [ ] Repo context retrieval with pgvector, advanced eval metrics (July)
- [ ] Dashboard, drift detection, technical post (August)

## Decision log

Architectural decisions are documented as ADRs in [`docs/decisions/`](docs/decisions/).

## Author

Gorka Pineda. AI Engineer, currently building production multi-agent systems at
Kyndryl. PhD candidate in Computer Science (UAB Barcelona).
[LinkedIn](https://www.linkedin.com/in/gorka-pineda/)
