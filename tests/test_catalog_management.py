from datetime import datetime, timezone

import pytest

from app.core.classification import classification_key
from app.db.models.audit_event import AuditEvent
from app.db.models.catalog_option import CatalogOption
from app.db.models.comment import Comment
from app.db.models.maintenance_notice import MaintenanceNotice
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from .conftest import login


def _option(db, kind="sector", name="Recepção"):
    return db.query(CatalogOption).filter_by(kind=kind, normalized_name=classification_key(name)).one()


def _admin(client, db, user_factory):
    admin = user_factory(email="catalog.manager@gmail.com", role="admin")
    db.commit()
    login(client, admin.email)
    return admin


@pytest.mark.parametrize("role", ["user", "technician"])
def test_rename_and_delete_require_admin_and_csrf(client, db, user_factory, role):
    option_id = _option(db).id
    path = f"/api/v1/admin/ticket-catalog/{option_id}"
    assert client.patch(path, json={"name": "Recepção central"}).status_code == 401
    assert client.delete(path).status_code == 401
    user = user_factory(email=f"catalog.{role}@gmail.com", role=role)
    db.commit()
    login(client, user.email)
    assert client.patch(path, json={"name": "Recepção central"}).status_code == 403
    assert client.delete(path).status_code == 403
    _admin(client, db, user_factory)
    client.headers.pop("X-CSRF-Token")
    assert client.patch(path, json={"name": "Recepção central"}).status_code == 403
    assert client.delete(path).status_code == 403


@pytest.mark.parametrize("kind,new_name", [("sector", "Recepção central"), ("category", "Equipamentos de TI")])
def test_rename_preserves_tickets_comments_events_and_operational_dates(client, db, user_factory, kind, new_name):
    admin = _admin(client, db, user_factory)
    owner = user_factory(email="catalog.history@gmail.com")
    old_name = "Recepção" if kind == "sector" else "Hardware"
    option_id = _option(db, kind, old_name).id
    old_date = datetime(2026, 1, 1)
    tickets = []
    for index, variant in enumerate([old_name, old_name.upper(), " " + classification_key(old_name) + " "]):
        ticket = Ticket(title="Histórico preservado", description="Conteúdo original", user_id=owner.id,
                        sector=variant if kind == "sector" else "Recepção",
                        category=variant if kind == "category" else "Hardware",
                        updated_at=old_date, deleted_at=old_date if index == 2 else None)
        db.add(ticket)
        db.flush()
        db.add(Comment(ticket_id=ticket.id, user_id=owner.id, content="Comentário preservado"))
        db.add(TicketEvent(ticket_id=ticket.id, user_id=owner.id, event_type="CREATED", to_status="open"))
        tickets.append(ticket.id)
    db.commit()
    response = client.patch(f"/api/v1/admin/ticket-catalog/{option_id}", json={"name": new_name})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == new_name
    db.expire_all()
    for ticket_id in tickets:
        ticket = db.get(Ticket, ticket_id)
        assert getattr(ticket, kind) == new_name
        assert ticket.updated_at == old_date
        assert ticket.description == "Conteúdo original"
    assert db.query(Comment).count() == 3
    assert db.query(TicketEvent).count() == 3
    audit = db.query(AuditEvent).filter_by(action="admin.ticket_catalog_renamed").one()
    assert audit.actor_id == admin.id
    assert audit.details["previous_name"] == old_name
    assert audit.details["tickets_updated"] == 3


def test_sector_rename_keeps_notice_targeting_and_user_department_consistent(client, db, user_factory):
    admin = _admin(client, db, user_factory)
    user = user_factory(email="catalog.department@gmail.com")
    user.department = "RECEPCAO"
    notice = MaintenanceNotice(title="Manutenção", message="Manutenção programada", target_sectors=["RECEPCAO", "TI"],
                               starts_at=datetime.now(timezone.utc), created_by_id=admin.id)
    db.add(notice)
    option_id = _option(db).id
    db.commit()
    response = client.patch(f"/api/v1/admin/ticket-catalog/{option_id}", json={"name": "Recepção central"})
    assert response.status_code == 200, response.text
    db.expire_all()
    assert user.department == "Recepção central"
    assert notice.target_sectors == ["Recepção central", "TI"]


def test_rename_rejects_duplicates_and_invalid_names_without_partial_changes(client, db, user_factory):
    _admin(client, db, user_factory)
    option_id = _option(db).id
    path = f"/api/v1/admin/ticket-catalog/{option_id}"
    assert client.patch(path, json={"name": "RADIOLOGIA"}).status_code == 409
    assert client.patch(path, json={"name": "S" * 31}).status_code == 422
    assert client.patch(path, json={"name": " "}).status_code == 422
    db.expire_all()
    assert db.get(CatalogOption, option_id).name == "Recepção"
    assert db.query(AuditEvent).filter_by(action="admin.ticket_catalog_renamed").count() == 0


def test_delete_unused_option_is_audited_and_not_listed(client, db, user_factory):
    _admin(client, db, user_factory)
    created = client.post("/api/v1/admin/ticket-catalog/", json={"kind": "sector", "name": "Setor temporário"})
    option_id = created.json()["id"]
    assert client.delete(f"/api/v1/admin/ticket-catalog/{option_id}").status_code == 204
    assert option_id not in {option["id"] for option in client.get("/api/v1/ticket-catalog/?include_inactive=true").json()}
    audit = db.query(AuditEvent).filter_by(action="admin.ticket_catalog_deleted").one()
    assert audit.target_id == option_id
    assert audit.details["name"] == "Setor temporário"


@pytest.mark.parametrize("kind", ["sector", "category"])
def test_delete_blocks_used_and_archived_classifications(client, db, user_factory, kind):
    owner = _admin(client, db, user_factory)
    name = "Recepção" if kind == "sector" else "Hardware"
    option_id = _option(db, kind, name).id
    ticket = Ticket(title="Chamado arquivado", description="Preservar", user_id=owner.id,
                    sector="RECEPCAO", category="HARDWARE", deleted_at=datetime.now(timezone.utc))
    db.add(ticket)
    db.commit()
    response = client.delete(f"/api/v1/admin/ticket-catalog/{option_id}")
    assert response.status_code == 409
    assert "Desative" in response.json()["detail"]
    assert db.get(Ticket, ticket.id) is not None
    assert db.get(CatalogOption, option_id) is not None


@pytest.mark.parametrize("reference", ["profile", "notice"])
def test_delete_blocks_sector_references_outside_tickets(client, db, user_factory, reference):
    admin = _admin(client, db, user_factory)
    if reference == "profile":
        admin.department = "RECEPCAO"
    else:
        db.add(MaintenanceNotice(title="Aviso antigo", message="Registro preservado", target_sectors=["RECEPCAO"],
                                starts_at=datetime.now(timezone.utc), active=False))
    db.commit()
    response = client.delete(f"/api/v1/admin/ticket-catalog/{_option(db).id}")
    assert response.status_code == 409


def test_catalog_management_returns_not_found_for_unknown_items(client, db, user_factory):
    _admin(client, db, user_factory)
    assert client.patch("/api/v1/admin/ticket-catalog/999999", json={"name": "Nome válido"}).status_code == 404
    assert client.delete("/api/v1/admin/ticket-catalog/999999").status_code == 404
