from datetime import datetime, timedelta, timezone
import re

import jwt
import pytest

from app.core.auth import create_access_token, decode_access_token
from app.core import security_policy as policy
from app.core.config import settings
from app.core.security import verify_password
from app.services.auth import account_verification as account_verification_service
from app.services.auth.rate_limits import (
    action_limits,
    check_login_rate_limit,
    consume_action_rate_limit,
    failed_logins,
    get_login_retry_after,
    register_failed_login,
)
from .conftest import sent_verification_codes


def test_access_jwt_requires_expected_claims_and_type():
    token = create_access_token({"sub": "7", "session_version": 1})
    payload = decode_access_token(token)

    assert payload is not None
    assert payload["iss"] == policy.JWT_ISSUER
    assert payload["aud"] == policy.JWT_AUDIENCE
    assert payload["typ"] == "access"
    assert payload["nbf"] >= payload["iat"]

    wrong_type_payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[policy.JWT_ALGORITHM],
        options={"verify_exp": False, "verify_aud": False},
    )
    wrong_type_payload["typ"] = "refresh"
    wrong_type_token = jwt.encode(
        wrong_type_payload,
        settings.SECRET_KEY,
        algorithm=policy.JWT_ALGORITHM,
    )

    assert decode_access_token(wrong_type_token) is None

    missing_audience_payload = dict(wrong_type_payload)
    missing_audience_payload["typ"] = "access"
    missing_audience_payload.pop("aud")
    missing_audience_token = jwt.encode(
        missing_audience_payload,
        settings.SECRET_KEY,
        algorithm=policy.JWT_ALGORITHM,
    )

    assert decode_access_token(missing_audience_token) is None


def test_malformed_password_hash_is_treated_as_invalid_password():
    assert verify_password("SenhaTeste123", "hash-corrompido") is False


def test_login_cookie_is_http_only_and_expires(client, db, user_factory):
    user_factory(email="helpweb.cookie@gmail.com")
    db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.cookie@gmail.com", "password": "SenhaTeste123"},
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200, response.text
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=1800" in set_cookie
    assert response.headers[policy.CSRF_HEADER_NAME] == client.cookies.get(
        policy.CSRF_COOKIE_NAME
    )
    assert policy.CSRF_HEADER_NAME.lower() in {
        header.strip().lower()
        for header in response.headers["access-control-expose-headers"].split(",")
    }


def test_privileged_login_requires_email_code_before_creating_session(
    client, db, user_factory
):
    technician = user_factory(
        email="helpweb.login-mfa@gmail.com",
        role="technician",
    )
    db.commit()

    first_factor = client.post(
        "/api/v1/auth/login",
        json={"email": technician.email, "password": "SenhaTeste123"},
    )

    assert first_factor.status_code == 200, first_factor.text
    assert first_factor.json()["status"] == "verification_required"
    assert not client.cookies.get(policy.AUTH_COOKIE_NAME)
    challenge_id = first_factor.json()["challenge_id"]
    code = next(
        code
        for recipient, code in reversed(sent_verification_codes)
        if recipient == technician.email
    )

    wrong_code = "000000" if code != "000000" else "000001"
    invalid_code = client.post(
        "/api/v1/auth/login/verify",
        json={"challenge_id": challenge_id, "code": wrong_code},
    )
    assert invalid_code.status_code == 400
    assert not client.cookies.get(policy.AUTH_COOKIE_NAME)

    verified = client.post(
        "/api/v1/auth/login/verify",
        json={"challenge_id": challenge_id, "code": code},
    )
    assert verified.status_code == 200, verified.text
    assert client.cookies.get(policy.AUTH_COOKIE_NAME)
    assert client.get("/api/v1/auth/me").json()["role"] == "technician"

    replayed = client.post(
        "/api/v1/auth/login/verify",
        json={"challenge_id": challenge_id, "code": code},
        headers={policy.CSRF_HEADER_NAME: client.cookies.get(policy.CSRF_COOKIE_NAME)},
    )
    assert replayed.status_code == 400


def test_local_mfa_code_is_logged_and_never_sent_to_placeholder_email(
    client, db, user_factory, monkeypatch, caplog
):
    technician = user_factory(
        email="helpweb.local-mfa@gmail.com",
        role="technician",
    )
    db.commit()
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///./local-test.db")
    monkeypatch.setattr(
        settings,
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", False)
    monkeypatch.setattr(
        account_verification_service,
        "send_email",
        lambda **kwargs: pytest.fail("MFA local nao deve enviar email ficticio"),
    )

    first_factor = client.post(
        "/api/v1/auth/login",
        json={"email": technician.email, "password": "SenhaTeste123"},
    )

    assert first_factor.status_code == 200, first_factor.text
    assert first_factor.json()["delivery"] == "log"
    assert not client.cookies.get(policy.AUTH_COOKIE_NAME)
    code_match = re.search(
        r"Codigo MFA de login para teste local \| user_id=\d+ \| code=(\d{6})",
        caplog.text,
    )
    assert code_match

    verified = client.post(
        "/api/v1/auth/login/verify",
        json={
            "challenge_id": first_factor.json()["challenge_id"],
            "code": code_match.group(1),
        },
    )

    assert verified.status_code == 200, verified.text
    assert client.cookies.get(policy.AUTH_COOKIE_NAME)


def test_authenticated_get_exposes_csrf_token_for_cross_origin_frontend(
    client, db, user_factory
):
    user_factory(email="helpweb.csrf-header@gmail.com")
    db.commit()

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.csrf-header@gmail.com", "password": "SenhaTeste123"},
    )
    assert login_response.status_code == 200

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.headers[policy.CSRF_HEADER_NAME] == client.cookies.get(
        policy.CSRF_COOKIE_NAME
    )


