import secrets

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core import security_policy as policy
from app.core.config import settings
from app.middlewares.common import JSON_ERROR_HEADERS


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/password/recovery/request",
    "/api/v1/auth/password/recovery/confirm",
}


def _is_csrf_exempt(path: str) -> bool:
    return (
        path in CSRF_EXEMPT_PATHS
        or path == "/api/v1/users"
        or path == "/api/v1/users/"
        or path.startswith("/api/v1/webhooks/")
    )


def _has_browser_session(request) -> bool:
    return bool(request.cookies.get(policy.AUTH_COOKIE_NAME))


def _set_csrf_cookie(response) -> str:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=policy.CSRF_COOKIE_NAME,
        value=token,
        max_age=policy.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=False,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
    )
    # O frontend pode estar em outro subdominio e, nesse caso, nao consegue
    # ler um cookie pertencente a API. O token nao autentica o usuario: ele
    # apenas precisa ser repetido no header para a comparacao double-submit.
    response.headers[policy.CSRF_HEADER_NAME] = token
    return token


def clear_csrf_cookie(response) -> None:
    response.delete_cookie(
        key=policy.CSRF_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        needs_check = (
            request.method in UNSAFE_METHODS
            and path.startswith("/api/")
            and not _is_csrf_exempt(path)
            and _has_browser_session(request)
        )

        if needs_check:
            cookie_token = request.cookies.get(policy.CSRF_COOKIE_NAME)
            header_token = request.headers.get(policy.CSRF_HEADER_NAME)
            if (
                not cookie_token
                or not header_token
                or not secrets.compare_digest(cookie_token, header_token)
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Token CSRF ausente ou inválido."},
                    headers=JSON_ERROR_HEADERS,
                )

        response = await call_next(request)
        if _has_browser_session(request) and path.startswith("/api/"):
            csrf_token = request.cookies.get(policy.CSRF_COOKIE_NAME)
            if not csrf_token:
                csrf_token = _set_csrf_cookie(response)
            else:
                # Permite que o frontend em outro subdominio recupere o
                # token sem expor o cookie de sessao ao JavaScript.
                response.headers.setdefault(policy.CSRF_HEADER_NAME, csrf_token)
        return response
