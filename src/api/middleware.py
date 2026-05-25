import time
import uuid
from collections.abc import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)

_EXCLUDED_PATHS = frozenset({"/health", "/metrics"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(
        self, app: ASGIApp, *, exclude_paths: frozenset[str] = _EXCLUDED_PATHS
    ) -> None:
        super().__init__(app)
        self.exclude_paths = exclude_paths

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        # Clear any context left by a previous request on this worker thread/task.
        structlog.contextvars.clear_contextvars()

        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            http_method=request.method,
            http_path=request.url.path,
            client_ip=request.client.host if request.client else None,
        )

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            # Must stay inside try: if call_next raises, response is never assigned.
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            if status_code < 400:
                log = logger.info
            elif status_code < 500:
                log = logger.warning
            else:
                log = logger.error
            log("request completed", status_code=status_code, duration_ms=duration_ms)
            structlog.contextvars.clear_contextvars()
