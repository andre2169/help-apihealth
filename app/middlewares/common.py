import logging
from uuid import uuid4

from fastapi import Request

from app.core.auth import decode_access_token
from app.core.config import settings

JSON_ERROR_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def request_id(request: Request) -> str:
    incoming = request.headers.get("x-request-id")
    if incoming and len(incoming) <= 80:
        return incoming
    return uuid4().hex


def token_identity(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    else:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME)

    if not token:
        return "anon"

    payload = decode_access_token(token)
    if payload and payload.get("sub"):
        return f"user:{payload['sub']}"
    return "anon"


def status_result(status_code: int) -> str:
    if status_code == 201:
        return "created"
    if status_code == 204:
        return "no_content"
    if 200 <= status_code < 300:
        return "success"
    if status_code == 400:
        return "bad_request"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 413:
        return "payload_too_large"
    if status_code == 414:
        return "uri_too_long"
    if status_code == 415:
        return "unsupported_media_type"
    if status_code == 422:
        return "validation_error"
    if status_code == 429:
        return "rate_limited"
    if status_code == 503:
        return "server_busy"
    if 400 <= status_code < 500:
        return "client_error"
    if status_code >= 500:
        return "server_error"
    return "other"


def request_action(method: str, path: str) -> str:
    normalized_path = path.rstrip("/") or "/"

    if method == "OPTIONS":
        return "cors.preflight"
    if normalized_path == "/":
        return "app.root"
    if normalized_path == "/health":
        return "health.check"
    if normalized_path == "/health/db":
        return "health.database"
    if normalized_path in {"/docs", "/redoc", "/openapi.json"}:
        return "docs.access"

    parts = normalized_path.strip("/").split("/")
    if len(parts) < 3 or parts[:2] != ["api", "v1"]:
        return "http.request"

    resource = parts[2]
    remainder = parts[3:]

    if resource == "users":
        if method == "POST" and not remainder:
            return "user.register"
        return "user.request"

    if resource == "auth":
        auth_path = "/".join(remainder)
        auth_actions = {
            "login": "auth.login",
            "logout": "auth.logout",
            "me": "auth.me",
            "password/recovery/request": "auth.password_recovery.request",
            "password/recovery/confirm": "auth.password_recovery.confirm",
            "me/email-verification/request": "auth.email_verification.request",
            "me/email-verification/confirm": "auth.email_verification.confirm",
            "me/password/request": "auth.password_change.request",
            "me/password/confirm": "auth.password_change.confirm",
            "me/email/request": "auth.email_change.request",
            "me/email/confirm": "auth.email_change.confirm",
        }
        if method == "PATCH" and auth_path == "me":
            return "auth.profile.update"
        return auth_actions.get(auth_path, "auth.request")

    if resource == "tickets":
        if not remainder:
            return "ticket.create" if method == "POST" else "ticket.list"
        if len(remainder) == 1:
            if method == "GET":
                return "ticket.detail"
            if method == "DELETE":
                return "ticket.delete"
            return "ticket.request"
        action = remainder[1]
        ticket_actions = {
            "assign": "ticket.assign",
            "resolve": "ticket.resolve",
            "close": "ticket.close",
            "reopen": "ticket.reopen",
            "timeline": "ticket.timeline",
            "comments": "comment.create" if method == "POST" else "comment.request",
        }
        return ticket_actions.get(action, "ticket.request")

    if resource == "admin":
        if remainder == ["network-debug"]:
            return "admin.network_debug"
        if remainder and remainder[0] == "users":
            if method == "GET" and len(remainder) == 1:
                return "admin.user.list"
            if method == "GET":
                return "admin.user.detail"
            if method == "PATCH" and len(remainder) >= 3 and remainder[2] == "role":
                return "admin.user.role_update"
            if method == "PATCH":
                return "admin.user.update"
            if method == "DELETE":
                return "admin.user.delete"
        return "admin.request"

    if resource == "dashboard":
        return "dashboard.summary"
    if resource == "reports":
        return "report.overview"
    if resource == "notifications":
        if method == "GET":
            return "notification.list"
        if remainder == ["read-all"]:
            return "notification.read_all"
        if method == "PATCH":
            return "notification.read"
        return "notification.request"

    return f"{resource}.request"


def request_log_level(method: str, path: str, status_code: int) -> int:
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    if method == "OPTIONS" or path in {"/health", "/health/db"}:
        return logging.DEBUG
    return logging.INFO
