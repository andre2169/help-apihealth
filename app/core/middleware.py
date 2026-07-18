import logging
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.auth import decode_access_token
from app.core.config import settings
from app.core.exceptions import (
    TicketNotFound,
    TicketInvalidStatus,
    TicketPermissionDenied,
    InvalidCredentials,
)

# Cria um logger específico para este arquivo.
# __name__ faz o log aparecer como app.core.middleware.
logger = logging.getLogger(__name__)

_rate_limit_buckets: dict[str, dict[str, float | int]] = {}


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _token_identity(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return "anon"

    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    if payload and payload.get("sub"):
        return f"user:{payload['sub']}"
    return "anon"


def _is_rate_limit_exempt(request: Request) -> bool:
    path = request.url.path
    return (
        request.method == "OPTIONS"
        or path == "/"
        or path == "/health"
        or (settings.ENABLE_DB_HEALTH_ENDPOINT and path == "/health/db")
        or (
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


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _is_rate_limit_exempt(request):
            return await call_next(request)

        now = time.time()
        _cleanup_rate_limit_buckets(now)
        window = settings.RATE_LIMIT_WINDOW_SECONDS
        scope, max_requests = _rate_limit_scope(request)
        client_ip = _client_ip(request)
        identity = _token_identity(request)
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
            return JSONResponse(
                status_code=429,
                content={"detail": "Muitas requisições. Tente novamente em instantes."},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
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

        try:
            # call_next envia a requisição para o endpoint correto.
            response = await call_next(request)

            # Calcula quanto tempo a requisição demorou.
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Log de requisição concluída com sucesso.
            logger.info(
                "Requisição concluída | method=%s | path=%s | status_code=%s | duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )

            return response

        except TicketNotFound as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Ticket não encontrado | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request.method,
                request.url.path,
                duration_ms,
                str(e) or "Ticket não encontrado",
            )

            return JSONResponse(
                status_code=404,
                content={"detail": str(e) or "Ticket não encontrado"},
            )

        except TicketInvalidStatus as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Status inválido em operação de ticket | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request.method,
                request.url.path,
                duration_ms,
                str(e) or "Status inválido para esta ação",
            )

            return JSONResponse(
                status_code=400,
                content={"detail": str(e) or "Status inválido para esta ação"},
            )

        except TicketPermissionDenied as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Permissão negada | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request.method,
                request.url.path,
                duration_ms,
                str(e) or "Permissão negada",
            )

            return JSONResponse(
                status_code=403,
                content={"detail": str(e) or "Permissão negada"},
            )

        except InvalidCredentials as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Credenciais inválidas | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request.method,
                request.url.path,
                duration_ms,
                str(e) or "Credenciais inválidas",
            )

            return JSONResponse(
                status_code=401,
                content={"detail": str(e) or "Credenciais inválidas"},
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            # exc_info=True mostra o traceback completo no terminal.
            # Isso ajuda muito a descobrir onde o erro aconteceu.
            logger.error(
                "Erro interno inesperado | method=%s | path=%s | duration_ms=%.2f | error=%s",
                request.method,
                request.url.path,
                duration_ms,
                str(e),
                exc_info=True,
            )

            return JSONResponse(
                status_code=500,
                content={"detail": "Erro interno do servidor"},
            )
