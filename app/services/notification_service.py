from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.notification import Notification
from app.db.models.ticket import Ticket
from app.db.models.user import User


SUPPORT_ROLES = ("technician", "admin")
NOTIFICATION_LIMIT_MAX = 50


def _shorten(value: str | None, max_length: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= max_length:
        return clean
    return f"{clean[: max_length - 3]}..."


def _support_recipient_ids(*, db: Session, actor_id: int | None) -> list[int]:
    query = db.query(User.id).filter(User.role.in_(SUPPORT_ROLES))
    if actor_id is not None:
        query = query.filter(User.id != actor_id)
    return [user_id for (user_id,) in query.all()]


def _create_support_notifications(
    *,
    db: Session,
    ticket: Ticket,
    actor: User,
    notification_type: str,
    title: str,
    message: str,
) -> int:
    recipient_ids = _support_recipient_ids(db=db, actor_id=actor.id)
    if not recipient_ids:
        return 0

    db.add_all(
        Notification(
            recipient_id=recipient_id,
            actor_id=actor.id,
            ticket_id=ticket.id,
            type=notification_type,
            title=title,
            message=message,
        )
        for recipient_id in recipient_ids
    )
    return len(recipient_ids)


def notify_support_users_about_new_ticket(
    *,
    db: Session,
    ticket: Ticket,
    actor: User,
) -> int:
    sector = _shorten(ticket.sector, 30) or "setor nao informado"
    title = _shorten(ticket.title, 70) or "chamado sem titulo"
    return _create_support_notifications(
        db=db,
        ticket=ticket,
        actor=actor,
        notification_type="ticket.created",
        title="Novo chamado recebido",
        message=f"{sector}: {title}",
    )


def notify_support_users_about_reopened_ticket(
    *,
    db: Session,
    ticket: Ticket,
    actor: User,
) -> int:
    sector = _shorten(ticket.sector, 30) or "setor nao informado"
    title = _shorten(ticket.title, 70) or "chamado sem titulo"
    return _create_support_notifications(
        db=db,
        ticket=ticket,
        actor=actor,
        notification_type="ticket.reopened",
        title="Chamado reaberto",
        message=f"{sector}: {title}",
    )


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


def delete_notifications_for_ticket(*, db: Session, ticket_id: int) -> None:
    db.query(Notification).filter(Notification.ticket_id == ticket_id).delete(
        synchronize_session=False
    )


def delete_notifications_for_tickets(*, db: Session, ticket_ids: list[int]) -> None:
    if not ticket_ids:
        return
    db.query(Notification).filter(Notification.ticket_id.in_(ticket_ids)).delete(
        synchronize_session=False
    )


def remove_user_from_notifications(*, db: Session, user_id: int) -> None:
    db.query(Notification).filter(Notification.recipient_id == user_id).delete(
        synchronize_session=False
    )
    db.query(Notification).filter(Notification.actor_id == user_id).update(
        {Notification.actor_id: None},
        synchronize_session=False,
    )
