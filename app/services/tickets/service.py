from datetime import datetime, timedelta, timezone
import re

from sqlalchemy.orm import Session, aliased
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.core.events import create_ticket_event
from app.db.models.user import User
from sqlalchemy import case, or_
import logging
from app.core import security_policy as policy
from app.core.exceptions import (
    TicketNotFound,
    TicketInvalidStatus,
    TicketPermissionDenied,
)
from app.services.audit.events import record_audit_event
from app.services.notifications.service import (
    delete_notifications_for_ticket,
    create_notifications_for_event,
)
from app.services.tickets.access import apply_ticket_visibility, can_view_ticket
from app.core.search import LIKE_ESCAPE, contains_pattern, normalize_search, page_rows
from app.services.ticket_catalog import require_catalog_name

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
    ticket = (
        db.query(Ticket)
        .filter(Ticket.id == ticket_id, Ticket.deleted_at.is_(None))
        .first()
    )
    if not ticket:
        raise TicketNotFound()
    return ticket


def get_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> Ticket:
    ticket = _get_ticket_or_fail(db, ticket_id)

    if not can_view_ticket(user=current_user, ticket=ticket):
        raise TicketPermissionDenied("Você não tem permissão para ver este ticket")

    ticket.can_cancel = (
        ticket.user_id == current_user.id
        and ticket.status == "open"
        and ticket.technician_id is None
        and not db.query(TicketEvent.id).filter(
            TicketEvent.ticket_id == ticket.id,
            TicketEvent.event_type == "ASSIGNED",
        ).first()
    )
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


def _ensure_ticket_image_quota(*, db: Session, current_user: User, issue_images: list[str]) -> None:
    if not issue_images:
        return

    since = datetime.now(timezone.utc) - timedelta(days=1)
    tickets_with_images = (
        db.query(Ticket.id)
        .filter(
            Ticket.user_id == current_user.id,
            Ticket.created_at >= since,
            or_(
                Ticket.issue_image.is_not(None),
                Ticket.issue_images.is_not(None),
            ),
        )
        .count()
    )

    if tickets_with_images >= policy.MAX_TICKET_IMAGE_TICKETS_PER_USER_DAY:
        raise TicketInvalidStatus(
            "Limite diário de chamados com imagens atingido. Tente novamente mais tarde ou abra o chamado sem fotos."
        )


def create_ticket_service(*, db: Session, ticket_in, current_user: User) -> Ticket:
    if not current_user.email_verified:
        raise TicketPermissionDenied("Confirme seu email antes de abrir chamados.")

    category = require_catalog_name(db, kind="category", value=ticket_in.category)
    sector = require_catalog_name(db, kind="sector", value=ticket_in.sector)
    impact = _value(ticket_in.operational_impact)
    priority = _value(ticket_in.priority)
    sla_hours = _sla_hours_for(impact, priority)
    issue_images = list(ticket_in.issue_images or [])
    if not issue_images and ticket_in.issue_image:
        issue_images = [ticket_in.issue_image]

    _ensure_ticket_image_quota(db=db, current_user=current_user, issue_images=issue_images)

    ticket = Ticket(
        title=ticket_in.title,
        description=ticket_in.description,
        category=category,
        priority=priority,
        sector=sector,
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
    db.flush()

    event = create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="CREATED",
        to_status="open",
    )
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="ticket.created",
        target_type="ticket",
        target_id=ticket.id,
        details={"has_images": bool(issue_images), "priority": priority, "impact": impact},
    )
    notifications_created = create_notifications_for_event(
        db=db,
        ticket=ticket,
        event=event,
        actor=current_user,
    )

    db.commit()

    logger.info(
        "Ticket criado | ticket_id=%s | user_id=%s | status=%s | notifications=%s",
        ticket.id,
        current_user.id,
        ticket.status,
        notifications_created,
    )

    return ticket


