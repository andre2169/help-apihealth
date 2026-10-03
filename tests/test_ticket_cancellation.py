from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import TicketInvalidStatus, TicketPermissionDenied
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.db.models.notification import Notification
from app.services.tickets import service
from .conftest import login


def make_ticket(db, owner, **changes):
    ticket = Ticket(
        title="Solicitação cancelável", description="Computador sem conexão com a rede.",
        category="Rede", sector="Recepção", priority="medium", operational_impact="medium",
        user_id=owner.id, status="open", sla_hours=24,
        due_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    for name, value in changes.items():
        setattr(ticket, name, value)
    db.add(ticket)
    db.flush()
    db.add(TicketEvent(ticket_id=ticket.id, user_id=owner.id, event_type="CREATED", to_status="open"))
    db.commit()
    return ticket


def test_cancel_preserves_history_excludes_operational_data_and_admin_can_restore(client, db, user_factory):
    owner = user_factory(email="cancel.owner@gmail.com")
    admin = user_factory(email="cancel.admin@gmail.com", role="admin")
    ticket = make_ticket(db, owner)
    db.add(Notification(
        recipient_id=admin.id, actor_id=owner.id, ticket_id=ticket.id,
        type="TICKET_CREATED", title="Novo chamado", message="Chamado aguardando atendimento.",
    ))
    db.commit()
    login(client, owner.email)
    comment = client.post(f"/api/v1/tickets/{ticket.id}/comments/", json={"content": "Solicitação duplicada, vou cancelar."})
    assert comment.status_code == 201
    assert client.get(f"/api/v1/tickets/{ticket.id}").json()["can_cancel"] is True
    assert client.patch(f"/api/v1/tickets/{ticket.id}/cancel").status_code == 204
    assert client.patch(f"/api/v1/tickets/{ticket.id}/cancel").status_code == 404
    assert client.get(f"/api/v1/tickets/{ticket.id}").status_code == 404
    assert client.get("/api/v1/tickets/").json()["items"] == []
    archive = client.get("/api/v1/tickets/deleted").json()["items"]
    assert len(archive) == 1 and archive[0]["status"] == "cancelled"
    assert client.post(f"/api/v1/admin/deleted-tickets/{ticket.id}/restore").status_code == 403
    timeline = client.get(f"/api/v1/tickets/{ticket.id}/deleted/timeline").json()
    assert [item["event_type"] for item in timeline if item["type"] == "event"] == ["CREATED", "CANCELLED"]
    assert any(item.get("content") == "Solicitação duplicada, vou cancelar." for item in timeline)
    assert db.query(Notification).filter_by(ticket_id=ticket.id).count() == 0
    assert client.post(f"/api/v1/tickets/{ticket.id}/comments/", json={"content": "Não permitido depois do cancelamento."}).status_code == 404

    login(client, admin.email)
    dashboard = client.get("/api/v1/dashboard/summary").json()
    assert dashboard["total"] == 0 and dashboard["technician_queue"] == []
    assert dashboard["technician_queue_total"] == 0
    report = client.get("/api/v1/reports/overview").json()
    assert report["summary_metrics"]["total_analyzed"] == 0
    assert client.get("/api/v1/reports/overview.pdf").status_code == 200
    restored = client.post(f"/api/v1/admin/deleted-tickets/{ticket.id}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "open"
    assert restored.json()["deleted_at"] is None
    deadline = datetime.fromisoformat(restored.json()["due_at"].replace("Z", "+00:00"))
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    assert deadline > datetime.now(timezone.utc)
    db.expire_all()
    assert db.query(TicketEvent).filter_by(ticket_id=ticket.id, event_type="CANCELLED").count() == 1
    recovered = db.query(TicketEvent).filter_by(ticket_id=ticket.id, event_type="RECOVERED").one()
    assert recovered.from_status == "cancelled" and recovered.to_status == "open"


@pytest.mark.parametrize("state", ["in_progress", "resolved", "closed", "reopened"])
def test_owner_cannot_cancel_after_open_state(client, db, user_factory, state):
    owner = user_factory(email="cancel.state@gmail.com")
    ticket = make_ticket(db, owner, status=state)
    login(client, owner.email)
    assert client.get(f"/api/v1/tickets/{ticket.id}").json()["can_cancel"] is False
    assert client.patch(f"/api/v1/tickets/{ticket.id}/cancel").status_code == 400
    db.expire_all()
    assert db.get(Ticket, ticket.id).deleted_at is None


def test_only_owner_can_cancel_and_csrf_is_required(client, db, user_factory):
    owner = user_factory(email="cancel.scope@gmail.com")
    other = user_factory(email="cancel.other@gmail.com")
    ticket = make_ticket(db, owner)
    login(client, other.email)
    assert client.patch(f"/api/v1/tickets/{ticket.id}/cancel").status_code == 403
    login(client, owner.email)
    client.headers.pop("X-CSRF-Token", None)
    assert client.patch(f"/api/v1/tickets/{ticket.id}/cancel").status_code == 403


def test_cancel_rejects_any_previous_assignment_even_if_technician_is_cleared(client, db, user_factory):
    owner = user_factory(email="cancel.history@gmail.com")
    tech = user_factory(email="cancel.tech@gmail.com", role="technician")
    ticket = make_ticket(db, owner)
    login(client, tech.email)
    assert client.patch(f"/api/v1/tickets/{ticket.id}/assign").status_code == 200
    db.expire_all()
    ticket.status = "open"
    ticket.technician_id = None
    db.commit()
    login(client, owner.email)
    assert client.get(f"/api/v1/tickets/{ticket.id}").json()["can_cancel"] is False
    assert client.patch(f"/api/v1/tickets/{ticket.id}/cancel").status_code == 400


@pytest.mark.parametrize("action", ["cancel", "assign"])
def test_conditional_update_rejects_stale_state(db, user_factory, monkeypatch, action):
    owner = user_factory(email="cancel.race.owner@gmail.com")
    tech = user_factory(email="cancel.race.tech@gmail.com", role="technician")
    ticket = make_ticket(db, owner)
    if action == "cancel":
        db.query(Ticket).filter_by(id=ticket.id).update(
            {"status": "in_progress", "technician_id": tech.id}, synchronize_session=False,
        )
    else:
        db.query(Ticket).filter_by(id=ticket.id).update(
            {"status": "cancelled", "deleted_at": datetime.now(timezone.utc)}, synchronize_session=False,
        )
    # Keep the old ORM object while changing the stored row, as in a concurrent request.
    monkeypatch.setattr(service, "_get_ticket_or_fail", lambda *_: ticket)
    with pytest.raises(TicketInvalidStatus):
        if action == "cancel":
            service.cancel_ticket_service(db=db, ticket_id=ticket.id, current_user=owner)
        else:
            service.assign_ticket_service(db=db, ticket_id=ticket.id, current_user=tech)
    assert db.query(TicketEvent).filter(TicketEvent.event_type.in_(["CANCELLED", "ASSIGNED"])).count() == 0


@pytest.mark.parametrize("role", ["user", "technician", "admin"])
def test_only_admin_can_reopen_or_delete_assigned_ticket(client, db, user_factory, role):
    actor = user_factory(email=f"cancel.reopen.{role}@gmail.com", role=role)
    ticket = make_ticket(db, actor, status="resolved", technician_id=actor.id)
    login(client, actor.email)
    reopened = client.patch(f"/api/v1/tickets/{ticket.id}/reopen")
    assert reopened.status_code == (200 if role == "admin" else 403)
    deleted = client.delete(f"/api/v1/tickets/{ticket.id}")
    assert deleted.status_code == (204 if role == "admin" else 403)
    if role != "admin":
        with pytest.raises(TicketPermissionDenied):
            service.reopen_ticket_service(db=db, ticket_id=ticket.id, current_user=actor)
        with pytest.raises(TicketPermissionDenied):
            service.delete_ticket_service(db=db, ticket_id=ticket.id, current_user=actor)


def test_deleted_tickets_never_appear_in_queue_previews_or_totals(client, db, user_factory):
    admin = user_factory(email="cancel.queue@gmail.com", role="admin")
    for index in range(12):
        make_ticket(db, admin, title=f"Solicitação {index}")
    assigned = make_ticket(db, admin, status="in_progress", technician_id=admin.id)
    login(client, admin.email)
    assert client.delete(f"/api/v1/tickets/{assigned.id}").status_code == 204
    dashboard = client.get("/api/v1/dashboard/summary").json()
    assert dashboard["technician_queue_total"] == 12
    assert len(dashboard["technician_queue"]) == 8
    assert dashboard["my_active_total"] == 0 and dashboard["my_active_tickets"] == []
