import logging

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.request_context import get_client_ip
from app.middlewares.common import JSON_ERROR_HEADERS

logger = logging.getLogger(__name__)


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
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
                        headers=JSON_ERROR_HEADERS,
                    )

        return await call_next(request)
