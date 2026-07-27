from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.auth import decode_access_token
from app.db.models.token_blocklist import TokenBlocklist


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expires_at_from_payload(payload: dict) -> datetime:
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        return datetime.fromtimestamp(exp, tz=timezone.utc)
    if isinstance(exp, str) and exp.isdigit():
        return datetime.fromtimestamp(int(exp), tz=timezone.utc)
    return _now()


def is_token_revoked(*, db: Session, jti: str) -> bool:
    token = (
        db.query(TokenBlocklist)
        .filter(TokenBlocklist.jti == jti)
        .first()
    )
    return token is not None


def revoke_token(*, db: Session, token: str, user_id: int | None = None) -> bool:
    """
    Revoga o token atual até o horário original de expiração.

    O JWT continua stateless para validação, mas o logout consulta esta tabela
    para impedir reuso do mesmo token depois que o usuário saiu.
    """
    payload = decode_access_token(token)
    if not payload:
        return False

    jti = payload.get("jti")
    if not jti or is_token_revoked(db=db, jti=jti):
        return False

    # Limpeza simples para a tabela não crescer com tokens já expirados.
    db.query(TokenBlocklist).filter(TokenBlocklist.expires_at <= _now()).delete(
        synchronize_session=False
    )

    db.add(
        TokenBlocklist(
            jti=jti,
            user_id=user_id,
            expires_at=_expires_at_from_payload(payload),
        )
    )
    db.commit()
    return True
