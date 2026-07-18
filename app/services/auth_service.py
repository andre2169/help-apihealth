from datetime import timedelta
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.core.security import verify_password
from app.core.auth import create_access_token
from app.core.config import settings
from app.core.exceptions import InvalidCredentials


def login_service(
    *,
    db: Session,
    email: str,
    password: str,
) -> dict:
    normalized_email = email.strip().lower()
    user = (
        db.query(User)
        .filter(User.email == normalized_email)
        .first()
    )

    if not user or not verify_password(password, user.password_hash):
        raise InvalidCredentials()

    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }
