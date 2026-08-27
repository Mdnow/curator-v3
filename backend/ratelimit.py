"""In-memory rate limiter for FastAPI (no extra dependencies)."""

import time
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimiter(BaseHTTPMiddleware):
    """Sliding-window limiter: {path_prefix: (max_requests, window_seconds)}."""

    def __init__(self, app, limits: dict[str, tuple[int, int]] | None = None):
        super().__init__(app)
        self._limits = limits or {
            "/api/login": (5, 60),
            "/api/register": (3, 60),
            "/api/ai/chat": (15, 60),
            "/api/ai/save-thought": (10, 60),
        }
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _cleanup(self, bucket: list[float], window: float) -> None:
        cutoff = time.time() - window
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        ip = self._client_ip(request)
        now = time.time()

        global_bucket = self._requests[f"_global:{ip}"]
        self._cleanup(global_bucket, 60)
        if len(global_bucket) >= 120:
            return JSONResponse(
                status_code=429,
                content={"detail": "слишком много запросов, подожди минуту"},
            )
        global_bucket.append(now)

        for prefix, (max_req, window) in self._limits.items():
            if path.startswith(prefix):
                bucket = self._requests[f"{prefix}:{ip}"]
                self._cleanup(bucket, window)
                if len(bucket) >= max_req:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "слишком много запросов, подожди минуту"},
                    )
                bucket.append(now)
                break

        return await call_next(request)
