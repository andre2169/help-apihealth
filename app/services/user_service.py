from sqlalchemy.orm import Session

from app.db.models.user import User
from app.schemas.user import UserCreate
from app.core.security import hash_password
from app.core.exceptions import UserAlreadyExists


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
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user
