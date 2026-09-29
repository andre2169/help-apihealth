import pytest
from pydantic import ValidationError
from types import SimpleNamespace

from app.core.config import Settings, settings
from app.core import security_policy as policy
from app.db.url import normalize_database_url
from app.middlewares.rate_limit import (
    _consume_local_rate_limit,
    _rate_limit_buckets,
    _rate_limit_scope,
)

from .conftest import login


def test_remote_postgres_cannot_disable_tls():
    normalized = normalize_database_url(
        "postgres://user:password@db.example:5432/helpweb?sslmode=disable"
    )

    assert "sslmode=require" in normalized


def test_local_sqlite_url_is_not_modified():
    url = "sqlite:///./helphealth-test.db"

    assert normalize_database_url(url) == url


def test_login_mfa_code_logging_is_enabled_only_for_local_sqlite_origins():
    local = Settings(
        DATABASE_URL="sqlite:///./test.db",
        SECRET_KEY="test-secret-key-with-at-least-32-characters",
        ADMIN_PASSWORD="test-admin-password-123",
        ALLOWED_ORIGINS="http://localhost:5173,http://127.0.0.1:5173",
        AUTH_COOKIE_SECURE=False,
    )
    remote_database = Settings(
        DATABASE_URL="postgresql://user:password@db.example/helphealth",
        SECRET_KEY="test-secret-key-with-at-least-32-characters",
        ADMIN_PASSWORD="test-admin-password-123",
        ALLOWED_ORIGINS="http://localhost:5173",
        AUTH_COOKIE_SECURE=False,
    )
    public_origin = Settings(
        DATABASE_URL="sqlite:///./test.db",
        SECRET_KEY="test-secret-key-with-at-least-32-characters",
        ADMIN_PASSWORD="test-admin-password-123",
        ALLOWED_ORIGINS="https://helpweb.example",
        AUTH_COOKIE_SECURE=True,
    )

    assert local.local_login_mfa_code_logging is True
    assert remote_database.local_login_mfa_code_logging is False
    assert public_origin.local_login_mfa_code_logging is False


@pytest.mark.parametrize(
    "url",
    (
        "http://evolution.example",
        "ftp://evolution.example",
        "https://user:password@evolution.example",
        "https://evolution.example/?token=secret",
    ),
)
def test_evolution_url_rejects_insecure_or_ambiguous_values(url):
    with pytest.raises(ValidationError):
        Settings(
            DATABASE_URL="sqlite:///./test.db",
            SECRET_KEY="test-secret-key-with-at-least-32-characters",
            ADMIN_PASSWORD="test-admin-password-123",
            EVOLUTION_API_URL=url,
        )


@pytest.mark.parametrize(
    "url",
    ("https://evolution.example", "http://localhost:8080", "http://127.0.0.1:8080"),
)
def test_evolution_url_allows_https_and_local_loopback(url):
    config = Settings(
        DATABASE_URL="sqlite:///./test.db",
        SECRET_KEY="test-secret-key-with-at-least-32-characters",
        ADMIN_PASSWORD="test-admin-password-123",
        EVOLUTION_API_URL=url,
    )

    assert config.EVOLUTION_API_URL == url


def test_security_headers_are_present_without_hsts_on_local_http(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"].startswith("default-src")
    assert "Strict-Transport-Security" not in response.headers


def test_untrusted_origin_is_rejected(client):
    response = client.get(
        "/api/v1/auth/me",
        headers={"Origin": "https://malicious.example"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Origem não autorizada."


def test_allowed_origin_preflight_is_explicit(client):
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert response.headers["Access-Control-Allow-Credentials"] == "true"


def test_login_does_not_return_a_bearer_token(client, db, user_factory):
    user_factory(email="helpweb.no-bearer@gmail.com")
    db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.no-bearer@gmail.com", "password": "SenhaTeste123"},
    )

    assert response.status_code == 200
    assert "access_token" not in response.json()
    assert client.cookies.get(policy.AUTH_COOKIE_NAME)


def test_protected_route_groups_require_authentication(client):
    protected_routes = (
        ("GET", "/api/v1/dashboard/summary"),
        ("GET", "/api/v1/reports/overview"),
        ("GET", "/api/v1/reports/overview.pdf"),
        ("GET", "/api/v1/notifications/"),
        ("GET", "/api/v1/admin/users"),
        ("GET", "/api/v1/tickets/"),
    )

    for method, path in protected_routes:
        response = client.request(method, path)
        assert response.status_code == 401, (method, path, response.text)


def test_dashboard_reports_and_admin_routes_enforce_roles(
    client, db, user_factory
):
    regular_user = user_factory(email="helpweb.route-guard.user@gmail.com")
    db.commit()
    login(client, regular_user.email)

    assert client.get("/api/v1/dashboard/summary").status_code == 403
    assert client.get("/api/v1/reports/overview").status_code == 403
    assert client.get("/api/v1/admin/users").status_code == 403


def test_rate_limit_uses_operation_specific_scopes():
    def request(path: str, method: str = "GET"):
        return SimpleNamespace(
            method=method,
            url=SimpleNamespace(path=path),
        )

    assert _rate_limit_scope(request("/api/v1/auth/login", "POST")) == (
        "auth.login",
        policy.RATE_LIMIT_AUTH_MAX_REQUESTS,
    )
    assert _rate_limit_scope(request("/api/v1/auth/password/recovery/request", "POST")) == (
        "auth.recovery",
        policy.RATE_LIMIT_RECOVERY_MAX_REQUESTS,
    )
    assert _rate_limit_scope(request("/api/v1/users/", "POST")) == (
        "user.registration",
        policy.RATE_LIMIT_REGISTRATION_MAX_REQUESTS,
    )
    assert _rate_limit_scope(request("/api/v1/dashboard/summary")) == (
        "dashboard.summary",
        policy.RATE_LIMIT_DASHBOARD_MAX_REQUESTS,
    )
    assert _rate_limit_scope(request("/api/v1/reports/overview.pdf")) == (
        "report.pdf",
        policy.RATE_LIMIT_REPORT_PDF_MAX_REQUESTS,
    )
    assert _rate_limit_scope(request("/api/v1/tickets/")) == (
        "ticket.read",
        policy.RATE_LIMIT_TICKET_READ_MAX_REQUESTS,
    )
    assert _rate_limit_scope(request("/api/v1/tickets/", "POST")) == (
        "ticket.write",
        policy.RATE_LIMIT_TICKET_WRITE_MAX_REQUESTS,
    )
    assert _rate_limit_scope(request("/api/v1/notifications/")) == (
        "notification.read",
        policy.RATE_LIMIT_NOTIFICATION_READ_MAX_REQUESTS,
    )
    assert _rate_limit_scope(request("/api/v1/admin/users")) == (
        "admin.read",
        policy.RATE_LIMIT_ADMIN_READ_MAX_REQUESTS,
    )
    assert _rate_limit_scope(request("/api/v1/admin/users", "PATCH")) == (
        "admin.write",
        policy.RATE_LIMIT_ADMIN_WRITE_MAX_REQUESTS,
    )
    assert _rate_limit_scope(request("/api/v1/webhooks/evolution", "POST")) == (
        "webhook.evolution",
        policy.RATE_LIMIT_WEBHOOK_MAX_REQUESTS,
    )


def test_local_rate_limit_uses_token_bucket_and_refills_gradually():
    _rate_limit_buckets.clear()
    results = [
        _consume_local_rate_limit(
            key="test:token-bucket",
            max_requests=2,
            window_seconds=60,
            now=1000.0,
        )
        for _ in range(3)
    ]

    assert results[0][0] is True
    assert results[0][2] == 1
    assert results[1][0] is True
    assert results[1][2] == 0
    assert results[2][0] is False
    assert results[2][1] == 30

    refilled = _consume_local_rate_limit(
        key="test:token-bucket",
        max_requests=2,
        window_seconds=60,
        now=1030.0,
    )
    assert refilled[0] is True
    assert refilled[2] == 0


def test_rate_limit_headers_are_exposed_on_api_responses(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["X-RateLimit-Limit"] == str(
        policy.RATE_LIMIT_AUTH_MAX_REQUESTS
    )
    assert int(response.headers["X-RateLimit-Remaining"]) >= 0
    assert int(response.headers["X-RateLimit-Reset"]) > 0
