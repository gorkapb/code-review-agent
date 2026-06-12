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

The API is authenticated, so issue yourself a tenant and API key before calling it:

```bash
docker compose exec app uv run python scripts/create_tenant.py "Acme Inc"
# prints tenant_id and a one-time api_key — store the key, it cannot be recovered
```

Tear everything down, including volumes:

```bash
docker compose down -v
```

## API

All `/reviews` endpoints require an API key, passed as a bearer token
(`Authorization: Bearer <key>`, per RFC 6750). Keys are issued per tenant with
`scripts/create_tenant.py`; jobs are scoped to the tenant that created them.

```bash
KEY=cra_...   # the api_key printed by create_tenant.py

# Enqueue a review — returns a job id
curl -X POST http://localhost:8000/reviews \
  -H "authorization: Bearer $KEY" \
  -H 'content-type: application/json' \
  -d '{"pr_url": "https://github.com/owner/repo/pull/123"}'
# => {"job_id": "..."}

# Poll for status / result
curl http://localhost:8000/reviews/<job_id> \
  -H "authorization: Bearer $KEY"
```

`GET /reviews/{job_id}` returns `queued` / `in_progress` while running and the
full review once `complete` (or `failed`); it returns the same `404` whether the
job doesn't exist or belongs to another tenant, so callers can't probe for other
tenants' jobs. Requests with a missing or invalid key get `401`. Keys are stored
only as an HMAC-SHA256 hash, never in plaintext. Health check at `GET /health`
(unauthenticated).

## Configuration

All configuration lives in `.env` (see `.env.example` for the full list). Notable
values:

- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` — the review model.
- `API_KEY_PEPPER` — server-side secret used to HMAC-hash tenant API keys.
  Required whenever `ENV` is not `development`; the app refuses to boot without it.
  Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`.
  Rotating it invalidates every existing key.
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
