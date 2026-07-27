import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.request_context import get_client_ip
from app.middlewares.common import JSON_ERROR_HEADERS

logger = logging.getLogger(__name__)


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
                headers=JSON_ERROR_HEADERS,
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
                    headers=JSON_ERROR_HEADERS,
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
                headers=JSON_ERROR_HEADERS,
            )
            await response(scope, receive, send)
            return

        content_lengths = headers.get("content-length", [])
        if len(content_lengths) > 1:
            response = JSONResponse(
                status_code=400,
                content={"detail": "Content-Length inválido."},
                headers=JSON_ERROR_HEADERS,
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
                    headers=JSON_ERROR_HEADERS,
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
                    headers=JSON_ERROR_HEADERS,
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
                    headers=JSON_ERROR_HEADERS,
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
                    headers=JSON_ERROR_HEADERS,
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
