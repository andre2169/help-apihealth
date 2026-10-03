import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.mfa_recovery_code import MFARecoveryCode
from app.db.models.user import User


RECOVERY_CODE_COUNT = 10


def _normalize_code(code: str) -> str:
    return str(code or "").strip().upper().replace("-", "")


def _code_hash(*, user_id: int, code: str) -> str:
    payload = f"mfa-recovery:{user_id}:{_normalize_code(code)}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def generate_recovery_codes(*, db: Session, user: User) -> list[str]:
    db.query(MFARecoveryCode).filter(
        MFARecoveryCode.user_id == user.id,
        MFARecoveryCode.used_at.is_(None),
    ).delete(synchronize_session=False)

    codes = []
    rows = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(6).upper()
        code = f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"
        codes.append(code)
        rows.append(
            MFARecoveryCode(
                user_id=user.id,
                code_hash=_code_hash(user_id=user.id, code=code),
            )
        )

    db.add_all(rows)
    db.flush()
    return codes


def count_recovery_codes(*, db: Session, user_id: int) -> int:
    return int(
        db.query(func.count(MFARecoveryCode.id))
        .filter(
            MFARecoveryCode.user_id == user_id,
            MFARecoveryCode.used_at.is_(None),
        )
        .scalar()
        or 0
    )


def consume_recovery_code(*, db: Session, user_id: int, code: str) -> bool:
    digest = _code_hash(user_id=user_id, code=code)
    row = (
        db.query(MFARecoveryCode.id)
        .filter(
            MFARecoveryCode.user_id == user_id,
            MFARecoveryCode.code_hash == digest,
            MFARecoveryCode.used_at.is_(None),
        )
        .first()
    )
    if not row:
        return False

    result = db.execute(
        update(MFARecoveryCode)
        .where(
            MFARecoveryCode.id == row.id,
            MFARecoveryCode.user_id == user_id,
            MFARecoveryCode.used_at.is_(None),
        )
        .values(used_at=datetime.now(timezone.utc))
    )
    return result.rowcount == 1
