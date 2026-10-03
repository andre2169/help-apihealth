from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db.models.comment import Comment
from app.db.models.maintenance_notice import MaintenanceNotice
from app.db.models.mfa_recovery_code import MFARecoveryCode
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.services.tickets.timeline import get_ticket_timeline
from .conftest import login, sent_verification_codes


def _ticket(*, owner_id: int, title: str, due_at: datetime | None = None) -> Ticket:
    return Ticket(
        title=title,
        description="Falha operacional de teste sem dados pessoais.",
        category="Rede",
        priority="medium",
        sector="UTI",
        operational_impact="medium",
        status="open",
        sla_hours=24,
        due_at=due_at,
        user_id=owner_id,
    )


def _begin_mfa(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "SenhaTeste123"},
    )
    assert response.status_code == 200, response.text
    challenge_id = response.json()["challenge_id"]
    return challenge_id


def test_ticket_timeline_shows_comment_once_with_its_message(client, db, user_factory):
    owner = user_factory(email="feature.timeline.owner@gmail.com")
    ticket = _ticket(owner_id=owner.id, title="Conversa sem duplicidade")
    db.add(ticket)
    db.commit()
    login(client, owner.email)

    response = client.post(
        f"/api/v1/tickets/{ticket.id}/comments/",
        json={"content": "O equipamento voltou a funcionar."},
    )
    assert response.status_code == 201, response.text

    items = get_ticket_timeline(db, ticket.id)
    assert len(items) == 1
    assert items[0]["type"] == "comment"
    assert items[0]["content"] == "O equipamento voltou a funcionar."

    assert db.query(Comment).filter(Comment.ticket_id == ticket.id).count() == 1
    assert db.query(TicketEvent).filter(
        TicketEvent.ticket_id == ticket.id,
        TicketEvent.event_type == "COMMENTED",
    ).count() == 1


def test_ticket_list_can_sort_sla_deadlines_and_includes_hours(client, db, user_factory):
    owner = user_factory(email="feature.sla.owner@gmail.com")
    now = datetime.now(timezone.utc)
    tickets = [
        _ticket(owner_id=owner.id, title="Prazo futuro", due_at=now + timedelta(hours=8)),
        _ticket(owner_id=owner.id, title="Prazo vencido", due_at=now - timedelta(hours=2)),
        _ticket(owner_id=owner.id, title="Prazo próximo", due_at=now + timedelta(minutes=20)),
    ]
    db.add_all(tickets)
    db.commit()
    login(client, owner.email)

    response = client.get("/api/v1/tickets/?order_by=due_at&direction=asc&limit=10")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["title"] for item in items] == [
        "Prazo vencido",
        "Prazo próximo",
        "Prazo futuro",
    ]
    assert all(item["sla_hours"] == 24 for item in items)


def test_privileged_user_can_use_a_recovery_code_once(client, db, user_factory):
    admin = user_factory(
        email="feature.mfa.admin@gmail.com",
        role="admin",
        password="SenhaTeste123",
    )
    db.commit()
    login(client, admin.email)

    generated = client.post(
        "/api/v1/auth/mfa/recovery-codes",
        json={"current_password": "SenhaTeste123"},
    )
    assert generated.status_code == 200, generated.text
    payload = generated.json()
    recovery_code = payload["codes"][0]
    assert len(payload["codes"]) == 10
    assert payload["remaining"] == 10

    stored_hashes = {
        row.code_hash
        for row in db.query(MFARecoveryCode).filter(MFARecoveryCode.user_id == admin.id).all()
    }
    assert recovery_code not in stored_hashes

    login_client = TestClient(client.app)
    challenge_id = _begin_mfa(login_client, admin.email)
    verified = login_client.post(
        "/api/v1/auth/login/verify",
        json={"challenge_id": challenge_id, "code": recovery_code},
    )
    assert verified.status_code == 200, verified.text
    from app.core import security_policy

    assert login_client.cookies.get(security_policy.AUTH_COOKIE_NAME)

    db.expire_all()
    used = db.query(MFARecoveryCode).filter(
        MFARecoveryCode.user_id == admin.id,
        MFARecoveryCode.used_at.is_not(None),
    ).count()
    assert used == 1

    second_client = TestClient(client.app)
    second_challenge = _begin_mfa(second_client, admin.email)
    replay = second_client.post(
        "/api/v1/auth/login/verify",
        json={"challenge_id": second_challenge, "code": recovery_code},
    )
    assert replay.status_code == 400


def test_recovery_codes_require_privileged_role_and_current_password(client, db, user_factory):
    user = user_factory(email="feature.mfa.user@gmail.com", role="user")
    db.commit()
    login(client, user.email)

    status_response = client.get("/api/v1/auth/mfa/recovery-codes")
    assert status_response.status_code == 403

    admin = user_factory(email="feature.mfa.admin2@gmail.com", role="admin")
    db.commit()
    admin_client = TestClient(client.app)
    login(admin_client, admin.email)
    denied = admin_client.post(
        "/api/v1/auth/mfa/recovery-codes",
        json={"current_password": "not-the-current-password"},
    )
    assert denied.status_code == 400
    assert db.query(MFARecoveryCode).filter(MFARecoveryCode.user_id == admin.id).count() == 0


def test_maintenance_notices_are_scoped_by_sector_and_admin_managed(client, db, user_factory):
    admin = user_factory(email="feature.notice.admin@gmail.com", role="admin")
    uti_user = user_factory(email="feature.notice.uti@gmail.com", role="user")
    pharmacy_user = user_factory(email="feature.notice.pharmacy@gmail.com", role="user")
    technician = user_factory(email="feature.notice.technician@gmail.com", role="technician")
    uti_user.department = "UTI"
    pharmacy_user.department = "Farmácia"
    db.commit()
    login(client, admin.email)

    ends_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    created = client.post(
        "/api/v1/admin/maintenance-notices/",
        json={
            "title": "Instabilidade de rede",
            "message": "A equipe técnica está verificando a conexão da UTI.",
            "severity": "warning",
            "target_sectors": ["UTI"],
            "ends_at": ends_at,
        },
    )
    assert created.status_code == 201, created.text
    notice_id = created.json()["id"]

    uti_client = TestClient(client.app)
    login(uti_client, uti_user.email)
    assert [item["id"] for item in uti_client.get("/api/v1/maintenance-notices/").json()] == [notice_id]

    pharmacy_client = TestClient(client.app)
    login(pharmacy_client, pharmacy_user.email)
    assert pharmacy_client.get("/api/v1/maintenance-notices/").json() == []

    technician_client = TestClient(client.app)
    login(technician_client, technician.email)
    assert [item["id"] for item in technician_client.get("/api/v1/maintenance-notices/").json()] == [notice_id]

    disabled = client.patch(
        f"/api/v1/admin/maintenance-notices/{notice_id}/active",
        json={"active": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["active"] is False
    assert db.query(MaintenanceNotice).filter(MaintenanceNotice.id == notice_id).count() == 1


def test_regular_user_cannot_create_maintenance_notice(client, db, user_factory):
    user = user_factory(email="feature.notice.user@gmail.com")
    db.commit()
    login(client, user.email)

    response = client.post(
        "/api/v1/admin/maintenance-notices/",
        json={"title": "Aviso", "message": "Mensagem de teste"},
    )

    assert response.status_code == 403
    assert db.query(MaintenanceNotice).count() == 0
