from datetime import datetime, timezone

from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent

from .conftest import login


def _ticket(*, owner_id: int) -> Ticket:
    return Ticket(
        title="Chamado para testar recuperação",
        description="Registro usado para validar a exclusão lógica.",
        category="Rede",
        priority="medium",
        sector="Recepção",
        equipment="Computador",
        operational_impact="medium",
        sla_hours=24,
        status="open",
        user_id=owner_id,
    )


def test_admin_can_list_view_and_restore_soft_deleted_ticket(
    client, db, user_factory
):
    owner = user_factory(email="helpweb.recycle.owner@gmail.com")
    admin = user_factory(
        email="helpweb.recycle.admin@gmail.com",
        role="admin",
        name="Administrador da Recuperação",
    )
    ticket = _ticket(owner_id=owner.id)
    db.add(ticket)
    db.flush()
    db.add(
        TicketEvent(
            ticket_id=ticket.id,
            user_id=owner.id,
            event_type="CREATED",
            to_status="open",
        )
    )
    db.commit()

    login(client, admin.email)
    deleted = client.delete(f"/api/v1/tickets/{ticket.id}")
    assert deleted.status_code == 204, deleted.text

    db.expire_all()
    stored = db.get(Ticket, ticket.id)
    assert stored.deleted_at is not None
    assert stored.deleted_by_id == admin.id

    active_detail = client.get(f"/api/v1/tickets/{ticket.id}")
    assert active_detail.status_code == 404
    active_list = client.get("/api/v1/tickets/?search=recuperação&limit=20")
    assert active_list.status_code == 200
    assert ticket.id not in {item["id"] for item in active_list.json()["items"]}

    deleted_list = client.get("/api/v1/admin/deleted-tickets?search=recuperação")
    assert deleted_list.status_code == 200, deleted_list.text
    assert deleted_list.json()["has_more"] is False
    assert len(deleted_list.json()["items"]) == 1
    assert deleted_list.json()["items"][0]["ticket_id"] == ticket.id

    deleted_detail = client.get(f"/api/v1/admin/deleted-tickets/{ticket.id}")
    assert deleted_detail.status_code == 200
    assert deleted_detail.json()["description"] == ticket.description
    assert deleted_detail.json()["deleted_by_id"] == admin.id

    restored = client.post(f"/api/v1/admin/deleted-tickets/{ticket.id}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["deleted_at"] is None
    assert restored.json()["status"] == "open"

    db.expire_all()
    stored = db.get(Ticket, ticket.id)
    assert stored.deleted_at is None
    assert stored.deleted_by_id is None
    assert db.query(TicketEvent).filter(
        TicketEvent.ticket_id == ticket.id,
        TicketEvent.event_type == "RECOVERED",
    ).count() == 1

    active_detail = client.get(f"/api/v1/tickets/{ticket.id}")
    assert active_detail.status_code == 200


def test_non_admin_cannot_access_deleted_ticket_area(client, db, user_factory):
    user = user_factory(email="helpweb.recycle.user@gmail.com")
    db.commit()
    login(client, user.email)

    response = client.get("/api/v1/admin/deleted-tickets")

    assert response.status_code == 403


def test_deleted_ticket_visibility_is_scoped_for_users_and_shared_with_technicians(
    client, db, user_factory
):
    owner_one = user_factory(email="helpweb.recycle.scope.owner1@gmail.com")
    owner_two = user_factory(email="helpweb.recycle.scope.owner2@gmail.com")
    technician = user_factory(
        email="helpweb.recycle.scope.technician@gmail.com", role="technician"
    )
    admin = user_factory(
        email="helpweb.recycle.scope.admin@gmail.com", role="admin"
    )
    first_ticket = _ticket(owner_id=owner_one.id)
    second_ticket = _ticket(owner_id=owner_two.id)
    db.add_all([first_ticket, second_ticket])
    db.commit()

    admin_client = client.__class__(client.app)
    login(admin_client, admin.email)
    for ticket in (first_ticket, second_ticket):
        response = admin_client.delete(f"/api/v1/tickets/{ticket.id}")
        assert response.status_code == 204, response.text

    owner_client = client.__class__(client.app)
    login(owner_client, owner_one.email)
    owner_list = owner_client.get("/api/v1/tickets/deleted")
    assert owner_list.status_code == 200, owner_list.text
    assert [item["ticket_id"] for item in owner_list.json()["items"]] == [first_ticket.id]
    assert owner_client.get(f"/api/v1/tickets/{first_ticket.id}/deleted").status_code == 200
    assert owner_client.get(f"/api/v1/tickets/{second_ticket.id}/deleted").status_code == 404
    assert owner_client.get(
        f"/api/v1/tickets/{first_ticket.id}/deleted/timeline"
    ).status_code == 200
    assert owner_client.get(
        f"/api/v1/tickets/{second_ticket.id}/deleted/timeline"
    ).status_code == 404

    technician_client = client.__class__(client.app)
    login(technician_client, technician.email)
    technician_list = technician_client.get("/api/v1/tickets/deleted")
    assert technician_list.status_code == 200, technician_list.text
    assert {item["ticket_id"] for item in technician_list.json()["items"]} == {
        first_ticket.id,
        second_ticket.id,
    }
    assert technician_client.get(
        f"/api/v1/tickets/{second_ticket.id}/deleted"
    ).status_code == 200
    assert technician_client.get(
        f"/api/v1/tickets/{second_ticket.id}/deleted/timeline"
    ).status_code == 200

    denied_restore = technician_client.post(
        f"/api/v1/admin/deleted-tickets/{first_ticket.id}/restore"
    )
    assert denied_restore.status_code == 403


def test_owner_cannot_add_comment_to_soft_deleted_ticket(client, db, user_factory):
    owner = user_factory(email="helpweb.deleted-comment.owner@gmail.com")
    ticket = _ticket(owner_id=owner.id)
    db.add(ticket)
    db.flush()
    ticket.deleted_at = datetime.now(timezone.utc)
    db.commit()

    login(client, owner.email)
    response = client.post(
        f"/api/v1/tickets/{ticket.id}/comments/",
        json={"content": "Comentário depois da exclusão"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Ticket não encontrado"
