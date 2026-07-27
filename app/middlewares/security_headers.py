from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
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
