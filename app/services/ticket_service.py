from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, aliased
from app.db.models.ticket import Ticket
from app.core.events import create_ticket_event
from app.db.models.user import User
from sqlalchemy import case
import logging
from app.core.exceptions import (
    TicketNotFound,
    TicketInvalidStatus,
    TicketPermissionDenied,
)

# loggs do sistema
logger = logging.getLogger(__name__)

SEVERITY_SLA_HOURS = {
    "low": 72,
    "medium": 24,
    "high": 8,
    "critical": 2,
}

SEVERITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _get_ticket_or_fail(db: Session, ticket_id: int) -> Ticket:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise TicketNotFound()
    return ticket


def get_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> Ticket:
    ticket = _get_ticket_or_fail(db, ticket_id)

    if current_user.role not in ["technician", "admin"] and ticket.user_id != current_user.id:
        raise TicketPermissionDenied("Você não tem permissão para ver este ticket")

    return ticket


def _value(value):
    return value.value if hasattr(value, "value") else value


def _sla_hours_for(impact: str, priority: str) -> int:
    """
    Calcula o SLA automaticamente pela maior gravidade informada.

    O usuário não define prazo manualmente. Em ambiente de saúde pública isso
    reduz erro de preenchimento: impacto crítico ou prioridade crítica sempre
    gera prazo crítico, mesmo se o outro campo estiver menor.
    """
    impact_rank = SEVERITY_RANK.get(impact, SEVERITY_RANK["medium"])
    priority_rank = SEVERITY_RANK.get(priority, SEVERITY_RANK["medium"])
    selected_rank = max(impact_rank, priority_rank)
    selected_level = next(
        level for level, rank in SEVERITY_RANK.items() if rank == selected_rank
    )
    return SEVERITY_SLA_HOURS[selected_level]


def _due_at(hours: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def create_ticket_service(*, db: Session, ticket_in, current_user: User) -> Ticket:
    impact = _value(ticket_in.operational_impact)
    priority = _value(ticket_in.priority)
    sla_hours = _sla_hours_for(impact, priority)
    issue_images = list(ticket_in.issue_images or [])
    if not issue_images and ticket_in.issue_image:
        issue_images = [ticket_in.issue_image]

    ticket = Ticket(
        title=ticket_in.title,
        description=ticket_in.description,
        category=ticket_in.category,
        priority=priority,
        sector=ticket_in.sector,
        equipment=ticket_in.equipment,
        asset_tag=ticket_in.asset_tag,
        operational_impact=impact,
        issue_image=issue_images[0] if issue_images else None,
        issue_images=issue_images or None,
        sla_hours=sla_hours,
        due_at=_due_at(sla_hours),
        user_id=current_user.id,
        status="open",
    )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    db.flush()

    create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="CREATED",
        to_status="open",
    )

    db.commit()

    logger.info(
        "Ticket criado | ticket_id=%s | user_id=%s | status=%s",
        ticket.id,
        current_user.id,
        ticket.status,
    )

    return ticket


def assign_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> Ticket:
    ticket = _get_ticket_or_fail(db, ticket_id)

    if ticket.status not in ["open", "reopened"]:
        raise TicketInvalidStatus("Ticket não pode ser assumido")

    ticket.technician_id = current_user.id
    old_status = ticket.status
    ticket.status = "in_progress"

    create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="ASSIGNED",
        from_status=old_status,
        to_status="in_progress",
    )

    db.commit()
    db.refresh(ticket)

    logger.info(
        "Ticket atribuído | ticket_id=%s | technician_id=%s | from_status=%s | to_status=%s",
        ticket.id,
        current_user.id,
        old_status,
        ticket.status,
    )

    return ticket


def resolve_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> Ticket:
    ticket = _get_ticket_or_fail(db, ticket_id)

    if ticket.status != "in_progress":
        raise TicketInvalidStatus("Ticket não está em andamento")

    if current_user.role != "admin" and ticket.technician_id != current_user.id:
        raise TicketPermissionDenied("Você não pode resolver este ticket")

    old_status = ticket.status
    ticket.status = "resolved"
    ticket.resolved_at = datetime.now(timezone.utc)

    create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="RESOLVED",
        from_status=old_status,
        to_status="resolved",
    )

    db.commit()
    db.refresh(ticket)

    logger.info(
        "Ticket resolvido | ticket_id=%s | technician_id=%s | from_status=%s | to_status=%s",
        ticket.id,
        current_user.id,
        old_status,
        ticket.status,
    )

    return ticket