def assign_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> Ticket:
    ticket = _get_ticket_or_fail(db, ticket_id)

    if ticket.status not in ["open", "reopened"]:
        raise TicketInvalidStatus("Ticket não pode ser assumido")

    if ticket.technician_id is not None and ticket.technician_id != current_user.id:
        raise TicketPermissionDenied("Este ticket já está atribuído a outro técnico")

    old_status = ticket.status
    # Conditional updates serialize assignment and cancellation, including stale reads.
    changed = db.query(Ticket).filter(
        Ticket.id == ticket.id,
        Ticket.deleted_at.is_(None),
        Ticket.status == old_status,
        or_(Ticket.technician_id.is_(None), Ticket.technician_id == current_user.id),
    ).update({Ticket.technician_id: current_user.id, Ticket.status: "in_progress"}, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise TicketInvalidStatus("O chamado foi alterado. Atualize a página antes de assumir.")
    db.refresh(ticket)

    event = create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="ASSIGNED",
        from_status=old_status,
        to_status="in_progress",
    )
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="ticket.assigned",
        target_type="ticket",
        target_id=ticket.id,
    )
    notifications_created = create_notifications_for_event(
        db=db,
        ticket=ticket,
        event=event,
        actor=current_user,
    )

    db.commit()
    db.refresh(ticket)

    logger.info(
        "Ticket atribuído | ticket_id=%s | technician_id=%s | from_status=%s | to_status=%s | notifications=%s",
        ticket.id,
        current_user.id,
        old_status,
        ticket.status,
        notifications_created,
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

    event = create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="RESOLVED",
        from_status=old_status,
        to_status="resolved",
    )
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="ticket.resolved",
        target_type="ticket",
        target_id=ticket.id,
    )
    notifications_created = create_notifications_for_event(
        db=db,
        ticket=ticket,
        event=event,
        actor=current_user,
    )

    db.commit()
    db.refresh(ticket)

    logger.info(
        "Ticket resolvido | ticket_id=%s | technician_id=%s | from_status=%s | to_status=%s | notifications=%s",
        ticket.id,
        current_user.id,
        old_status,
        ticket.status,
        notifications_created,
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

    event = create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="CLOSED",
        from_status=old_status,
        to_status="closed",
    )
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="ticket.closed",
        target_type="ticket",
        target_id=ticket.id,
    )
    notifications_created = create_notifications_for_event(
        db=db,
        ticket=ticket,
        event=event,
        actor=current_user,
    )

    db.commit()
    db.refresh(ticket)

    logger.info(
        "Ticket fechado | ticket_id=%s | user_id=%s | from_status=%s | to_status=%s | notifications=%s",
        ticket.id,
        current_user.id,
        old_status,
        ticket.status,
        notifications_created,
    )

    return ticket


def delete_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> None:
    """Marca um chamado como excluído sem remover seus dados do banco."""
    if current_user.role != "admin":
        raise TicketPermissionDenied("Apenas administradores podem excluir chamados")
    ticket = _get_ticket_or_fail(db, ticket_id)

    logger.warning(
        "Ticket excluído por administrador | ticket_id=%s | admin_user_id=%s",
        ticket.id,
        current_user.id,
    )

    delete_notifications_for_ticket(db=db, ticket_id=ticket.id)
    ticket.deleted_at = datetime.now(timezone.utc)
    ticket.deleted_by_id = current_user.id
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="ticket.deleted",
        target_type="ticket",
        target_id=ticket_id,
        details={"deletion_mode": "soft"},
    )
    db.commit()


def cancel_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> None:
    """Cancela o próprio chamado somente antes do primeiro atendimento."""
    ticket = _get_ticket_or_fail(db, ticket_id)
    if ticket.user_id != current_user.id:
        raise TicketPermissionDenied("Você só pode cancelar seus próprios chamados")

    was_assigned = db.query(TicketEvent.id).filter(
        TicketEvent.ticket_id == Ticket.id,
        TicketEvent.event_type == "ASSIGNED",
    ).exists()
    changed = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.user_id == current_user.id,
        Ticket.deleted_at.is_(None),
        Ticket.status == "open",
        Ticket.technician_id.is_(None),
        ~was_assigned,
    ).update({
        Ticket.status: "cancelled",
        Ticket.deleted_at: datetime.now(timezone.utc),
        Ticket.deleted_by_id: current_user.id,
    }, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise TicketInvalidStatus("Só é possível cancelar antes de um técnico assumir o chamado.")
    delete_notifications_for_ticket(db=db, ticket_id=ticket_id)
    create_ticket_event(
        db=db, ticket_id=ticket_id, user_id=current_user.id,
        event_type="CANCELLED", from_status="open", to_status="cancelled",
    )
    record_audit_event(
        db, actor_id=current_user.id, action="ticket.cancelled",
        target_type="ticket", target_id=ticket_id,
        details={"deletion_mode": "soft", "reason": "owner_before_assignment"},
    )
    db.commit()


def reopen_ticket_service(*, db: Session, ticket_id: int, current_user: User) -> Ticket:
    """Somente o administrador pode reabrir um chamado resolvido ou fechado."""
    if current_user.role != "admin":
        raise TicketPermissionDenied("Apenas administradores podem reabrir chamados")

    ticket = _get_ticket_or_fail(db, ticket_id)

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

    event = create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="REOPENED",
        from_status=old_status,
        to_status="reopened",
    )
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="ticket.reopened",
        target_type="ticket",
        target_id=ticket.id,
    )
    notifications_created = create_notifications_for_event(
        db=db,
        ticket=ticket,
        event=event,
        actor=current_user,
    )

    db.commit()
    db.refresh(ticket)

    logger.info(
        "Ticket reaberto | ticket_id=%s | user_id=%s | from_status=%s | to_status=%s | notifications=%s",
        ticket.id,
        current_user.id,
        old_status,
        ticket.status,
        notifications_created,
    )

    return ticket


