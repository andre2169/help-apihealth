from datetime import datetime, timezone
import re

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.notification import Notification
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.db.models.user import User
from app.services.notifications.recipient_policy import (
    can_receive_whatsapp,
    recipients_for_ticket_event,
)
from app.core.search import LIKE_ESCAPE, contains_pattern, normalize_search, page_rows


NOTIFICATION_LIMIT_MAX = 50
ADMIN_EVENT_LIMIT_MAX = 100
ADMIN_TICKET_EVENT_LIMIT_MAX = 50

EVENT_COPY = {
    "CREATED": ("Novo chamado recebido", "Novo chamado"),
    "REOPENED": ("Chamado reaberto", "Chamado reaberto"),
    "COMMENTED": ("Novo comentário no chamado", "Novo comentário"),
    "ASSIGNED": ("Chamado atribuído", "Chamado atribuído"),
    "RESOLVED": ("Chamado resolvido", "Chamado resolvido"),
    "CLOSED": ("Chamado encerrado", "Chamado encerrado"),
    "RECOVERED": ("Chamado recuperado", "Chamado recuperado"),
}


def _shorten(value: str | None, max_length: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= max_length:
        return clean
    return f"{clean[: max_length - 3]}..."


def _event_content(event_type: str, ticket: Ticket) -> tuple[str, str]:
    title, prefix = EVENT_COPY.get(event_type, ("Atualização de chamado", "Atualização"))
    sector = _shorten(ticket.sector, 30) or "setor não informado"
    ticket_title = _shorten(ticket.title, 70) or "chamado sem título"
    return title, _shorten(f"{prefix} | CH-{ticket.id:06d} | {sector}: {ticket_title}", 280)


def create_notifications_for_event(
    *,
    db: Session,
    ticket: Ticket,
    event: TicketEvent,
    actor: User,
) -> int:
    """Cria notificações internas e entregas WhatsApp do evento.

    Esta função apenas grava o estado transacional no banco. O contato com a
    Evolution API fica para o worker, evitando que uma falha externa impeça a
    criação ou atualização do chamado.
    """

    db.flush()
    recipients = recipients_for_ticket_event(
        db=db,
        ticket=ticket,
        event=event,
        actor=actor,
    )
    if not recipients:
        return 0

    title, message = _event_content(event.event_type, ticket)
    notifications = [
        Notification(
            recipient_id=recipient.id,
            actor_id=actor.id,
            ticket_id=ticket.id,
            ticket_event_id=event.id,
            type=f"ticket.{event.event_type.lower()}",
            title=title,
            message=message,
        )
        for recipient in recipients
    ]
    db.add_all(notifications)
    db.flush()

    if settings.WHATSAPP_ENABLED:
        db.add_all(
            NotificationDelivery(
                notification_id=notification.id,
                recipient_id=recipient.id,
                channel="whatsapp",
                status="pending",
            )
            for notification, recipient in zip(notifications, recipients)
            if can_receive_whatsapp(recipient)
        )

    return len(notifications)


# Mantemos estes nomes para não quebrar chamadas internas ou integrações locais
# antigas enquanto o fluxo novo passa a usar create_notifications_for_event.
def notify_support_users_about_new_ticket(
    *,
    db: Session,
    ticket: Ticket,
    actor: User,
    event: TicketEvent | None = None,
) -> int:
    if event is None:
        event = TicketEvent(
            ticket_id=ticket.id,
            user_id=actor.id,
            event_type="CREATED",
            to_status="open",
        )
        db.add(event)
    return create_notifications_for_event(db=db, ticket=ticket, event=event, actor=actor)


def notify_support_users_about_reopened_ticket(
    *,
    db: Session,
    ticket: Ticket,
    actor: User,
    event: TicketEvent | None = None,
) -> int:
    if event is None:
        event = TicketEvent(
            ticket_id=ticket.id,
            user_id=actor.id,
            event_type="REOPENED",
            to_status="reopened",
        )
        db.add(event)
    return create_notifications_for_event(db=db, ticket=ticket, event=event, actor=actor)


def list_my_notifications(
    *,
    db: Session,
    current_user: User,
    unread_only: bool = False,
    limit: int = 20,
) -> dict:
    safe_limit = min(max(limit, 1), NOTIFICATION_LIMIT_MAX)
    query = db.query(Notification).filter(Notification.recipient_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))

    items = (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(safe_limit)
        .all()
    )
    unread_count = (
        db.query(Notification)
        .filter(
            Notification.recipient_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .count()
    )
    return {"items": items, "unread_count": unread_count}


def list_admin_notification_events(
    *,
    db: Session,
    skip: int = 0,
    limit: int = 50,
) -> dict:
    """Consulta administrativa dos eventos sem transformar admin em destinatário."""

    safe_skip = max(skip, 0)
    safe_limit = min(max(limit, 1), ADMIN_EVENT_LIMIT_MAX)
    query = db.query(TicketEvent).join(Ticket, Ticket.id == TicketEvent.ticket_id).filter(
        Ticket.deleted_at.is_(None)
    ).order_by(
        TicketEvent.created_at.desc(),
        TicketEvent.id.desc(),
    )
    rows, has_more = page_rows(query, skip=safe_skip, limit=safe_limit)
    return {
        "items": [
            {
                "id": event.id,
                "ticket_id": event.ticket_id,
                "event_type": event.event_type,
                "from_status": event.from_status,
                "to_status": event.to_status,
                "created_at": event.created_at,
            }
            for event in rows
        ],
        "total": None,
        "skip": safe_skip,
        "limit": safe_limit,
        "has_more": has_more,
    }


def list_admin_ticket_event_summaries(
    *,
    db: Session,
    search: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    """Lista chamados com eventos agrupados para a área administrativa.

    A consulta retorna somente um resumo por chamado. O histórico completo é
    carregado sob demanda pela rota de timeline já protegida por autorização.
    """

    safe_skip = max(skip, 0)
    safe_limit = min(max(limit, 1), ADMIN_TICKET_EVENT_LIMIT_MAX)
    event_summary = (
        db.query(
            TicketEvent.ticket_id.label("ticket_id"),
            func.count(TicketEvent.id).label("event_count"),
            func.max(TicketEvent.created_at).label("last_event_at"),
        )
        .group_by(TicketEvent.ticket_id)
        .subquery()
    )

    owner_alias = User.__table__.alias("ticket_owner")
    technician_alias = User.__table__.alias("ticket_technician")
    query = (
        db.query(
            Ticket.id.label("ticket_id"),
            Ticket.title,
            Ticket.status,
            Ticket.priority,
            Ticket.sector,
            Ticket.category,
            Ticket.created_at,
            Ticket.updated_at,
            owner_alias.c.name.label("owner_name"),
            technician_alias.c.name.label("technician_name"),
            event_summary.c.event_count,
            event_summary.c.last_event_at,
        )
        .join(event_summary, event_summary.c.ticket_id == Ticket.id)
        .outerjoin(owner_alias, owner_alias.c.id == Ticket.user_id)
        .outerjoin(technician_alias, technician_alias.c.id == Ticket.technician_id)
        .filter(Ticket.deleted_at.is_(None))
    )

    clean_search = normalize_search(search)
    if clean_search:
        filters = [
            Ticket.title.ilike(contains_pattern(clean_search), escape=LIKE_ESCAPE),
            Ticket.description.ilike(contains_pattern(clean_search), escape=LIKE_ESCAPE),
            Ticket.sector.ilike(contains_pattern(clean_search), escape=LIKE_ESCAPE),
            Ticket.category.ilike(contains_pattern(clean_search), escape=LIKE_ESCAPE),
        ]
        code_match = re.fullmatch(r"(?i)(?:(?:ch[-\s]*m?)[-\s]*)?0*(\d+)", clean_search)
        if code_match and len(code_match.group(1)) <= 18:
            filters.insert(0, Ticket.id == int(code_match.group(1)))
        query = query.filter(or_(*filters))

    rows_query = (
        query.order_by(event_summary.c.last_event_at.desc(), Ticket.id.desc())
    )
    rows, has_more = page_rows(rows_query, skip=safe_skip, limit=safe_limit)

    ticket_ids = [row.ticket_id for row in rows]
    events_by_ticket: dict[int, list[TicketEvent]] = {}
    if ticket_ids:
        event_rows = (
            db.query(TicketEvent)
            .filter(TicketEvent.ticket_id.in_(ticket_ids))
            .order_by(TicketEvent.created_at.desc(), TicketEvent.id.desc())
            .all()
        )
        for event in event_rows:
            events_by_ticket.setdefault(event.ticket_id, []).append(event)

    items = []
    for row in rows:
        last_event = events_by_ticket.get(row.ticket_id, [None])[0]
        items.append(
            {
                "ticket_id": row.ticket_id,
                "title": row.title,
                "status": row.status,
                "priority": row.priority,
                "sector": row.sector,
                "category": row.category,
                "owner_name": row.owner_name,
                "technician_name": row.technician_name,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "event_count": int(row.event_count or 0),
                "last_event": (
                    {
                        "id": last_event.id,
                        "ticket_id": last_event.ticket_id,
                        "event_type": last_event.event_type,
                        "from_status": last_event.from_status,
                        "to_status": last_event.to_status,
                        "created_at": last_event.created_at,
                    }
                    if last_event
                    else None
                ),
            }
        )

    return {
        "items": items,
        "total": None,
        "skip": safe_skip,
        "limit": safe_limit,
        "has_more": has_more,
    }


def mark_notification_read(
    *,
    db: Session,
    notification_id: int,
    current_user: User,
) -> Notification | None:
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.recipient_id == current_user.id,
        )
        .first()
    )
    if not notification:
        return None

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)

    return notification


