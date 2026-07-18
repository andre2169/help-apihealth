from app.core.config import settings
from app.core.security import hash_password
from app.db.models.user import User
from app.db.session import SessionLocal


def create_admin():
    db = SessionLocal()

    admin_email = settings.ADMIN_EMAIL

    existing = db.query(User).filter(User.email == admin_email).first()
    if existing:
        print("Admin já existe!")
        db.close()
        return

    admin = User(
        name="Admin",
        email=admin_email,
        password_hash=hash_password(settings.ADMIN_PASSWORD),
        role="admin"
    )

    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.close()

    print("Admin criado com sucesso!")


if __name__ == "__main__":
    create_admin()
