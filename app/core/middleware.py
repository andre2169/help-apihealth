import asyncio
import logging
import time
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

try:
    import redis.asyncio as redis_async
except ImportError:  # pragma: no cover - Redis e opcional.
    redis_async = None

from app.core.auth import decode_access_token
from app.core.config import settings
from app.core.exceptions import (
    TicketNotFound,
    TicketInvalidStatus,
    TicketPermissionDenied,
    InvalidCredentials,
    InvalidUserRole,
    UserAlreadyExists,
    UserNotFound,
)
from app.core.request_context import get_client_ip

# Cria um logger específico para este arquivo.
# __name__ faz o log aparecer como app.core.middleware.
logger = logging.getLogger(__name__)

_rate_limit_buckets: dict[str, dict[str, float | int]] = {}

_JSON_ERROR_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}

_REDIS_FALLBACK_SECONDS = 30


def _request_id(request: Request) -> str:
    incoming = request.headers.get("x-request-id")
    if incoming and len(incoming) <= 80:
        return incoming
    return uuid4().hex


def _token_identity(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    else:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME)

    if not token:
        return "anon"

    payload = decode_access_token(token)
    if payload and payload.get("sub"):
        return f"user:{payload['sub']}"
    return "anon"


def _is_rate_limit_exempt(request: Request) -> bool:
    path = request.url.path
    return (
        (
            settings.ENABLE_API_DOCS
            and (
                path.startswith("/docs")
                or path.startswith("/redoc")
                or path == "/openapi.json"
            )
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
        headers={**_JSON_ERROR_HEADERS, "Retry-After": str(retry_after)},
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
        identity = _token_identity(request)

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


class RequestGuardMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        raw_headers = scope.get("headers", [])
        path_length = len(scope.get("raw_path", b"")) + len(scope.get("query_string", b""))

        if path_length > settings.MAX_REQUEST_URL_BYTES:
            logger.warning(
                "URL bloqueada por tamanho | method=%s | path=%s | ip=%s | bytes=%s",
                method,
                path,
                get_client_ip(request),
                path_length,
            )
            response = JSONResponse(
                status_code=414,
                content={"detail": "URL muito longa."},
                headers=_JSON_ERROR_HEADERS,
            )
            await response(scope, receive, send)
            return

        header_total = 0
        headers: dict[str, list[str]] = {}
        for name, value in raw_headers:
            header_total += len(name) + len(value)
            header_name = name.decode("latin-1", errors="ignore").lower()
            header_value = value.decode("latin-1", errors="ignore")
            headers.setdefault(header_name, []).append(header_value)

            if len(value) > settings.MAX_REQUEST_HEADER_VALUE_BYTES:
                logger.warning(
                    "Header bloqueado por tamanho | method=%s | path=%s | ip=%s | header=%s",
                    method,
                    path,
                    get_client_ip(request),
                    header_name,
                )
                response = JSONResponse(
                    status_code=431,
                    content={"detail": "Cabeçalho muito grande."},
                    headers=_JSON_ERROR_HEADERS,
                )
                await response(scope, receive, send)
                return

        if header_total > settings.MAX_REQUEST_HEADER_BYTES:
            logger.warning(
                "Requisição bloqueada por soma de headers | method=%s | path=%s | ip=%s | bytes=%s",
                method,
                path,
                get_client_ip(request),
                header_total,
            )
            response = JSONResponse(
                status_code=431,
                content={"detail": "Cabeçalhos muito grandes."},
                headers=_JSON_ERROR_HEADERS,
            )
            await response(scope, receive, send)
            return

        content_lengths = headers.get("content-length", [])
        if len(content_lengths) > 1:
            response = JSONResponse(
                status_code=400,
                content={"detail": "Content-Length inválido."},
                headers=_JSON_ERROR_HEADERS,
            )
            await response(scope, receive, send)
            return

        content_length = content_lengths[0] if content_lengths else ""
        if content_length:
            try:
                request_body_bytes = int(content_length)
            except ValueError:
                response = JSONResponse(
                    status_code=400,
                    content={"detail": "Content-Length inválido."},
                    headers=_JSON_ERROR_HEADERS,
                )
                await response(scope, receive, send)
                return

            if request_body_bytes > settings.MAX_REQUEST_BODY_BYTES:
                logger.warning(
                    "Requisição bloqueada por tamanho de corpo | method=%s | path=%s | ip=%s | bytes=%s",
                    method,
                    path,
                    get_client_ip(request),
                    request_body_bytes,
                )
                response = JSONResponse(
                    status_code=413,
                    content={"detail": "Requisição muito grande."},
                    headers=_JSON_ERROR_HEADERS,
                )
                await response(scope, receive, send)
                return

        has_body = content_length and content_length != "0"
        if (
            (has_body or headers.get("content-type"))
            and method in {"POST", "PUT", "PATCH"}
            and path.startswith("/api/")
        ):
            content_type = (headers.get("content-type") or [""])[0].split(";", 1)[0].strip().lower()
            if content_type and content_type != "application/json":
                response = JSONResponse(
                    status_code=415,
                    content={"detail": "Tipo de conteúdo não suportado."},
                    headers=_JSON_ERROR_HEADERS,
                )
                await response(scope, receive, send)
                return

        should_buffer_body = method in {"POST", "PUT", "PATCH"} and path.startswith("/api/")
        if not should_buffer_body:
            await self.app(scope, receive, send)
            return

        body_messages: list[Message] = []
        received_bytes = 0

        while True:
            message = await receive()
            body_messages.append(message)

            if message["type"] != "http.request":
                break

            received_bytes += len(message.get("body", b""))
            if received_bytes > settings.MAX_REQUEST_BODY_BYTES:
                logger.warning(
                    "Requisição bloqueada por stream de corpo | method=%s | path=%s | ip=%s | bytes=%s",
                    method,
                    path,
                    get_client_ip(request),
                    received_bytes,
                )
                response = JSONResponse(
                    status_code=413,
                    content={"detail": "Requisição muito grande."},
                    headers=_JSON_ERROR_HEADERS,
                )
                await response(scope, receive, send)
                return

            if not message.get("more_body", False):
                break

        message_index = 0

        async def replay_receive() -> Message:
            nonlocal message_index
            if message_index < len(body_messages):
                message = body_messages[message_index]
                message_index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS)

    async def dispatch(self, request: Request, call_next):
        acquired = False
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=settings.CONCURRENCY_WAIT_TIMEOUT_SECONDS,
            )
            acquired = True
            return await call_next(request)
        except asyncio.TimeoutError:
            logger.warning(
                "Concorrência excedida | method=%s | path=%s | ip=%s | max=%s",
                request.method,
                request.url.path,
                get_client_ip(request),
                settings.MAX_CONCURRENT_REQUESTS,
            )
            return JSONResponse(
                status_code=503,
                content={"detail": "Servidor ocupado. Tente novamente em instantes."},
                headers={**_JSON_ERROR_HEADERS, "Retry-After": "2"},
            )
        finally:
            if acquired:
                self._semaphore.release()


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin:
                normalized_origin = origin.rstrip("/")
                if normalized_origin not in settings.allowed_origins:
                    logger.warning(
                        "Origem bloqueada | method=%s | path=%s | origin=%s | ip=%s",
                        request.method,
                        request.url.path,
                        normalized_origin,
                        get_client_ip(request),
                    )
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Origem não autorizada."},
                        headers=_JSON_ERROR_HEADERS,
                    )

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        docs_path = request.url.path in {"/docs", "/redoc", "/openapi.json"}

        response.headers.setdefault("X-Frame-Options", "DENY")
        if docs_path and settings.ENABLE_API_DOCS:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self' https: 'unsafe-inline'; img-src 'self' data: https:; frame-ancestors 'none'; base-uri 'none'",
            )
        else:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-DNS-Prefetch-Control", "off")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )

        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")

        return response


class ExceptionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        """
        Este método intercepta todas as requisições que passam pela API.

        Ele serve para:
        - medir o tempo da requisição;
        - registrar logs de sucesso;
        - registrar logs de erro;
        - devolver respostas padronizadas para exceções conhecidas.
        """

        # Marca o momento em que a requisição começou.
        start_time = time.perf_counter()
        request_id = _request_id(request)

        try:
            # call_next envia a requisição para o endpoint correto.
            response = await call_next(request)
            response.headers.setdefault("X-Request-ID", request_id)

            # Calcula quanto tempo a requisição demorou.
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Log de requisição concluída com sucesso.
            logger.info(
                "Requisição concluída | request_id=%s | method=%s | path=%s | status_code=%s | duration_ms=%.2f | ip=%s",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                get_client_ip(request),
            )

            return response

        except TicketNotFound as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Ticket não encontrado | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(e) or "Ticket não encontrado",
            )

            return JSONResponse(
                status_code=404,
                content={"detail": str(e) or "Ticket não encontrado"},
                headers={"X-Request-ID": request_id},
            )

        except TicketInvalidStatus as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Status inválido em operação de ticket | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(e) or "Status inválido para esta ação",
            )

            return JSONResponse(
                status_code=400,
                content={"detail": str(e) or "Status inválido para esta ação"},
                headers={"X-Request-ID": request_id},
            )

        except TicketPermissionDenied as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Permissão negada | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(e) or "Permissão negada",
            )

            return JSONResponse(
                status_code=403,
                content={"detail": str(e) or "Permissão negada"},
                headers={"X-Request-ID": request_id},
            )

        except InvalidCredentials as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Credenciais inválidas | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(e) or "Credenciais inválidas",
            )

            return JSONResponse(
                status_code=401,
                content={"detail": str(e) or "Credenciais inválidas"},
                headers={"X-Request-ID": request_id},
            )

        except UserNotFound as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Usuário não encontrado | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(e) or "Usuário não encontrado",
            )

            return JSONResponse(
                status_code=404,
                content={"detail": str(e) or "Usuário não encontrado"},
                headers={"X-Request-ID": request_id},
            )

        except (InvalidUserRole, UserAlreadyExists) as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Erro de validação de usuário | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(e) or "Dados de usuário inválidos",
            )

            return JSONResponse(
                status_code=400,
                content={"detail": str(e) or "Dados de usuário inválidos"},
                headers={"X-Request-ID": request_id},
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            # exc_info=True mostra o traceback completo no terminal.
            # Isso ajuda muito a descobrir onde o erro aconteceu.
            logger.error(
                "Erro interno inesperado | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(e),
                exc_info=True,
            )

            return JSONResponse(
                status_code=500,
                content={"detail": "Erro interno do servidor"},
                headers={"X-Request-ID": request_id},
            )
