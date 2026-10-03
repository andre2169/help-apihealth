import re
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session, aliased

from app.core.events import create_ticket_event
from app.core.exceptions import TicketNotFound, TicketPermissionDenied
from app.db.models.ticket import Ticket
from app.db.models.user import User
from app.services.audit.events import record_audit_event
from app.services.tickets.timeline import get_ticket_timeline
from app.services.tickets.service import _due_at, _sla_hours_for
from app.core.search import LIKE_ESCAPE, contains_pattern, normalize_search, page_rows


DELETED_TICKET_LIMIT_MAX = 50


def _can_view_deleted_ticket(*, user: User, ticket: Ticket) -> bool:
    if user.role in {"admin", "technician"}:
        return True
    return ticket.user_id == user.id


def _get_deleted_ticket_or_fail(
    db: Session, ticket_id: int, current_user: User
) -> Ticket:
    ticket = (
        db.query(Ticket)
        .filter(Ticket.id == ticket_id, Ticket.deleted_at.is_not(None))
        .first()
    )
    if not ticket or not _can_view_deleted_ticket(user=current_user, ticket=ticket):
        raise TicketNotFound("Chamado excluído não encontrado")
    return ticket


def list_deleted_tickets_service(
    *,
    db: Session,
    current_user: User,
    search: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    sector: str | None = None,
    operational_impact: str | None = None,
    direction: str = "desc",
    skip: int = 0,
    limit: int = 20,
) -> dict:
    safe_skip = max(skip, 0)
    safe_limit = min(max(limit, 1), DELETED_TICKET_LIMIT_MAX)
    owner_alias = aliased(User)
    technician_alias = aliased(User)
    deleted_by_alias = aliased(User)
    query = db.query(Ticket).filter(Ticket.deleted_at.is_not(None))
    if current_user.role not in {"admin", "technician"}:
        query = query.filter(Ticket.user_id == current_user.id)

    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if category:
        query = query.filter(Ticket.category == category)
    if sector:
        query = query.filter(Ticket.sector == sector)
    if operational_impact:
        query = query.filter(Ticket.operational_impact == operational_impact)

    clean_search = normalize_search(search)
    if clean_search:
        filters = [
            Ticket.title.ilike(contains_pattern(clean_search), escape=LIKE_ESCAPE),
            Ticket.description.ilike(contains_pattern(clean_search), escape=LIKE_ESCAPE),
            Ticket.sector.ilike(contains_pattern(clean_search), escape=LIKE_ESCAPE),
            Ticket.category.ilike(contains_pattern(clean_search), escape=LIKE_ESCAPE),
        ]
        code_match = re.fullmatch(r"(?i)(?:ch[-\s]*)?0*(\d+)", clean_search)
        if code_match and len(code_match.group(1)) <= 18:
            filters.insert(0, Ticket.id == int(code_match.group(1)))
        query = query.filter(or_(*filters))

    rows_query = (
        query.with_entities(
            Ticket.id.label("ticket_id"),
            Ticket.title,
            Ticket.status,
            Ticket.priority,
            Ticket.sector,
            Ticket.category,
            Ticket.created_at,
            Ticket.updated_at,
            Ticket.deleted_at,
            owner_alias.name.label("owner_name"),
            technician_alias.name.label("technician_name"),
            deleted_by_alias.name.label("deleted_by_name"),
        )
        .outerjoin(owner_alias, owner_alias.id == Ticket.user_id)
        .outerjoin(technician_alias, technician_alias.id == Ticket.technician_id)
        .outerjoin(deleted_by_alias, deleted_by_alias.id == Ticket.deleted_by_id)
        .order_by(
            Ticket.deleted_at.asc() if direction == "asc" else Ticket.deleted_at.desc(),
            Ticket.id.asc() if direction == "asc" else Ticket.id.desc(),
        )
    )
    rows, has_more = page_rows(rows_query, skip=safe_skip, limit=safe_limit)

    return {
        "items": [
            {
                "ticket_id": ticket.ticket_id,
                "title": ticket.title,
                "status": ticket.status,
                "priority": ticket.priority,
                "sector": ticket.sector,
                "category": ticket.category,
                "owner_name": ticket.owner_name,
                "technician_name": ticket.technician_name,
                "created_at": ticket.created_at,
                "updated_at": ticket.updated_at,
                "deleted_at": ticket.deleted_at,
                "deleted_by_name": ticket.deleted_by_name,
            }
            for ticket in rows
        ],
        "total": None,
        "skip": safe_skip,
        "limit": safe_limit,
        "has_more": has_more,
    }


def get_deleted_ticket_service(
    *, db: Session, ticket_id: int, current_user: User
) -> Ticket:
    return _get_deleted_ticket_or_fail(db, ticket_id, current_user)


def get_deleted_ticket_timeline_service(
    *, db: Session, ticket_id: int, current_user: User
) -> list[dict]:
    _get_deleted_ticket_or_fail(db, ticket_id, current_user)
    return get_ticket_timeline(db, ticket_id)


def restore_deleted_ticket_service(
    *,
    db: Session,
    ticket_id: int,
    current_user: User,
) -> Ticket:
    if current_user.role != "admin":
        raise TicketPermissionDenied("Apenas administradores podem recuperar chamados")

    ticket = _get_deleted_ticket_or_fail(db, ticket_id, current_user)
    previous_status = ticket.status
    restored_values = {"deleted_at": None, "deleted_by_id": None}
    if previous_status == "cancelled":
        sla_hours = _sla_hours_for(ticket.operational_impact, ticket.priority)
        restored_values.update(
            status="open", resolved_at=None, sla_hours=sla_hours, due_at=_due_at(sla_hours)
        )

    # Only the request that restores the archived row may record recovery events.
    updated = (
        db.query(Ticket)
        .filter(
            Ticket.id == ticket_id,
            Ticket.deleted_at.is_not(None),
            Ticket.status == previous_status,
        )
        .update(restored_values, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        raise TicketNotFound("Chamado excluído não encontrado")
    db.refresh(ticket)
    event = create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="RECOVERED",
        from_status=previous_status,
        to_status=ticket.status,
    )
    db.flush()
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="ticket.recovered",
        target_type="ticket",
        target_id=ticket.id,
        details={"previous_status": previous_status, "event_id": event.id},
    )
    db.commit()
    db.refresh(ticket)
    return ticket