def test_csrf_endpoint_returns_only_the_current_csrf_token(client, db, user_factory):
    user_factory(email="helpweb.csrf-endpoint@gmail.com")
    db.commit()
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.csrf-endpoint@gmail.com", "password": "SenhaTeste123"},
    )
    assert login_response.status_code == 200

    response = client.get("/api/v1/auth/csrf")

    assert response.status_code == 200
    assert response.json() == {
        "csrf_token": client.cookies.get(policy.CSRF_COOKIE_NAME)
    }


def test_logout_revokes_the_current_bearer_token(client, db, user_factory):
    user_factory(email="helpweb.logout@gmail.com")
    db.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.logout@gmail.com", "password": "SenhaTeste123"},
    )
    token = client.cookies.get(policy.AUTH_COOKIE_NAME)
    assert login.status_code == 200
    assert token

    logout = client.post(
        "/api/v1/auth/logout",
        headers={
            "Authorization": f"Bearer {token}",
            policy.CSRF_HEADER_NAME: client.cookies.get(policy.CSRF_COOKIE_NAME),
        },
    )
    assert logout.status_code == 200

    private_request = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert private_request.status_code == 401


def test_private_route_requires_authentication(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_validation_errors_do_not_echo_submitted_password(client):
    secret_input = "SENTINEL_PASSWORD_MUST_NOT_BE_REFLECTED_" + ("x" * 130)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.validation@gmail.com", "password": secret_input},
    )

    assert response.status_code == 422
    assert "SENTINEL_PASSWORD_MUST_NOT_BE_REFLECTED" not in response.text
    assert response.json()["detail"] == "Dados inválidos. Revise os campos e tente novamente."


def test_login_account_block_applies_across_source_ips():
    email = "helpweb.brute-force@gmail.com"
    for _ in range(5):
        register_failed_login("192.0.2.10", email)

    assert check_login_rate_limit("192.0.2.10", email) is False
    assert check_login_rate_limit("192.0.2.20", email) is False
    assert check_login_rate_limit("192.0.2.20", "another-account@gmail.com") is True


def test_local_auth_rate_limit_storage_has_a_hard_memory_cap(monkeypatch):
    monkeypatch.setattr(policy, "MAX_TRACKED_RATE_LIMIT_KEYS", 4)

    for index in range(5):
        register_failed_login("192.0.2.50", f"account-{index}@gmail.com")
        consume_action_rate_limit(
            action="test",
            key=f"key-{index}",
            max_requests=10,
            window_seconds=60,
        )

    assert len(failed_logins) <= 4
    assert len(action_limits) <= 4


def test_login_context_block_does_not_block_another_account_on_shared_ip():
    shared_ip = "192.0.2.40"
    blocked_email = "helpweb.shared-a@gmail.com"
    other_email = "helpweb.shared-b@gmail.com"

    for _ in range(5):
        register_failed_login(shared_ip, blocked_email)

    assert check_login_rate_limit(shared_ip, blocked_email) is False
    assert check_login_rate_limit(shared_ip, other_email) is True


def test_login_ip_lock_progresses_every_five_failures():
    email = "helpweb.progressive-rate-limit@gmail.com"
    ip = "192.0.2.30"

    for expected_seconds in (5, 10, 15, 20, 60, 300, 1800, 7200, 21600):
        for _ in range(5):
            register_failed_login(ip, email)

        retry_after = get_login_retry_after(ip, email)
        assert expected_seconds - 1 <= retry_after <= expected_seconds

        # Simula a passagem do bloqueio sem esperar durante o teste. O
        # historico continua dentro da janela e, portanto, a proxima faixa
        # progressiva e preservada.
        for data in failed_logins.values():
            data["blocked_until"] = data["blocked_until"] - timedelta(seconds=expected_seconds + 1)


def test_correct_password_cannot_bypass_the_current_ip_login_block(client, db, user_factory):
    user_factory(email="helpweb.rate-limit@gmail.com")
    db.commit()

    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": "helpweb.rate-limit@gmail.com", "password": "SenhaErrada123"},
        )

    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.rate-limit@gmail.com", "password": "SenhaErrada123"},
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0

    recovered_during_block = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.rate-limit@gmail.com", "password": "SenhaTeste123"},
    )
    assert recovered_during_block.status_code == 429
    assert int(recovered_during_block.headers["Retry-After"]) > 0

    for data in failed_logins.values():
        data["blocked_until"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    recovered_after_block = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.rate-limit@gmail.com", "password": "SenhaTeste123"},
    )
    assert recovered_after_block.status_code == 200, recovered_after_block.text


def test_state_changing_request_requires_csrf_token(client, db, user_factory):
    user_factory(email="helpweb.csrf@gmail.com")
    db.commit()
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.csrf@gmail.com", "password": "SenhaTeste123"},
    )
    assert login_response.status_code == 200
    client.headers.pop(policy.CSRF_HEADER_NAME, None)

    response = client.post(
        "/api/v1/tickets/",
        json={
            "title": "Impressora indisponível",
            "description": "Teste de proteção CSRF",
            "sector": "Recepção",
            "category": "Hardware",
            "equipment": "Impressora",
            "impact": "low",
            "priority": "low",
        },
    )

    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


def test_unverified_user_cannot_access_business_routes(client, db, user_factory):
    user_factory(email="helpweb.unverified@gmail.com", email_verified=False)
    db.commit()
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "helpweb.unverified@gmail.com", "password": "SenhaTeste123"},
    )
    assert login_response.status_code == 200
    client.headers.update(
        {policy.CSRF_HEADER_NAME: client.cookies.get(policy.CSRF_COOKIE_NAME)}
    )

    response = client.get("/api/v1/tickets/")

    assert response.status_code == 403
    assert "Confirme seu email" in response.json()["detail"]
