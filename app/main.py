from fastapi import FastAPI
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
    docs_url="/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
)

# CORS Middleware
allowed_origins = settings.allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
