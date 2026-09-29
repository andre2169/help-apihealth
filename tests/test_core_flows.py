from app.db.models.notification import Notification
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.services.messaging.whatsapp import build_ticket_message, to_evolution_number
from app.services.notifications.service import create_notifications_for_event

from .conftest import login


def _ticket_payload():
    return {
        "title": "Impressora da recepção parou",
        "description": "A impressora não imprime a prescrição.",
        "category": "Hardware",
        "priority": "medium",
        "sector": "Recepção",
        "equipment": "Impressora",
        "asset_tag": "PAT-001",
        "operational_impact": "medium",
        "issue_images": [],
    }


def test_create_ticket_returns_201_and_owner_isolated(client, db, user_factory):
    owner = user_factory(email="helpweb.owner@gmail.com", name="Dono do Chamado")
    other_user = user_factory(email="helpweb.other@gmail.com", name="Outro Usuario")
    db.commit()

    login(client, owner.email)
    response = client.post("/api/v1/tickets/", json=_ticket_payload())

    assert response.status_code == 201, response.text
    ticket_id = response.json()["id"]

    other_client = client.__class__(client.app)
    login(other_client, other_user.email)
    forbidden = other_client.get(f"/api/v1/tickets/{ticket_id}")
    assert forbidden.status_code == 403


def test_ticket_search_matches_code_or_text_without_crossing_owner_scope(
    client, db, user_factory
):
    owner = user_factory(email="helpweb.search.owner@gmail.com", name="Dono da Busca")
    other_user = user_factory(email="helpweb.search.other@gmail.com", name="Outro Usuario")
    db.commit()

    login(client, owner.email)
    created = client.post("/api/v1/tickets/", json=_ticket_payload())
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    by_code = client.get(f"/api/v1/tickets/?search={ticket_id}&limit=20")
    assert by_code.status_code == 200
    assert by_code.json()["has_more"] is False
    assert len(by_code.json()["items"]) == 1
    assert by_code.json()["items"][0]["id"] == ticket_id

    by_title = client.get("/api/v1/tickets/?search=impressora&limit=20")
    assert by_title.status_code == 200
    assert len(by_title.json()["items"]) == 1

    summary = client.get(
        f"/api/v1/tickets/?search={ticket_id}&limit=20&include_total=true"
    )
    assert summary.status_code == 200
    assert summary.json()["total"] == 1

    other_client = client.__class__(client.app)
    login(other_client, other_user.email)
    hidden = other_client.get(f"/api/v1/tickets/?search={ticket_id}&limit=20")
    assert hidden.status_code == 200
    assert hidden.json()["has_more"] is False
    assert hidden.json()["items"] == []


def test_technician_scope_separates_personal_metrics_from_shared_queue(
    client, db, user_factory
):
    owner = user_factory(email="helpweb.scope.owner@gmail.com", name="Solicitante")
    technician = user_factory(
        email="helpweb.scope.technician@gmail.com",
        role="technician",
        name="Tecnico Atual",
    )
    other_technician = user_factory(
        email="helpweb.scope.other@gmail.com",
        role="technician",
        name="Outro Tecnico",
    )

    def add_ticket(*, status, assigned_to=None, title):
        ticket = Ticket(
            title=title,
            description="Chamado usado no teste de escopo.",
            category="Rede",
            priority="medium",
            sector="Recepção",
            equipment="Computador",
            operational_impact="medium",
            sla_hours=24,
            status=status,
            user_id=owner.id,
            technician_id=assigned_to.id if assigned_to else None,
        )
        db.add(ticket)
        db.flush()
        return ticket

    personal_active = add_ticket(
        status="in_progress", assigned_to=technician, title="Meu atendimento ativo"
    )
    personal_done = add_ticket(
        status="resolved", assigned_to=technician, title="Meu atendimento concluído"
    )
    shared_queue = add_ticket(status="open", title="Chamado na fila compartilhada")
    other_personal = add_ticket(
        status="in_progress", assigned_to=other_technician, title="Atendimento de outro técnico"
    )
    closed_unassigned = add_ticket(status="closed", title="Chamado antigo sem responsável")
    db.commit()

    login(client, technician.email)

    listed = client.get("/api/v1/tickets/?limit=100")
    assert listed.status_code == 200, listed.text
    listed_ids = {item["id"] for item in listed.json()["items"]}
    assert listed_ids == {personal_active.id, personal_done.id, shared_queue.id}

    assert client.get(f"/api/v1/tickets/{shared_queue.id}").status_code == 200
    assert client.get(f"/api/v1/tickets/{other_personal.id}").status_code == 403
    assert client.get(f"/api/v1/tickets/{closed_unassigned.id}").status_code == 403

    dashboard = client.get("/api/v1/dashboard/summary")
    assert dashboard.status_code == 200, dashboard.text
    dashboard_data = dashboard.json()
    assert dashboard_data["total"] == 2
    assert dashboard_data["by_status"] == {"in_progress": 1, "resolved": 1}
    assert [item["id"] for item in dashboard_data["technician_queue"]] == [shared_queue.id]

    report = client.get("/api/v1/reports/overview")
    assert report.status_code == 200, report.text
    report_data = report.json()
    assert report_data["summary_metrics"]["total_analyzed"] == 2
    assert [item["id"] for item in report_data["technicians"]] == [technician.id]

    admin = user_factory(email="helpweb.scope.admin@gmail.com", role="admin")
    db.commit()
    admin_client = client.__class__(client.app)
    login(admin_client, admin.email)
    admin_dashboard = admin_client.get("/api/v1/dashboard/summary")
    assert admin_dashboard.status_code == 200
    assert admin_dashboard.json()["total"] == 5


