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

# Run the API server
uv run python main.py
```

The server starts at `http://localhost:8000`. Hot-reload is enabled by default.

Pre-commit runs `ruff` (lint + format) automatically on every `git commit`. To run it manually:

```bash
uv run pre-commit run --all-files
```

### Docker Compose (recommended for local development)

Starts the API server together with Postgres and Redis — no local installs required beyond Docker.

```bash
docker compose up --build
```

The API is available at `http://localhost:8000`. Data is persisted in named volumes (`postgres_data`, `redis_data`) across restarts.

To tear everything down and remove volumes:

```bash
docker compose down -v
```

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
- [ ] Architecture diagram + ARQ worker + LLM-as-Judge study (week 2)
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
