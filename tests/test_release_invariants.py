from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest

from app.core import security_policy as policy
from app.core.exceptions import TicketInvalidStatus, TicketNotFound
from app.db.models.audit_event import AuditEvent
from app.db.models.notification import Notification
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.db.models.user import User
from app.db.session import SessionLocal
from app.services.tickets import deleted, service
from .conftest import login
from .test_ticket_cancellation import make_ticket


@pytest.mark.parametrize("contenders", [("cancel", "assign"), ("assign", "assign"), ("cancel", "cancel")])
def test_real_concurrent_actions_have_one_winner(db, user_factory, monkeypatch, contenders):
    owner = user_factory(email="concurrent.owner@gmail.com")
    first = user_factory(email="concurrent.first@gmail.com", role="technician")
    second = user_factory(email="concurrent.second@gmail.com", role="technician")
    ticket = make_ticket(db, owner)
    ticket_id, owner_id, tech_ids = ticket.id, owner.id, [first.id, second.id]
    barrier = Barrier(2)
    original = service._get_ticket_or_fail

    def synchronized_read(session, identifier):
        found = original(session, identifier)
        barrier.wait(timeout=15)
        return found

    monkeypatch.setattr(service, "_get_ticket_or_fail", synchronized_read)

    def run(index, action):
        with SessionLocal() as session:
            actor = session.get(User, owner_id if action == "cancel" else tech_ids[index])
            try:
                operation = service.cancel_ticket_service if action == "cancel" else service.assign_ticket_service
                operation(db=session, ticket_id=ticket_id, current_user=actor)
                return action, True
            except (TicketInvalidStatus, TicketNotFound):
                session.rollback()
                return action, False

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, index, action) for index, action in enumerate(contenders)]
        results = [future.result(timeout=30) for future in futures]
    assert sum(won for _, won in results) == 1
    winner = next(action for action, won in results if won)
    db.expire_all()
    stored = db.get(Ticket, ticket_id)
    assert stored.status == ("cancelled" if winner == "cancel" else "in_progress")
    assert (stored.deleted_at is not None) == (winner == "cancel")
    assert (stored.technician_id is None) == (winner == "cancel")
    assert db.query(TicketEvent).filter(
        TicketEvent.ticket_id == ticket_id,
        TicketEvent.event_type.in_(["CANCELLED", "ASSIGNED"]),
    ).count() == 1


def test_duplicate_concurrent_restore_does_not_duplicate_audit(db, user_factory, monkeypatch):
    admin = user_factory(email="concurrent.restore@gmail.com", role="admin")
    ticket = make_ticket(db, admin, status="cancelled", deleted_at=datetime.now(timezone.utc))
    ticket_id, admin_id = ticket.id, admin.id
    barrier = Barrier(2)
    original = deleted._get_deleted_ticket_or_fail

    def synchronized_read(session, identifier, actor):
        found = original(session, identifier, actor)
        barrier.wait(timeout=15)
        return found

    monkeypatch.setattr(deleted, "_get_deleted_ticket_or_fail", synchronized_read)

    def restore():
        with SessionLocal() as session:
            try:
                deleted.restore_deleted_ticket_service(db=session, ticket_id=ticket_id, current_user=session.get(User, admin_id))
                return True
            except (TicketInvalidStatus, TicketNotFound):
                session.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(restore) for _ in range(2)]
        assert sum(job.result(timeout=30) for job in jobs) == 1
    db.expire_all()
    assert db.get(Ticket, ticket_id).status == "open"
    assert db.query(TicketEvent).filter_by(ticket_id=ticket_id, event_type="RECOVERED").count() == 1
    assert db.query(AuditEvent).filter_by(target_id=str(ticket_id), action="ticket.recovered").count() == 1


def test_failed_cancel_rolls_back_ticket_event_and_notification(client, db, user_factory, monkeypatch):
    owner = user_factory(email="rollback.owner@gmail.com")
    ticket = make_ticket(db, owner)
    db.add(Notification(recipient_id=owner.id, ticket_id=ticket.id, type="TICKET_CREATED", title="Novo chamado", message="Aguardando atendimento"))
    db.commit()
    login(client, owner.email)

    def fail_audit(*args, **kwargs):
        raise RuntimeError("Simulated audit storage failure")

    monkeypatch.setattr(service, "record_audit_event", fail_audit)
    isolated = client.__class__(client.app, raise_server_exceptions=False)
    isolated.cookies.update(client.cookies)
    isolated.headers.update(client.headers)
    assert isolated.patch(f"/api/v1/tickets/{ticket.id}/cancel").status_code == 500
    db.expire_all()
    assert db.get(Ticket, ticket.id).status == "open"
    assert db.get(Ticket, ticket.id).deleted_at is None
    assert db.query(Notification).filter_by(ticket_id=ticket.id).count() == 1
    assert db.query(TicketEvent).filter_by(ticket_id=ticket.id, event_type="CANCELLED").count() == 0


@pytest.mark.parametrize("guard", ["untrusted-origin", "wrong-csrf", "unverified", "inactive", "revoked-session"])
def test_cancel_security_guards_never_mutate_ticket(client, db, user_factory, guard):
    owner = user_factory(email="guards.owner@gmail.com")
    ticket = make_ticket(db, owner)
    login(client, owner.email)
    headers = {}
    if guard == "untrusted-origin":
        headers["Origin"] = "https://untrusted.invalid"
    elif guard == "wrong-csrf":
        headers[policy.CSRF_HEADER_NAME] = "not-the-session-csrf"
    else:
        if guard == "unverified":
            owner.email_verified = False
        elif guard == "inactive":
            owner.is_active = False
        else:
            owner.session_version += 1
        db.commit()
    response = client.patch(f"/api/v1/tickets/{ticket.id}/cancel", headers=headers)
    assert response.status_code in {401, 403}, response.text
    db.expire_all()
    assert db.get(Ticket, ticket.id).status == "open"
    assert db.get(Ticket, ticket.id).deleted_at is None
    assert db.query(TicketEvent).filter_by(ticket_id=ticket.id, event_type="CANCELLED").count() == 0


@pytest.mark.parametrize("previous_status", ["open", "in_progress", "resolved", "closed", "reopened"])
def test_restore_preserves_existing_status_technician_and_deadline(db, user_factory, previous_status):
    admin = user_factory(email="restore.policy@gmail.com", role="admin")
    ticket = make_ticket(db, admin, status=previous_status, technician_id=admin.id, deleted_at=datetime.now(timezone.utc))
    original_deadline = ticket.due_at
    restored = deleted.restore_deleted_ticket_service(db=db, ticket_id=ticket.id, current_user=admin)
    assert restored.status == previous_status
    assert restored.technician_id == admin.id
    assert restored.due_at == original_deadline
    assert restored.deleted_at is None
    assert restored.deleted_by_id is None
    with pytest.raises(TicketNotFound):
        deleted.restore_deleted_ticket_service(db=db, ticket_id=ticket.id, current_user=admin)
