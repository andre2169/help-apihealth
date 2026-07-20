import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.security import hash_password
from app.db.models.user import User
from app.db.session import SessionLocal


logger = logging.getLogger(__name__)


def create_initial_admin() -> None:
    """
    Garante a existência do administrador inicial usando apenas variáveis
    de ambiente. Nenhuma credencial de demonstração fica gravada no código.
    """
    db = SessionLocal()
    try:
        admin_email = settings.ADMIN_EMAIL.strip().lower()
        existing = db.query(User).filter(User.email == admin_email).first()
        if existing:
            logger.info("Admin inicial já existe")
            return

        admin = User(
            name="Admin",
            email=admin_email,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            role="admin",
            email_verified=True,
            email_verified_at=datetime.now(timezone.utc),
            session_version=1,
        )

        db.add(admin)
        db.commit()
        logger.info("Admin inicial criado com sucesso")
    finally:
        db.close()