def mark_all_notifications_read(*, db: Session, current_user: User) -> int:
    now = datetime.now(timezone.utc)
    updated = (
        db.query(Notification)
        .filter(
            Notification.recipient_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .update(
            {Notification.is_read: True, Notification.read_at: now},
            synchronize_session=False,
        )
    )
    db.commit()
    return int(updated or 0)


def _delete_deliveries_for_notification_ids(*, db: Session, notification_ids: list[int]) -> None:
    if notification_ids:
        db.query(NotificationDelivery).filter(
            NotificationDelivery.notification_id.in_(notification_ids)
        ).delete(synchronize_session=False)


def delete_notifications_for_ticket(*, db: Session, ticket_id: int) -> None:
    notification_ids = [
        notification_id
        for (notification_id,) in db.query(Notification.id)
        .filter(Notification.ticket_id == ticket_id)
        .all()
    ]
    _delete_deliveries_for_notification_ids(db=db, notification_ids=notification_ids)
    db.query(Notification).filter(Notification.ticket_id == ticket_id).delete(
        synchronize_session=False
    )


def delete_notifications_for_tickets(*, db: Session, ticket_ids: list[int]) -> None:
    if not ticket_ids:
        return
    notification_ids = [
        notification_id
        for (notification_id,) in db.query(Notification.id)
        .filter(Notification.ticket_id.in_(ticket_ids))
        .all()
    ]
    _delete_deliveries_for_notification_ids(db=db, notification_ids=notification_ids)
    db.query(Notification).filter(Notification.ticket_id.in_(ticket_ids)).delete(
        synchronize_session=False
    )


def remove_user_from_notifications(*, db: Session, user_id: int) -> None:
    notification_ids = [
        notification_id
        for (notification_id,) in db.query(Notification.id)
        .filter(Notification.recipient_id == user_id)
        .all()
    ]
    _delete_deliveries_for_notification_ids(db=db, notification_ids=notification_ids)
    db.query(NotificationDelivery).filter(
        NotificationDelivery.recipient_id == user_id
    ).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.recipient_id == user_id).delete(
        synchronize_session=False
    )
    db.query(Notification).filter(Notification.actor_id == user_id).update(
        {Notification.actor_id: None},
        synchronize_session=False,
    )
