from sqlalchemy.orm import Session

from app.db.models.comment import Comment
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.db.models.token_blocklist import TokenBlocklist
from app.db.models.user import User
from app.core.exceptions import (
    UserNotFound,
    InvalidUserRole,
    TicketPermissionDenied,
)


VALID_ROLES = ["user", "technician", "admin"]


def list_users_service(*, db: Session):
    return db.query(User).all()


def get_user_service(*, db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise UserNotFound("Usuário não encontrado")
    return user


def change_user_role_service(
    *,
    db: Session,
    user_id: int,
    role: str,
) -> User:
    if role not in VALID_ROLES:
        raise InvalidUserRole("Role inválido")

    user = get_user_service(db=db, user_id=user_id)

    user.role = role
    db.commit()
    db.refresh(user)

    return user


def update_user_service(
    *,
    db: Session,
    user_id: int,
    name: str | None,
    email: str | None,
    phone: str | None,
    job_title: str | None,
    department: str | None,
    unit_name: str | None,
    notification_preference: str | None,
) -> User:
    user = get_user_service(db=db, user_id=user_id)

    if name is not None:
        user.name = name

    if email is not None:
        user.email = email
    if phone is not None:
        user.phone = phone
    if job_title is not None:
        user.job_title = job_title
    if department is not None:
        user.department = department
    if unit_name is not None:
        user.unit_name = unit_name
    if notification_preference is not None:
        user.notification_preference = notification_preference

    db.commit()
    db.refresh(user)

    return user


def delete_user_service(
    *,
    db: Session,
    user_id: int,
    current_user: User,
):
    user = get_user_service(db=db, user_id=user_id)

    if user.id == current_user.id:
        raise TicketPermissionDenied(
            "Admin não pode deletar a si mesmo"
        )

    owned_ticket_ids = [
        ticket_id
        for (ticket_id,) in db.query(Ticket.id)
        .filter(Ticket.user_id == user.id)
        .all()
    ]

    if owned_ticket_ids:
        db.query(Comment).filter(Comment.ticket_id.in_(owned_ticket_ids)).delete(
            synchronize_session=False
        )
        db.query(TicketEvent).filter(TicketEvent.ticket_id.in_(owned_ticket_ids)).delete(
            synchronize_session=False
        )
        db.query(Ticket).filter(Ticket.id.in_(owned_ticket_ids)).delete(
            synchronize_session=False
        )

    db.query(Comment).filter(Comment.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(TicketEvent).filter(TicketEvent.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(Ticket).filter(Ticket.technician_id == user.id).update(
        {Ticket.technician_id: None},
        synchronize_session=False,
    )
    db.query(TokenBlocklist).filter(TokenBlocklist.user_id == user.id).delete(
        synchronize_session=False
    )

    db.delete(user)
    db.commit()
