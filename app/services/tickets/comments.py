from sqlalchemy.orm import Session

from app.db.models.comment import Comment
from app.db.models.ticket import Ticket
from app.db.models.user import User

from app.core.exceptions import (
    TicketNotFound,
    TicketInvalidStatus,
    TicketPermissionDenied,
)
from app.core.events import create_ticket_event
from app.services.audit.events import record_audit_event
from app.services.notifications.service import create_notifications_for_event


def create_comment_service(
    *,
    db: Session,
    ticket_id: int,
    content: str,
    current_user: User,
) -> Comment:
    ticket = (
        db.query(Ticket)
        .filter(Ticket.id == ticket_id, Ticket.deleted_at.is_(None))
        .first()
    )

    if not ticket:
        raise TicketNotFound()

    if ticket.status == "closed":
        raise TicketInvalidStatus(
            "Ticket encerrado não permite comentários"
        )

    # Usuário comum → só no próprio ticket
    if current_user.role == "user" and ticket.user_id != current_user.id:
        raise TicketPermissionDenied(
            "Você não pode comentar neste ticket"
        )

    # Técnico → só se estiver atribuído
    if (
        current_user.role == "technician"
        and ticket.technician_id != current_user.id
    ):
        raise TicketPermissionDenied(
            "Técnico não atribuído ao ticket"
        )

    comment = Comment(
        content=content,
        user_id=current_user.id,
        ticket_id=ticket.id,
    )

    db.add(comment)
    db.flush()

    event = create_ticket_event(
        db=db,
        ticket_id=ticket.id,
        user_id=current_user.id,
        event_type="COMMENTED",
    )
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="ticket.comment_created",
        target_type="ticket",
        target_id=ticket.id,
    )
    create_notifications_for_event(
        db=db,
        ticket=ticket,
        event=event,
        actor=current_user,
    )

    db.commit()
    db.refresh(comment)

    return comment