def list_tickets_service(
    *,
    db: Session,
    current_user: User,
    search: str | None = None,
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
    include_total: bool = False,
):
    query = apply_ticket_visibility(db.query(Ticket), current_user)

    logger.info(
        "Listagem de tickets solicitada | current_user_id=%s | role=%s | search_set=%s | status=%s | technician_id=%s | user_id=%s | priority=%s | category_set=%s | sector_set=%s | impact=%s | order_by=%s | direction=%s | skip=%s | limit=%s",
        current_user.id,
        current_user.role,
        bool(search),
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

    if current_user.role == "user":
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
    elif user_id is not None:
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

    if search:
        # O codigo publico e derivado do ID do chamado (por exemplo, CH-00016).
        # Numeros digitados pelo usuario procuram o ID exato, enquanto textos
        # procuram titulo e descricao. O escopo de visibilidade ja foi aplicado
        # acima, antes desta expressao de busca.
        search_term = normalize_search(search)
        code_match = re.fullmatch(r"(?i)(?:ch[-\s]*)?0*(\d+)", search_term)
        search_filters = [
            Ticket.title.ilike(contains_pattern(search_term), escape=LIKE_ESCAPE),
            Ticket.description.ilike(contains_pattern(search_term), escape=LIKE_ESCAPE),
        ]
        if code_match and len(code_match.group(1)) <= 18:
            search_filters.insert(0, Ticket.id == int(code_match.group(1)))
        query = query.filter(or_(*search_filters))

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

    if order_by == "due_at":
        if direction == "asc":
            query = query.order_by(
                Ticket.due_at.is_(None).asc(),
                Ticket.due_at.asc(),
                Ticket.id.asc(),
            )
        else:
            query = query.order_by(
                Ticket.due_at.is_(None).asc(),
                Ticket.due_at.desc(),
                Ticket.id.desc(),
            )
    elif direction == "asc":
        query = query.order_by(order_column.asc(), Ticket.id.asc())
    else:
        query = query.order_by(order_column.desc(), Ticket.id.desc())

    owner_alias = aliased(User)
    technician_alias = aliased(User)

    rows_query = (
        query.with_entities(
            Ticket.id,
            Ticket.title,
            Ticket.category,
            Ticket.priority,
            Ticket.sector,
            Ticket.equipment,
            Ticket.operational_impact,
            Ticket.status,
            Ticket.sla_hours,
            Ticket.technician_id,
            owner_alias.name.label("owner_name"),
            technician_alias.name.label("technician_name"),
            Ticket.created_at,
            Ticket.due_at,
        )
        .outerjoin(owner_alias, owner_alias.id == Ticket.user_id)
        .outerjoin(technician_alias, technician_alias.id == Ticket.technician_id)
    )
    total = rows_query.count() if include_total else None
    rows, has_more = page_rows(rows_query, skip=skip, limit=limit)

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
            "sla_hours": row.sla_hours,
            "technician_id": row.technician_id,
            "owner_name": row.owner_name,
            "technician_name": row.technician_name,
            "created_at": row.created_at,
            "due_at": row.due_at,
        }
        for row in rows
    ]

    logger.info(
        "Listagem de tickets concluída | current_user_id=%s | returned=%s | has_more=%s",
        current_user.id,
        len(tickets),
        has_more,
    )

    return {
        "items": tickets,
        "total": total,
        "skip": max(skip, 0),
        "limit": limit,
        "has_more": has_more,
    }
