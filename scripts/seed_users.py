from app.db.session import SessionLocal
from app.db.models.user import User
from app.core.security import hash_password


DEMO_PASSWORD = "SenhaDemo!2026"


def seed_users():
    db = SessionLocal()

    try:
        users = [
            {
                "name": "User 8",
                "email": "user8@test.com",
                "password": DEMO_PASSWORD,
                "role": "user",
            },
            {
                "name": "User 9",
                "email": "user9@test.com",
                "password": DEMO_PASSWORD,
                "role": "user",
            },
            {
                "name": "User 10",
                "email": "user10@test.com",
                "password": DEMO_PASSWORD,
                "role": "user",
            },
            {
                "name": "User 11",
                "email": "user11@test.com",
                "password": DEMO_PASSWORD,
                "role": "user",
            },
        ]

        for u in users:
            existing = db.query(User).filter(User.email == u["email"]).first()
            if existing:
                print(f"Usuário já existe: {u['email']}")
                continue

            user = User(
                name=u["name"],
                email=u["email"],
                password_hash=hash_password(u["password"]),
                role=u["role"],
            )

            db.add(user)

        db.commit()
        print("Seed de usuários concluído!")

    finally:
        db.close()


if __name__ == "__main__":
    seed_users()
