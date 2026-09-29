import logging
import time

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core import security_policy as policy
from app.core.exceptions import (
    InvalidCredentials,
    InvalidUserRole,
    TicketInvalidStatus,
    TicketNotFound,
    TicketPermissionDenied,
    UserAlreadyExists,
    UserNotFound,
)
from app.core.request_context import get_client_ip
from app.middlewares.common import (
    request_action,
    request_id,
    request_log_level,
    error_category,
    http_status_label,
    safe_error_reason,
    status_reason,
    status_result,
    token_identity,
)

logger = logging.getLogger(__name__)


def _http_event_title(status_code: int) -> str:
    if status_code >= 500:
        return "Falha HTTP interna"
    if status_code >= 400:
        return "Solicitacao HTTP rejeitada"
    return "Solicitacao HTTP concluida"


def _log_controlled_failure(request, request_id_value, start_time, *, status_code: int, exc: Exception):
    action = request_action(request.method, request.url.path)
    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.log(
        request_log_level(request.method, request.url.path, status_code),
        "Falha HTTP controlada | action=%s | result=%s | status=%s (%s) | error_type=%s | reason=%s | request_id=%s | method=%s | route=%s | duration_ms=%.2f | ip=%s | identity=%s",
        action,
        status_result(status_code),
        status_code,
        http_status_label(status_code),
        exc.__class__.__name__,
        safe_error_reason(exc),
        request_id_value,
        request.method,
        request.url.path,
        duration_ms,
        get_client_ip(request),
        token_identity(request),
    )


class ExceptionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.perf_counter()
        current_request_id = request_id(request)
        request.state.request_id = current_request_id

        try:
            response = await call_next(request)
            response.headers.setdefault("X-Request-ID", current_request_id)

            duration_ms = (time.perf_counter() - start_time) * 1000
            action = request_action(request.method, request.url.path)
            result = status_result(response.status_code)
            level = request_log_level(request.method, request.url.path, response.status_code)

            logger.log(
                level,
                "%s | action=%s | result=%s | reason=%s | status=%s (%s) | request_id=%s | method=%s | route=%s | duration_ms=%.2f | ip=%s | identity=%s",
                _http_event_title(response.status_code),
                action,
                result,
                status_reason(response.status_code),
                response.status_code,
                http_status_label(response.status_code),
                current_request_id,
                request.method,
                request.url.path,
                duration_ms,
                get_client_ip(request),
                token_identity(request),
            )

            return response

        except TicketNotFound as exc:
            _log_controlled_failure(request, current_request_id, start_time, status_code=404, exc=exc)

            return JSONResponse(
                status_code=404,
                content={"detail": str(exc) or "Ticket não encontrado"},
                headers={"X-Request-ID": current_request_id},
            )

        except TicketInvalidStatus as exc:
            _log_controlled_failure(request, current_request_id, start_time, status_code=400, exc=exc)

            return JSONResponse(
                status_code=400,
                content={"detail": str(exc) or "Status inválido para esta ação"},
                headers={"X-Request-ID": current_request_id},
            )

        except TicketPermissionDenied as exc:
            _log_controlled_failure(request, current_request_id, start_time, status_code=403, exc=exc)

            return JSONResponse(
                status_code=403,
                content={"detail": str(exc) or "Permissão negada"},
                headers={"X-Request-ID": current_request_id},
            )

        except InvalidCredentials as exc:
            _log_controlled_failure(request, current_request_id, start_time, status_code=401, exc=exc)

            return JSONResponse(
                status_code=401,
                content={"detail": str(exc) or "Credenciais inválidas"},
                headers={"X-Request-ID": current_request_id},
            )

        except UserNotFound as exc:
            _log_controlled_failure(request, current_request_id, start_time, status_code=404, exc=exc)

            return JSONResponse(
                status_code=404,
                content={"detail": str(exc) or "Usuário não encontrado"},
                headers={"X-Request-ID": current_request_id},
            )

        except (InvalidUserRole, UserAlreadyExists) as exc:
            _log_controlled_failure(request, current_request_id, start_time, status_code=400, exc=exc)

            return JSONResponse(
                status_code=400,
                content={"detail": str(exc) or "Dados de usuário inválidos"},
                headers={"X-Request-ID": current_request_id},
            )

        except Exception as exc:
            action = request_action(request.method, request.url.path)
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Falha HTTP inesperada | action=%s | result=server_error | status=500 (%s) | error_type=%s | error_category=%s | reason=%s | request_id=%s | method=%s | route=%s | duration_ms=%.2f | ip=%s | identity=%s",
                action,
                http_status_label(500),
                exc.__class__.__name__,
                error_category(exc),
                safe_error_reason(exc),
                current_request_id,
                request.method,
                request.url.path,
                duration_ms,
                get_client_ip(request),
                token_identity(request),
                exc_info=policy.LOG_INCLUDE_STACKTRACE,
            )

            return JSONResponse(
                status_code=500,
                content={"detail": "Erro interno do servidor"},
                headers={"X-Request-ID": current_request_id},
            )
