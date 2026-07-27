import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.audit_event import AuditEvent


logger = logging.getLogger(__name__)


def record_audit_event(
    db: Session,
    *,
    action: str,
    target_type: str,
    actor_id: int | None = None,
    target_id: int | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
    commit: bool = False,
) -> None:
    """
    Registra trilha de auditoria em tabela propria.

    Nao coloque senhas, tokens, codigos de verificacao ou emails completos em
    details. Esta trilha deve ajudar investigacao sem aumentar vazamento de PII.
    """
    try:
        db.add(
            AuditEvent(
                actor_id=actor_id,
                action=action[:80],
                target_type=target_type[:60],
                target_id=target_id,
                ip_address=ip_address[:64] if ip_address else None,
                details=details or {},
            )
        )
        if commit:
            db.commit()
    except Exception:
        logger.exception(
            "Falha ao registrar auditoria | action=%s | actor_id=%s | target_type=%s | target_id=%s",
            action,
            actor_id,
            target_type,
            target_id,
        )
        if commit:
            db.rollback()
