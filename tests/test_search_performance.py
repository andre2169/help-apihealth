from datetime import datetime, timedelta

from app.db.models.ticket import Ticket
from app.services.reports.metrics import (
    _active_age_counts,
    _queue_snapshot,
    _sla_metrics,
)
from app.services.tickets.deleted import list_deleted_tickets_service
from app.services.tickets.service import list_tickets_service
from app.services.users.admin import list_users_service

from .conftest import login


def test_ticket_search_uses_one_paged_query_and_reports_next_page(
    client, db, user_factory, query_statements
):
    owner = user_factory(email="helpweb.performance.owner@gmail.com")
    for index in range(3):
        db.add(
            Ticket(
                title=f"Computador da recepcao {index}",
                description="Falha de rede para validar busca paginada.",
                category="Rede",
                priority="medium",
                sector="Recepção",
                operational_impact="medium",
                sla_hours=24,
                status="open",
                user_id=owner.id,
            )
        )
    db.commit()

    db.refresh(owner)
    query_statements.clear()
    result = list_tickets_service(
        db=db,
        current_user=owner,
        search="computador",
        skip=0,
        limit=2,
    )

    assert len(result["items"]) == 2
    assert result["has_more"] is True
    assert result["total"] is None
    assert len(query_statements) == 1


def test_user_prefix_search_escapes_wildcards_and_uses_one_query(
    db, user_factory, query_statements
):
    admin = user_factory(email="helpweb.performance.admin@gmail.com", role="admin")
    user_factory(email="helpweb.performance.alice@gmail.com", name="Alice Andrade")
    user_factory(email="helpweb.performance.ana@gmail.com", name="Ana Souza")
    user_factory(email="helpweb.performance.percent@gmail.com", name="A%literal")
    db.commit()

    query_statements.clear()
    result = list_users_service(db=db, search="A", skip=0, limit=2)
    assert len(result["items"]) == 2
    assert result["has_more"] is True
    assert len(query_statements) == 1

    query_statements.clear()
    literal = list_users_service(db=db, search="A%", skip=0, limit=20)
    assert [item["name"] for item in literal["items"]] == ["A%literal"]
    assert len(query_statements) == 1
    assert admin.id not in {item["id"] for item in literal["items"]}


def test_deleted_ticket_list_avoids_relationship_n_plus_one(
    db, user_factory, query_statements
):
    owner = user_factory(email="helpweb.performance.deleted.owner@gmail.com")
    technician = user_factory(
        email="helpweb.performance.deleted.technician@gmail.com",
        role="technician",
    )
    admin = user_factory(
        email="helpweb.performance.deleted.admin@gmail.com",
        role="admin",
    )
    db.add(
        Ticket(
            title="Chamado excluido para teste de consulta",
            description="Descricao do registro excluido.",
            category="Rede",
            priority="low",
            sector="Recepção",
            operational_impact="low",
            sla_hours=24,
            status="closed",
            user_id=owner.id,
            technician_id=technician.id,
            deleted_by_id=admin.id,
            deleted_at=datetime.utcnow(),
        )
    )
    db.commit()

    owner_name = owner.name
    technician_name = technician.name
    admin_name = admin.name
    query_statements.clear()
    result = list_deleted_tickets_service(
        db=db, current_user=admin, search="excluido", limit=20
    )

    assert len(result["items"]) == 1
    assert result["items"][0]["owner_name"] == owner_name
    assert result["items"][0]["technician_name"] == technician_name
    assert result["items"][0]["deleted_by_name"] == admin_name
    assert len(query_statements) == 1


def test_report_aggregates_are_bounded_to_one_query_each(db, user_factory, query_statements):
    owner = user_factory(email="helpweb.performance.metrics@gmail.com")
    now = datetime.utcnow()
    db.add_all(
        [
            Ticket(
                title="Chamado ativo",
                description="Ativo",
                category="Rede",
                priority="high",
                sector="TI",
                operational_impact="high",
                sla_hours=8,
                status="in_progress",
                user_id=owner.id,
                created_at=now - timedelta(hours=2),
                due_at=now + timedelta(hours=2),
            ),
            Ticket(
                title="Chamado resolvido",
                description="Resolvido",
                category="Hardware",
                priority="medium",
                sector="Recepção",
                operational_impact="medium",
                sla_hours=24,
                status="resolved",
                user_id=owner.id,
                created_at=now - timedelta(hours=4),
                resolved_at=now - timedelta(hours=1),
                due_at=now + timedelta(hours=20),
            ),
        ]
    )
    db.commit()
    query = db.query(Ticket)

    for metric in (_sla_metrics, _active_age_counts, _queue_snapshot):
        query_statements.clear()
        result = metric(query)
        assert result
        assert len(query_statements) == 1


def test_ticket_search_route_preserves_permissions_and_has_more(client, db, user_factory):
    owner = user_factory(email="helpweb.performance.route.owner@gmail.com")
    other = user_factory(email="helpweb.performance.route.other@gmail.com")
    for index in range(3):
        db.add(
            Ticket(
                title=f"Internet lenta {index}",
                description="Chamado visivel somente ao solicitante.",
                category="Internet",
                priority="medium",
                sector="TI",
                operational_impact="medium",
                sla_hours=24,
                status="open",
                user_id=owner.id,
            )
        )
    db.commit()

    login(client, owner.email)
    response = client.get("/api/v1/tickets/?search=internet&limit=2")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    assert response.json()["has_more"] is True

    other_client = client.__class__(client.app)
    login(other_client, other.email)
    hidden = other_client.get("/api/v1/tickets/?search=internet&limit=2")
    assert hidden.status_code == 200
    assert hidden.json()["items"] == []
    assert hidden.json()["has_more"] is False
