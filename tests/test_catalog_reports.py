from datetime import date, datetime, timedelta
import re

import pytest
from fastapi import HTTPException

from app.core.classification import classification_key
from app.db.models.catalog_option import CatalogOption
from app.db.models.ticket import Ticket
from app.schemas.catalog_option import CatalogOptionCreate
from app.schemas.ticket import TicketCreate
from app.services.reports.aggregation import activity_series, normalize_counts
from app.services.reports.metrics import reports_overview_service
from app.services.reports.pdf import _ranked_rows, _technician_rows, build_reports_overview_pdf
from app.services.ticket_catalog import create_catalog_option
from app.services.tickets.service import create_ticket_service
from .conftest import login


def test_normalizes_known_names_without_guessing_typos():
    counts = normalize_counts({" Recepção ": 2, "RECEPCAO": 3, "recepção": 4, "Receoao": 1}, ["Recepção"])
    assert counts == {"Receoao": 1, "Recepção": 9}
    assert classification_key("  Centro   CIRÚRGICO ") == "centro cirurgico"


@pytest.mark.parametrize("days", [7, 30, 90, 366, 1500, 20000, 100000])
def test_activity_is_bounded_and_keeps_the_entire_period(days):
    start = date(1600, 1, 1)
    counts = {(start + timedelta(days=index)).isoformat(): index % 5 + 1 for index in range(days)}
    series = activity_series(counts)
    assert len(series["counts"]) <= 8
    assert sum(series["counts"].values()) == sum(counts.values())
    assert series["start_date"] == start.isoformat()
    assert series["end_date"] == (start + timedelta(days=days - 1)).isoformat()


def test_activity_includes_zero_intervals_and_requested_boundaries():
    series = activity_series({"2026-09-02": 2, "2026-09-06": 4}, start_date=date(2026, 9, 1), end_date=date(2026, 9, 7))
    assert list(series["counts"].values()) == [0, 2, 0, 0, 0, 4, 0]


def test_catalog_prevents_duplicates_and_canonicalizes_new_tickets(db, user_factory):
    owner = user_factory(email="catalog.owner@test.local")
    with pytest.raises(HTTPException) as duplicate:
        create_catalog_option(db, CatalogOptionCreate(kind="sector", name="RECEPCAO"))
    assert duplicate.value.status_code == 409
    ticket = create_ticket_service(
        db=db, current_user=owner,
        ticket_in=TicketCreate(title="Problema no computador", description="Computador não inicia.", sector="recepcao", category="HARDWARE"),
    )
    assert ticket.sector == "Recepção"
    assert ticket.category == "Hardware"
    with pytest.raises(HTTPException) as missing:
        create_ticket_service(
            db=db, current_user=owner,
            ticket_in=TicketCreate(title="Problema no computador", description="Computador não inicia.", sector="Receoao", category="Hardware"),
        )
    assert missing.value.status_code == 422


def test_catalog_changes_are_admin_only_and_inactive_items_preserve_history(client, db, user_factory):
    admin = user_factory(email="catalog.admin@gmail.com", role="admin")
    owner = user_factory(email="catalog.user@gmail.com")
    db.commit()
    assert client.get("/api/v1/ticket-catalog/").status_code == 401
    login(client, owner.email)
    assert client.post("/api/v1/admin/ticket-catalog/", json={"kind": "sector", "name": "Consultórios"}).status_code == 403
    login(client, admin.email)
    csrf = client.headers.pop("X-CSRF-Token")
    blocked = client.post("/api/v1/admin/ticket-catalog/", json={"kind": "sector", "name": "Consultórios"})
    assert blocked.status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    created = client.post("/api/v1/admin/ticket-catalog/", json={"kind": "sector", "name": "Consultórios"})
    assert created.status_code == 201, created.text
    option_id = created.json()["id"]
    duplicate = client.post("/api/v1/admin/ticket-catalog/", json={"kind": "sector", "name": "CONSULTORIOS"})
    assert duplicate.status_code == 409
    assert client.post("/api/v1/admin/ticket-catalog/", json={"kind": "sector", "name": "S" * 31}).status_code == 422
    ticket = Ticket(title="Registro antigo", description="Preservar o histórico.", sector="Consultórios", category="Rede", user_id=owner.id)
    db.add(ticket)
    db.commit()
    ticket_id = ticket.id
    assert client.patch(f"/api/v1/admin/ticket-catalog/{option_id}/active", json={"active": False}).status_code == 200
    assert option_id not in {item["id"] for item in client.get("/api/v1/ticket-catalog/").json()}
    assert option_id in {item["id"] for item in client.get("/api/v1/ticket-catalog/?include_inactive=true").json()}
    assert db.get(Ticket, ticket_id).sector == "Consultórios"
    rejected = client.post("/api/v1/tickets/", json={"title": "Novo problema", "description": "Não deve abrir.", "sector": "Consultórios", "category": "Rede"})
    assert rejected.status_code == 422
    assert client.patch(f"/api/v1/admin/ticket-catalog/{option_id}/active", json={"active": True}).status_code == 200


def test_reports_merge_legacy_variants_and_exclude_admins_only_from_technician_table(db, user_factory):
    admin = user_factory(email="report.admin@test.local", role="admin")
    tech = user_factory(email="report.tech@test.local", role="technician", name="Técnico")
    user = user_factory(email="report.user@test.local")
    for index, sector in enumerate(["Recepção", "RECEPCAO", " recepção ", "Receoao"]):
        db.add(Ticket(title=f"Registro {index}", description="Teste de agrupamento.", sector=sector, category="REDE", user_id=user.id, technician_id=tech.id if index % 2 else admin.id))
    db.commit()
    report = reports_overview_service(db=db, current_user=admin)
    assert report["sector_counts"]["Recepção"] == 3
    assert report["category_counts"] == {"Rede": 4}
    assert report["summary_metrics"]["total_analyzed"] == 4
    assert [row["id"] for row in report["technicians"]] == [tech.id]
    assert report["non_technician_assigned_total"] == 2
    filtered = reports_overview_service(db=db, current_user=admin, sector="RECEPCAO")
    assert filtered["summary_metrics"]["total_analyzed"] == 3
    db.query(CatalogOption).filter(CatalogOption.kind == "sector", CatalogOption.name == "Recepção").update({"active": False})
    assert reports_overview_service(db=db, current_user=admin)["sector_counts"]["Recepção"] == 3


def test_pdf_is_compact_and_summary_rows_preserve_totals():
    counts = {f"Nome {index}": index + 1 for index in range(1000)}
    rows = _ranked_rows(counts, max_rows=4)
    assert len(rows) == 5
    assert sum(value for _, value in rows) == sum(counts.values())
    technicians = [{"id": index, "name": f"Técnico {index}", "assigned_total": index + 1, "resolved_total": 1, "closed_total": 0} for index in range(1000)]
    compact = _technician_rows(technicians, max_rows=5)
    assert sum(row["assigned_total"] for row in compact) == sum(row["assigned_total"] for row in technicians)
    series = activity_series({f"{year}-01-01": 1 for year in range(2000, 2027)})
    pdf = build_reports_overview_pdf({
        "sector_counts": counts, "category_counts": counts, "equipment_counts": counts,
        "activity_series": series, "technicians": technicians,
        "generated_at": datetime(2026, 9, 1), "summary_metrics": {"total_analyzed": 500500},
    }, viewer_role="admin")
    assert pdf.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type\s*/Page\b", pdf)) <= 3
