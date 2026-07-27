import logging
import time

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

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
    status_result,
    token_identity,
)

logger = logging.getLogger(__name__)


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
                "Evento HTTP | action=%s | result=%s | request_id=%s | method=%s | path=%s | status_code=%s | duration_ms=%.2f | ip=%s | identity=%s",
                action,
                result,
                current_request_id,
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                get_client_ip(request),
                token_identity(request),
            )

            return response

        except TicketNotFound as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Ticket não encontrado | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                current_request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(exc) or "Ticket não encontrado",
            )

            return JSONResponse(
                status_code=404,
                content={"detail": str(exc) or "Ticket não encontrado"},
                headers={"X-Request-ID": current_request_id},
            )

        except TicketInvalidStatus as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Status inválido em operação de ticket | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                current_request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(exc) or "Status inválido para esta ação",
            )

            return JSONResponse(
                status_code=400,
                content={"detail": str(exc) or "Status inválido para esta ação"},
                headers={"X-Request-ID": current_request_id},
            )

        except TicketPermissionDenied as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Permissão negada | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                current_request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(exc) or "Permissão negada",
            )

            return JSONResponse(
                status_code=403,
                content={"detail": str(exc) or "Permissão negada"},
                headers={"X-Request-ID": current_request_id},
            )

        except InvalidCredentials as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Credenciais inválidas | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                current_request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(exc) or "Credenciais inválidas",
            )

            return JSONResponse(
                status_code=401,
                content={"detail": str(exc) or "Credenciais inválidas"},
                headers={"X-Request-ID": current_request_id},
            )

        except UserNotFound as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Usuário não encontrado | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                current_request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(exc) or "Usuário não encontrado",
            )

            return JSONResponse(
                status_code=404,
                content={"detail": str(exc) or "Usuário não encontrado"},
                headers={"X-Request-ID": current_request_id},
            )

        except (InvalidUserRole, UserAlreadyExists) as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "Erro de validação de usuário | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                current_request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(exc) or "Dados de usuário inválidos",
            )

            return JSONResponse(
                status_code=400,
                content={"detail": str(exc) or "Dados de usuário inválidos"},
                headers={"X-Request-ID": current_request_id},
            )

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.error(
                "Erro interno inesperado | request_id=%s | method=%s | path=%s | duration_ms=%.2f | error=%s",
                current_request_id,
                request.method,
                request.url.path,
                duration_ms,
                str(exc),
                exc_info=True,
            )

            return JSONResponse(
                status_code=500,
                content={"detail": "Erro interno do servidor"},
                headers={"X-Request-ID": current_request_id},
            )
