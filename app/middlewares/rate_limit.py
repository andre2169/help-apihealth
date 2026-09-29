import hashlib
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
from app.core import security_policy as policy
from app.core.request_context import get_client_ip
from app.middlewares.common import JSON_ERROR_HEADERS, token_identity

logger = logging.getLogger(__name__)

_rate_limit_buckets: dict[str, dict[str, float | int]] = {}


def _rate_limit_headers(
    *,
    limit: int,
    remaining: int,
    reset_at: int,
    retry_after: int | None = None,
) -> dict[str, str]:
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Reset": str(max(0, reset_at)),
    }
    if retry_after is not None:
        headers["Retry-After"] = str(max(1, retry_after))
    return headers

def _is_rate_limit_exempt(request: Request) -> bool:
    path = request.url.path
    return (
        policy.ENABLE_API_DOCS
        and (
            path.startswith("/docs")
            or path.startswith("/redoc")
            or path == "/openapi.json"
        )
    )


def _rate_limit_scope(request: Request) -> tuple[str, int]:
    path = request.url.path
    method = request.method.upper()
    normalized_path = path.rstrip("/") or "/"

    if request.method == "OPTIONS" or path in {"/", "/health"}:
        return "public", policy.RATE_LIMIT_PUBLIC_MAX_REQUESTS
    if policy.ENABLE_DB_HEALTH_ENDPOINT and path == "/health/db":
        return "public", policy.RATE_LIMIT_PUBLIC_MAX_REQUESTS

    # Webhook sem sessao: a assinatura continua sendo validada na rota, e o
    # limite evita que retries anormais do provedor sobrecarreguem a API.
    if normalized_path == "/api/v1/webhooks/evolution":
        return "webhook.evolution", policy.RATE_LIMIT_WEBHOOK_MAX_REQUESTS

    # Operacoes publicas de identidade possuem limites proprios. O login
    # tambem tem bloqueio progressivo por contexto IP + email no servico de
    # autenticacao; este e o segundo obstaculo, por IP e identidade da sessao.
    if normalized_path == "/api/v1/auth/login":
        return "auth.login", policy.RATE_LIMIT_AUTH_MAX_REQUESTS
    if normalized_path.startswith("/api/v1/auth/password/recovery"):
        return "auth.recovery", policy.RATE_LIMIT_RECOVERY_MAX_REQUESTS
    if normalized_path == "/api/v1/users":
        return "user.registration", policy.RATE_LIMIT_REGISTRATION_MAX_REQUESTS
    if normalized_path.startswith("/api/v1/auth"):
        return "auth.account", policy.RATE_LIMIT_AUTH_MAX_REQUESTS

    # As rotas mais caras ficam separadas para que uma tela nao consuma a
    # mesma cota usada por leitura de chamados ou por operacoes administrativas.
    if normalized_path == "/api/v1/dashboard/summary":
        return "dashboard.summary", policy.RATE_LIMIT_DASHBOARD_MAX_REQUESTS
    if normalized_path == "/api/v1/reports/overview.pdf":
        return "report.pdf", policy.RATE_LIMIT_REPORT_PDF_MAX_REQUESTS
    if normalized_path == "/api/v1/reports/overview":
        return "report.overview", policy.RATE_LIMIT_REPORT_MAX_REQUESTS

    if normalized_path.startswith("/api/v1/notifications"):
        if method == "GET":
            return "notification.read", policy.RATE_LIMIT_NOTIFICATION_READ_MAX_REQUESTS
        return "notification.write", policy.RATE_LIMIT_NOTIFICATION_WRITE_MAX_REQUESTS

    if normalized_path.startswith("/api/v1/admin"):
        if method in {"GET", "HEAD"}:
            return "admin.read", policy.RATE_LIMIT_ADMIN_READ_MAX_REQUESTS
        return "admin.write", policy.RATE_LIMIT_ADMIN_WRITE_MAX_REQUESTS

    if normalized_path.startswith("/api/v1/tickets"):
        if method in {"GET", "HEAD"}:
            return "ticket.read", policy.RATE_LIMIT_TICKET_READ_MAX_REQUESTS
        return "ticket.write", policy.RATE_LIMIT_TICKET_WRITE_MAX_REQUESTS

    if normalized_path.startswith("/api/v1/comments"):
        return "comment.write", policy.RATE_LIMIT_TICKET_WRITE_MAX_REQUESTS

    if method in {"POST", "PATCH", "DELETE", "PUT"}:
        return "sensitive", policy.RATE_LIMIT_SENSITIVE_MAX_REQUESTS
    return "general", policy.RATE_LIMIT_MAX_REQUESTS


