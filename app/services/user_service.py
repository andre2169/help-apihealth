from sqlalchemy.orm import Session

from app.db.models.user import User
from app.schemas.user import UserCreate
from app.core.security import hash_password
from app.core.exceptions import UserAlreadyExists
from app.services.account_verification_service import (
    PURPOSE_EMAIL_VERIFICATION,
    create_account_verification,
)
from app.services.audit_service import record_audit_event


def create_user_service(
    *,
    db: Session,
    user_in: UserCreate,
) -> User:
    normalized_email = str(user_in.email).strip().lower()
    user_exists = (
        db.query(User)
        .filter(User.email == normalized_email)
        .first()
    )

    if user_exists:
        raise UserAlreadyExists()

    user = User(
        name=user_in.name,
        email=normalized_email,
        phone=user_in.phone,
        job_title=user_in.job_title,
        department=user_in.department,
        unit_name=user_in.unit_name,
        password_hash=hash_password(user_in.password),
        role="user",
        email_verified=False,
        session_version=1,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    create_account_verification(
        db=db,
        user=user,
        purpose=PURPOSE_EMAIL_VERIFICATION,
        recipient_email=user.email,
        target_value=user.email,
    )
    record_audit_event(
        db,
        actor_id=user.id,
        action="user.registered",
        target_type="user",
        target_id=user.id,
        details={"email_verification_required": True},
        commit=True,
    )

    return user
