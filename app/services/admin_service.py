from sqlalchemy.orm import Session

from app.db.models.audit_event import AuditEvent
from app.db.models.comment import Comment
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.db.models.token_blocklist import TokenBlocklist
from app.db.models.user import User
from app.core.request_context import mask_email
from app.core.exceptions import (
    UserNotFound,
    InvalidUserRole,
    TicketPermissionDenied,
)
from app.services.audit_service import record_audit_event
from app.services.notification_service import (
    delete_notifications_for_tickets,
    remove_user_from_notifications,
)


VALID_ROLES = ["user", "technician", "admin"]


def list_users_service(*, db: Session):
    users = db.query(User).order_by(User.created_at.desc(), User.id.desc()).all()
    return [
        {
            "id": user.id,
            "name": user.name,
            "email_masked": mask_email(user.email),
            "role": user.role,
            "email_verified": bool(user.email_verified),
            "job_title": user.job_title,
            "department": user.department,
            "unit_name": user.unit_name,
            "created_at": user.created_at,
        }
        for user in users
    ]


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
    actor: User,
    ip_address: str | None = None,
) -> User:
    if role not in VALID_ROLES:
        raise InvalidUserRole("Role inválido")

    user = get_user_service(db=db, user_id=user_id)
    old_role = user.role

    user.role = role
    user.session_version = (user.session_version or 1) + 1
    record_audit_event(
        db,
        actor_id=actor.id,
        action="admin.user_role_changed",
        target_type="user",
        target_id=user.id,
        ip_address=ip_address,
        details={"old_role": old_role, "new_role": role},
    )
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
    actor: User,
    ip_address: str | None = None,
) -> User:
    user = get_user_service(db=db, user_id=user_id)
    changed_fields: list[str] = []

    if name is not None:
        user.name = name
        changed_fields.append("name")

    if email is not None:
        user.email = email
        user.email_verified = True
        user.session_version = (user.session_version or 1) + 1
        changed_fields.append("email")
    if phone is not None:
        user.phone = phone
        changed_fields.append("phone")
    if job_title is not None:
        user.job_title = job_title
        changed_fields.append("job_title")
    if department is not None:
        user.department = department
        changed_fields.append("department")
    if unit_name is not None:
        user.unit_name = unit_name
        changed_fields.append("unit_name")
    if notification_preference is not None:
        user.notification_preference = notification_preference
        changed_fields.append("notification_preference")

    if changed_fields:
        record_audit_event(
            db,
            actor_id=actor.id,
            action="admin.user_updated",
            target_type="user",
            target_id=user.id,
            ip_address=ip_address,
            details={"changed_fields": changed_fields},
        )

    db.commit()
    db.refresh(user)

    return user


def delete_user_service(
    *,
    db: Session,
    user_id: int,
    current_user: User,
    ip_address: str | None = None,
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
        delete_notifications_for_tickets(db=db, ticket_ids=owned_ticket_ids)
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
    remove_user_from_notifications(db=db, user_id=user.id)
    db.query(AuditEvent).filter(AuditEvent.actor_id == user.id).update(
        {AuditEvent.actor_id: None},
        synchronize_session=False,
    )

    deleted_role = user.role
    db.delete(user)
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="admin.user_deleted",
        target_type="user",
        target_id=user_id,
        ip_address=ip_address,
        details={"deleted_role": deleted_role},
    )
    db.commit()
