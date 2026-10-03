import base64
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core import security_policy as policy
from app.core.auth import create_access_token, decode_access_token
from app.core.config import settings
from app.db.models.maintenance_notice import MaintenanceNotice
from app.db.models.ticket import Ticket
from .conftest import login
from .test_ticket_cancellation import make_ticket


@pytest.mark.parametrize("claims", [
    {"iss": "untrusted-issuer"}, {"aud": "another-application"},
    {"exp": 1}, {"nbf": 4102444800}, {"typ": "refresh"},
    {"exp": None}, {"iat": []}, {"nbf": {}},
])
def test_invalid_signed_claims_are_rejected_without_server_error(client, user_factory, claims):
    actor = user_factory(email="jwt.claims@gmail.com")
    valid = create_access_token({"sub": str(actor.id), "session_version": actor.session_version})
    payload = jwt.decode(valid, settings.SECRET_KEY, algorithms=[policy.JWT_ALGORITHM], audience=policy.JWT_AUDIENCE)
    token = jwt.encode({**payload, **claims}, settings.SECRET_KEY, algorithm=policy.JWT_ALGORITHM)
    assert decode_access_token(token) is None
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "Traceback" not in response.text


@pytest.mark.parametrize("algorithm", ["none", "HS384"])
def test_token_algorithm_cannot_be_selected_by_the_client(algorithm):
    token = jwt.encode({"sub": "1"}, "" if algorithm == "none" else "test-only-" + "x" * 64, algorithm=algorithm)
    assert decode_access_token(token) is None


def test_non_alphabet_signature_is_not_an_alternate_valid_token():
    token = create_access_token({"sub": "1", "session_version": 1})
    assert decode_access_token(token + "!!!!") is None


def test_deeply_nested_unsigned_header_is_rejected_cleanly():
    header = base64.urlsafe_b64encode(b"[" * 1500 + b"0" + b"]" * 1500).rstrip(b"=").decode()
    assert decode_access_token(header + ".e30.eA") is None


@pytest.mark.parametrize("suffix,archived", [("", False), ("/timeline", False), ("/deleted", True), ("/deleted/timeline", True)])
def test_user_cannot_read_another_users_active_or_archived_history(client, db, user_factory, suffix, archived):
    owner = user_factory(email="idor.owner@gmail.com")
    stranger = user_factory(email="idor.stranger@gmail.com")
    ticket = make_ticket(db, owner, deleted_at=datetime.now(timezone.utc) if archived else None)
    login(client, stranger.email)
    response = client.get(f"/api/v1/tickets/{ticket.id}{suffix}")
    assert response.status_code in {403, 404}
    assert ticket.title not in response.text
    assert client.get("/api/v1/tickets/").json()["items"] == []
    assert client.get("/api/v1/tickets/deleted").json()["items"] == []


ADMIN_OPERATIONS = [
    ("PATCH", "/api/v1/admin/ticket-catalog/1", {"name": "Setor adulterado"}),
    ("DELETE", "/api/v1/admin/ticket-catalog/1", None),
    ("PATCH", "/api/v1/admin/maintenance-notices/{notice}", {"title": "Aviso adulterado", "message": "Texto", "severity": "info", "audience": "all", "target_sectors": [], "ends_at": None}),
    ("DELETE", "/api/v1/admin/maintenance-notices/{notice}", None),
    ("POST", "/api/v1/admin/deleted-tickets/{ticket}/restore", None),
    ("PATCH", "/api/v1/tickets/{ticket}/reopen", None),
]


@pytest.mark.parametrize("role", ["user", "technician"])
@pytest.mark.parametrize("method,path,body", ADMIN_OPERATIONS)
def test_new_admin_operations_cannot_be_used_by_lower_roles(client, db, user_factory, role, method, path, body):
    actor = user_factory(email=f"admin.guard.{role}@gmail.com", role=role)
    ticket = make_ticket(db, actor, status="cancelled", deleted_at=datetime.now(timezone.utc))
    notice = MaintenanceNotice(title="Aviso protegido", message="Comunicado original", severity="info", target_sectors=[], starts_at=datetime.now(timezone.utc) - timedelta(days=1))
    db.add(notice); db.commit()
    login(client, actor.email)
    response = client.request(method, path.format(ticket=ticket.id, notice=notice.id), json=body)
    assert response.status_code == 403, response.text
    db.expire_all()
    assert db.get(Ticket, ticket.id).deleted_at is not None
    assert db.get(MaintenanceNotice, notice.id).title == "Aviso protegido"


@pytest.mark.parametrize("method,path,body", ADMIN_OPERATIONS[:5])
def test_new_admin_operations_require_csrf_even_for_an_administrator(client, db, user_factory, method, path, body):
    actor = user_factory(email="admin.csrf@gmail.com", role="admin")
    ticket = make_ticket(db, actor, status="cancelled", deleted_at=datetime.now(timezone.utc))
    notice = MaintenanceNotice(title="Aviso protegido", message="Comunicado original", severity="info", target_sectors=[], starts_at=datetime.now(timezone.utc) - timedelta(days=1))
    db.add(notice); db.commit()
    login(client, actor.email)
    client.headers.pop(policy.CSRF_HEADER_NAME)
    response = client.request(method, path.format(ticket=ticket.id, notice=notice.id), json=body)
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    db.expire_all()
    assert db.get(Ticket, ticket.id).deleted_at is not None
    assert db.get(MaintenanceNotice, notice.id).title == "Aviso protegido"


@pytest.mark.parametrize("path", ["/api/v1/auth/me", "/api/v1/tickets/", "/api/v1/maintenance-notices/"])
def test_sensitive_api_responses_cannot_be_stored_by_browser_or_proxy(client, db, user_factory, path):
    actor = user_factory(email="private.cache@gmail.com")
    db.commit()
    assert client.get(path).headers["Cache-Control"] == "no-store"
    login(client, actor.email)
    assert client.get(path).headers["Cache-Control"] == "no-store"


def test_production_cookie_is_secure_http_only_with_explicit_same_site(client, db, user_factory, monkeypatch):
    actor = user_factory(email="secure.cookie@gmail.com")
    db.commit()
    monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", True)
    monkeypatch.setattr(settings, "AUTH_COOKIE_SAMESITE", "none")
    response = client.post("/api/v1/auth/login", json={"email": actor.email, "password": "SenhaTeste123"})
    assert response.status_code == 200
    session = next(value for value in response.headers.get_list("set-cookie") if value.startswith(policy.AUTH_COOKIE_NAME + "="))
    assert "secure" in session.lower() and "httponly" in session.lower() and "samesite=none" in session.lower()
    assert "access_token" not in response.json()
