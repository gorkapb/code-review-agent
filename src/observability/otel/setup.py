from typing import Any

import structlog
from opentelemetry import metrics as otel_metrics
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.trace import ProxyTracerProvider

from src.config import settings

logger = structlog.get_logger(__name__)

TRACER_NAME = "code-review-agent"
FASTAPI_EXCLUDED_URLS = "^/health$,^/metrics$"

_trace_provider_configured = False
_meter_provider_configured = False
_owned_trace_provider: TracerProvider | None = None
_owned_meter_provider: MeterProvider | None = None
_httpx_instrumented = False
_sqlalchemy_instrumented = False


def configure_otel(*, sqlalchemy_engine: Any | None = None) -> None:
    """Configure OpenTelemetry once and attach low-noise library instrumentation."""
    _configure_trace_provider()
    _configure_meter_provider()
    _instrument_httpx()
    if sqlalchemy_engine is not None:
        instrument_sqlalchemy(sqlalchemy_engine)


def instrument_fastapi_app(app: Any) -> None:
    if not _traces_enabled():
        return

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=FASTAPI_EXCLUDED_URLS,
        exclude_spans=["receive", "send"],
    )


def instrument_sqlalchemy(engine: Any) -> None:
    global _sqlalchemy_instrumented

    if _sqlalchemy_instrumented or not _traces_enabled():
        return

    sync_engine = getattr(engine, "sync_engine", engine)
    SQLAlchemyInstrumentor().instrument(engine=sync_engine)
    _sqlalchemy_instrumented = True


def shutdown_otel() -> None:
    global _owned_meter_provider, _owned_trace_provider

    if _owned_meter_provider is not None:
        _owned_meter_provider.shutdown()
        _owned_meter_provider = None
    if _owned_trace_provider is not None:
        _owned_trace_provider.shutdown()
        _owned_trace_provider = None


def _configure_trace_provider() -> None:
    global _owned_trace_provider, _trace_provider_configured

    if _trace_provider_configured:
        return

    _trace_provider_configured = True
    if not _traces_enabled():
        logger.info("otel tracing disabled")
        return

    current_provider = trace.get_tracer_provider()
    if not isinstance(current_provider, ProxyTracerProvider):
        logger.info("otel tracer provider already configured")
        return

    provider = TracerProvider(
        resource=_resource(),
        sampler=TraceIdRatioBased(settings.otel_sample_rate),
    )
    exporter = _build_otlp_exporter()
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _owned_trace_provider = provider
    logger.info(
        "otel tracing configured",
        exporter="otlp" if exporter is not None else "none",
        sample_rate=settings.otel_sample_rate,
    )


def _configure_meter_provider() -> None:
    global _meter_provider_configured, _owned_meter_provider

    if _meter_provider_configured:
        return

    _meter_provider_configured = True
    if not _metrics_enabled():
        logger.info("otel metrics disabled")
        return

    current_provider = otel_metrics.get_meter_provider()
    if isinstance(current_provider, MeterProvider):
        logger.info("otel meter provider already configured")
        return

    metric_reader = _build_metric_reader()
    provider = MeterProvider(
        resource=_resource(),
        metric_readers=[metric_reader] if metric_reader is not None else [],
    )
    otel_metrics.set_meter_provider(provider)
    _owned_meter_provider = provider
    logger.info(
        "otel metrics configured",
        exporter="otlp" if metric_reader is not None else "none",
        export_interval_millis=settings.otel_metric_export_interval_millis,
    )


def _instrument_httpx() -> None:
    global _httpx_instrumented

    if _httpx_instrumented or not _traces_enabled():
        return

    HTTPXClientInstrumentor().instrument()
    _httpx_instrumented = True


def _build_otlp_exporter() -> OTLPSpanExporter | None:
    endpoint = _otlp_traces_endpoint()
    if endpoint is None:
        return None

    return OTLPSpanExporter(
        endpoint=endpoint,
        headers=_otlp_headers(),
        timeout=settings.otel_exporter_otlp_timeout,
    )


def _build_metric_reader() -> PeriodicExportingMetricReader | None:
    endpoint = _otlp_metrics_endpoint()
    if endpoint is None:
        return None

    exporter = OTLPMetricExporter(
        endpoint=endpoint,
        headers=_otlp_headers(),
        timeout=settings.otel_exporter_otlp_timeout,
    )
    return PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=settings.otel_metric_export_interval_millis,
        export_timeout_millis=settings.otel_exporter_otlp_timeout * 1000,
    )


def _otlp_traces_endpoint() -> str | None:
    return _otlp_signal_endpoint(settings.otel_exporter_otlp_traces_endpoint, "traces")


def _otlp_metrics_endpoint() -> str | None:
    return _otlp_signal_endpoint(
        settings.otel_exporter_otlp_metrics_endpoint,
        "metrics",
    )


def _otlp_signal_endpoint(specific_endpoint: str, signal: str) -> str | None:
    endpoint = specific_endpoint.strip()
    if endpoint:
        return endpoint

    endpoint = settings.otel_exporter_otlp_endpoint.strip().rstrip("/")
    if not endpoint:
        return None
    endpoint = endpoint.removesuffix("/v1/traces").removesuffix("/v1/metrics")
    return f"{endpoint}/v1/{signal}"


def _otlp_headers() -> dict[str, str] | None:
    headers: dict[str, str] = {}
    for header in settings.otel_exporter_otlp_headers.split(","):
        key, separator, value = header.partition("=")
        if not separator:
            continue
        key = key.strip()
        if key:
            headers[key] = value.strip()
    return headers or None


def _resource() -> Resource:
    return Resource.create(
        {
            "service.name": settings.service_name,
            "service.version": settings.service_version,
            "deployment.environment.name": settings.env,
        }
    )


def _otel_enabled() -> bool:
    return settings.otel_enabled


def _traces_enabled() -> bool:
    return _otel_enabled() and settings.otel_traces_enabled


def _metrics_enabled() -> bool:
    return _otel_enabled() and settings.otel_metrics_enabled


def tracer() -> trace.Tracer:
    configure_otel()
    return trace.get_tracer(TRACER_NAME, settings.service_version)


def meter() -> otel_metrics.Meter:
    configure_otel()
    return otel_metrics.get_meter(TRACER_NAME, settings.service_version)
