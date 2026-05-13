import uvicorn

from src.observability.logging import configure_logging


def main() -> None:
    configure_logging()
    uvicorn.run(
        "src.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_config=None,  # structlog owns all logging configuration
    )


if __name__ == "__main__":
    main()
