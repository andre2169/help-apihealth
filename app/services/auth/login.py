from sqlalchemy.orm import Session

from app.db.models.user import User
from app.core.security import hash_password, verify_password
from app.core.exceptions import InvalidCredentials


_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-constant-login-time")


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

    # Executa bcrypt mesmo quando o email nao existe. Isso reduz a diferenca
    # de tempo entre "email inexistente" e "senha incorreta".
    hash_to_check = user.password_hash if user else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(password, hash_to_check)

    if not user or not user.is_active or not password_ok:
        raise InvalidCredentials()

    return user
