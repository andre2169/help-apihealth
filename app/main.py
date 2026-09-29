import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.logging_config import setup_logging
from app.core import security_policy as policy
from app.middlewares import (
    ConcurrencyLimitMiddleware,
    CSRFMiddleware,
    ExceptionMiddleware,
    OriginCheckMiddleware,
    RateLimitMiddleware,
    RequestGuardMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.config import settings
from app.db.session import engine
from app.api.v1 import (
    tickets,
    comments,
    users,
    auth,
    admin,
    dashboard,
    notifications,
    reports,
    webhooks,
)

setup_logging()


app = FastAPI(
    title="HelpWeb Health API",
    description="API de chamados de TI para instituições de saúde",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": "Dados inválidos. Revise os campos e tente novamente."},
    )

docs_security = HTTPBasic(auto_error=False)


def require_docs_access(credentials: HTTPBasicCredentials | None = Depends(docs_security)):
    if not policy.API_DOCS_PASSWORD:
        return True

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação necessária",
            headers={"WWW-Authenticate": "Basic"},
        )

    valid_user = secrets.compare_digest(credentials.username, policy.API_DOCS_USERNAME)
    valid_password = secrets.compare_digest(credentials.password, policy.API_DOCS_PASSWORD)

    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação necessária",
            headers={"WWW-Authenticate": "Basic"},
        )

    return True

# Middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestGuardMiddleware)
app.add_middleware(ConcurrencyLimitMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(ExceptionMiddleware)

# CORS fica por último para envolver inclusive respostas de erro geradas por middleware.
allowed_origins = settings.allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Request-ID",
        policy.CSRF_HEADER_NAME,
    ],
    expose_headers=[
        "X-Request-ID",
        "Retry-After",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "Content-Disposition",
        policy.CSRF_HEADER_NAME,
    ],
)


# -------------------------
# API v1
# -------------------------
app.include_router(users.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(tickets.router, prefix="/api/v1")
app.include_router(comments.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")


if policy.ENABLE_API_DOCS:
    @app.get("/openapi.json", include_in_schema=False)
    def openapi_schema(_: bool = Depends(require_docs_access)):
        return get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )


    @app.get("/docs", include_in_schema=False)
    def swagger_docs(_: bool = Depends(require_docs_access)):
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title=f"{app.title} - Docs",
        )


    @app.get("/redoc", include_in_schema=False)
    def redoc_docs(_: bool = Depends(require_docs_access)):
        return get_redoc_html(
            openapi_url="/openapi.json",
            title=f"{app.title} - ReDoc",
        )




@app.get("/health")
def health_check():
    return {"status": "ok"}


if policy.ENABLE_DB_HEALTH_ENDPOINT:
    @app.get("/health/db")
    def database_health_check():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}


@app.get("/")
def root():
    response = {"name": "HelpWeb Health API", "status": "ok"}
    if policy.ENABLE_API_DOCS:
        response["docs"] = "/docs"
    return response