def close_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> Ticket:
    ticket = _get_ticket_or_fail(db, ticket_id)

    if current_user.role != "admin" and ticket.user_id != current_user.id:
        logger.warning(
            "Tentativa de fechar ticket de outro usuário | ticket_id=%s | current_user_id=%s | ticket_owner_id=%s",
            ticket.id,
            current_user.id,
            ticket.user_id,
        )

        raise TicketPermissionDenied("Você não pode fechar este ticket")

    if ticket.status != "resolved":
        raise TicketInvalidStatus("Ticket ainda não foi resolvido")

    old_status = ticket.status
    ticket.status = "closed"

    create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="CLOSED",
        from_status=old_status,
        to_status="closed",
    )

    db.commit()
    db.refresh(ticket)

    logger.info(
        "Ticket fechado | ticket_id=%s | user_id=%s | from_status=%s | to_status=%s",
        ticket.id,
        current_user.id,
        old_status,
        ticket.status,
    )

    return ticket


def delete_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> None:
    """
    Remove um chamado do sistema.

    A rota que chama este serviço é protegida para administradores. Mantemos o
    usuário no log para auditoria operacional sem expor dados sensíveis.
    """
    ticket = _get_ticket_or_fail(db, ticket_id)

    logger.warning(
        "Ticket excluído por administrador | ticket_id=%s | admin_user_id=%s",
        ticket.id,
        current_user.id,
    )

    db.delete(ticket)
    db.commit()


def reopen_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> Ticket:
    """
    Reabre um ticket que estava resolvido ou fechado.

    Regra:
    - Usuário comum só pode reabrir os próprios tickets.
    - Admin pode reabrir qualquer ticket.
    - Técnico não reabre por enquanto; ele resolve/atua, mas a reabertura representa contestação do usuário.
    """

    ticket = _get_ticket_or_fail(db, ticket_id)

    # Admin pode reabrir qualquer ticket.
    # Usuário comum só pode reabrir ticket dele.
    if current_user.role != "admin" and ticket.user_id != current_user.id:
        logger.warning(
            "Tentativa de reabrir ticket sem permissão | ticket_id=%s | current_user_id=%s | ticket_owner_id=%s | role=%s",
            ticket.id,
            current_user.id,
            ticket.user_id,
            current_user.role,
        )

        raise TicketPermissionDenied("Você não tem permissão para reabrir este ticket")

    # Só faz sentido reabrir ticket que foi resolvido ou fechado.
    if ticket.status not in ["resolved", "closed"]:
        raise TicketInvalidStatus(
            "Apenas tickets resolvidos ou fechados podem ser reabertos"
        )

    old_status = ticket.status
    ticket.status = "reopened"
    ticket.resolved_at = None
    ticket.sla_hours = _sla_hours_for(ticket.operational_impact, ticket.priority)
    ticket.due_at = _due_at(ticket.sla_hours)

    create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="REOPENED",
        from_status=old_status,
        to_status="reopened",
    )

    db.commit()
    db.refresh(ticket)

    logger.info(
        "Ticket reaberto | ticket_id=%s | user_id=%s | from_status=%s | to_status=%s",
        ticket.id,
        current_user.id,
        old_status,
        ticket.status,
    )

    return ticket


