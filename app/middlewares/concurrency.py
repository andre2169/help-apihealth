import asyncio
import logging

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core import security_policy as policy
from app.core.request_context import get_client_ip
from app.middlewares.common import JSON_ERROR_HEADERS

logger = logging.getLogger(__name__)


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._semaphore = asyncio.Semaphore(policy.MAX_CONCURRENT_REQUESTS)

    async def dispatch(self, request, call_next):
        acquired = False
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=policy.CONCURRENCY_WAIT_TIMEOUT_SECONDS,
            )
            acquired = True
            return await call_next(request)
        except asyncio.TimeoutError:
            logger.warning(
                "Concorrência excedida | method=%s | path=%s | ip=%s | max=%s",
                request.method,
                request.url.path,
                get_client_ip(request),
                policy.MAX_CONCURRENT_REQUESTS,
            )
            return JSONResponse(
                status_code=503,
                content={"detail": "Servidor ocupado. Tente novamente em instantes."},
                headers={**JSON_ERROR_HEADERS, "Retry-After": "2"},
            )
        finally:
            if acquired:
                self._semaphore.release()