def _cleanup_rate_limit_buckets(now: float) -> None:
    if len(_rate_limit_buckets) < policy.MAX_TRACKED_RATE_LIMIT_KEYS:
        return

    # Sob pressão, remova primeiro as chaves ociosas. Se todas estiverem
    # ativas, expulse as mais antigas para impedir crescimento ilimitado por
    # meio de IPs aleatórios.
    expired_keys = [
        key
        for key, bucket in _rate_limit_buckets.items()
        if now - float(bucket.get("last_seen_at", now))
        >= policy.RATE_LIMIT_WINDOW_SECONDS * 2
    ]
    for key in expired_keys:
        _rate_limit_buckets.pop(key, None)

    overflow = len(_rate_limit_buckets) - policy.MAX_TRACKED_RATE_LIMIT_KEYS + 1
    if overflow > 0:
        oldest_keys = sorted(
            _rate_limit_buckets,
            key=lambda key: float(_rate_limit_buckets[key].get("last_seen_at", 0)),
        )[:overflow]
        for key in oldest_keys:
            _rate_limit_buckets.pop(key, None)


def _rate_limit_response(
    *,
    limit: int,
    remaining: int,
    reset_at: int,
    retry_after: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Muitas requisições. Tente novamente em instantes."},
        headers={
            **JSON_ERROR_HEADERS,
            **_rate_limit_headers(
                limit=limit,
                remaining=remaining,
                reset_at=reset_at,
                retry_after=retry_after,
            ),
        },
    )


def _consume_local_rate_limit(
    *,
    key: str,
    max_requests: int,
    window_seconds: int,
    now: float,
) -> tuple[bool, int, int, int]:
    """Aplica Token Bucket em memoria para uma unica instancia da API."""
    capacity = float(max(max_requests, 1))
    refill_rate = capacity / max(float(window_seconds), 1.0)
    bucket = _rate_limit_buckets.get(key)

    if bucket is None:
        tokens = capacity
        last_refill_at = now
    else:
        last_refill_at = float(bucket.get("last_refill_at", now))
        elapsed = max(0.0, now - last_refill_at)
        tokens = min(
            capacity,
            float(bucket.get("tokens", capacity)) + elapsed * refill_rate,
        )

    allowed = tokens >= 1.0
    if allowed:
        tokens -= 1.0

    _rate_limit_buckets[key] = {
        "tokens": tokens,
        "last_refill_at": now,
        "last_seen_at": now,
    }

    retry_after = 0
    if not allowed:
        retry_after = max(1, int((1.0 - tokens) / refill_rate + 0.999999))

    # O reset informa quando o balde volta a capacidade total. Em uma
    # rejeicao, Retry-After informa o primeiro instante em que uma requisicao
    # pode ser aceita novamente.
    reset_after = max(1, int((capacity - tokens) / refill_rate + 0.999999))
    reset_at = int(now + reset_after)
    remaining = int(tokens)
    return allowed, retry_after, remaining, reset_at


def _safe_redis_key_part(value: str) -> str:
    # IP e identidade sao dados operacionais; nao os grave em claro no Redis.
    digest = hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()
    return digest[:32]


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
                socket_connect_timeout=policy.REDIS_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=policy.REDIS_OPERATION_TIMEOUT_SECONDS,
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
    ) -> tuple[bool, int, int, int] | None:
        if not settings.REDIS_URL or now < self._unavailable_until:
            return None

        client = self._build_client()
        if client is None:
            return None

        bucket_id = int(now // window_seconds)
        redis_key = ":".join(
            (
                policy.REDIS_RATE_LIMIT_PREFIX,
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
            remaining = max(0, max_requests - count)
            reset_at = int((bucket_id + 1) * window_seconds)
            return count <= max_requests, retry_after, remaining, reset_at
        except Exception as exc:  # pragma: no cover - depende de servico externo.
            self._unavailable_until = now + policy.REDIS_FALLBACK_SECONDS
            logger.warning(
                "Redis indisponivel para rate limit; usando memoria local por %ss | error=%s",
                policy.REDIS_FALLBACK_SECONDS,
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
        window = policy.RATE_LIMIT_WINDOW_SECONDS
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
            allowed, retry_after, remaining, reset_at = redis_result
            if not allowed:
                logger.warning(
                    "Rate limit excedido no Redis | scope=%s | method=%s | path=%s | ip=%s | identity=%s",
                    scope,
                    request.method,
                    request.url.path,
                    client_ip,
                    identity,
                )
                return _rate_limit_response(
                    limit=max_requests,
                    remaining=remaining,
                    reset_at=reset_at,
                    retry_after=retry_after,
                )

            response = await call_next(request)
            response.headers.update(
                _rate_limit_headers(
                    limit=max_requests,
                    remaining=remaining,
                    reset_at=reset_at,
                )
            )
            return response

        key = f"{scope}:{client_ip}:{identity}"
        allowed, retry_after, remaining, reset_at = _consume_local_rate_limit(
            key=key,
            max_requests=max_requests,
            window_seconds=window,
            now=now,
        )

        if not allowed:
            logger.warning(
                "Rate limit excedido | scope=%s | method=%s | path=%s | ip=%s | identity=%s",
                scope,
                request.method,
                request.url.path,
                client_ip,
                identity,
            )
            return _rate_limit_response(
                limit=max_requests,
                remaining=remaining,
                reset_at=reset_at,
                retry_after=retry_after,
            )

        response = await call_next(request)
        response.headers.update(
            _rate_limit_headers(
                limit=max_requests,
                remaining=remaining,
                reset_at=reset_at,
            )
        )
        return response
