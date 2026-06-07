FROM python:3.13-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini main.py ./

# Run as an unprivileged user.
RUN useradd --create-home --uid 1000 app \
    && chown -R app:app /app
USER app

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uv run uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT}"]
