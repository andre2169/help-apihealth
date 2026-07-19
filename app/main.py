import secrets

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.logging_config import setup_logging
from app.core.middleware import ExceptionMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from app.core.config import settings
from app.db.session import engine
from app.api.v1 import (
    tickets,
    comments,
    users,
    auth,
    admin,
    dashboard,
    reports,
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

docs_security = HTTPBasic(auto_error=False)


def require_docs_access(credentials: HTTPBasicCredentials | None = Depends(docs_security)):
    if not settings.API_DOCS_PASSWORD:
        return True

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação necessária",
            headers={"WWW-Authenticate": "Basic"},
        )

    valid_user = secrets.compare_digest(credentials.username, settings.API_DOCS_USERNAME)
    valid_password = secrets.compare_digest(credentials.password, settings.API_DOCS_PASSWORD)

    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação necessária",
            headers={"WWW-Authenticate": "Basic"},
        )

    return True

# CORS Middleware
allowed_origins = settings.allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
)


# Middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ExceptionMiddleware)


# -------------------------
# API v1
# -------------------------
app.include_router(users.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(tickets.router, prefix="/api/v1")
app.include_router(comments.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")


if settings.ENABLE_API_DOCS:
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


if settings.ENABLE_DB_HEALTH_ENDPOINT:
    @app.get("/health/db")
    def database_health_check():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}


@app.get("/")
def root():
    response = {"name": "HelpWeb Health API", "status": "ok"}
    if settings.ENABLE_API_DOCS:
        response["docs"] = "/docs"
    return response
