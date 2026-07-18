from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from jose import JWTError, jwt

from app.core.config import settings


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
):
    """
    Cria um token JWT
    """
    to_encode = data.copy()
    issued_at = datetime.now(timezone.utc)

    if expires_delta:
        expire = issued_at + expires_delta
    else:
        expire = issued_at + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    # jti identifica este token específico e permite revogação no logout.
    to_encode.update({
        "exp": expire,
        "iat": issued_at,
        "jti": uuid4().hex,
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )

    return encoded_jwt


def decode_access_token(token: str):
    """
    Decodifica e valida um token JWT
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None
