from sqlalchemy.orm import Session
from app.db.models.ticket_event import TicketEvent


def create_ticket_event(
    *,
    db: Session,
    ticket_id: int,
    user_id: int,
    event_type: str,
    from_status: str | None = None,
    to_status: str | None = None,
):
    event = TicketEvent(
        ticket_id=ticket_id,
        user_id=user_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
    )

    db.add(event)
    return event