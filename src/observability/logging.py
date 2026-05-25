import logging
import sys
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.trace import format_span_id, format_trace_id
from structlog.types import EventDict, Processor

from src.config import settings


def _add_service_context(_: Any, __: str, event_dict: EventDict) -> EventDict:
    event_dict.setdefault("service", settings.service_name)
    event_dict.setdefault("version", settings.service_version)
    return event_dict


def _add_otel_trace_context(_: Any, __: str, event_dict: EventDict) -> EventDict:
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict.setdefault("trace_id", format_trace_id(span_context.trace_id))
        event_dict.setdefault("span_id", format_span_id(span_context.span_id))
    return event_dict


def _rename_event_to_message(_: Any, __: str, event_dict: EventDict) -> EventDict:
    event_dict["message"] = event_dict.pop("event", "")
    return event_dict


def configure_logging() -> None:
    is_production = settings.env.lower() in ("production", "prod")
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _add_service_context,
        _add_otel_trace_context,
    ]

    if is_production:
        final_processors: list[Processor] = [
            structlog.processors.ExceptionRenderer(),
            _rename_event_to_message,
            structlog.processors.JSONRenderer(),
        ]
    else:
        final_processors = [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta]
        + final_processors,
        # Only foreign (stdlib) records need the shared chain — structlog records already ran it
        foreign_pre_chain=shared_processors
        + [structlog.processors.ExceptionRenderer()],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Silence uvicorn access log — replaced by RequestLoggingMiddleware
    logging.getLogger("uvicorn.access").propagate = False
    # Quiet noisy libs at WARNING unless explicitly overridden
    for lib in ("sqlalchemy.engine", "alembic", "arq"):
        logging.getLogger(lib).setLevel(max(log_level, logging.WARNING))
