from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import jwt
from jwt import InvalidTokenError

from app.core import security_policy as policy
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
            minutes=policy.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    # jti identifica este token específico e permite revogação no logout.
    to_encode.update({
        "exp": expire,
        "iat": issued_at,
        "nbf": issued_at,
        "jti": uuid4().hex,
        "iss": policy.JWT_ISSUER,
        "aud": policy.JWT_AUDIENCE,
        "typ": "access",
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=policy.JWT_ALGORITHM
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
            algorithms=[policy.JWT_ALGORITHM],
            issuer=policy.JWT_ISSUER,
            audience=policy.JWT_AUDIENCE,
            options={
                "require": [
                    "exp",
                    "iat",
                    "nbf",
                    "jti",
                    "sub",
                    "session_version",
                    "iss",
                    "aud",
                    "typ",
                ]
            },
        )
        if payload.get("typ") != "access":
            return None
        return payload
    except InvalidTokenError:
        return None
