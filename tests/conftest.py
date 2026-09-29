import os
import re
import shutil
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="helphealth-tests-"))
TEST_DATABASE = TEST_ROOT / "test.db"

# Estas variaveis precisam existir antes de importar app.main, pois a API
# constroi o engine e carrega as configuracoes durante o import.
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{TEST_DATABASE.as_posix()}",
        "SECRET_KEY": "test-secret-key-with-at-least-32-characters",
        "ADMIN_PASSWORD": "test-admin-password-123",
        "ADMIN_EMAIL": "admin@test.local",
        "ALLOWED_ORIGINS": "http://testserver,http://localhost:5173",
        "AUTH_COOKIE_SECURE": "false",
        "AUTH_COOKIE_SAMESITE": "lax",
        "WHATSAPP_ENABLED": "false",
        "SMTP_USERNAME": "",
        "SMTP_PASSWORD": "",
    }
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.config import settings
from app.core import security_policy as policy
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.deps import get_db
from app.main import app
from app.middlewares.rate_limit import _rate_limit_buckets
from app.services.auth import rate_limits as auth_rate_limits
from app.services.auth import account_verification as account_verification_service
from app.db.models.user import User


sent_verification_codes: list[tuple[str, str]] = []


@pytest.fixture(scope="session", autouse=True)
def database_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_database():
    db = SessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()

    _rate_limit_buckets.clear()
    auth_rate_limits.failed_logins.clear()
    auth_rate_limits.action_limits.clear()


@pytest.fixture(autouse=True)
def capture_verification_emails(monkeypatch):
    sent_verification_codes.clear()

    def fake_send_email(*, to_email: str, subject: str, body: str) -> bool:
        match = re.search(r"é:\s*([0-9]{6})", body)
        if match:
            sent_verification_codes.append((to_email.lower(), match.group(1)))
        return True

    monkeypatch.setattr(account_verification_service, "send_email", fake_send_email)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def override_database_dependency():
    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def query_statements():
    """Captura SQL emitido por uma operacao para detectar consultas extras."""
    statements = []

    def before_cursor_execute(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def user_factory(db):
    def make_user(
        *,
        email: str,
        role: str = "user",
        name: str = "Usuario de Teste",
        password: str = "SenhaTeste123",
        phone: str | None = None,
        notification_preference: str = "email",
        email_verified: bool = True,
        is_active: bool = True,
    ) -> User:
        user = User(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role=role,
            phone=phone,
            notification_preference=notification_preference,
            email_verified=email_verified,
            is_active=is_active,
            session_version=1,
        )
        db.add(user)
        db.flush()
        return user

    return make_user


def login(client: TestClient, email: str, password: str = "SenhaTeste123"):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    if response.status_code == 200 and response.json().get("status") == "verification_required":
        challenge_id = response.json()["challenge_id"]
        code = next(
            code
            for recipient, code in reversed(sent_verification_codes)
            if recipient == email.lower()
        )
        response = client.post(
            "/api/v1/auth/login/verify",
            json={"challenge_id": challenge_id, "code": code},
        )
    assert response.status_code == 200, response.text
    assert client.cookies.get(policy.AUTH_COOKIE_NAME)
    csrf_token = client.cookies.get(policy.CSRF_COOKIE_NAME)
    assert csrf_token
    client.headers.update({policy.CSRF_HEADER_NAME: csrf_token})
