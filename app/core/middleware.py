"""
Custom middleware for the Nakh application.
"""
import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware.

    Limits requests per IP address based on settings.rate_limit_per_minute.
    """

    def __init__(self, app, rate_limit: int = None, enabled: bool = None):
        super().__init__(app)
        self.rate_limit = rate_limit or settings.rate_limit_per_minute
        self.enabled = enabled if enabled is not None else settings.rate_limit_enabled
        self.requests: dict[str, list[float]] = defaultdict(list)
        self.lock = Lock()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Handle request with rate limiting."""
        if not self.enabled:
            return await call_next(request)

        # Get client IP
        ip = self._get_client_ip(request)

        # Check rate limit
        if self._is_rate_limited(ip):
            logger.warning(f"Rate limit exceeded for IP: {ip}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "message": "Too many requests. Please try again later.",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )

        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        """Get the client's IP address from the request."""
        # Check for X-Forwarded-For header (behind proxy)
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "127.0.0.1"
        return ip

    def _is_rate_limited(self, ip: str) -> bool:
        """Check if the IP has exceeded the rate limit."""
        now = time.time()
        window_start = now - 60  # 1 minute window

        with self.lock:
            # Clean old requests
            self.requests[ip] = [t for t in self.requests[ip] if t > window_start]

            # Check if limit exceeded
            if len(self.requests[ip]) >= self.rate_limit:
                return True

            # Record this request
            self.requests[ip].append(now)

            # Clean up old IPs periodically (every 10000 requests)
            total_requests = sum(len(v) for v in self.requests.values())
            if total_requests > 10000:
                self._cleanup_old_entries(window_start)

            return False

    def _cleanup_old_entries(self, window_start: float) -> None:
        """Remove old request records to prevent memory growth."""
        to_delete = []
        for ip, times in self.requests.items():
            if not times or max(times) < window_start:
                to_delete.append(ip)
        for ip in to_delete:
            del self.requests[ip]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Request logging middleware.

    Logs request method, path, status code, and processing time.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Handle request with logging."""
        start_time = time.time()

        # Process request
        response = await call_next(request)

        # Calculate processing time
        process_time = (time.time() - start_time) * 1000  # Convert to ms

        # Log request
        logger.info(
            f"{request.method} {request.url.path} "
            f"- {response.status_code} ({process_time:.2f}ms)"
        )

        # Add processing time header
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"

        return response