def list_tickets_service(
    *,
    db: Session,
    current_user: User,
    status: str | None = None,
    technician_id: int | None = None,
    user_id: int | None = None,
    priority: str | None = None,
    category: str | None = None,
    sector: str | None = None,
    operational_impact: str | None = None,
    order_by: str = "created_at",
    direction: str = "desc",
    skip: int = 0,
    limit: int = 10,
):
    query = db.query(Ticket)

    logger.info(
        "Listagem de tickets solicitada | current_user_id=%s | role=%s | status=%s | technician_id=%s | user_id=%s | priority=%s | category_set=%s | sector_set=%s | impact=%s | order_by=%s | direction=%s | skip=%s | limit=%s",
        current_user.id,
        current_user.role,
        status,
        technician_id,
        user_id,
        priority,
        bool(category),
        bool(sector),
        operational_impact,
        order_by,
        direction,
        skip,
        limit,
    )

    if current_user.role not in ["technician", "admin"]:
        if user_id is not None and user_id != current_user.id:
            logger.warning(
                "Filtro por user_id negado | current_user_id=%s | requested_user_id=%s",
                current_user.id,
                user_id,
            )

            raise TicketPermissionDenied(
                "Você não tem permissão para filtrar tickets de outro usuário"
            )

        query = query.filter(Ticket.user_id == current_user.id)
    else:
        if user_id is not None:
            query = query.filter(Ticket.user_id == user_id)

    if status:
        query = query.filter(Ticket.status == status)

    if technician_id is not None:
        query = query.filter(Ticket.technician_id == technician_id)

    if priority:
        query = query.filter(Ticket.priority == priority)

    if category:
        query = query.filter(Ticket.category == category)

    if sector:
        query = query.filter(Ticket.sector == sector)

    if operational_impact:
        query = query.filter(Ticket.operational_impact == operational_impact)

    allowed_order_fields = {
        "id": Ticket.id,
        "created_at": Ticket.created_at,
        "due_at": Ticket.due_at,
        "status": Ticket.status,
        "priority": Ticket.priority,
        "operational_impact": Ticket.operational_impact,
    }

    if order_by == "status":
        order_column = case(
            (Ticket.status == "open", 1),
            (Ticket.status == "reopened", 2),
            (Ticket.status == "in_progress", 3),
            (Ticket.status == "resolved", 4),
            (Ticket.status == "closed", 5),
        )
    elif order_by == "priority":
        order_column = case(
            (Ticket.priority == "critical", 1),
            (Ticket.priority == "high", 2),
            (Ticket.priority == "medium", 3),
            (Ticket.priority == "low", 4),
        )
    elif order_by == "operational_impact":
        order_column = case(
            (Ticket.operational_impact == "critical", 1),
            (Ticket.operational_impact == "high", 2),
            (Ticket.operational_impact == "medium", 3),
            (Ticket.operational_impact == "low", 4),
        )
    else:
        order_column = allowed_order_fields.get(order_by, Ticket.created_at)

    if direction == "asc":
        query = query.order_by(order_column.asc(), Ticket.id.asc())
    else:
        query = query.order_by(order_column.desc(), Ticket.id.desc())

    total = query.count()

    owner_alias = aliased(User)
    technician_alias = aliased(User)

    rows = (
        query.with_entities(
            Ticket.id,
            Ticket.title,
            Ticket.category,
            Ticket.priority,
            Ticket.sector,
            Ticket.equipment,
            Ticket.operational_impact,
            Ticket.status,
            Ticket.technician_id,
            owner_alias.name.label("owner_name"),
            technician_alias.name.label("technician_name"),
            Ticket.created_at,
            Ticket.due_at,
        )
        .outerjoin(owner_alias, owner_alias.id == Ticket.user_id)
        .outerjoin(technician_alias, technician_alias.id == Ticket.technician_id)
        .offset(skip)
        .limit(limit)
        .all()
    )

    tickets = [
        {
            "id": row.id,
            "title": row.title,
            "category": row.category,
            "priority": row.priority,
            "sector": row.sector,
            "equipment": row.equipment,
            "operational_impact": row.operational_impact,
            "status": row.status,
            "technician_id": row.technician_id,
            "owner_name": row.owner_name,
            "technician_name": row.technician_name,
            "created_at": row.created_at,
            "due_at": row.due_at,
        }
        for row in rows
    ]

    logger.info(
        "Listagem de tickets concluída | current_user_id=%s | total=%s | returned=%s",
        current_user.id,
        total,
        len(tickets),
    )

    return {
        "items": tickets,
        "total": total,
        "skip": skip,
        "limit": limit,
    }
