import logging
import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

try:
    import redis.asyncio as redis_async
except ImportError:  # pragma: no cover - Redis e opcional.
    redis_async = None

from app.core.config import settings
from app.core.request_context import get_client_ip
from app.middlewares.common import JSON_ERROR_HEADERS, token_identity

logger = logging.getLogger(__name__)

_rate_limit_buckets: dict[str, dict[str, float | int]] = {}
_REDIS_FALLBACK_SECONDS = 30


def _is_rate_limit_exempt(request: Request) -> bool:
    path = request.url.path
    return (
        settings.ENABLE_API_DOCS
        and (
            path.startswith("/docs")
            or path.startswith("/redoc")
            or path == "/openapi.json"
        )
    )


def _rate_limit_scope(request: Request) -> tuple[str, int]:
    path = request.url.path
    sensitive_prefixes = (
        "/api/v1/auth",
        "/api/v1/users",
        "/api/v1/admin",
    )
    if request.method == "OPTIONS" or path in {"/", "/health"}:
        return "public", settings.RATE_LIMIT_PUBLIC_MAX_REQUESTS
    if settings.ENABLE_DB_HEALTH_ENDPOINT and path == "/health/db":
        return "public", settings.RATE_LIMIT_PUBLIC_MAX_REQUESTS
    if request.method == "GET" and path.startswith("/api/v1/notifications"):
        return "polling", settings.RATE_LIMIT_POLLING_MAX_REQUESTS
    if request.method in {"POST", "PATCH", "DELETE"} or path.startswith(sensitive_prefixes):
        return "sensitive", settings.RATE_LIMIT_SENSITIVE_MAX_REQUESTS
    return "general", settings.RATE_LIMIT_MAX_REQUESTS


def _cleanup_rate_limit_buckets(now: float) -> None:
    if len(_rate_limit_buckets) < 5000:
        return

    expired_keys = [
        key
        for key, bucket in _rate_limit_buckets.items()
        if now >= float(bucket["reset_at"])
    ]
    for key in expired_keys:
        _rate_limit_buckets.pop(key, None)


def _rate_limit_response(*, retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Muitas requisições. Tente novamente em instantes."},
        headers={**JSON_ERROR_HEADERS, "Retry-After": str(retry_after)},
    )


def _safe_redis_key_part(value: str) -> str:
    return value.replace(" ", "_").replace("\n", "_").replace("\r", "_")[:120]


class RedisRateLimiter:
    def __init__(self):
        self._client: Any | None = None
        self._unavailable_until = 0.0
        self._missing_dependency_logged = False

    def _build_client(self):
        if not settings.REDIS_URL:
            return None

        if redis_async is None:
            if not self._missing_dependency_logged:
                logger.warning(
                    "REDIS_URL configurada, mas pacote redis nao esta instalado. "
                    "Rate limit distribuido desativado."
                )
                self._missing_dependency_logged = True
            return None

        if not self._client:
            self._client = redis_async.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=settings.REDIS_OPERATION_TIMEOUT_SECONDS,
            )
        return self._client

    async def consume(
        self,
        *,
        scope: str,
        client_ip: str,
        identity: str,
        max_requests: int,
        window_seconds: int,
        now: float,
    ) -> tuple[bool, int] | None:
        if not settings.REDIS_URL or now < self._unavailable_until:
            return None

        client = self._build_client()
        if client is None:
            return None

        bucket_id = int(now // window_seconds)
        redis_key = ":".join(
            (
                settings.REDIS_RATE_LIMIT_PREFIX,
                _safe_redis_key_part(scope),
                _safe_redis_key_part(client_ip),
                _safe_redis_key_part(identity),
                str(bucket_id),
            )
        )

        try:
            count = int(await client.incr(redis_key))
            if count == 1:
                await client.expire(redis_key, window_seconds + 5)

            retry_after = max(1, int(((bucket_id + 1) * window_seconds) - now))
            return count <= max_requests, retry_after
        except Exception as exc:  # pragma: no cover - depende de servico externo.
            self._unavailable_until = now + _REDIS_FALLBACK_SECONDS
            logger.warning(
                "Redis indisponivel para rate limit; usando memoria local por %ss | error=%s",
                _REDIS_FALLBACK_SECONDS,
                exc.__class__.__name__,
            )
            return None


_redis_rate_limiter = RedisRateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _is_rate_limit_exempt(request):
            return await call_next(request)

        now = time.time()
        _cleanup_rate_limit_buckets(now)
        window = settings.RATE_LIMIT_WINDOW_SECONDS
        scope, max_requests = _rate_limit_scope(request)
        client_ip = get_client_ip(request)
        identity = token_identity(request)

        redis_result = await _redis_rate_limiter.consume(
            scope=scope,
            client_ip=client_ip,
            identity=identity,
            max_requests=max_requests,
            window_seconds=window,
            now=now,
        )
        if redis_result is not None:
            allowed, retry_after = redis_result
            if not allowed:
                logger.warning(
                    "Rate limit excedido no Redis | scope=%s | method=%s | path=%s | ip=%s | identity=%s",
                    scope,
                    request.method,
                    request.url.path,
                    client_ip,
                    identity,
                )
                return _rate_limit_response(retry_after=retry_after)

            return await call_next(request)

        key = f"{scope}:{client_ip}:{identity}"
        bucket = _rate_limit_buckets.get(key)

        if not bucket or now >= float(bucket["reset_at"]):
            bucket = {"count": 0, "reset_at": now + window}

        bucket["count"] = int(bucket["count"]) + 1
        _rate_limit_buckets[key] = bucket

        if int(bucket["count"]) > max_requests:
            retry_after = max(1, int(float(bucket["reset_at"]) - now))
            logger.warning(
                "Rate limit excedido | scope=%s | method=%s | path=%s | ip=%s | identity=%s",
                scope,
                request.method,
                request.url.path,
                client_ip,
                identity,
            )
            return _rate_limit_response(retry_after=retry_after)

        return await call_next(request)
