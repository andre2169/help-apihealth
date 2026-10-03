import logging
import re
from uuid import uuid4

from fastapi import Request

from app.core.auth import decode_access_token
from app.core import security_policy as policy

JSON_ERROR_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def request_id(request: Request) -> str:
    incoming = request.headers.get("x-request-id")
    if incoming and re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", incoming):
        return incoming
    return uuid4().hex


def token_identity(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    else:
        token = request.cookies.get(policy.AUTH_COOKIE_NAME)

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
    if status_code == 408:
        return "request_timeout"
    if status_code == 409:
        return "conflict"
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
    if status_code == 431:
        return "headers_too_large"
    if status_code == 503:
        return "server_busy"
    if 400 <= status_code < 500:
        return "client_error"
    if status_code >= 500:
        return "server_error"
    return "other"


HTTP_STATUS_LABELS = {
    200: "OK",
    201: "Created",
    202: "Accepted",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    304: "Not Modified",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    409: "Conflict",
    413: "Payload Too Large",
    414: "URI Too Long",
    415: "Unsupported Media Type",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def http_status_label(status_code: int) -> str:
    """Retorna uma descricao segura para leitura humana dos logs."""
    return HTTP_STATUS_LABELS.get(status_code, "HTTP Status")


def status_reason(status_code: int) -> str:
    """Resume o significado operacional do status sem registrar a entrada."""
    reasons = {
        201: "resource_created",
        204: "operation_completed_without_body",
        400: "invalid_request_or_business_rule",
        401: "authentication_required_or_invalid_credentials",
        403: "authorization_denied",
        404: "resource_not_found",
        408: "request_timeout",
        409: "resource_conflict",
        413: "request_body_too_large",
        414: "request_url_too_long",
        415: "unsupported_content_type",
        422: "input_validation_failed",
        429: "rate_limit_exceeded",
        431: "request_headers_too_large",
        500: "unexpected_server_error",
        502: "upstream_service_error",
        503: "service_unavailable",
        504: "upstream_timeout",
    }
    if status_code in reasons:
        return reasons[status_code]
    if 200 <= status_code < 300:
        return "request_completed"
    if 300 <= status_code < 400:
        return "redirected"
    if 400 <= status_code < 500:
        return "client_error"
    if status_code >= 500:
        return "server_error"
    return "unknown_status"


def error_category(exc: Exception) -> str:
    """Classifica falhas sem registrar a mensagem ou os dados da entrada."""
    error_type = exc.__class__.__name__
    if error_type == "ResponseValidationError":
        return "response_validation"
    if error_type in {"ValidationError", "RequestValidationError"}:
        return "request_validation"
    if error_type in {"IntegrityError", "OperationalError", "DBAPIError"}:
        return "database"
    if "Timeout" in error_type:
        return "dependency_timeout"
    if error_type in {"ConnectionError", "ConnectError"}:
        return "dependency_connection"
    return "unexpected"


def safe_error_reason(exc: Exception) -> str:
    """Converte excecoes conhecidas em codigos sem PII ou texto do usuario."""
    reason_by_type = {
        "TicketNotFound": "ticket_not_found",
        "TicketInvalidStatus": "invalid_ticket_status",
        "TicketPermissionDenied": "ticket_permission_denied",
        "InvalidCredentials": "invalid_credentials",
        "UserNotFound": "user_not_found",
        "InvalidUserRole": "invalid_user_role",
        "UserAlreadyExists": "user_already_exists",
        "ResponseValidationError": "response_validation_failed",
        "RequestValidationError": "request_validation_failed",
    }
    return reason_by_type.get(exc.__class__.__name__, error_category(exc))


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
            "mfa/recovery-codes": (
                "auth.mfa_recovery_codes.create"
                if method == "POST"
                else "auth.mfa_recovery_codes.status"
            ),
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
            "cancel": "ticket.cancel",
            "timeline": "ticket.timeline",
            "comments": "comment.create" if method == "POST" else "comment.request",
        }
        return ticket_actions.get(action, "ticket.request")

    if resource == "admin":
        if remainder and remainder[0] == "maintenance-notices":
            return "admin.maintenance_notice.update"
        if remainder == ["network-debug"]:
            return "admin.network_debug"
        if remainder == ["notification-events"]:
            return "admin.notification_events"
        if remainder == ["ticket-events"]:
            return "admin.ticket_events"
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

    if resource == "maintenance-notices":
        if method == "POST" and len(remainder) == 2 and remainder[1] == "read":
            return "maintenance_notice.read"
        return "maintenance_notice.list"

    return f"{resource}.request"


def request_log_level(method: str, path: str, status_code: int) -> int:
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    if method == "OPTIONS" or path in {"/health", "/health/db"}:
        return logging.DEBUG
    return logging.INFO
