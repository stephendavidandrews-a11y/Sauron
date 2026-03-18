"""Security hardening — auth, rate limiting, exception handling, request logging."""

import logging
import os
import time

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("sauron.security")

# ── API Key Authentication ──

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Paths that skip authentication
_PUBLIC_PATHS = {
    "/api/health",
}


def _get_api_key() -> str:
    """Load the API key from environment. Raises on missing key."""
    key = os.environ.get("SAURON_API_KEY", "")
    if not key:
        logger.warning("SAURON_API_KEY not set — all API requests will be rejected")
    return key


async def require_api_key(
    request: Request,
    api_key: str | None = Security(_API_KEY_HEADER),
):
    """FastAPI dependency that enforces API key on /api/* routes.

    Skips auth for public paths and non-API paths (frontend static files).
    """
    path = request.url.path

    # Skip auth for non-API paths (frontend) and public endpoints
    if not path.startswith("/api/") or path in _PUBLIC_PATHS:
        return None

    expected = _get_api_key()
    if not expected:
        raise HTTPException(status_code=503, detail="Service misconfigured")

    if not api_key or api_key != expected:
        logger.warning("Auth failed: %s %s from %s", request.method, path, request.client.host)
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return api_key


# ── Global Exception Handler ──

async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions — log details, return generic error to client."""
    logger.exception(
        "Unhandled exception: %s %s from %s",
        request.method, request.url.path, request.client.host,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ── Request Audit Logging Middleware ──

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status code, latency, and client IP."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Skip noisy static asset requests
        path = request.url.path
        if path.startswith("/assets/") or path.endswith((".js", ".css", ".svg", ".ico")):
            return response

        logger.info(
            "%s %s %d %.0fms [%s]",
            request.method,
            path,
            response.status_code,
            elapsed_ms,
            request.client.host if request.client else "unknown",
        )
        return response
