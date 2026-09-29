from sqlalchemy.orm import Session

from app.db.models.ticket import Ticket
from app.db.models.user import User
from app.db.models.ticket_event import TicketEvent


SUPPORT_ROLE = "technician"
USER_ROLE = "user"
WHATSAPP_PREFERENCES = {"whatsapp", "both"}

# Eventos que pertencem ao ciclo de vida de um chamado já vinculado. Eles não
# devem ser distribuídos para toda a fila de suporte.
LINKED_TICKET_EVENTS = {
    "REOPENED",
    "COMMENTED",
    "ASSIGNED",
    "RESOLVED",
    "CLOSED",
}


def _append_unique(recipients: list[User], candidate: User | None, actor_id: int) -> None:
    if not candidate or not candidate.is_active or candidate.id == actor_id:
        return
    if candidate.id not in {recipient.id for recipient in recipients}:
        recipients.append(candidate)


def recipients_for_ticket_event(
    *,
    db: Session,
    ticket: Ticket,
    event: TicketEvent,
    actor: User,
) -> list[User]:
    """Resolve destinatários sem aceitar IDs enviados pelo frontend.

    A abertura é uma distribuição para a equipe técnica ativa. Os demais
    eventos são privados ao solicitante e ao técnico realmente vinculado.
    Administradores permanecem com acesso administrativo, mas não entram na
    caixa de notificações nem na entrega de WhatsApp.
    """

    recipients: list[User] = []

    if event.event_type == "CREATED":
        return (
            db.query(User)
            .filter(
                User.role == SUPPORT_ROLE,
                User.is_active.is_(True),
            )
            .order_by(User.id.asc())
            .all()
        )

    if event.event_type not in LINKED_TICKET_EVENTS:
        return recipients

    owner = (
        db.query(User)
        .filter(
            User.id == ticket.user_id,
            User.role == USER_ROLE,
            User.is_active.is_(True),
        )
        .first()
    )
    _append_unique(recipients, owner, actor.id)

    if ticket.technician_id:
        technician = (
            db.query(User)
            .filter(
                User.id == ticket.technician_id,
                User.role == SUPPORT_ROLE,
                User.is_active.is_(True),
            )
            .first()
        )
        _append_unique(recipients, technician, actor.id)

    return recipients


def can_receive_whatsapp(user: User) -> bool:
    """Exige opt-in explícito e telefone brasileiro já validado pela API."""

    return bool(
        user.is_active
        and user.phone
        and user.notification_preference in WHATSAPP_PREFERENCES
    )