def test_admin_user_search_is_prefix_filtered_and_paginated(client, db, user_factory):
    admin = user_factory(
        email="helpweb.search.admin@gmail.com",
        role="admin",
        name="Administrador",
    )
    user_factory(
        email="helpweb.search.alice@gmail.com",
        role="technician",
        name="Alice Andrade",
    )
    user_factory(
        email="helpweb.search.ana@gmail.com",
        role="technician",
        name="Ana Souza",
    )
    user_factory(
        email="helpweb.search.bruno@gmail.com",
        role="user",
        name="Bruno Lima",
    )
    user_factory(
        email="helpweb.search.inactive@gmail.com",
        role="user",
        name="Zilda Inativa",
        is_active=False,
    )
    db.commit()

    login(client, admin.email)
    prefix = client.get("/api/v1/admin/users?search=Al&limit=1")
    assert prefix.status_code == 200
    assert prefix.json()["has_more"] is False
    assert len(prefix.json()["items"]) == 1
    assert prefix.json()["items"][0]["name"] == "Alice Andrade"

    by_role = client.get("/api/v1/admin/users?role=technician&limit=1")
    assert by_role.status_code == 200
    assert by_role.json()["has_more"] is True
    assert len(by_role.json()["items"]) == 1
    assert by_role.json()["items"][0]["role"] == "technician"

    inactive = client.get("/api/v1/admin/users?is_active=false&order_by=name&direction=asc")
    assert inactive.status_code == 200
    assert inactive.json()["has_more"] is False
    assert inactive.json()["items"][0]["name"] == "Zilda Inativa"


def test_admin_ticket_events_are_grouped_searchable_and_admin_only(
    client, db, user_factory
):
    owner = user_factory(
        email="helpweb.events.owner@gmail.com",
        name="Solicitante dos Eventos",
    )
    admin = user_factory(
        email="helpweb.events.admin@gmail.com",
        role="admin",
        name="Administrador dos Eventos",
    )
    first_ticket = Ticket(
        title="Falha no switch da recepção",
        description="Chamado para testar a tela administrativa de eventos.",
        category="Rede",
        priority="high",
        sector="Recepção",
        operational_impact="high",
        sla_hours=8,
        status="in_progress",
        user_id=owner.id,
    )
    second_ticket = Ticket(
        title="Impressora sem conexão",
        description="Outro chamado para confirmar o agrupamento.",
        category="Hardware",
        priority="medium",
        sector="Arquivo",
        operational_impact="medium",
        sla_hours=24,
        status="open",
        user_id=owner.id,
    )
    db.add_all([first_ticket, second_ticket])
    db.flush()
    db.add_all(
        [
            TicketEvent(
                ticket_id=first_ticket.id,
                user_id=owner.id,
                event_type="CREATED",
                to_status="open",
            ),
            TicketEvent(
                ticket_id=first_ticket.id,
                user_id=owner.id,
                event_type="ASSIGNED",
                from_status="open",
                to_status="in_progress",
            ),
            TicketEvent(
                ticket_id=second_ticket.id,
                user_id=owner.id,
                event_type="CREATED",
                to_status="open",
            ),
        ]
    )
    db.commit()

    login(client, admin.email)
    grouped = client.get("/api/v1/admin/ticket-events?limit=20")
    assert grouped.status_code == 200, grouped.text
    grouped_data = grouped.json()
    assert grouped_data["has_more"] is False
    assert len(grouped_data["items"]) == 2
    first_summary = next(
        item for item in grouped_data["items"] if item["ticket_id"] == first_ticket.id
    )
    assert first_summary["event_count"] == 2
    assert first_summary["last_event"]["event_type"] == "ASSIGNED"

    by_numeric_code = client.get(
        f"/api/v1/admin/ticket-events?search={first_ticket.id}&limit=20"
    )
    assert by_numeric_code.status_code == 200
    assert len(by_numeric_code.json()["items"]) == 1
    assert by_numeric_code.json()["items"][0]["ticket_id"] == first_ticket.id

    by_title = client.get("/api/v1/admin/ticket-events?search=impressora&limit=20")
    assert by_title.status_code == 200
    assert len(by_title.json()["items"]) == 1
    assert by_title.json()["items"][0]["ticket_id"] == second_ticket.id

    user_client = client.__class__(client.app)
    login(user_client, owner.email)
    forbidden = user_client.get("/api/v1/admin/ticket-events")
    assert forbidden.status_code == 403


