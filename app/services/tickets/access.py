from sqlalchemy import and_, or_

from app.core.exceptions import TicketPermissionDenied
from app.db.models.ticket import Ticket


QUEUE_STATUSES = ("open", "reopened")


def apply_ticket_visibility(query, user):
    """Aplica o escopo de consulta conforme o perfil autenticado."""
    query = query.filter(Ticket.deleted_at.is_(None))

    if user.role == "admin":
        return query

    if user.role == "technician":
        return query.filter(
            or_(
                Ticket.technician_id == user.id,
                and_(
                    Ticket.technician_id.is_(None),
                    Ticket.status.in_(QUEUE_STATUSES),
                ),
            )
        )

    return query.filter(Ticket.user_id == user.id)


def apply_ticket_personal_scope(query, user):
    """Aplica o escopo usado pelos indicadores, sem incluir a fila compartilhada."""
    query = query.filter(Ticket.deleted_at.is_(None))

    if user.role == "admin":
        return query

    if user.role == "technician":
        return query.filter(Ticket.technician_id == user.id)

    return query.filter(Ticket.user_id == user.id)


def can_view_ticket(*, user, ticket):
    if ticket.deleted_at is not None:
        return False

    if user.role == "admin":
        return True

    if user.role == "technician":
        return ticket.technician_id == user.id or (
            ticket.technician_id is None and ticket.status in QUEUE_STATUSES
        )

    return ticket.user_id == user.id

def can_view_ticket_timeline(*, user, ticket):
    if can_view_ticket(user=user, ticket=ticket):
        return

    raise TicketPermissionDenied(
        "Você não tem permissão para ver a timeline deste ticket"
    )