def test_ticket_deletion_is_admin_only(client, db, user_factory):
    owner = user_factory(email="helpweb.owner.delete@gmail.com")
    admin = user_factory(email="helpweb.admin.delete@gmail.com", role="admin", name="Administrador")
    db.commit()

    login(client, owner.email)
    created = client.post("/api/v1/tickets/", json=_ticket_payload())
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    denied = client.delete(f"/api/v1/tickets/{ticket_id}")
    assert denied.status_code == 403

    admin_client = client.__class__(client.app)
    login(admin_client, admin.email)
    deleted = admin_client.delete(f"/api/v1/tickets/{ticket_id}")
    assert deleted.status_code == 204


def test_new_ticket_notifies_active_technicians_but_not_admins(db, user_factory):
    owner = user_factory(email="helpweb.ticket.owner@gmail.com")
    technician = user_factory(
        email="helpweb.technician@gmail.com",
        role="technician",
        phone="71999999999",
        notification_preference="whatsapp",
    )
    admin = user_factory(email="helpweb.notification.admin@gmail.com", role="admin")
    ticket = Ticket(
        title="Falha na rede da UTI",
        description="A estação não acessa o sistema.",
        category="Rede",
        priority="high",
        sector="UTI",
        operational_impact="high",
        sla_hours=8,
        status="open",
        user_id=owner.id,
    )
    db.add(ticket)
    db.flush()
    event = TicketEvent(
        ticket_id=ticket.id,
        user_id=owner.id,
        event_type="CREATED",
        to_status="open",
    )
    db.add(event)

    created = create_notifications_for_event(
        db=db,
        ticket=ticket,
        event=event,
        actor=owner,
    )
    db.commit()

    assert created == 1
    notifications = db.query(Notification).all()
    assert [notification.recipient_id for notification in notifications] == [technician.id]
    assert admin.id not in [notification.recipient_id for notification in notifications]
    assert db.query(NotificationDelivery).count() == 0


def test_whatsapp_outbox_is_created_without_calling_external_services(db, user_factory, monkeypatch):
    owner = user_factory(email="helpweb.outbox.owner@gmail.com")
    technician = user_factory(
        email="helpweb.outbox.technician@gmail.com",
        role="technician",
        phone="71999999999",
        notification_preference="both",
    )
    ticket = Ticket(
        title="Tela azul no computador",
        description="O equipamento reinicia após apresentar erro.",
        category="Hardware",
        priority="critical",
        sector="Laboratório",
        operational_impact="critical",
        sla_hours=2,
        status="open",
        user_id=owner.id,
    )
    db.add(ticket)
    db.flush()
    event = TicketEvent(
        ticket_id=ticket.id,
        user_id=owner.id,
        event_type="CREATED",
        to_status="open",
    )
    db.add(event)

    monkeypatch.setattr("app.services.notifications.service.settings.WHATSAPP_ENABLED", True)
    created = create_notifications_for_event(
        db=db,
        ticket=ticket,
        event=event,
        actor=owner,
    )
    db.commit()

    delivery = db.query(NotificationDelivery).one()
    assert created == 1
    assert delivery.channel == "whatsapp"
    assert delivery.status == "pending"
    assert delivery.recipient_id == technician.id


def test_whatsapp_message_contains_only_operational_summary(db, user_factory):
    owner = user_factory(email="helpweb.message.owner@gmail.com")
    ticket = Ticket(
        title="Falha no Wi-Fi",
        description="Detalhes que não devem ser enviados ao WhatsApp.",
        category="Rede",
        priority="medium",
        sector="Recepção",
        operational_impact="medium",
        sla_hours=24,
        status="open",
        user_id=owner.id,
    )
    db.add(ticket)
    db.flush()
    notification = Notification(
        recipient_id=owner.id,
        actor_id=owner.id,
        ticket_id=ticket.id,
        type="ticket.created",
        title="Novo chamado recebido",
        message="Resumo interno",
    )
    db.add(notification)
    db.commit()

    message = build_ticket_message(notification)
    assert "CH-" in message
    assert "Recepção" in message
    assert "Detalhes que não devem ser enviados" not in message
    assert to_evolution_number("71999999999") == "5571999999999"
